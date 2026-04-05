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
  "action": "supply_aave" or "swap" or "rebalance" or "diversify" or "lp_add" or "lp_remove" or "withdraw" or "none",
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
    """Third mind: rule-based agent logic (no API call, instant).

    Strategy priorities:
        1. Security reject if risk detected
        2. Rebalance if USDT > 2x USDC (too concentrated)
        3. Diversify into OKB occasionally (every ~5th cycle when OKB is low)
        4. Supply/swap USDC→USDT if idle USDC > $10
        5. Hold if balanced
    """
    portfolio = market_data.get("portfolio", {})
    signals = market_data.get("signals", [])
    security = market_data.get("security", {})

    idle_usdc = float(portfolio.get("usdc_balance", 0))
    usdt_bal = float(portfolio.get("usdt_balance", 0))
    okb_bal = float(portfolio.get("okb_balance", 0))
    total_usd = float(portfolio.get("total_usd", 0)) or 1.0  # avoid div-by-zero
    has_opportunity = len(signals) > 0
    is_safe = security.get("safe", True)

    # 1. Security reject
    if not is_safe:
        return {"vote": "SKIP", "confidence": 0.9, "reasoning": "Security risk detected",
                "action": "none", "risk_score": 0.8}

    # 2. Rebalance: if USDT is more than double USDC, swap some back
    if usdt_bal > idle_usdc * 2 and usdt_bal > 3:
        return {"vote": "EXECUTE", "confidence": 0.75,
                "reasoning": f"USDT ${usdt_bal:.0f} > 2x USDC ${idle_usdc:.0f}, rebalance needed",
                "action": "rebalance", "risk_score": 0.1}

    # 3. Rebalance: if USDT > 60% of total portfolio
    if usdt_bal > total_usd * 0.6 and usdt_bal > 3:
        return {"vote": "EXECUTE", "confidence": 0.7,
                "reasoning": f"USDT is {usdt_bal/total_usd*100:.0f}% of portfolio, rebalancing to USDC",
                "action": "rebalance", "risk_score": 0.1}

    # 4. Diversify: buy small OKB if we have none and enough USDC
    #    Use timestamp-based pseudo-randomness to trigger ~20% of cycles
    import time as _t
    cycle_hash = int(_t.time()) % 5
    if okb_bal < 0.01 and idle_usdc > 10 and cycle_hash == 0:
        return {"vote": "EXECUTE", "confidence": 0.65,
                "reasoning": "No OKB exposure, diversifying small amount into native token",
                "action": "diversify", "risk_score": 0.2}

    # 5. Supply/yield: idle USDC should be put to work
    if idle_usdc > 10:
        return {"vote": "EXECUTE", "confidence": 0.7,
                "reasoning": f"Idle USDC ${idle_usdc:.0f} should earn yield (swap to USDT)",
                "action": "supply_aave", "risk_score": 0.1}

    # 6. Opportunity swap on signal
    if has_opportunity and is_safe and idle_usdc > 5:
        return {"vote": "EXECUTE", "confidence": 0.6,
                "reasoning": "Signal detected, safe to trade USDC→USDT",
                "action": "swap", "risk_score": 0.3}

    # 7. Balanced -- hold
    return {"vote": "HOLD", "confidence": 0.5,
            "reasoning": f"Portfolio balanced (USDC=${idle_usdc:.0f} USDT=${usdt_bal:.0f}), no action needed",
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
