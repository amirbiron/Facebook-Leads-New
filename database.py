import re
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
    with _get_conn() as conn:
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('pre_filter', 'block')),
                created_at TEXT NOT NULL,
                UNIQUE(word, type)
            )
        """)

# ── CRUD ──────────────────────────────────────────────────────
def is_seen(post_id: str) -> bool:
    row = _get_conn().execute(
        "SELECT 1 FROM seen_posts WHERE post_id = ?", (post_id,)
    ).fetchone()
    return row is not None

def mark_seen(post_id: str, group_name: str):
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_posts (post_id, group_name, seen_at) VALUES (?, ?, ?)",
            (post_id, group_name, datetime.now().isoformat())
        )

def save_lead(post_id: str, group_name: str, content: str, reason: str):
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sent_leads (post_id, group_name, content, reason, sent_at) VALUES (?, ?, ?, ?, ?)",
            (post_id, group_name, content, reason, datetime.now().isoformat())
        )

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

# ── Groups CRUD ───────────────────────────────────────────────

def _normalize_group_url(raw_url: str) -> str:
    """ממיר URL לפורמט m.facebook.com ומנקה."""
    url = raw_url.strip().rstrip("/")
    url = url.replace("www.facebook.com", "m.facebook.com")
    if not url.startswith("http"):
        url = "https://m.facebook.com/groups/" + url
    return url

def _extract_group_name(url: str) -> str:
    """מחלץ שם קבוצה מ-URL."""
    match = re.search(r"/groups/([^/?]+)", url)
    return match.group(1) if match else url

def add_group(raw_url: str) -> tuple[bool, str]:
    """מוסיף קבוצה ל-DB. מחזיר (success, message)."""
    url = _normalize_group_url(raw_url)
    name = _extract_group_name(url)
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO groups (name, url, created_at) VALUES (?, ?, ?)",
                (name, url, datetime.now().isoformat()),
            )
        return True, f"קבוצה נוספה: {name}\n{url}"
    except sqlite3.IntegrityError:
        return False, f"הקבוצה כבר קיימת: {url}"

def remove_group(raw_url: str) -> tuple[bool, str]:
    """מסיר קבוצה מה-DB. מחזיר (success, message)."""
    url = _normalize_group_url(raw_url)
    with _get_conn() as conn:
        deleted = conn.execute("DELETE FROM groups WHERE url = ?", (url,)).rowcount
    if deleted:
        return True, f"קבוצה הוסרה: {url}"
    return False, f"קבוצה לא נמצאה: {url}"

def get_db_groups() -> list[dict]:
    """מחזיר את כל הקבוצות מה-DB."""
    rows = _get_conn().execute("SELECT name, url FROM groups ORDER BY id").fetchall()
    return [{"name": r[0], "url": r[1]} for r in rows]

# ── Keywords CRUD ─────────────────────────────────────────────

def add_keyword(word: str, kw_type: str) -> tuple[bool, str]:
    """מוסיף מילת מפתח ל-DB. kw_type: 'pre_filter' או 'block'."""
    word = word.strip().lower()
    if not word:
        return False, "מילה ריקה"
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO keywords (word, type, created_at) VALUES (?, ?, ?)",
                (word, kw_type, datetime.now().isoformat()),
            )
        label = "מילת מפתח" if kw_type == "pre_filter" else "מילה חסומה"
        return True, f"{label} נוספה: {word}"
    except sqlite3.IntegrityError:
        return False, f"המילה כבר קיימת: {word}"

def remove_keyword(word: str, kw_type: str) -> tuple[bool, str]:
    """מסיר מילת מפתח מה-DB."""
    word = word.strip().lower()
    with _get_conn() as conn:
        deleted = conn.execute(
            "DELETE FROM keywords WHERE word = ? AND type = ?", (word, kw_type)
        ).rowcount
    if deleted:
        return True, f"מילה הוסרה: {word}"
    return False, f"מילה לא נמצאה: {word}"

def get_db_keywords(kw_type: str) -> list[str]:
    """מחזיר מילות מפתח מה-DB לפי סוג."""
    rows = _get_conn().execute(
        "SELECT word FROM keywords WHERE type = ? ORDER BY id", (kw_type,)
    ).fetchall()
    return [r[0] for r in rows]

# ── Cleanup ───────────────────────────────────────────────────
def cleanup_old_posts(days: int = 30) -> int:
    """מוחק רשומות ישנות מטבלת seen_posts (ברירת מחדל: מעל 30 יום)."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with _get_conn() as conn:
        deleted = conn.execute(
            "DELETE FROM seen_posts WHERE seen_at < ?", (cutoff,)
        ).rowcount
    return deleted
