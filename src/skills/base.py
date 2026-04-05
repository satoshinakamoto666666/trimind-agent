"""OnchainOS skill wrapper."""

import json
import logging
import os
import shutil
import subprocess
from decimal import Decimal, ROUND_DOWN

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
    """Build env dict with both legacy and official OKX credential keys."""
    from config import OKX_DEX_API_KEY, OKX_DEX_SECRET_KEY, OKX_DEX_PASSPHRASE, OKX_DEX_PROJECT_ID

    env = os.environ.copy()
    aliases = {
        "OKX_DEX_API_KEY": OKX_DEX_API_KEY,
        "OKX_DEX_SECRET_KEY": OKX_DEX_SECRET_KEY,
        "OKX_DEX_PASSPHRASE": OKX_DEX_PASSPHRASE,
        "OKX_DEX_PROJECT_ID": OKX_DEX_PROJECT_ID,
        "OKX_API_KEY": OKX_DEX_API_KEY,
        "OKX_SECRET_KEY": OKX_DEX_SECRET_KEY,
        "OKX_PASSPHRASE": OKX_DEX_PASSPHRASE,
        "OKX_PROJECT_ID": OKX_DEX_PROJECT_ID,
    }
    for key, value in aliases.items():
        if value:
            env[key] = value
    return env


