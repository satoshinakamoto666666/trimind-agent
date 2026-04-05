"""Discord notifier for TriMind Agent."""

import atexit
import json
import logging
import queue
import threading
import time

import requests

from config import DISCORD_WEBHOOK_URL

LOG = logging.getLogger("TriMindDiscord")

GREEN = 0x00FF00
RED = 0xE74C3C
BLUE = 0x3498DB
YELLOW = 0xF1C40F


class TriMindNotifier:
    """Sends Discord embeds on a background worker thread."""

    def __init__(self):
        self._url = DISCORD_WEBHOOK_URL
        self._queue: queue.Queue[dict] = queue.Queue(maxsize=256)
        self._stop = threading.Event()
        self._session = requests.Session()
        self._worker = threading.Thread(target=self._run, name="trimind-discord", daemon=True)
        self._last_sent = 0.0
        if self._url:
            self._worker.start()
            atexit.register(self.close)

    def close(self):
        if not self._url:
            return
        self._stop.set()
        if self._worker.is_alive():
            self._worker.join(timeout=2)
        self._session.close()

    def _run(self):
        while not self._stop.is_set() or not self._queue.empty():
            try:
                embed = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            wait_for = 1.25 - (time.time() - self._last_sent)
            if wait_for > 0:
                time.sleep(wait_for)

            payload = {
                "username": "TriMind Agent",
                "embeds": [embed],
                "allowed_mentions": {"parse": []},
            }
            try:
                resp = self._session.post(self._url, json=payload, timeout=10)
                self._last_sent = time.time()
                if resp.status_code == 429:
                    retry_after = 2.0
                    try:
                        retry_after = float(resp.json().get("retry_after", 2))
                    except Exception:
                        retry_after = 2.0
                    time.sleep(max(1.0, retry_after))
            except Exception as exc:
                LOG.debug("Discord send error: %s", exc)
            finally:
                self._queue.task_done()

    def _send(self, embed: dict):
        if not self._url:
            return
        try:
            self._queue.put_nowait(embed)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(embed)
            except queue.Full:
                LOG.debug("Dropping Discord embed because queue is full")

    def bot_started(self, dry_run: bool):
        self._send(
            {
                "title": "TRIMIND AGENT STARTED",
                "description": f"Mode: {'DRY RUN' if dry_run else 'LIVE'} | Chain: X Layer (196)",
                "color": GREEN,
                "fields": [
                    {"name": "Mind 1", "value": "GPT quantitative strategy", "inline": True},
                    {"name": "Mind 2", "value": "Grok flow and sentiment", "inline": True},
                    {"name": "Mind 3", "value": "Agent rule engine", "inline": True},
                ],
                "timestamp": self._iso(),
            }
        )

    def bot_stopped(self):
        self._send({"title": "TRIMIND AGENT STOPPED", "color": RED, "timestamp": self._iso()})

    def report_decision(self, decision: dict, market_data: dict):
        votes = decision.get("votes", {})
        consensus = decision.get("consensus", False)
        action = decision.get("action", "none")
        execute = decision.get("execute", False)

        vote_lines = []
        emoji_map = {"EXECUTE": "[+]", "SKIP": "[-]", "HOLD": "[ ]"}
        for name, vote in votes.items():
            emoji = emoji_map.get(vote.get("vote", "HOLD"), "[?]")
            confidence = float(vote.get("confidence", 0))
            vote_lines.append(
                f"{emoji} {name.upper()}: {vote.get('vote', '?')} / {vote.get('action', 'none')} ({confidence:.0%}) - {vote.get('reasoning', '?')}"
            )

        color = GREEN if execute else YELLOW if consensus else RED
        portfolio = market_data.get("portfolio", {})
        fields = [
            {"name": "Council Votes", "value": "\n".join(vote_lines)[:1024] or "No votes", "inline": False},
            {
                "name": "Consensus",
                "value": f"{'YES' if consensus else 'NO'} ({decision.get('execute_count', 0)}/3 execute)",
                "inline": True,
            },
            {"name": "Action", "value": action.upper() if execute else "HOLD", "inline": True},
            {"name": "Avg Confidence", "value": f"{decision.get('avg_confidence', 0):.0%}", "inline": True},
            {
                "name": "Portfolio",
                "value": (
                    f"USDC ${portfolio.get('usdc_balance', 0):,.2f} | "
                    f"XLAYER USDT ${portfolio.get('xlayer_usdt_balance', 0):,.2f} | "
                    f"Aave USDT ${portfolio.get('canonical_usdt_balance', 0):,.2f} | "
                    f"TITAN ${portfolio.get('weth_usd', 0):,.2f}"
                )[:1024],
                "inline": False,
            },
        ]

        self._send(
            {
                "title": "TRIMIND DECISION",
                "color": color,
                "fields": fields,
                "timestamp": self._iso(),
            }
        )

    def report_stats(self, stats: dict):
        self._send(
            {
                "title": "TRIMIND STATS",
                "color": BLUE,
                "fields": [
                    {"name": "Uptime", "value": f"{stats.get('uptime_min', 0):.0f} min", "inline": True},
                    {"name": "Cycles", "value": str(stats.get("cycles", 0)), "inline": True},
                    {"name": "API Calls", "value": str(stats.get("api_calls", 0)), "inline": True},
                    {"name": "Decisions", "value": str(stats.get("total_decisions", 0)), "inline": True},
                    {"name": "Executed Trades", "value": str(stats.get("total_trades", 0)), "inline": True},
                    {"name": "Rejected Memes", "value": str(stats.get("memes_rejected", 0)), "inline": True},
                ],
                "timestamp": self._iso(),
            }
        )

    def report_trade(self, action: str, amount: float, result: str | dict):
        result_text = result if isinstance(result, str) else json.dumps(result, default=str)
        self._send(
            {
                "title": f"EXECUTED: {action.upper()}",
                "description": f"${amount:.2f} on X Layer (chain 196)",
                "color": GREEN,
                "fields": [
                    {"name": "Action", "value": action, "inline": True},
                    {"name": "Amount", "value": f"${amount:.2f}", "inline": True},
                    {"name": "Result", "value": result_text[:1024] or "No result", "inline": False},
                ],
                "timestamp": self._iso(),
            }
        )

    def report_portfolio(self, balance_data: dict):
        self._send(
            {
                "title": "X LAYER PORTFOLIO",
                "color": BLUE,
                "fields": [
                    {"name": "USDC", "value": f"${balance_data.get('usdc_balance', 0):,.2f}", "inline": True},
                    {
                        "name": "XLAYER USDT",
                        "value": f"${balance_data.get('xlayer_usdt_balance', 0):,.2f}",
                        "inline": True,
                    },
                    {
                        "name": "Aave USDT",
                        "value": f"${balance_data.get('canonical_usdt_balance', 0):,.2f}",
                        "inline": True,
                    },
                    {"name": "TITAN USD", "value": f"${balance_data.get('weth_usd', 0):,.2f}", "inline": True},
                    {"name": "OKB USD", "value": f"${balance_data.get('okb_usd', 0):,.2f}", "inline": True},
                    {"name": "Total USD", "value": f"${balance_data.get('total_usd', 0):,.2f}", "inline": False},
                ],
                "timestamp": self._iso(),
            }
        )

    def report_security_scan(self, token: str, risk_score: float, safe: bool, details: str):
        verdict = "SAFE" if safe else "UNSAFE"
        color = GREEN if safe else RED
        self._send(
            {
                "title": f"SECURITY SCAN: {verdict}",
                "color": color,
                "fields": [
                    {"name": "Token", "value": f"`{token}`", "inline": False},
                    {"name": "Risk Score", "value": f"{risk_score:.1f} / 100", "inline": True},
                    {"name": "Verdict", "value": verdict, "inline": True},
                    {"name": "Details", "value": details[:1024] if details else "No details", "inline": False},
                ],
                "timestamp": self._iso(),
            }
        )

    def report_error(self, error: str):
        self._send(
            {
                "title": "TRIMIND ERROR",
                "description": error[:1900],
                "color": RED,
                "timestamp": self._iso(),
            }
        )

    @staticmethod
    def _iso() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

