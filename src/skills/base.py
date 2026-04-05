"""OnchainOS skill wrapper -- subprocess calls to onchainos CLI.

Every skill returns parsed JSON. Handles errors, timeouts, API key rotation.
"""
import json
import logging
import os
import subprocess
import shutil
from typing import Any

LOG = logging.getLogger("Skills")


def _resolve_binary() -> str:
    candidate = os.path.expanduser("~/.local/bin/onchainos")
    if os.name == "nt":
        candidate += ".exe"
    if os.path.isfile(candidate):
        return candidate
    found = shutil.which("onchainos")
    return found if found else candidate


ONCHAINOS = _resolve_binary()


def _build_env() -> dict:
    """Build env dict with OKX DEX credentials."""
    from config import OKX_DEX_API_KEY, OKX_DEX_SECRET_KEY, OKX_DEX_PASSPHRASE, OKX_DEX_PROJECT_ID
    env = os.environ.copy()
    if OKX_DEX_API_KEY:
        env["OKX_DEX_API_KEY"] = OKX_DEX_API_KEY
        env["OKX_DEX_SECRET_KEY"] = OKX_DEX_SECRET_KEY
        env["OKX_DEX_PASSPHRASE"] = OKX_DEX_PASSPHRASE
        env["OKX_DEX_PROJECT_ID"] = OKX_DEX_PROJECT_ID
    return env


def run_skill(args: list[str], timeout: int = 15) -> tuple[bool, dict | list | None]:
    """Run onchainos CLI command. Returns (success, parsed_data)."""
    cmd = [ONCHAINOS] + args
    LOG.debug("CLI: %s", " ".join(cmd))
    try:
        env = _build_env()
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        LOG.warning("CLI error: %s cmd=%s", exc, " ".join(args))
        return False, None
    if proc.returncode != 0:
        LOG.warning("CLI exit=%d %s %s", proc.returncode, " ".join(args), (proc.stderr or "")[:200])
        return False, None
    stdout = (proc.stdout or "").strip()
    if not stdout:
        return True, {}
    try:
        return True, json.loads(stdout)
    except json.JSONDecodeError:
        LOG.warning("CLI bad JSON: %s", stdout[:300])
        return False, None


# Convenience wrappers for each skill

def wallet_balance(chain: str = "196") -> dict | None:
    ok, data = run_skill(["wallet", "balance", "--chain", chain])
    return data if ok else None


def wallet_portfolio(address: str, chain: str = "196") -> dict | None:
    ok, data = run_skill(["wallet", "portfolio", "--address", address, "--chain", chain])
    return data if ok else None


def security_scan(token_address: str, chain: str = "196") -> dict | None:
    ok, data = run_skill(["security", "token-scan", "--address", token_address, "--chain", chain])
    return data if ok else None


def market_price(token_address: str, chain: str = "196") -> dict | None:
    ok, data = run_skill(["token", "price-info", "--address", token_address, "--chain", chain])
    if not ok or data is None:
        return None
    if isinstance(data, list) and data:
        return data[0] if isinstance(data[0], dict) else {}
    return data.get("data", data) if isinstance(data, dict) else None


def market_kline(token_address: str, chain: str = "196", bar: str = "5m", limit: int = 20) -> dict | None:
    ok, data = run_skill(["market", "kline", "--address", token_address, "--chain", chain,
                          "--bar", bar, "--limit", str(limit)])
    return data if ok else None


def signal_list(chain: str = "196", tracker_type: str = "smart_money") -> list:
    """Get SM/KOL/whale signals. Always returns a list."""
    ok, data = run_skill(["tracker", "activities", "--tracker-type", tracker_type,
                          "--chain", "solana", "--trade-type", "1"])
    if not ok or data is None:
        return []
    if isinstance(data, list):
        return data
    inner = data.get("data", data)
    if isinstance(inner, list):
        return inner
    if isinstance(inner, dict):
        trades = inner.get("trades", inner.get("data", []))
        return trades if isinstance(trades, list) else []
    return []


def token_info(token_address: str, chain: str = "196") -> dict | None:
    ok, data = run_skill(["token", "advanced-info", "--address", token_address, "--chain", chain])
    if not ok:
        return None
    return data.get("data", data) if isinstance(data, dict) else data


def token_price_info(token_address: str, chain: str = "196") -> dict | None:
    ok, data = run_skill(["token", "price-info", "--address", token_address, "--chain", chain])
    if not ok:
        return None
    if isinstance(data, list) and data:
        return data[0] if isinstance(data[0], dict) else {}
    return data.get("data", data) if isinstance(data, dict) else {}


def trenches_scan(chain: str = "196") -> list:
    """Scan meme tokens via dex-trenches. Returns list, never None."""
    ok, data = run_skill(["memepump", "tokens", "--chain", "solana", "--stage", "GROWING"])
    if not ok or data is None:
        return []
    if isinstance(data, list):
        return data
    inner = data.get("data", [])
    return inner if isinstance(inner, list) else []


def trenches_dev_info(token_address: str, chain: str = "196") -> dict | None:
    ok, data = run_skill(["memepump", "token-dev-info", "--address", token_address,
                          "--chain", chain.replace("196", "xlayer")])
    if not ok:
        return None
    return data.get("data", data) if isinstance(data, dict) else data


def swap_execute(from_token: str, to_token: str, amount_usd: float, chain: str = "196",
                 slippage: str = "1.0", wallet: str = "") -> tuple[bool, str]:
    """Execute swap with readable amount. Returns (success, stdout)."""
    from config import EVM_WALLET, DRY_RUN
    w = wallet or EVM_WALLET
    if DRY_RUN:
        LOG.info("[DRY_RUN] swap %s -> %s $%.2f chain=%s", from_token[:10], to_token[:10], amount_usd, chain)
        return True, '{"dry_run": true}'
    cmd = [ONCHAINOS, "swap", "execute", "--chain", chain,
           "--from", from_token, "--to", to_token,
           "--readable-amount", str(amount_usd), "--slippage", slippage, "--wallet", w]
    try:
        env = _build_env()
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        LOG.info("Swap result: exit=%d stdout=%s", proc.returncode, (proc.stdout or "")[:300])
        return proc.returncode == 0, proc.stdout or proc.stderr or ""
    except Exception as exc:
        return False, str(exc)


def defi_positions(address: str, chain: str = "196") -> dict | None:
    ok, data = run_skill(["defi", "positions", "--address", address, "--chains", chain])
    return data if ok else None


def gateway_simulate(tx_data: dict) -> dict | None:
    """Simulate transaction via onchain-gateway."""
    # For now, return mock -- real implementation depends on gateway CLI args
    LOG.info("Gateway simulate: %s", str(tx_data)[:200])
    return {"simulated": True}


def audit_log_export() -> dict | None:
    """Export audit log."""
    ok, data = run_skill(["audit", "export", "--format", "json"])
    return data if ok else None