def _run_process(args: list[str], timeout: int = 20, parse_json: bool = True) -> tuple[bool, dict | list | str | None, str, str]:
    cmd = [ONCHAINOS] + args
    LOG.debug("CLI: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_build_env(),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        LOG.warning("CLI error: %s cmd=%s", exc, " ".join(args))
        return False, {"error": str(exc)}, "", str(exc)

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    payload: dict | list | str | None = None

    if parse_json and stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = {"stdout": stdout, "stderr": stderr}
    elif parse_json:
        payload = {} if proc.returncode == 0 else None
    else:
        payload = stdout or stderr

    ok = proc.returncode == 0
    if parse_json and isinstance(payload, dict) and payload.get("ok") is False:
        ok = False

    if not ok:
        preview = stderr or stdout
        LOG.warning("CLI exit=%d %s %s", proc.returncode, " ".join(args), preview[:300])

    return ok, payload, stdout, stderr


def run_skill(args: list[str], timeout: int = 20) -> tuple[bool, dict | list | None]:
    """Run onchainos CLI command. Returns (success, parsed_data)."""
    ok, payload, _stdout, _stderr = _run_process(args, timeout=timeout, parse_json=True)
    if payload is None:
        return ok, None
    if isinstance(payload, str):
        return ok, {"raw": payload}
    return ok, payload


def _format_readable_amount(amount: float | str) -> str:
    dec = Decimal(str(amount)).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
    text = format(dec.normalize(), "f")
    return text.rstrip("0").rstrip(".") or "0"


def _readable_to_minimal(amount_readable: float | str, decimals: int) -> str:
    amount = Decimal(_format_readable_amount(amount_readable))
    scale = Decimal(10) ** decimals
    return str(int((amount * scale).to_integral_value(rounding=ROUND_DOWN)))


def _hex_to_minimal(value: str | int | None) -> str:
    if value is None:
        return "0"
    if isinstance(value, int):
        return str(value)
    value = str(value).strip()
    if value.startswith("0x"):
        return str(int(value, 16))
    return value or "0"


# Convenience wrappers for each skill

def wallet_balance(chain: str = "196") -> dict | None:
    ok, data = run_skill(["wallet", "balance", "--chain", str(chain)])
    return data if ok else None


def portfolio_all_balances(address: str, chain: str = "196") -> dict | None:
    ok, data = run_skill(
        ["portfolio", "all-balances", "--address", address, "--chains", str(chain), "--chain", str(chain)]
    )
    return data if ok else None


def portfolio_total_value(address: str, chain: str = "196") -> dict | None:
    ok, data = run_skill(
        ["portfolio", "total-value", "--address", address, "--chains", str(chain), "--chain", str(chain)]
    )
    return data if ok else None


def wallet_portfolio(address: str, chain: str = "196") -> dict | None:
    return portfolio_all_balances(address, chain)


def security_scan(token_address: str, chain: str = "196") -> dict | None:
    ok, data = run_skill(["security", "token-scan", "--address", token_address, "--chain", str(chain)])
    return data if ok else None


def market_price(token_address: str, chain: str = "196") -> dict | None:
    ok, data = run_skill(["token", "price-info", "--address", token_address, "--chain", str(chain)])
    if not ok or data is None:
        return None
    if isinstance(data, list) and data:
        return data[0] if isinstance(data[0], dict) else {}
    return data.get("data", data) if isinstance(data, dict) else None


def market_kline(token_address: str, chain: str = "196", bar: str = "5m", limit: int = 20) -> dict | None:
    ok, data = run_skill(
        ["market", "kline", "--address", token_address, "--chain", str(chain), "--bar", bar, "--limit", str(limit)]
    )
    return data if ok else None


def signal_list(chain: str = "196", tracker_type: str = "smart_money") -> list:
    ok, data = run_skill(
        ["tracker", "activities", "--tracker-type", tracker_type, "--chain", str(chain), "--trade-type", "1"]
    )
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
    ok, data = run_skill(["token", "advanced-info", "--address", token_address, "--chain", str(chain)])
    if not ok:
        return None
    return data.get("data", data) if isinstance(data, dict) else data


def token_price_info(token_address: str, chain: str = "196") -> dict | None:
    ok, data = run_skill(["token", "price-info", "--address", token_address, "--chain", str(chain)])
    if not ok:
        return None
    if isinstance(data, list) and data:
        return data[0] if isinstance(data[0], dict) else {}
    return data.get("data", data) if isinstance(data, dict) else {}


def trenches_scan(chain: str = "196") -> list:
    ok, data = run_skill(["memepump", "tokens", "--chain", str(chain)])
    if not ok or data is None:
        return []
    if isinstance(data, list):
        return data
    inner = data.get("data", [])
    return inner if isinstance(inner, list) else []


def trenches_dev_info(token_address: str, chain: str = "196") -> dict | None:
    ok, data = run_skill(["memepump", "token-dev-info", "--address", token_address, "--chain", str(chain)])
    if not ok:
        return None
    return data.get("data", data) if isinstance(data, dict) else data


def swap_quote(from_token: str, to_token: str, amount_usd: float, chain: str = "196") -> dict | None:
    ok, data = run_skill(
        [
            "swap",
            "quote",
            "--chain",
            str(chain),
            "--from",
            from_token,
            "--to",
            to_token,
            "--readable-amount",
            _format_readable_amount(amount_usd),
        ],
        timeout=30,
    )
    return data if ok else None


def _swap_execute_once(from_token: str, to_token: str, amount_usd: float, chain: str, slippage: str, wallet: str) -> tuple[bool, dict | None]:
    ok, payload, stdout, stderr = _run_process(
        [
            "swap",
            "execute",
            "--chain",
            str(chain),
            "--from",
            from_token,
            "--to",
            to_token,
            "--readable-amount",
            _format_readable_amount(amount_usd),
            "--slippage",
            slippage,
            "--wallet",
            wallet,
        ],
        timeout=45,
        parse_json=True,
    )
    if isinstance(payload, dict):
        return ok, payload
    if isinstance(payload, list):
        return ok, {"data": payload}
    return ok, {"stdout": stdout, "stderr": stderr}


def swap_execute(from_token: str, to_token: str, amount_usd: float, chain: str = "196", slippage: str = "1.0", wallet: str = "") -> tuple[bool, dict]:
    """Execute swap with adaptive sizing. Returns (success, result_json)."""
    from config import DRY_RUN, EVM_WALLET

    wallet = wallet or EVM_WALLET
    requested = Decimal(_format_readable_amount(amount_usd))
    if requested <= 0:
        return False, {"error": "amount must be positive"}

    if DRY_RUN:
        return True, {
            "dry_run": True,
            "from": from_token,
            "to": to_token,
            "amount": _format_readable_amount(amount_usd),
            "wallet": wallet,
        }

    candidates: list[str] = []
    for candidate in (
        requested,
        min(requested, Decimal("3")),
        requested * Decimal("0.75"),
        requested * Decimal("0.5"),
        Decimal("2"),
        Decimal("1"),
    ):
        if candidate <= 0:
            continue
        text = _format_readable_amount(candidate)
        if Decimal(text) < Decimal("1"):
            continue
        if text not in candidates:
            candidates.append(text)

    last_result: dict = {"error": "swap failed before execution"}
    for amount_text in candidates:
        quote = swap_quote(from_token, to_token, float(amount_text), chain)
        if not quote:
            last_result = {"error": "quote failed", "amount": amount_text}
            continue

        ok, result = _swap_execute_once(from_token, to_token, float(amount_text), chain, slippage, wallet)
        if ok:
            result = result or {}
            result.setdefault("requestedAmount", _format_readable_amount(amount_usd))
            result.setdefault("executedAmount", amount_text)
            return True, result

        last_result = result or {"error": "unknown swap error", "amount": amount_text}
        error_text = json.dumps(last_result, default=str).lower()
        if "another order processing" in error_text:
            break

    return False, last_result


def defi_positions(address: str, chain: str = "196") -> dict | None:
    ok, data = run_skill(["defi", "positions", "--address", address, "--chains", str(chain)])
    return data if ok else None


def defi_search(token: str = "", platform: str = "", chain: str = "196", product_group: str = "SINGLE_EARN") -> dict | None:
    args = ["defi", "search", "--chain", str(chain), "--product-group", product_group]
    if token:
        args.extend(["--token", token])
    if platform:
        args.extend(["--platform", platform])
    ok, data = run_skill(args, timeout=30)
    return data if ok else None


def defi_detail(investment_id: int | str, chain: str = "196") -> dict | None:
    ok, data = run_skill(["defi", "detail", "--investment-id", str(investment_id), "--chain", str(chain)], timeout=30)
    return data if ok else None


def defi_invest_plan(
    investment_id: int | str,
    address: str,
    token: str,
    amount_readable: float,
    chain: str = "196",
    decimals: int = 6,
) -> dict | None:
    amount = _readable_to_minimal(amount_readable, decimals)
    ok, data = run_skill(
        [
            "defi",
            "invest",
            "--investment-id",
            str(investment_id),
            "--address",
            address,
            "--token",
            token,
            "--amount",
            amount,
            "--chain",
            str(chain),
        ],
        timeout=45,
    )
    return data if ok else None


def defi_withdraw_plan(
    investment_id: int | str,
    address: str,
    chain: str = "196",
    ratio: str = "0.25",
) -> dict | None:
    ok, data = run_skill(
        [
            "defi",
            "withdraw",
            "--investment-id",
            str(investment_id),
            "--address",
            address,
            "--chain",
            str(chain),
            "--ratio",
            ratio,
        ],
        timeout=45,
    )
    return data if ok else None


def gateway_simulate(tx_data: dict | None = None, *, from_address: str = "", to_address: str = "", data: str = "0x", chain: str = "196", amount: str = "0") -> dict | None:
    payload = tx_data or {}
    sender = payload.get("from") or payload.get("from_address") or from_address
    target = payload.get("to") or payload.get("to_address") or to_address
    calldata = payload.get("data") or payload.get("input_data") or data or "0x"
    chain_value = payload.get("chain") or chain
    amount_value = payload.get("amount") or amount or "0"
    if not sender or not target:
        return {"ok": False, "error": "gateway_simulate requires from and to"}
    ok, result = run_skill(
        [
            "gateway",
            "simulate",
            "--from",
            sender,
            "--to",
            target,
            "--data",
            calldata,
            "--amount",
            str(amount_value),
            "--chain",
            str(chain_value),
        ],
        timeout=30,
    )
    return result if ok else result


def wallet_contract_call(
    to_address: str,
    input_data: str,
    chain: str = "196",
    from_address: str = "",
    amount: str = "0",
) -> tuple[bool, dict]:
    args = [
        "wallet",
        "contract-call",
        "--to",
        to_address,
        "--chain",
        str(chain),
        "--input-data",
        input_data,
        "--amt",
        str(amount),
        "--force",
    ]
    if from_address:
        args.extend(["--from", from_address])
    ok, payload, stdout, stderr = _run_process(args, timeout=60, parse_json=True)
    if isinstance(payload, dict):
        return ok, payload
    if isinstance(payload, list):
        return ok, {"data": payload}
    return ok, {"stdout": stdout, "stderr": stderr}


def _extract_call_bundle(payload: dict | None) -> list[dict]:
    if not payload or not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)
    if isinstance(data, dict):
        data_list = data.get("dataList", [])
        return data_list if isinstance(data_list, list) else []
    return []


