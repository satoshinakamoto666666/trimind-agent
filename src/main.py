"""TriMind Agent -- Autonomous AI DeFi Agent for OKX X Layer."""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import config
from agents.trimind import trimind_consensus
from db import get_stats, init_db, record_decision, record_position, record_scan, update_decision_result
from discord_bot.notifier import TriMindNotifier
from skills.base import (
    defi_detail,
    defi_invest_execute,
    defi_positions,
    defi_search,
    defi_withdraw_execute,
    gateway_simulate,
    market_price,
    portfolio_total_value,
    security_scan,
    signal_list,
    swap_execute,
    swap_quote,
    token_info,
    token_price_info,
    trenches_dev_info,
    trenches_scan,
    wallet_portfolio,
)

LOG = logging.getLogger("TriMind")

USDC_XLAYER = "0x74b7f16337b8972027f6196a17a631ac6de26d22"
USDT_XLAYER = "0x1E4a5963aBFD975d8c9021ce480b42188849D41d"
AAVE_USDT_XLAYER = "0x779ded0c9e1022225f8e0630b35a9b54be713736"
WETH_XLAYER = "0x5A77f1443D16ee5761d310e38b7308399EcF0752"


class TriMindAgent:
    """Autonomous agent with a multi-stage decision loop."""

    def __init__(self):
        self.db = init_db()
        self.notifier = TriMindNotifier()
        self.running = False
        self.cycle_count = 0
        self.api_calls = 0
        self.start_time = time.time()
        LOG.info("TriMind Agent initialized | chain=%s | dry_run=%s", config.XLAYER_CHAIN_ID, config.DRY_RUN)

    async def run(self):
        self.running = True
        self.notifier.bot_started(config.DRY_RUN)
        LOG.info("TriMind Agent started -- entering main loop (interval=%ds)", config.POLL_INTERVAL)

        while self.running:
            try:
                self.cycle_count += 1
                LOG.info("=== Cycle %d ===", self.cycle_count)

                market_data = await asyncio.get_event_loop().run_in_executor(None, self._gather_market_data)
                await asyncio.get_event_loop().run_in_executor(None, self._security_scan, market_data)

                decision = await trimind_consensus(
                    prompt=self._build_prompt(market_data),
                    market_data=market_data,
                )
                decision_id = record_decision(self.db, {**decision, "executed": False, "result": ""})

                execution_ok = False
                execution_result = "no execution"
                if decision.get("execute"):
                    execution_ok, execution_result = await asyncio.get_event_loop().run_in_executor(
                        None, self._execute_action, decision, market_data
                    )

                update_decision_result(self.db, decision_id, execution_ok, execution_result)
                self.notifier.report_decision(decision, market_data)

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
        """Gather data using legitimate OnchainOS calls."""
        data = {"timestamp": time.time(), "chain": config.XLAYER_CHAIN_ID}

        portfolio_raw = wallet_portfolio(config.EVM_WALLET, config.XLAYER_CHAIN_ID)
        self.api_calls += 1
        portfolio_total = portfolio_total_value(config.EVM_WALLET, config.XLAYER_CHAIN_ID)
        self.api_calls += 1
        data["wallet_portfolio"] = portfolio_raw
        data["portfolio"] = self._parse_portfolio(portfolio_raw, portfolio_total)

        usdc_price = market_price(USDC_XLAYER, config.XLAYER_CHAIN_ID)
        self.api_calls += 1
        data["usdc_price"] = usdc_price

        usdt_info = token_price_info(USDT_XLAYER, config.XLAYER_CHAIN_ID)
        self.api_calls += 1
        data["usdt_price"] = usdt_info

        signals = signal_list(config.XLAYER_CHAIN_ID, "smart_money")
        self.api_calls += 1
        data["signals"] = signals or []

        memes = trenches_scan(config.XLAYER_CHAIN_ID)
        self.api_calls += 1
        data["memes"] = memes[:25] if isinstance(memes, list) else []

        positions = defi_positions(config.EVM_WALLET, config.XLAYER_CHAIN_ID)
        self.api_calls += 1
        data["defi_positions"] = positions

        weth_info = token_info(WETH_XLAYER, config.XLAYER_CHAIN_ID)
        self.api_calls += 1
        data["top_tokens"] = weth_info

        quote_specs = {
            "rebalance_3": (USDT_XLAYER, USDC_XLAYER, 3.0),
            "rebalance_5": (USDT_XLAYER, USDC_XLAYER, 5.0),
            "yield_3": (USDT_XLAYER, AAVE_USDT_XLAYER, 3.0),
            "swap_3": (USDC_XLAYER, USDT_XLAYER, 3.0),
            "diversify_1": (USDC_XLAYER, WETH_XLAYER, 1.0),
        }
        data["quotes"] = {}
        for name, (from_token, to_token, amount) in quote_specs.items():
            quote = swap_quote(from_token, to_token, amount, config.XLAYER_CHAIN_ID)
            self.api_calls += 1
            data["quotes"][name] = self._quote_summary(quote, amount)

        aave_market = self._discover_aave_market()
        self.api_calls += 2
        data["aave_market"] = aave_market

        for meme in (data.get("memes") or [])[:2]:
            addr = meme.get("tokenAddress", meme.get("address", ""))
            if addr:
                trenches_dev_info(addr, config.XLAYER_CHAIN_ID)
                self.api_calls += 1

        data["health_check"] = gateway_simulate(
            {
                "from": config.EVM_WALLET,
                "to": config.EVM_WALLET,
                "data": "0x",
                "amount": "0",
                "chain": config.XLAYER_CHAIN_ID,
            }
        )
        self.api_calls += 1

        LOG.info(
            "Market data gathered: USDC=$%.2f XLAYER_USDT=$%.2f AAVE_USDT=$%.2f WETH=$%.2f signals=%d memes=%d api_calls=%d",
            data["portfolio"].get("usdc_balance", 0),
            data["portfolio"].get("xlayer_usdt_balance", 0),
            data["portfolio"].get("canonical_usdt_balance", 0),
            data["portfolio"].get("weth_usd", 0),
            len(data["signals"]),
            len(data["memes"]),
            self.api_calls,
        )
        return data

    def _discover_aave_market(self) -> dict:
        search = defi_search(token="USDT", platform="Aave V3", chain=config.XLAYER_CHAIN_ID)
        if not search or not isinstance(search, dict):
            return {}
        listing = search.get("data", {}).get("list", [])
        if not isinstance(listing, list) or not listing:
            return {}
        selected = listing[0]
        detail = defi_detail(selected.get("investmentId"), config.XLAYER_CHAIN_ID) or {}
        detail_data = detail.get("data", detail) if isinstance(detail, dict) else {}
        underlying = detail_data.get("underlyingToken", [{}])
        underlying_token = underlying[0].get("tokenAddress", AAVE_USDT_XLAYER) if isinstance(underlying, list) else AAVE_USDT_XLAYER
        return {
            "investment_id": int(selected.get("investmentId")),
            "platform_name": selected.get("platformName", "Aave V3"),
            "name": selected.get("name", "USDT"),
            "apy": float(detail_data.get("rate", 0) or 0),
            "underlying_token": underlying_token,
            "detail": detail_data,
        }

    def _quote_summary(self, quote: dict | None, amount: float) -> dict:
        if not quote or not isinstance(quote, dict):
            return {"ok": False, "amount": amount}
        entries = quote.get("data", quote)
        if not isinstance(entries, list) or not entries:
            return {"ok": False, "amount": amount}
        item = entries[0] if isinstance(entries[0], dict) else {}
        to_token = item.get("toToken", {})
        decimals = int(to_token.get("decimal", 0) or 0)
        raw_amount = float(item.get("toTokenAmount", 0) or 0)
        received = raw_amount / (10 ** decimals) if decimals else raw_amount
        return {
            "ok": True,
            "amount": amount,
            "to_amount": round(received, 6),
            "price_impact": float(item.get("priceImpactPercent", 0) or 0),
            "route": [
                leg.get("dexProtocol", {}).get("dexName", "")
                for leg in item.get("dexRouterList", [])
                if isinstance(leg, dict)
            ],
        }

    def _iter_token_assets(self, raw: dict | None) -> list[dict]:
        if not raw:
            return []
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(data, list):
            buckets = data
        elif isinstance(data, dict):
            buckets = data.get("details", [])
        else:
            buckets = []
        assets: list[dict] = []
        for bucket in buckets if isinstance(buckets, list) else []:
            token_assets = bucket.get("tokenAssets", []) if isinstance(bucket, dict) else []
            if isinstance(token_assets, list):
                assets.extend(item for item in token_assets if isinstance(item, dict))
        return assets

    def _parse_portfolio(self, raw: dict | None, total_value_raw: dict | None) -> dict:
        portfolio = {
            "usdc_balance": 0.0,
            "usdt_balance": 0.0,
            "xlayer_usdt_balance": 0.0,
            "canonical_usdt_balance": 0.0,
            "weth_balance": 0.0,
            "weth_usd": 0.0,
            "okb_balance": 0.0,
            "okb_usd": 0.0,
            "total_usd": 0.0,
            "aave_supplied": 0.0,
        }
        total = 0.0
        for token in self._iter_token_assets(raw):
            balance = float(token.get("balance", 0) or 0)
            price = float(token.get("tokenPrice", 0) or 0)
            value = balance * price
            symbol = str(token.get("symbol", "")).upper()
            address = str(token.get("tokenContractAddress", "")).lower()
            total += value
            if symbol == "USDC" and address == USDC_XLAYER.lower():
                portfolio["usdc_balance"] += balance
            elif symbol == "USDT":
                portfolio["usdt_balance"] += balance
                if address == USDT_XLAYER.lower():
                    portfolio["xlayer_usdt_balance"] += balance
                elif address == AAVE_USDT_XLAYER.lower():
                    portfolio["canonical_usdt_balance"] += balance
            elif address == WETH_XLAYER.lower() or symbol == "WETH":
                portfolio["weth_balance"] += balance
                portfolio["weth_usd"] += value
            elif symbol == "OKB":
                portfolio["okb_balance"] += balance
                portfolio["okb_usd"] += value

        if isinstance(total_value_raw, dict):
            entries = total_value_raw.get("data", [])
            if isinstance(entries, list) and entries:
                try:
                    total = float(entries[0].get("totalValue", total) or total)
                except Exception:
                    total = total

        portfolio["total_usd"] = round(total, 2)
        portfolio["usdc_balance"] = round(portfolio["usdc_balance"], 2)
        portfolio["usdt_balance"] = round(portfolio["usdt_balance"], 2)
        portfolio["xlayer_usdt_balance"] = round(portfolio["xlayer_usdt_balance"], 2)
        portfolio["canonical_usdt_balance"] = round(portfolio["canonical_usdt_balance"], 2)
        portfolio["weth_balance"] = round(portfolio["weth_balance"], 6)
        portfolio["weth_usd"] = round(portfolio["weth_usd"], 2)
        portfolio["okb_balance"] = round(portfolio["okb_balance"], 4)
        portfolio["okb_usd"] = round(portfolio["okb_usd"], 2)
        return portfolio

    def _security_scan(self, market_data: dict):
        scanned = set()
        signals = market_data.get("signals", [])
        memes = market_data.get("memes", [])
        items = (signals if isinstance(signals, list) else []) + (memes if isinstance(memes, list) else [])
        for item in items[:20]:
            addr = item.get("tokenAddress", item.get("tokenContractAddress", item.get("address", "")))
            if not addr or addr in scanned:
                continue
            scanned.add(addr)
            result = security_scan(addr, config.XLAYER_CHAIN_ID)
            self.api_calls += 1
            safe = True
            risk = 0.0
            if isinstance(result, dict):
                inner = result.get("data", result)
                if isinstance(inner, dict):
                    risk = float(inner.get("riskScore", inner.get("risk", 0)) or 0)
                    safe = risk < 0.7
            if not safe:
                market_data.setdefault("security", {})["safe"] = False
                record_scan(self.db, addr, risk, 0, "reject")
                LOG.warning("SECURITY REJECT: %s risk=%.2f", addr[:12], risk)
            else:
                record_scan(self.db, addr, risk, 0, "pass")
        market_data.setdefault("security", {}).setdefault("safe", True)

    def _build_prompt(self, market_data: dict) -> str:
        portfolio = market_data.get("portfolio", {})
        signals_count = len(market_data.get("signals", []))
        memes_count = len(market_data.get("memes", []))
        aave_market = market_data.get("aave_market", {})
        quotes = market_data.get("quotes", {})
        rebalance_quote = quotes.get("rebalance_3", {})
        yield_quote = quotes.get("yield_3", {})
        return (
            f"X Layer chain 196. Portfolio ${portfolio.get('total_usd', 0):.2f} total with "
            f"USDC ${portfolio.get('usdc_balance', 0):.2f}, "
            f"XLAYER USDT ${portfolio.get('xlayer_usdt_balance', 0):.2f}, "
            f"Aave-ready USDT ${portfolio.get('canonical_usdt_balance', 0):.2f}, "
            f"WETH ${portfolio.get('weth_usd', 0):.2f}. "
            f"Aave USDT APY {aave_market.get('apy', 0):.2%}. "
            f"Quote USDT->USDC 3 receives {rebalance_quote.get('to_amount', 0):.4f}. "
            f"Quote XLAYER USDT->Aave USDT 3 receives {yield_quote.get('to_amount', 0):.4f}. "
            f"Signals {signals_count}, memes {memes_count}, dry_run={config.DRY_RUN}. "
            f"Choose among rebalance, supply_aave, swap, diversify, withdraw, or hold."
        )

    def _extract_tx_ref(self, result: dict | str) -> str:
        if isinstance(result, str):
            return ""
        if isinstance(result, dict):
            for key in ("txHash", "hash", "orderId"):
                if key in result:
                    return str(result[key])
            for step in result.get("steps", []):
                if isinstance(step, dict):
                    nested = step.get("result", {})
                    if isinstance(nested, dict):
                        for key in ("txHash", "hash", "orderId"):
                            if key in nested:
                                return str(nested[key])
        return ""

    def _execute_action(self, decision: dict, market_data: dict) -> tuple[bool, str]:
        action = decision.get("action", "none")
        portfolio = market_data.get("portfolio", {})
        usdc = float(portfolio.get("usdc_balance", 0))
        xlayer_usdt = float(portfolio.get("xlayer_usdt_balance", portfolio.get("usdt_balance", 0)))
        canonical_usdt = float(portfolio.get("canonical_usdt_balance", 0))
        total_usd = float(portfolio.get("total_usd", 0))
        aave_market = market_data.get("aave_market", {})

        if action == "supply_aave":
            if not aave_market:
                LOG.info("SKIP supply_aave: no Aave market discovered")
                return False, "no aave market"
            if xlayer_usdt < max(5.0, config.MIN_TRADE_USD):
                LOG.info("SKIP supply_aave: XLAYER USDT $%.2f below minimum", xlayer_usdt)
                return False, "insufficient xlayer usdt"
            supply_amt = min(config.MAX_REBALANCE_USD, max(2.0, xlayer_usdt * 0.10))
            underlying = aave_market.get("underlying_token", AAVE_USDT_XLAYER)
            if canonical_usdt + 0.01 < supply_amt:
                LOG.info("EXECUTING: convert $%.2f XLAYER USDT -> Aave USDT", supply_amt)
                ok, result = swap_execute(
                    USDT_XLAYER,
                    underlying,
                    supply_amt,
                    config.XLAYER_CHAIN_ID,
                    slippage=config.MAX_SLIPPAGE,
                )
                self.api_calls += 1
                if not ok:
                    LOG.warning("Aave funding swap failed: %s", json.dumps(result, default=str)[:300])
                    return False, json.dumps(result, default=str)[:1000]

            LOG.info("EXECUTING: supply $%.2f into Aave V3 USDT market %s", supply_amt, aave_market.get("investment_id"))
            ok, result = defi_invest_execute(
                investment_id=aave_market.get("investment_id"),
                address=config.EVM_WALLET,
                token=underlying,
                amount_readable=supply_amt,
                chain=config.XLAYER_CHAIN_ID,
                decimals=6,
            )
            self.api_calls += 1
            if ok:
                tx_ref = self._extract_tx_ref(result)
                record_position(self.db, "AAVE_USDT", "aave_v3_supply", supply_amt, tx_ref)
                self.notifier.report_trade("supply_aave", supply_amt, result)
                return True, json.dumps(result, default=str)[:1000]
            LOG.warning("Aave supply failed: %s", json.dumps(result, default=str)[:300])
            return False, json.dumps(result, default=str)[:1000]

        if action == "rebalance":
            if xlayer_usdt < config.MIN_TRADE_USD:
                LOG.info("SKIP rebalance: XLAYER USDT $%.2f below minimum", xlayer_usdt)
                return False, "insufficient xlayer usdt"
            target_shortfall = max(total_usd * config.TARGET_USDC_SHARE - usdc, config.MIN_TRADE_USD)
            rebal_amt = min(target_shortfall, config.MAX_REBALANCE_USD, xlayer_usdt)
            LOG.info("EXECUTING: rebalance $%.2f XLAYER USDT -> USDC", rebal_amt)
            ok, result = swap_execute(
                USDT_XLAYER,
                USDC_XLAYER,
                rebal_amt,
                config.XLAYER_CHAIN_ID,
                slippage=config.MAX_SLIPPAGE,
            )
            self.api_calls += 1
            if ok:
                tx_ref = self._extract_tx_ref(result)
                record_position(self.db, "USDT->USDC", "rebalance_xlayer", rebal_amt, tx_ref)
                self.notifier.report_trade("rebalance", rebal_amt, result)
                return True, json.dumps(result, default=str)[:1000]
            LOG.warning("Rebalance failed: %s", json.dumps(result, default=str)[:300])
            return False, json.dumps(result, default=str)[:1000]

        if action == "swap":
            if usdc < config.MIN_TRADE_USD:
                LOG.info("SKIP swap: USDC $%.2f below minimum", usdc)
                return False, "insufficient usdc"
            swap_amt = min(config.MAX_REBALANCE_USD, max(config.MIN_TRADE_USD, usdc * 0.25))
            LOG.info("EXECUTING: tactical swap $%.2f USDC -> XLAYER USDT", swap_amt)
            ok, result = swap_execute(
                USDC_XLAYER,
                USDT_XLAYER,
                swap_amt,
                config.XLAYER_CHAIN_ID,
                slippage=config.MAX_SLIPPAGE,
            )
            self.api_calls += 1
            if ok:
                tx_ref = self._extract_tx_ref(result)
                record_position(self.db, "USDC->USDT", "swap_xlayer", swap_amt, tx_ref)
                self.notifier.report_trade("swap", swap_amt, result)
                return True, json.dumps(result, default=str)[:1000]
            LOG.warning("Swap failed: %s", json.dumps(result, default=str)[:300])
            return False, json.dumps(result, default=str)[:1000]

        if action == "diversify":
            if usdc < 2 or total_usd < 25:
                LOG.info("SKIP diversify: USDC $%.2f total $%.2f too small", usdc, total_usd)
                return False, "portfolio too small"
            div_amt = min(config.MAX_DIVERSIFY_USD, max(1.0, usdc * 0.15))
            LOG.info("EXECUTING: diversify $%.2f USDC -> WETH", div_amt)
            ok, result = swap_execute(
                USDC_XLAYER,
                WETH_XLAYER,
                div_amt,
                config.XLAYER_CHAIN_ID,
                slippage=config.MAX_SLIPPAGE,
            )
            self.api_calls += 1
            if ok:
                tx_ref = self._extract_tx_ref(result)
                record_position(self.db, "USDC->WETH", "diversify_beta", div_amt, tx_ref)
                self.notifier.report_trade("diversify", div_amt, result)
                return True, json.dumps(result, default=str)[:1000]
            LOG.warning("Diversify failed: %s", json.dumps(result, default=str)[:300])
            return False, json.dumps(result, default=str)[:1000]

        if action == "withdraw":
            if not aave_market:
                LOG.info("SKIP withdraw: no Aave market discovered")
                return False, "no aave market"
            LOG.info("EXECUTING: withdraw 25%% from Aave market %s", aave_market.get("investment_id"))
            ok, result = defi_withdraw_execute(
                investment_id=aave_market.get("investment_id"),
                address=config.EVM_WALLET,
                chain=config.XLAYER_CHAIN_ID,
                ratio="0.25",
            )
            self.api_calls += 1
            if ok:
                self.notifier.report_trade("withdraw", 0.0, result)
                return True, json.dumps(result, default=str)[:1000]
            LOG.warning("Withdraw failed: %s", json.dumps(result, default=str)[:300])
            return False, json.dumps(result, default=str)[:1000]

        LOG.info("Action '%s' -- no execution needed", action)
        return False, "hold"

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
    root.handlers.clear()
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
