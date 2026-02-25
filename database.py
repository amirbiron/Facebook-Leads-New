import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/leads.db")

def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
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

def is_seen(post_id: str) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT 1 FROM seen_posts WHERE post_id = ?", (post_id,)
        ).fetchone()
        return row is not None

def mark_seen(post_id: str, group_name: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_posts (post_id, group_name, seen_at) VALUES (?, ?, ?)",
            (post_id, group_name, datetime.now().isoformat())
        )
        conn.commit()

def save_lead(post_id: str, group_name: str, content: str, reason: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sent_leads (post_id, group_name, content, reason, sent_at) VALUES (?, ?, ?, ?, ?)",
            (post_id, group_name, content, reason, datetime.now().isoformat())
        )
        conn.commit()

def get_stats() -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        seen = conn.execute("SELECT COUNT(*) FROM seen_posts").fetchone()[0]
        sent = conn.execute("SELECT COUNT(*) FROM sent_leads").fetchone()[0]
        return {"seen": seen, "sent": sent}
