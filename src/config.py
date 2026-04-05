"""TriMind Agent Configuration -- all env-driven."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=False)

# X Layer
XLAYER_CHAIN_ID = "196"
XLAYER_RPC = os.getenv("XLAYER_RPC", "https://rpc.xlayer.tech")

# OKX DEX API (onchainos)
OKX_DEX_API_KEY = os.getenv("OKX_DEX_API_KEY", "")
OKX_DEX_SECRET_KEY = os.getenv("OKX_DEX_SECRET_KEY", "")
OKX_DEX_PASSPHRASE = os.getenv("OKX_DEX_PASSPHRASE", "")
OKX_DEX_PROJECT_ID = os.getenv("OKX_DEX_PROJECT_ID", "")

# AI APIs
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
GROK_API_KEY = os.getenv("GROK_API_KEY", "")
GROK_MODEL = os.getenv("GROK_MODEL", "grok-4.20-0309-reasoning")

# Wallets
EVM_WALLET = os.getenv("EVM_WALLET", "0xbcd403e543529cb9e6a90fd736f4477bcd9ad8c8")
SOLANA_WALLET = os.getenv("SOLANA_WALLET", "HQxopiNW76K38W9ZGrvbfnijuHhmt95eSAwLNDrsL5ti")

# Discord
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# Agent config
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))
DRY_RUN = os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes")
CONSENSUS_THRESHOLD = int(os.getenv("CONSENSUS_THRESHOLD", "2"))  # 2 of 3 minds must agree
MAX_TRADE_USD = float(os.getenv("MAX_TRADE_USD", "50"))
MAX_DAILY_TRADES = int(os.getenv("MAX_DAILY_TRADES", "20"))

# DB
DB_PATH = ROOT / "db" / "trimind.db"

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = ROOT / "logs" / "trimind.log"
