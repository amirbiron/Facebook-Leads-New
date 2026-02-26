import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path("data/leads.db")

# ── Connection Pool (thread-local) ────────────────────────────
_local = threading.local()

def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(DB_PATH)
    return _local.conn

# ── Init ──────────────────────────────────────────────────────
def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen_posts (
            post_id TEXT PRIMARY KEY,
            group_name TEXT,
            seen_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sent_leads (
            post_id TEXT PRIMARY KEY,
            group_name TEXT,
            content TEXT,
            reason TEXT,
            sent_at TEXT
        )
    """)
    conn.commit()

# ── CRUD ──────────────────────────────────────────────────────
def is_seen(post_id: str) -> bool:
    row = _get_conn().execute(
        "SELECT 1 FROM seen_posts WHERE post_id = ?", (post_id,)
    ).fetchone()
    return row is not None

def mark_seen(post_id: str, group_name: str):
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO seen_posts (post_id, group_name, seen_at) VALUES (?, ?, ?)",
        (post_id, group_name, datetime.now().isoformat())
    )
    conn.commit()

def save_lead(post_id: str, group_name: str, content: str, reason: str):
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO sent_leads (post_id, group_name, content, reason, sent_at) VALUES (?, ?, ?, ?, ?)",
        (post_id, group_name, content, reason, datetime.now().isoformat())
    )
    conn.commit()

def is_lead_sent(post_id: str) -> bool:
    row = _get_conn().execute(
        "SELECT 1 FROM sent_leads WHERE post_id = ?", (post_id,)
    ).fetchone()
    return row is not None

def get_stats() -> dict:
    conn = _get_conn()
    seen = conn.execute("SELECT COUNT(*) FROM seen_posts").fetchone()[0]
    sent = conn.execute("SELECT COUNT(*) FROM sent_leads").fetchone()[0]
    return {"seen": seen, "sent": sent}

# ── Cleanup ───────────────────────────────────────────────────
def cleanup_old_posts(days: int = 30) -> int:
    """מוחק רשומות ישנות מטבלת seen_posts (ברירת מחדל: מעל 30 יום)."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    conn = _get_conn()
    deleted = conn.execute(
        "DELETE FROM seen_posts WHERE seen_at < ?", (cutoff,)
    ).rowcount
    conn.commit()
    return deleted
