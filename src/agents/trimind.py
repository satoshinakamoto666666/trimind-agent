"""TriMind Consensus Engine -- GPT + Grok + Agent Logic vote on every action.

Each "mind" analyzes the same market data and returns a structured decision.
2/3 must agree before execution. Disagreements are logged for self-evolution.
"""
import asyncio
import json
import logging
import time
from typing import Any

import aiohttp

from config import OPENAI_API_KEY, OPENAI_MODEL, GROK_API_KEY, GROK_MODEL, CONSENSUS_THRESHOLD

LOG = logging.getLogger("TriMind")

SYSTEM_PROMPT = """You are a DeFi AI analyst for an autonomous agent on OKX X Layer (chain 196, zero gas).
You analyze market data, signals, and token info to make trading decisions.

Your response must be EXACTLY this JSON format (no markdown, no explanation):
{
  "vote": "EXECUTE" or "SKIP" or "HOLD",
  "confidence": 0.0 to 1.0,
  "reasoning": "one sentence why",
  "action": "supply_aave" or "swap" or "lp_add" or "lp_remove" or "withdraw" or "none",
  "risk_score": 0.0 to 1.0
}
"""


async def _call_openai(prompt: str, data: str) -> dict | None:
    """Call GPT API for strategy analysis."""
    if not OPENAI_API_KEY:
        return None
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Analyze this data and decide:\n{data}\n\nContext: {prompt}"}
        ],
        "temperature": 0.3,
        "max_tokens": 300,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.openai.com/v1/chat/completions",
                                    headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    LOG.warning("GPT API error: %d", resp.status)
                    return None
                result = await resp.json()
                content = result["choices"][0]["message"]["content"].strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                return json.loads(content)
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        LOG.warning("GPT parse error: %s", exc)
        return None
    except Exception as exc:
        LOG.warning("GPT call failed: %s", exc)
        return None


async def _call_grok(prompt: str, data: str) -> dict | None:
    """Call Grok API for sentiment/social analysis."""
    if not GROK_API_KEY:
        return None
    headers = {"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": GROK_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Analyze this data and decide:\n{data}\n\nContext: {prompt}"}
        ],
        "temperature": 0.3,
        "max_tokens": 300,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.x.ai/v1/chat/completions",
                                    headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    LOG.warning("Grok API error: %d", resp.status)
                    return None
                result = await resp.json()
                content = result["choices"][0]["message"]["content"].strip()
                # Strip markdown code blocks if present
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                return json.loads(content)
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        LOG.warning("Grok parse error: %s", exc)
        return None
    except Exception as exc:
        LOG.warning("Grok call failed: %s", exc)
        return None


def _agent_logic_vote(market_data: dict) -> dict:
    """Third mind: rule-based agent logic (no API call, instant)."""
    portfolio = market_data.get("portfolio", {})
    signals = market_data.get("signals", [])
    security = market_data.get("security", {})

    # Simple heuristic rules
    idle_usdc = float(portfolio.get("usdc_balance", 0))
    aave_supplied = float(portfolio.get("aave_supplied", 0))
    has_opportunity = len(signals) > 0
    is_safe = security.get("safe", True)

    if not is_safe:
        return {"vote": "SKIP", "confidence": 0.9, "reasoning": "Security risk detected",
                "action": "none", "risk_score": 0.8}

    if idle_usdc > 10 and aave_supplied < idle_usdc * 3:
        return {"vote": "EXECUTE", "confidence": 0.7, "reasoning": "Idle USDC should earn yield on Aave",
                "action": "supply_aave", "risk_score": 0.1}

    if has_opportunity and is_safe:
        return {"vote": "EXECUTE", "confidence": 0.6, "reasoning": "Signal detected, safe to trade",
                "action": "swap", "risk_score": 0.3}

    return {"vote": "HOLD", "confidence": 0.5, "reasoning": "No clear opportunity",
            "action": "none", "risk_score": 0.0}


async def trimind_consensus(prompt: str, market_data: dict) -> dict[str, Any]:
    """Run all 3 minds in parallel, tally votes, return consensus decision.

    Returns:
        {
            "consensus": True/False,
            "action": "supply_aave" / "swap" / "none",
            "votes": {"gpt": {...}, "grok": {...}, "agent": {...}},
            "execute": True/False,
            "reasoning": "summary",
            "timestamp": float,
        }
    """
    data_str = json.dumps(market_data, indent=2, default=str)[:3000]

    # Run GPT + Grok in parallel, agent logic is instant
    gpt_task = _call_openai(prompt, data_str)
    grok_task = _call_grok(prompt, data_str)

    results = await asyncio.gather(gpt_task, grok_task, return_exceptions=True)

    gpt_vote = results[0] if isinstance(results[0], dict) else None
    grok_vote = results[1] if isinstance(results[1], dict) else None
    agent_vote = _agent_logic_vote(market_data)

    # Default votes for failed API calls
    if gpt_vote is None:
        gpt_vote = {"vote": "HOLD", "confidence": 0.0, "reasoning": "API unavailable",
                     "action": "none", "risk_score": 0.5}
    if grok_vote is None:
        grok_vote = {"vote": "HOLD", "confidence": 0.0, "reasoning": "API unavailable",
                      "action": "none", "risk_score": 0.5}

    votes = {"gpt": gpt_vote, "grok": grok_vote, "agent": agent_vote}

    # Tally
    execute_votes = sum(1 for v in votes.values() if v.get("vote") == "EXECUTE")
    skip_votes = sum(1 for v in votes.values() if v.get("vote") == "SKIP")

    consensus = execute_votes >= CONSENSUS_THRESHOLD
    if skip_votes >= CONSENSUS_THRESHOLD:
        consensus = False

    # Pick action from majority
    if consensus:
        actions = [v.get("action", "none") for v in votes.values() if v.get("vote") == "EXECUTE"]
        action = actions[0] if actions else "none"
    else:
        action = "none"

    # Build reasoning summary
    reasons = [f"{name}: {v.get('reasoning', '?')}" for name, v in votes.items()]
    avg_confidence = sum(v.get("confidence", 0) for v in votes.values()) / 3
    avg_risk = sum(v.get("risk_score", 0) for v in votes.values()) / 3

    result = {
        "consensus": consensus,
        "execute": consensus and action != "none",
        "action": action,
        "votes": votes,
        "execute_count": execute_votes,
        "skip_count": skip_votes,
        "avg_confidence": round(avg_confidence, 3),
        "avg_risk": round(avg_risk, 3),
        "reasoning": " | ".join(reasons),
        "timestamp": time.time(),
    }

    LOG.info("TRIMIND: consensus=%s action=%s votes=%d/%d conf=%.2f risk=%.2f",
             consensus, action, execute_votes, 3, avg_confidence, avg_risk)
    for name, v in votes.items():
        LOG.info("  %s: %s (conf=%.2f) -- %s", name.upper(), v.get("vote"), v.get("confidence", 0), v.get("reasoning", ""))

    return result
