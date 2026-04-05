"""Discord notifier for TriMind Agent -- rich embeds for council decisions."""
import logging
import time
import requests
from config import DISCORD_WEBHOOK_URL

LOG = logging.getLogger("TriMindDiscord")

GREEN = 0x00FF00
RED = 0xE74C3C
BLUE = 0x3498DB
YELLOW = 0xF1C40F
PURPLE = 0x9B59B6


class TriMindNotifier:
    """Sends rich Discord embeds for TriMind decisions."""

    def __init__(self):
        self._url = DISCORD_WEBHOOK_URL
        self._last_sent = 0

    def _send(self, embed: dict):
        if not self._url:
            return
        now = time.time()
        if now - self._last_sent < 2:
            time.sleep(2 - (now - self._last_sent))
        try:
            resp = requests.post(f"{self._url}?wait=true", json={
                "username": "TriMind Agent",
                "embeds": [embed],
                "allowed_mentions": {"parse": []},
            }, timeout=10)
            self._last_sent = time.time()
            if resp.status_code == 429:
                time.sleep(3)
        except Exception as exc:
            LOG.debug("Discord send error: %s", exc)

    def bot_started(self, dry_run: bool):
        self._send({
            "title": "🧠 TRIMIND AGENT STARTED",
            "description": f"Three minds. One consensus. Zero gas.\nMode: **{'DRY RUN' if dry_run else 'LIVE'}** | Chain: X Layer (196)",
            "color": GREEN,
            "fields": [
                {"name": "Mind 1", "value": "🤖 GPT-5.4 (Strategy)", "inline": True},
                {"name": "Mind 2", "value": "🔮 Grok-4.20 (Sentiment)", "inline": True},
                {"name": "Mind 3", "value": "⚡ Agent Logic (Rules)", "inline": True},
            ],
            "timestamp": self._iso(),
        })

    def bot_stopped(self):
        self._send({
            "title": "🔴 TRIMIND AGENT STOPPED",
            "color": RED,
            "timestamp": self._iso(),
        })

    def report_decision(self, decision: dict, market_data: dict):
        """Post council vote result to Discord."""
        votes = decision.get("votes", {})
        consensus = decision.get("consensus", False)
        action = decision.get("action", "none")
        execute = decision.get("execute", False)

        # Vote display
        vote_lines = []
        emoji_map = {"EXECUTE": "✅", "SKIP": "❌", "HOLD": "⏸️"}
        for name, v in votes.items():
            emoji = emoji_map.get(v.get("vote", "HOLD"), "❓")
            conf = v.get("confidence", 0)
            vote_lines.append(f"{emoji} **{name.upper()}**: {v.get('vote', '?')} ({conf:.0%}) -- {v.get('reasoning', '?')}")

        color = GREEN if execute else YELLOW if consensus else RED

        fields = [
            {"name": "Council Votes", "value": "\n".join(vote_lines), "inline": False},
            {"name": "Consensus", "value": f"{'✅ YES' if consensus else '❌ NO'} ({decision.get('execute_count', 0)}/3)", "inline": True},
            {"name": "Action", "value": action.upper() if execute else "HOLD", "inline": True},
            {"name": "Avg Confidence", "value": f"{decision.get('avg_confidence', 0):.0%}", "inline": True},
        ]

        portfolio = market_data.get("portfolio", {})
        signals = market_data.get("signals", [])
        signal_count = len(signals) if isinstance(signals, list) else market_data.get("signal_count", 0)

        portfolio_parts = [
            f"USDC: ${portfolio.get('usdc_balance', 0):,.2f}",
            f"USDT: ${portfolio.get('usdt_balance', 0):,.2f}",
            f"OKB: {portfolio.get('okb_balance', 0):,.4f}",
            f"**Total: ${portfolio.get('total_usd', 0):,.2f}**",
        ]
        fields.append({"name": "Portfolio", "value": " | ".join(portfolio_parts), "inline": False})
        fields.append({"name": "Signals", "value": f"{signal_count} signal(s) evaluated", "inline": True})

        title = f"{'🟢 EXECUTE' if execute else '⏸️ HOLD'}: {action.upper()}" if consensus else "🔴 NO CONSENSUS"

        self._send({
            "title": f"🧠 {title}",
            "color": color,
            "fields": fields,
            "timestamp": self._iso(),
        })

    def report_stats(self, stats: dict):
        """Periodic stats embed."""
        self._send({
            "title": "📊 TRIMIND STATS",
            "color": BLUE,
            "fields": [
                {"name": "Uptime", "value": f"{stats.get('uptime_min', 0):.0f} min", "inline": True},
                {"name": "Cycles", "value": str(stats.get("cycles", 0)), "inline": True},
                {"name": "API Calls", "value": str(stats.get("api_calls", 0)), "inline": True},
                {"name": "Decisions", "value": str(stats.get("total_decisions", 0)), "inline": True},
                {"name": "Trades", "value": str(stats.get("total_trades", 0)), "inline": True},
                {"name": "Rejected", "value": str(stats.get("memes_rejected", 0)), "inline": True},
            ],
            "timestamp": self._iso(),
        })

    def report_trade(self, action: str, amount: float, result: str):
        """Trade execution embed."""
        self._send({
            "title": f"💰 EXECUTED: {action.upper()}",
            "description": f"${amount:.2f} on X Layer (chain 196)",
            "color": GREEN,
            "fields": [
                {"name": "Action", "value": action, "inline": True},
                {"name": "Amount", "value": f"${amount:.2f}", "inline": True},
                {"name": "Result", "value": str(result)[:200], "inline": False},
            ],
            "timestamp": self._iso(),
        })

    def report_portfolio(self, balance_data: dict):
        """Show current X Layer portfolio breakdown."""
        usdc = balance_data.get("usdc_balance", 0)
        usdt = balance_data.get("usdt_balance", 0)
        okb = balance_data.get("okb_balance", 0)
        total = balance_data.get("total_usd", 0)
        aave = balance_data.get("aave_positions", [])

        fields = [
            {"name": "USDC", "value": f"${usdc:,.2f}", "inline": True},
            {"name": "USDT", "value": f"${usdt:,.2f}", "inline": True},
            {"name": "OKB", "value": f"{okb:,.4f}", "inline": True},
            {"name": "Total USD Value", "value": f"**${total:,.2f}**", "inline": False},
        ]

        if aave:
            aave_lines = []
            for pos in aave:
                side = pos.get("side", "supply")
                token = pos.get("token", "?")
                amt = pos.get("amount", 0)
                apy = pos.get("apy", 0)
                aave_lines.append(f"{side.upper()} {amt:,.2f} {token} @ {apy:.2f}% APY")
            fields.append({"name": "Aave Positions", "value": "\n".join(aave_lines) or "None", "inline": False})

        self._send({
            "title": "💼 X LAYER PORTFOLIO",
            "color": BLUE,
            "fields": fields,
            "timestamp": self._iso(),
        })

    def report_security_scan(self, token: str, risk_score: float, safe: bool, details: str):
        """Show security scan results for a token."""
        verdict = "✅ SAFE" if safe else "🚨 UNSAFE"
        color = GREEN if safe else RED

        self._send({
            "title": f"🔍 SECURITY SCAN: {verdict}",
            "color": color,
            "fields": [
                {"name": "Token", "value": f"`{token}`", "inline": False},
                {"name": "Risk Score", "value": f"**{risk_score:.1f}** / 100", "inline": True},
                {"name": "Verdict", "value": verdict, "inline": True},
                {"name": "Details", "value": details[:1024] if details else "No details", "inline": False},
            ],
            "timestamp": self._iso(),
        })

    def report_error(self, error: str):
        self._send({
            "title": "⚠️ ERROR",
            "description": error[:1900],
            "color": RED,
            "timestamp": self._iso(),
        })

    @staticmethod
    def _iso() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()