def _execute_call_bundle(plan: dict | None, address: str, chain: str) -> tuple[bool, dict]:
    from config import DRY_RUN

    steps = _extract_call_bundle(plan)
    if not steps:
        return False, {"error": "empty call bundle", "plan": plan}

    if DRY_RUN:
        return True, {
            "dry_run": True,
            "steps": [step.get("callDataType", "UNKNOWN") for step in steps],
        }

    executed: list[dict] = []
    for step in steps:
        step_name = step.get("callDataType", "UNKNOWN")
        to_address = step.get("to", "")
        input_data = step.get("serializedData", "")
        amount = _hex_to_minimal(step.get("value", "0"))
        simulation = gateway_simulate(
            {
                "from": step.get("from") or address,
                "to": to_address,
                "data": input_data,
                "amount": amount,
                "chain": chain,
            }
        )
        if isinstance(simulation, dict) and simulation.get("ok") is False:
            return False, {"stage": step_name, "simulate": simulation, "executed": executed}
        ok, result = wallet_contract_call(
            to_address=to_address,
            input_data=input_data,
            chain=chain,
            from_address=address,
            amount=amount,
        )
        executed.append({"step": step_name, "result": result})
        if not ok:
            return False, {"stage": step_name, "executed": executed}
    return True, {"steps": executed}


def defi_invest_execute(
    investment_id: int | str,
    address: str,
    token: str,
    amount_readable: float,
    chain: str = "196",
    decimals: int = 6,
) -> tuple[bool, dict]:
    plan = defi_invest_plan(investment_id, address, token, amount_readable, chain=chain, decimals=decimals)
    if not plan:
        return False, {"error": "defi invest plan failed", "investment_id": investment_id}
    return _execute_call_bundle(plan, address, str(chain))


def defi_withdraw_execute(
    investment_id: int | str,
    address: str,
    chain: str = "196",
    ratio: str = "0.25",
) -> tuple[bool, dict]:
    plan = defi_withdraw_plan(investment_id, address, chain=chain, ratio=ratio)
    if not plan:
        return False, {"error": "defi withdraw plan failed", "investment_id": investment_id}
    return _execute_call_bundle(plan, address, str(chain))


def audit_log_export() -> dict:
    """The audit CLI does not exist in onchainos 2.2.5."""
    return {"ok": False, "unsupported": True, "reason": "onchainos 2.2.5 has no audit command"}
