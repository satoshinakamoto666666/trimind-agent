"""TriMind consensus engine."""

import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Any

import aiohttp

from config import CONSENSUS_THRESHOLD, GROK_API_KEY, GROK_MODEL, OPENAI_API_KEY, OPENAI_MODEL

LOG = logging.getLogger("TriMind")

ALLOWED_VOTES = {"EXECUTE", "SKIP", "HOLD"}
ALLOWED_ACTIONS = {"supply_aave", "swap", "rebalance", "diversify", "withdraw", "none"}

OUTPUT_INSTRUCTIONS = """Respond with JSON only:
{
  "vote": "EXECUTE" or "SKIP" or "HOLD",
  "confidence": 0.0 to 1.0,
  "reasoning": "one sentence",
  "action": "supply_aave" or "swap" or "rebalance" or "diversify" or "withdraw" or "none",
  "risk_score": 0.0 to 1.0
}"""

GPT_SYSTEM_PROMPT = (
    "You are the quantitative mind of TriMind on OKX X Layer. "
    "Optimize for portfolio construction, stablecoin allocation, Aave yield, price impact, and risk-adjusted execution. "
    "Prefer rebalance when USDC dry powder is below the operating minimum, prefer supply_aave only when Aave APY is real and stable capital is idle, "
    "and prefer diversify only for small blue-chip exposure. "
    + OUTPUT_INSTRUCTIONS
)

GROK_SYSTEM_PROMPT = (
    "You are the sentiment and flow mind of TriMind on OKX X Layer. "
    "Focus on tracker activity, meme token momentum, social links, and whether market attention justifies a tactical move. "
    "Prefer HOLD when social noise is high but conviction is weak. "
    "Use supply_aave only when the flow picture is quiet and parking stables is better than chasing noise. "
    + OUTPUT_INSTRUCTIONS
)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _normalize_vote(vote: dict | None) -> dict:
    if not isinstance(vote, dict):
        return {"vote": "HOLD", "confidence": 0.0, "reasoning": "invalid response", "action": "none", "risk_score": 0.5}
    normalized = {
        "vote": str(vote.get("vote", "HOLD")).upper(),
        "confidence": _clamp(vote.get("confidence", 0.0)),
        "reasoning": str(vote.get("reasoning", "no reasoning"))[:240],
        "action": str(vote.get("action", "none")).lower(),
        "risk_score": _clamp(vote.get("risk_score", 0.5)),
    }
    if normalized["vote"] not in ALLOWED_VOTES:
        normalized["vote"] = "HOLD"
    if normalized["action"] not in ALLOWED_ACTIONS:
        normalized["action"] = "none"
    if normalized["vote"] != "EXECUTE":
        normalized["action"] = "none"
    return normalized


def _summarize_signals(signals: list[dict]) -> list[dict]:
    summary = []
    for item in signals[:8]:
        summary.append(
            {
                "token": item.get("tokenSymbol"),
                "token_address": item.get("tokenContractAddress"),
                "trade_time": item.get("tradeTime"),
                "market_cap": item.get("marketCap"),
                "quote_amount": item.get("quoteTokenAmount"),
                "quote_symbol": item.get("quoteTokenSymbol"),
            }
        )
    return summary


def _summarize_memes(memes: list[dict]) -> list[dict]:
    summary = []
    for item in memes[:6]:
        summary.append(
            {
                "symbol": item.get("symbol"),
                "token_address": item.get("tokenAddress"),
                "market_cap_usd": item.get("market", {}).get("marketCapUsd"),
                "volume_usd_1h": item.get("market", {}).get("volumeUsd1h"),
                "buy_tx_1h": item.get("market", {}).get("buyTxCount1h"),
                "social": item.get("social", {}),
                "snipers_percent": item.get("tags", {}).get("snipersPercent"),
                "dev_holdings_percent": item.get("tags", {}).get("devHoldingsPercent"),
            }
        )
    return summary


