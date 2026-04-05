"""SQLite persistence for TriMind agent."""
import json
import sqlite3
import time
from pathlib import Path

from config import DB_PATH


def init_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.execute("""CREATE TABLE IF NOT EXISTS positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asset TEXT,
        protocol TEXT,
        amount REAL,
        entry_time INTEGER,
        status TEXT DEFAULT 'open',
        tx_hash TEXT,
        extra TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        consensus INTEGER,
        action TEXT,
        votes_json TEXT,
        reasoning TEXT,
        executed INTEGER DEFAULT 0,
        result TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS scans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        token TEXT,
        risk_score REAL,
        signal_strength REAL,
        action TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        api_calls INTEGER DEFAULT 0,
        trades INTEGER DEFAULT 0,
        yield_earned REAL DEFAULT 0,
        memes_rejected INTEGER DEFAULT 0
    )""")
    conn.commit()
    return conn


def record_decision(conn: sqlite3.Connection, decision: dict):
    conn.execute(
        "INSERT INTO decisions (timestamp, consensus, action, votes_json, reasoning, executed) VALUES (?,?,?,?,?,?)",
        (int(time.time()), int(decision.get("consensus", False)), decision.get("action", "none"),
         json.dumps(decision.get("votes", {}), default=str), decision.get("reasoning", ""),
         int(decision.get("execute", False)))
    )
    conn.commit()


def record_scan(conn: sqlite3.Connection, token: str, risk: float, signal: float, action: str):
    conn.execute(
        "INSERT INTO scans (timestamp, token, risk_score, signal_strength, action) VALUES (?,?,?,?,?)",
        (int(time.time()), token, risk, signal, action)
    )
    conn.commit()


def record_position(conn: sqlite3.Connection, asset: str, protocol: str, amount: float, tx_hash: str = ""):
    conn.execute(
        "INSERT INTO positions (asset, protocol, amount, entry_time, tx_hash) VALUES (?,?,?,?,?)",
        (asset, protocol, amount, int(time.time()), tx_hash)
    )
    conn.commit()


def get_stats(conn: sqlite3.Connection) -> dict:
    """Get aggregate stats for dashboard."""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM decisions WHERE executed=1")
    total_trades = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM decisions")
    total_decisions = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM scans WHERE action='reject'")
    rejected = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM positions WHERE status='open'")
    open_positions = cur.fetchone()[0]
    return {
        "total_decisions": total_decisions,
        "total_trades": total_trades,
        "memes_rejected": rejected,
        "open_positions": open_positions,
    }
