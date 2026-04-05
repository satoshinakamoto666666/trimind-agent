"""TriMind Agent configuration."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=False)


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value
    return default


# X Layer
XLAYER_CHAIN_ID = _env("XLAYER_CHAIN_ID", default="196")
XLAYER_RPC = _env("XLAYER_RPC", default="https://rpc.xlayer.tech")

# OKX / OnchainOS credentials
OKX_DEX_API_KEY = _env("OKX_DEX_API_KEY", "OKX_API_KEY")
OKX_DEX_SECRET_KEY = _env("OKX_DEX_SECRET_KEY", "OKX_SECRET_KEY")
OKX_DEX_PASSPHRASE = _env("OKX_DEX_PASSPHRASE", "OKX_PASSPHRASE")
OKX_DEX_PROJECT_ID = _env("OKX_DEX_PROJECT_ID", "OKX_PROJECT_ID")

# AI APIs
OPENAI_API_KEY = _env("OPENAI_API_KEY")
OPENAI_MODEL = _env("OPENAI_MODEL", default="gpt-5.4")
GROK_API_KEY = _env("GROK_API_KEY")
GROK_MODEL = _env("GROK_MODEL", default="grok-4.20-0309-reasoning")

# Wallets
EVM_WALLET = _env("EVM_WALLET", "EVM_WALLET_ADDRESS", default="0xbcd403e543529cb9e6a90fd736f4477bcd9ad8c8")
SOLANA_WALLET = _env("SOLANA_WALLET", default="HQxopiNW76K38W9ZGrvbfnijuHhmt95eSAwLNDrsL5ti")

# Discord
DISCORD_BOT_TOKEN = _env("DISCORD_BOT_TOKEN")
DISCORD_WEBHOOK_URL = _env("DISCORD_WEBHOOK_URL")

# Agent config
POLL_INTERVAL = int(_env("POLL_INTERVAL", default="300"))
DRY_RUN = _env("DRY_RUN", "PAPER_MODE", default="true").lower() in ("1", "true", "yes")
CONSENSUS_THRESHOLD = int(_env("CONSENSUS_THRESHOLD", default="2"))
MAX_TRADE_USD = float(_env("MAX_TRADE_USD", default="50"))
MAX_DAILY_TRADES = int(_env("MAX_DAILY_TRADES", default="20"))
MIN_TRADE_USD = float(_env("MIN_TRADE_USD", default="1"))
MAX_REBALANCE_USD = float(_env("MAX_REBALANCE_USD", default="3"))
MAX_DIVERSIFY_USD = float(_env("MAX_DIVERSIFY_USD", default="1.5"))
TARGET_USDC_SHARE = float(_env("TARGET_USDC_SHARE", default="0.40"))
TARGET_WETH_SHARE = float(_env("TARGET_WETH_SHARE", default="0.05"))
AAVE_MIN_APY = float(_env("AAVE_MIN_APY", default="0.015"))
MAX_SLIPPAGE = _env("MAX_SLIPPAGE", default="5.0")

# DB
DB_PATH = ROOT / "db" / "trimind.db"

# Logging
LOG_LEVEL = _env("LOG_LEVEL", default="INFO")
LOG_FILE = ROOT / "logs" / "trimind.log"