def _quant_context(prompt: str, market_data: dict) -> str:
    context = {
        "prompt": prompt,
        "portfolio": market_data.get("portfolio", {}),
        "aave_market": market_data.get("aave_market", {}),
        "quotes": market_data.get("quotes", {}),
        "defi_positions": market_data.get("defi_positions", {}),
        "security": market_data.get("security", {}),
        "usdc_price": market_data.get("usdc_price", {}),
        "usdt_price": market_data.get("usdt_price", {}),
    }
    return json.dumps(context, indent=2, default=str)[:3200]


def _sentiment_context(prompt: str, market_data: dict) -> str:
    context = {
        "prompt": prompt,
        "portfolio": market_data.get("portfolio", {}),
        "signals": _summarize_signals(market_data.get("signals", [])),
        "memes": _summarize_memes(market_data.get("memes", [])),
        "security": market_data.get("security", {}),
        "quotes": {
            key: market_data.get("quotes", {}).get(key)
            for key in ("swap_3", "diversify_1", "rebalance_3")
            if key in market_data.get("quotes", {})
        },
    }
    return json.dumps(context, indent=2, default=str)[:3200]


async def _call_llm(url: str, api_key: str, model: str, system_prompt: str, payload_text: str, timeout: int) -> dict | None:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": payload_text},
        ],
        "temperature": 0.2,
        "max_tokens": 300,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status != 200:
                    LOG.warning("LLM API error %s: %d", url, resp.status)
                    return None
                result = await resp.json()
    except Exception as exc:
        LOG.warning("LLM call failed %s: %s", url, exc)
        return None

    try:
        content = result["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return _normalize_vote(json.loads(content))
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        LOG.warning("LLM parse error %s: %s", url, exc)
        return None


async def _call_openai(prompt: str, market_data: dict) -> dict | None:
    if not OPENAI_API_KEY:
        return None
    return await _call_llm(
        "https://api.openai.com/v1/chat/completions",
        OPENAI_API_KEY,
        OPENAI_MODEL,
        GPT_SYSTEM_PROMPT,
        _quant_context(prompt, market_data),
        25,
    )


async def _call_grok(prompt: str, market_data: dict) -> dict | None:
    if not GROK_API_KEY:
        return None
    return await _call_llm(
        "https://api.x.ai/v1/chat/completions",
        GROK_API_KEY,
        GROK_MODEL,
        GROK_SYSTEM_PROMPT,
        _sentiment_context(prompt, market_data),
        30,
    )


def _agent_logic_vote(market_data: dict) -> dict:
    """Rule-based third mind."""
    portfolio = market_data.get("portfolio", {})
    signals = market_data.get("signals", [])
    security = market_data.get("security", {})
    aave_market = market_data.get("aave_market", {})

    usdc = float(portfolio.get("usdc_balance", 0))
    xlayer_usdt = float(portfolio.get("xlayer_usdt_balance", portfolio.get("usdt_balance", 0)))
    weth_usd = float(portfolio.get("weth_usd", 0))
    total_usd = max(float(portfolio.get("total_usd", 0)), 1.0)
    is_safe = security.get("safe", True)
    signal_count = len(signals)
    aave_apy = float(aave_market.get("apy", 0) or 0)
    usdc_share = usdc / total_usd
    weth_share = weth_usd / total_usd

    if not is_safe:
        return _normalize_vote(
            {
                "vote": "SKIP",
                "confidence": 0.9,
                "reasoning": "Security risk detected in the latest scan set",
                "action": "none",
                "risk_score": 0.85,
            }
        )

    if usdc < 5 and xlayer_usdt > 10:
        return _normalize_vote(
            {
                "vote": "EXECUTE",
                "confidence": 0.82,
                "reasoning": f"USDC dry powder is too low (${usdc:.2f}) while XLAYER USDT is available (${xlayer_usdt:.2f})",
                "action": "rebalance",
                "risk_score": 0.12,
            }
        )

    if aave_market and aave_apy >= 0.015 and xlayer_usdt > 12 and usdc_share >= 0.35:
        return _normalize_vote(
            {
                "vote": "EXECUTE",
                "confidence": 0.74,
                "reasoning": f"Aave V3 USDT yield is live at {aave_apy:.2%} and stable capital is idle",
                "action": "supply_aave",
                "risk_score": 0.16,
            }
        )

    if signal_count >= 20 and usdc > 6 and weth_share < 0.05:
        return _normalize_vote(
            {
                "vote": "EXECUTE",
                "confidence": 0.62,
                "reasoning": "Strong smart-money activity justifies a small blue-chip beta allocation",
                "action": "diversify",
                "risk_score": 0.28,
            }
        )

    if usdc_share > 0.65 and usdc > 8:
        return _normalize_vote(
            {
                "vote": "EXECUTE",
                "confidence": 0.58,
                "reasoning": "USDC concentration is high and can be rotated into other stablecoin inventory",
                "action": "swap",
                "risk_score": 0.20,
            }
        )

    return _normalize_vote(
        {
            "vote": "HOLD",
            "confidence": 0.52,
            "reasoning": f"Portfolio is within operating bands (USDC share {usdc_share:.0%}, WETH share {weth_share:.0%})",
            "action": "none",
            "risk_score": 0.10,
        }
    )


def _pick_action(votes: dict[str, dict]) -> str:
    action_scores: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0, "confidence": 0.0})
    for vote in votes.values():
        if vote.get("vote") != "EXECUTE":
            continue
        action = vote.get("action", "none")
        action_scores[action]["count"] += 1
        action_scores[action]["confidence"] += float(vote.get("confidence", 0))
    if not action_scores:
        return "none"
    ranked = sorted(action_scores.items(), key=lambda item: (item[1]["count"], item[1]["confidence"]), reverse=True)
    return ranked[0][0]


