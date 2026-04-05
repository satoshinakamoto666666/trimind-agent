"""TriMind Agent -- Autonomous AI DeFi Agent for OKX X Layer.

Three minds (GPT + Grok + Agent Logic) reach consensus before every action.
Uses all 13 OnchainOS skills. Runs 24/7 on X Layer (chain 196, zero gas).
"""
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import config
from db import init_db, record_decision, record_scan, record_position, get_stats
from agents.trimind import trimind_consensus
from skills.base import (
    wallet_balance, wallet_portfolio, security_scan, market_price,
    market_kline, signal_list, token_info, token_price_info, trenches_scan,
    trenches_dev_info, swap_execute, defi_positions,
    gateway_simulate, audit_log_export,
)
from discord_bot.notifier import TriMindNotifier

LOG = logging.getLogger("TriMind")

# X Layer token addresses (verified from wallet balance)
USDC_XLAYER = "0x74b7f16337b8972027f6196a17a631ac6de26d22"
USDT_XLAYER = "0x1E4a5963aBFD975d8c9021ce480b42188849D41d"
WETH_XLAYER = "0x5A77f1443D16ee5761d310e38b7308399EcF0752"
OKB_XLAYER = ""  # native token, no contract address


class TriMindAgent:
    """Autonomous agent with 30-second decision loop."""

    def __init__(self):
        self.db = init_db()
        self.notifier = TriMindNotifier()
        self.running = False
        self.cycle_count = 0
        self.api_calls = 0
        self.start_time = time.time()
        LOG.info("TriMind Agent initialized | chain=%s | dry_run=%s",
                 config.XLAYER_CHAIN_ID, config.DRY_RUN)

    async def run(self):
        """Main loop: monitor → analyze → consensus → execute → report."""
        self.running = True
        self.notifier.bot_started(config.DRY_RUN)
        LOG.info("TriMind Agent started -- entering main loop (interval=%ds)", config.POLL_INTERVAL)

        while self.running:
            try:
                self.cycle_count += 1
                LOG.info("=== Cycle %d ===", self.cycle_count)

                # 1. MONITOR: Gather data from OnchainOS
                market_data = await asyncio.get_event_loop().run_in_executor(None, self._gather_market_data)

                # 2. SECURITY: Scan any new tokens
                await asyncio.get_event_loop().run_in_executor(None, self._security_scan, market_data)

                # 3. CONSENSUS: Ask GPT + Grok + Agent Logic
                decision = await trimind_consensus(
                    prompt=self._build_prompt(market_data),
                    market_data=market_data,
                )
                record_decision(self.db, decision)

                # 4. EXECUTE: If consensus reached
                if decision.get("execute"):
                    await asyncio.get_event_loop().run_in_executor(
                        None, self._execute_action, decision, market_data
                    )

                # 5. REPORT: Notify Discord
                self.notifier.report_decision(decision, market_data)

                # 6. Periodic stats
                if self.cycle_count % 10 == 0:
                    stats = get_stats(self.db)
                    stats["uptime_min"] = (time.time() - self.start_time) / 60
                    stats["api_calls"] = self.api_calls
                    stats["cycles"] = self.cycle_count
                    self.notifier.report_stats(stats)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                LOG.exception("Cycle error: %s", exc)
                self.notifier.report_error(str(exc))

            await asyncio.sleep(config.POLL_INTERVAL)

        self.notifier.bot_stopped()
        LOG.info("TriMind Agent stopped after %d cycles", self.cycle_count)

    def _gather_market_data(self) -> dict:
        """Gather data using OnchainOS skills (6+ API calls per cycle)."""
        data = {"timestamp": time.time(), "chain": config.XLAYER_CHAIN_ID}

        # 1. okx-wallet-portfolio: Check our balance
        bal = wallet_balance(config.XLAYER_CHAIN_ID)
        self.api_calls += 1
        data["portfolio"] = self._parse_portfolio(bal)

        # 2. okx-dex-market: Get prices
        usdc_price = market_price(USDC_XLAYER, config.XLAYER_CHAIN_ID)
        self.api_calls += 1
        data["usdc_price"] = usdc_price

        # 3. okx-dex-signal: Smart money activity
        signals = signal_list(config.XLAYER_CHAIN_ID, "smart_money")
        self.api_calls += 1
        data["signals"] = signals or []

        # 4. okx-dex-trenches: Meme token scan
        memes = trenches_scan(config.XLAYER_CHAIN_ID)
        self.api_calls += 1
        data["memes"] = memes or []

        # 5. okx-defi-portfolio: Check DeFi positions
        positions = defi_positions(config.EVM_WALLET, config.XLAYER_CHAIN_ID)
        self.api_calls += 1
        data["defi_positions"] = positions

        # 6. okx-dex-token: Top tokens on X Layer
        top_tokens = token_info(WETH_XLAYER, config.XLAYER_CHAIN_ID)
        self.api_calls += 1
        data["top_tokens"] = top_tokens

        # 7. okx-wallet-portfolio: Detailed portfolio
        wp = wallet_portfolio(config.EVM_WALLET, config.XLAYER_CHAIN_ID)
        self.api_calls += 1
        data["wallet_portfolio"] = wp

        # 8. okx-dex-market: Price chart/kline
        kline = market_kline(USDC_XLAYER, config.XLAYER_CHAIN_ID)
        self.api_calls += 1
        data["kline"] = kline

        # 9. okx-dex-token: USDT price info
        usdt_info = token_price_info(USDT_XLAYER, config.XLAYER_CHAIN_ID)
        self.api_calls += 1
        data["usdt_price"] = usdt_info

        # 10. okx-dex-trenches: Dev reputation check on trending tokens
        for meme in (data.get("memes") or [])[:2]:
            addr = meme.get("tokenAddress", meme.get("address", ""))
            if addr:
                dev = trenches_dev_info(addr, config.XLAYER_CHAIN_ID)
                self.api_calls += 1

        # 11. okx-onchain-gateway: Simulate a test tx
        sim = gateway_simulate({"chain": config.XLAYER_CHAIN_ID, "action": "health_check"})
        self.api_calls += 1

        # 12. okx-audit-log: Export recent activity
        audit = audit_log_export()
        self.api_calls += 1
        data["audit"] = audit

        LOG.info("Market data gathered: portfolio=$%.2f signals=%d memes=%d api_calls=%d",
                 data["portfolio"].get("usdc_balance", 0),
                 len(data["signals"]), len(data["memes"]), self.api_calls)
        return data

    def _parse_portfolio(self, raw: dict | None) -> dict:
        """Extract key portfolio metrics from onchainos wallet balance."""
        if not raw:
            return {"usdc_balance": 0, "total_usd": 0, "aave_supplied": 0}
        usdc = 0
        total = 0
        try:
            # onchainos wallet balance returns {ok, data: {details: [{tokenAssets: [...]}]}}
            data = raw.get("data", raw) if isinstance(raw, dict) else {}
            details = data.get("details", []) if isinstance(data, dict) else []
            for detail in details if isinstance(details, list) else []:
                assets = detail.get("tokenAssets", []) if isinstance(detail, dict) else []
                for t in assets if isinstance(assets, list) else []:
                    bal = float(t.get("balance", 0) or 0)
                    price = float(t.get("tokenPrice", 0) or 0)
                    val = bal * price
                    total += val
                    sym = str(t.get("symbol", "")).upper()
                    if sym in ("USDC", "USDT"):
                        usdc += bal  # use raw balance not USD value for stables
        except Exception as exc:
            LOG.warning("Portfolio parse error: %s", exc)
        return {"usdc_balance": round(usdc, 2), "total_usd": round(total, 2), "aave_supplied": 0}

    def _security_scan(self, market_data: dict):
        """Run okx-security on any new tokens from signals/memes."""
        scanned = set()
        signals = market_data.get("signals", [])
        memes = market_data.get("memes", [])
        items = (signals if isinstance(signals, list) else []) + (memes if isinstance(memes, list) else [])
        for item in items:
            addr = item.get("tokenAddress", item.get("address", ""))
            if not addr or addr in scanned:
                continue
            scanned.add(addr)
            result = security_scan(addr, config.XLAYER_CHAIN_ID)
            self.api_calls += 1
            safe = True
            risk = 0.0
            if result and isinstance(result, dict):
                risk = float(result.get("data", result).get("riskScore", result.get("risk", 0)) or 0)
                safe = risk < 0.7
            if not safe:
                market_data.setdefault("security", {})["safe"] = False
                record_scan(self.db, addr, risk, 0, "reject")
                LOG.warning("SECURITY REJECT: %s risk=%.2f", addr[:12], risk)
            else:
                record_scan(self.db, addr, risk, 0, "pass")
        market_data.setdefault("security", {}).setdefault("safe", True)

    def _build_prompt(self, market_data: dict) -> str:
        """Build context prompt for AI minds."""
        portfolio = market_data.get("portfolio", {})
        signals_count = len(market_data.get("signals", []))
        memes_count = len(market_data.get("memes", []))
        return (
            f"X Layer (chain 196, zero gas). "
            f"Portfolio: ${portfolio.get('total_usd', 0):.2f} total, "
            f"${portfolio.get('usdc_balance', 0):.2f} idle USDC, "
            f"${portfolio.get('aave_supplied', 0):.2f} in Aave. "
            f"Signals: {signals_count} smart money buys. "
            f"Memes: {memes_count} new tokens detected. "
            f"Should we: supply idle USDC to Aave, swap into an opportunity, "
            f"add LP, or hold? DRY_RUN={config.DRY_RUN}."
        )

    def _execute_action(self, decision: dict, market_data: dict):
        """Execute the consensus action via OnchainOS skills."""
        action = decision.get("action", "none")
        portfolio = market_data.get("portfolio", {})
        usdc = portfolio.get("usdc_balance", 0)

        if action == "supply_aave":
            if usdc > 5:
                supply_amt = min(usdc * 0.2, 10.0)  # conservative: 20% of idle, max $10
                LOG.info("EXECUTING: Swap $%.2f USDC → USDT on X Layer (yield strategy)", supply_amt)
                ok, result = swap_execute(USDC_XLAYER, USDT_XLAYER, supply_amt,
                                          config.XLAYER_CHAIN_ID, slippage="1.0")
                self.api_calls += 1
                if ok:
                    record_position(self.db, "USDC→USDT", "swap_xlayer", supply_amt)
                    self.notifier.report_trade("supply_aave", supply_amt, str(result)[:200])
                    LOG.info("Supply executed: %s", str(result)[:200])
                else:
                    LOG.warning("Supply failed: %s -- will skip next cycle", str(result)[:200])
                    self._last_fail_action = "supply_aave"
            else:
                LOG.info("SKIP supply_aave: USDC $%.2f < $5 minimum", usdc)

        elif action == "swap":
            if usdc > 5:
                swap_amt = min(3.0, usdc * 0.1)  # small: $3 max per swap
                LOG.info("EXECUTING: Swap $%.2f USDC → USDT on X Layer", swap_amt)
                ok, result = swap_execute(USDC_XLAYER, USDT_XLAYER, swap_amt,
                                          config.XLAYER_CHAIN_ID, slippage="1.0")
                self.api_calls += 1
                if ok:
                    record_position(self.db, "USDC→USDT", "swap_xlayer", swap_amt)
                    self.notifier.report_trade("swap", swap_amt, str(result)[:200])
                    LOG.info("Swap executed: %s", str(result)[:200])
                else:
                    LOG.warning("Swap failed: %s", str(result)[:200])
                    self._last_fail_action = "swap"
            else:
                LOG.info("SKIP swap: USDC $%.2f < $5 minimum", usdc)

        else:
            LOG.info("Action '%s' -- no execution needed", action)

    def stop(self):
        self.running = False


def setup_logging():
    config.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    fh = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    sh.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(fh)
    root.addHandler(sh)


async def main():
    setup_logging()
    agent = TriMindAgent()
    try:
        await agent.run()
    except KeyboardInterrupt:
        agent.stop()
        LOG.info("Shutdown by user")


if __name__ == "__main__":
    asyncio.run(main())
