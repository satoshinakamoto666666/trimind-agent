"""Export real TriMind data into a demo-friendly bundle.

Usage:
    python scripts/export_demo_data.py
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config

DEMO_DIR = ROOT / "demo"
DB_PATH = config.DB_PATH


def resolve_onchainos() -> str:
    candidate = shutil.which("onchainos")
    if candidate:
        return candidate
    fallback = Path.home() / ".local" / "bin" / "onchainos"
    return str(fallback)


ONCHAINOS = resolve_onchainos()


def run_json(args: list[str]) -> dict:
    cmd = [ONCHAINOS] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "command": cmd}
    stdout = (proc.stdout or "").strip()
    if not stdout:
        return {"ok": proc.returncode == 0, "data": []}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {
            "ok": False,
            "error": "non-json response",
            "stdout": stdout,
            "stderr": (proc.stderr or "").strip(),
            "returncode": proc.returncode,
        }


def parse_votes(raw: str) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def query_db() -> dict:
    if not DB_PATH.exists():
        return {"decisions": [], "positions": [], "stats": {}}

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    decisions = []
    for row in conn.execute(
        "SELECT id, timestamp, consensus, action, votes_json, reasoning, executed, result FROM decisions ORDER BY id DESC LIMIT 12"
    ):
        item = dict(row)
        item["votes"] = parse_votes(item.pop("votes_json", ""))
        decisions.append(item)

    positions = [
        dict(row)
        for row in conn.execute(
            "SELECT id, asset, protocol, amount, entry_time, status, tx_hash FROM positions ORDER BY id DESC LIMIT 12"
        )
    ]

    stats_row = conn.execute(
        "SELECT COUNT(*) AS total_decisions, SUM(CASE WHEN executed=1 THEN 1 ELSE 0 END) AS executed_decisions FROM decisions"
    ).fetchone()
    stats = dict(stats_row) if stats_row else {}
    conn.close()
    return {"decisions": decisions, "positions": positions, "stats": stats}


def extract_balances(portfolio: dict) -> dict:
    token_assets = []
    data = portfolio.get("data", []) if isinstance(portfolio, dict) else []
    for bucket in data if isinstance(data, list) else []:
        token_assets.extend(bucket.get("tokenAssets", []))
    balances = {}
    for token in token_assets:
        symbol = token.get("symbol", "?")
        balances[symbol] = {
            "balance": float(token.get("balance", 0) or 0),
            "price": float(token.get("tokenPrice", 0) or 0),
            "address": token.get("tokenContractAddress", ""),
        }
    return balances


def extract_history(history: dict) -> list[dict]:
    order_list = []
    data = history.get("data", []) if isinstance(history, dict) else []
    for page in data if isinstance(data, list) else []:
        order_list.extend(page.get("orderList", []))
    return order_list[:10]


def build_scenes(bundle: dict) -> list[dict]:
    decisions = bundle["db"].get("decisions", [])
    orders = bundle["wallet_history"]
    balances = bundle["balances"]
    latest_decision = decisions[0] if decisions else {}
    latest_success = next((o for o in orders if o.get("txStatus") == "SUCCESS"), {})
    scenes = [
        {
            "id": "overview",
            "title": "TriMind live overview",
            "duration_sec": 10,
            "focus": "hero",
            "voice_hint": "Open with the wallet, the chain, and the fact that three minds decide every move.",
        },
        {
            "id": "council",
            "title": "Latest council decision",
            "duration_sec": 16,
            "focus": "decision",
            "decision_id": latest_decision.get("id"),
            "voice_hint": "Show the three votes and why the winning action was selected.",
        },
        {
            "id": "execution",
            "title": "Recent live execution",
            "duration_sec": 18,
            "focus": "tx",
            "tx_hash": latest_success.get("txHash", ""),
            "voice_hint": "Show a real successful transaction from wallet history.",
        },
        {
            "id": "yield",
            "title": "Aave market discovery",
            "duration_sec": 16,
            "focus": "aave",
            "voice_hint": "Show that the agent discovers the live Aave V3 USDT market on X Layer.",
        },
        {
            "id": "proof",
            "title": "Autonomy proof",
            "duration_sec": 16,
            "focus": "timeline",
            "voice_hint": "End on logs, positions, and decisions to prove it is autonomous.",
        },
        {
            "id": "closing",
            "title": "Closing frame",
            "duration_sec": 8,
            "focus": "summary",
            "voice_hint": "Close on balances, API activity, and the product statement.",
        },
    ]
    scenes[0]["headline"] = f"${balances.get('USDC', {}).get('balance', 0):.2f} USDC | ${balances.get('USDT', {}).get('balance', 0):.2f} XLAYER_USDT"
    return scenes


def main() -> None:
    DEMO_DIR.mkdir(parents=True, exist_ok=True)

    db = query_db()
    portfolio = run_json(
        [
            "portfolio",
            "all-balances",
            "--address",
            config.EVM_WALLET,
            "--chains",
            config.XLAYER_CHAIN_ID,
            "--chain",
            config.XLAYER_CHAIN_ID,
        ]
    )
    total_value = run_json(
        [
            "portfolio",
            "total-value",
            "--address",
            config.EVM_WALLET,
            "--chains",
            config.XLAYER_CHAIN_ID,
            "--chain",
            config.XLAYER_CHAIN_ID,
        ]
    )
    wallet_history = run_json(
        [
            "wallet",
            "history",
            "--chain",
            config.XLAYER_CHAIN_ID,
            "--address",
            config.EVM_WALLET,
            "--limit",
            "10",
        ]
    )
    aave_search = run_json(
        [
            "defi",
            "search",
            "--platform",
            "Aave V3",
            "--token",
            "USDT",
            "--chain",
            config.XLAYER_CHAIN_ID,
            "--product-group",
            "SINGLE_EARN",
        ]
    )
    aave_list = aave_search.get("data", {}).get("list", []) if isinstance(aave_search, dict) else []
    aave_id = aave_list[0].get("investmentId") if aave_list else None
    aave_detail = run_json(["defi", "detail", "--investment-id", str(aave_id), "--chain", config.XLAYER_CHAIN_ID]) if aave_id else {}

    bundle = {
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "wallet": config.EVM_WALLET,
        "chain": config.XLAYER_CHAIN_ID,
        "db": db,
        "portfolio": portfolio,
        "balances": extract_balances(portfolio),
        "total_value": total_value,
        "wallet_history": extract_history(wallet_history),
        "aave_search": aave_search,
        "aave_detail": aave_detail,
    }
    bundle["scenes"] = build_scenes(bundle)

    json_path = DEMO_DIR / "demo_data.json"
    js_path = DEMO_DIR / "demo_data.js"
    json_text = json.dumps(bundle, indent=2)
    json_path.write_text(json_text, encoding="utf-8")
    js_path.write_text(f"window.TRIMIND_DEMO = {json_text};\n", encoding="utf-8")

    print(f"Wrote {json_path}")
    print(f"Wrote {js_path}")


if __name__ == "__main__":
    main()