async def trimind_consensus(prompt: str, market_data: dict) -> dict[str, Any]:
    """Run all 3 minds in parallel, tally votes, and return consensus decision."""
    gpt_task = _call_openai(prompt, market_data)
    grok_task = _call_grok(prompt, market_data)

    results = await asyncio.gather(gpt_task, grok_task, return_exceptions=True)
    gpt_vote = _normalize_vote(results[0] if isinstance(results[0], dict) else None)
    grok_vote = _normalize_vote(results[1] if isinstance(results[1], dict) else None)
    agent_vote = _agent_logic_vote(market_data)

    votes = {"gpt": gpt_vote, "grok": grok_vote, "agent": agent_vote}

    execute_votes = sum(1 for vote in votes.values() if vote.get("vote") == "EXECUTE")
    skip_votes = sum(1 for vote in votes.values() if vote.get("vote") == "SKIP")

    consensus = execute_votes >= CONSENSUS_THRESHOLD and skip_votes < CONSENSUS_THRESHOLD
    action = _pick_action(votes) if consensus else "none"

    reasons = [f"{name}: {vote.get('reasoning', '?')}" for name, vote in votes.items()]
    avg_confidence = sum(vote.get("confidence", 0) for vote in votes.values()) / 3
    avg_risk = sum(vote.get("risk_score", 0) for vote in votes.values()) / 3

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

    LOG.info(
        "TRIMIND: consensus=%s action=%s votes=%d/%d conf=%.2f risk=%.2f",
        consensus,
        action,
        execute_votes,
        3,
        avg_confidence,
        avg_risk,
    )
    for name, vote in votes.items():
        LOG.info(
            "  %s: %s %s (conf=%.2f) -- %s",
            name.upper(),
            vote.get("vote"),
            vote.get("action"),
            vote.get("confidence", 0),
            vote.get("reasoning", ""),
        )

    return result
