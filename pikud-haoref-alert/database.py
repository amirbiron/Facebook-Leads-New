"""שכבת נתונים — SQLite עם thread-local connections.

טבלאות:
  seen_messages — מעקב אחרי הודעות שכבר עובדו (dedup)
  sent_alerts  — הודעות שנשלחו לטלגרם (היסטוריה + dedup נוסף)
"""
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import os

from logger import get_logger

log = get_logger("DB")

_TZ = ZoneInfo(os.environ.get("TIMEZONE", "Asia/Jerusalem"))
DB_PATH = Path(__file__).resolve().parent / "data" / "alerts.db"
_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn"):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(DB_PATH))
        _local.conn.execute("PRAGMA journal_mode=WAL")
    return _local.conn


def _now_str() -> str:
    return datetime.now(_TZ).isoformat()


def init_db():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS seen_messages (
                msg_id TEXT PRIMARY KEY,
                channel TEXT NOT NULL,
                seen_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sent_alerts (
                msg_id TEXT PRIMARY KEY,
                channel TEXT NOT NULL,
                content TEXT NOT NULL,
                sent_at TEXT NOT NULL
            )
        """)
    log.info("DB מאותחל")


def is_seen(msg_id: str) -> bool:
    row = _get_conn().execute(
        "SELECT 1 FROM seen_messages WHERE msg_id = ?", (msg_id,)
    ).fetchone()
    return row is not None


def mark_seen(msg_id: str, channel: str):
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_messages (msg_id, channel, seen_at) VALUES (?, ?, ?)",
            (msg_id, channel, _now_str()),
        )


def is_alert_sent(msg_id: str) -> bool:
    row = _get_conn().execute(
        "SELECT 1 FROM sent_alerts WHERE msg_id = ?", (msg_id,)
    ).fetchone()
    return row is not None


def save_alert(msg_id: str, channel: str, content: str):
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sent_alerts (msg_id, channel, content, sent_at) VALUES (?, ?, ?, ?)",
            (msg_id, channel, content, _now_str()),
        )


def cleanup_old(days: int = 14):
    """מוחק רשומות ישנות מ-seen_messages — מונע גדילת DB אינסופית."""
    from datetime import timedelta
    cutoff = (datetime.now(_TZ) - timedelta(days=days)).isoformat()
    with _get_conn() as conn:
        deleted = conn.execute(
            "DELETE FROM seen_messages WHERE seen_at < ?", (cutoff,)
        ).rowcount
    if deleted:
        log.info(f"נוקו {deleted} רשומות ישנות מ-seen_messages")
