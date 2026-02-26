import asyncio
import os
import signal
import sys
import threading
from datetime import datetime, time, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from zoneinfo import ZoneInfo
from database import (
    init_db, is_seen, is_lead_sent, mark_seen, save_lead, get_stats,
    cleanup_old_posts, add_group, remove_group, get_db_groups,
    add_keyword, remove_keyword, get_db_keywords,
)
from logger import get_logger

log = get_logger("Main")

INTERVAL_MINUTES = int(os.environ.get("INTERVAL_MINUTES", "10"))
TIMEZONE_NAME = os.environ.get("TIMEZONE", "UTC")
QUIET_HOURS = os.environ.get("QUIET_HOURS", "").strip()
TELEGRAM_CONTROL = os.environ.get("TELEGRAM_CONTROL", "1").strip().lower() not in ("0", "false", "no", "off")

HEALTH_PORT = int(os.environ.get("HEALTH_PORT", "8080"))

FB_EMAIL = os.environ.get("FB_EMAIL")
FB_PASSWORD = os.environ.get("FB_PASSWORD")

# מילים חסומות — פוסט שמכיל מילה מהרשימה לא יישלח ל-AI
# ניתן לערוך דרך משתנה סביבה BLOCK_KEYWORDS (מופרד בפסיקים)
# או דינמית דרך פקודות טלגרם /block, /unblock
_block_env = os.environ.get("BLOCK_KEYWORDS", "").strip()
_BLOCK_KEYWORDS_ENV = [w.strip().lower() for w in _block_env.split(",") if w.strip()] if _block_env else []

# מילות מפתח לסינון מוקדם — רק פוסטים שמכילים לפחות מילה אחת יעברו ל-AI
# ניתן לערוך דינמית דרך פקודת טלגרם /add_keyword, /remove_keyword
_PRE_FILTER_KEYWORDS_DEFAULT = [
    "בוט", "אוטומציה", "סקריפט", "מתכנת", "פיתוח", "מחפש מפתח",
    "דרוש מפתח", "צריך עזרה", "מישהו יכול", "לבנות מערכת",
    "טלגרם", "אינטגרציה", "אוטומטי", "ווטסאפ", "בהתנדבות",
    "צ'אטבוט", "צאטבוט",
]

def _load_block_keywords() -> list[str]:
    """טוען מילים חסומות מ-DB עם fallback למשתנה סביבה.
    None מ-DB = מעולם לא הוגדר → fallback.  [] = המשתמש רוקן הכל → רשימה ריקה.
    """
    try:
        db_kw = get_db_keywords("block")
        if db_kw is not None:
            return db_kw
    except Exception:
        pass
    return _BLOCK_KEYWORDS_ENV

def _load_pre_filter_keywords() -> list[str]:
    """טוען מילות מפתח לסינון מוקדם מ-DB עם fallback לרשימת ברירת מחדל.
    None מ-DB = מעולם לא הוגדר → fallback.  [] = המשתמש רוקן הכל → רשימה ריקה.
    """
    try:
        db_kw = get_db_keywords("pre_filter")
        if db_kw is not None:
            return db_kw
    except Exception:
        pass
    return _PRE_FILTER_KEYWORDS_DEFAULT

# טעינה ראשונית — יתעדכנו דינמית בכל סבב
BLOCK_KEYWORDS = _load_block_keywords()
PRE_FILTER_KEYWORDS = _load_pre_filter_keywords()

def reload_keywords():
    """טוען מחדש את מילות המפתח מ-DB (נקרא אחרי שינוי דרך טלגרם)."""
    global BLOCK_KEYWORDS, PRE_FILTER_KEYWORDS
    BLOCK_KEYWORDS = _load_block_keywords()
    PRE_FILTER_KEYWORDS = _load_pre_filter_keywords()

def passes_keyword_filter(text: str) -> bool:
    """בודק אם הפוסט מכיל לפחות מילת מפתח אחת.
    אם הרשימה ריקה — מעביר הכל (אין סינון מוקדם).
    """
    if not PRE_FILTER_KEYWORDS:
        return True
    text_lower = text.lower()
    return any(kw in text_lower for kw in PRE_FILTER_KEYWORDS)

def is_blocked(text: str) -> bool:
    """בודק אם הפוסט מכיל מילה חסומה — אם כן, לא יישלח ל-AI."""
    if not BLOCK_KEYWORDS:
        return False
    text_lower = text.lower()
    return any(kw in text_lower for kw in BLOCK_KEYWORDS)

def _now_local() -> datetime:
    try:
        tz = ZoneInfo(TIMEZONE_NAME)
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz=tz)

def _parse_hhmm(value: str) -> time:
    value = value.strip()
    if not value:
        raise ValueError("empty time")

    if ":" in value:
        hh, mm = value.split(":", 1)
    else:
        hh, mm = value, "0"

    h = int(hh)
    m = int(mm)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"invalid time: {value}")
    return time(hour=h, minute=m)

def _parse_quiet_hours(spec: str) -> tuple[time, time] | None:
    spec = (spec or "").strip()
    if not spec:
        return None

    # Accept common formats: "02:00-07:00", "2-7", "02-07", "2:00-7:00"
    if "-" not in spec:
        raise ValueError("QUIET_HOURS must look like '02:00-07:00'")

    start_s, end_s = spec.split("-", 1)
    start_t = _parse_hhmm(start_s)
    end_t = _parse_hhmm(end_s)
    return start_t, end_t

def _is_quiet_now(now: datetime, quiet: tuple[time, time]) -> bool:
    start_t, end_t = quiet
    now_t = now.timetz().replace(tzinfo=None)

    if start_t == end_t:
        # Treat as "always quiet" (config means full-day).
        return True

    if start_t < end_t:
        return start_t <= now_t < end_t

    # Wraps over midnight (e.g., 22:00-06:00)
    return now_t >= start_t or now_t < end_t

def _seconds_until_quiet_end(now: datetime, quiet: tuple[time, time]) -> float:
    start_t, end_t = quiet

    today_end = now.replace(hour=end_t.hour, minute=end_t.minute, second=0, microsecond=0)

    if start_t < end_t:
        # Same-day window.
        end_dt = today_end
    else:
        # Wraps midnight. If we're after start, end is next day; otherwise it's today.
        now_t = now.timetz().replace(tzinfo=None)
        end_dt = today_end if now_t < end_t else (today_end + timedelta(days=1))

    return max(0.0, (end_dt - now).total_seconds())

def _parse_allowed_chat_ids(spec: str | None) -> set[int]:
    """Parses TELEGRAM_CHAT_ID (supports '123', '-100...', '123,456')."""
    if not spec:
        return set()
    parts = []
    for chunk in spec.replace("\n", ",").replace(" ", ",").split(","):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    ids: set[int] = set()
    for p in parts:
        try:
            ids.add(int(p))
        except Exception:
            continue
    return ids

async def _telegram_control_loop(
    *,
    scan_now_event: asyncio.Event,
    scan_force_event: asyncio.Event,
    quiet: tuple[time, time] | None,
    state: dict,
):
    """
    Telegram polling loop for basic control commands.
    Commands:
      - /scan: run scan now (respects quiet hours)
      - /scan_force: run scan now (ignores quiet hours)
      - /status: show basic status
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    allowed_chat_ids = _parse_allowed_chat_ids(os.environ.get("TELEGRAM_CHAT_ID"))
    if not bot_token or not allowed_chat_ids:
        log.info("בקרת טלגרם לא מופעלת (חסרים TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID)")
        return

    from notifier import send_message
    import requests
    import json

    offset_file = Path("data/telegram_offset.txt")

    def load_offset() -> int:
        try:
            if offset_file.exists():
                return int(offset_file.read_text().strip() or "0")
        except Exception:
            return 0
        return 0

    def save_offset(value: int):
        try:
            offset_file.parent.mkdir(exist_ok=True)
            offset_file.write_text(str(value))
        except Exception:
            pass

    def fetch_updates(offset: int, timeout: int = 30) -> list[dict]:
        url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
        params: dict = {"timeout": timeout, "allowed_updates": json.dumps(["message", "edited_message"])}
        if offset:
            params["offset"] = offset
        resp = requests.get(url, params=params, timeout=timeout + 10)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram getUpdates failed: {data}")
        return data.get("result") or []

    # ניקוי webhook קודם וביטול polling תקוע מאינסטנס ישן
    try:
        await asyncio.to_thread(
            requests.post,
            f"https://api.telegram.org/bot{bot_token}/deleteWebhook",
            json={"drop_pending_updates": False},
            timeout=10,
        )
        log.debug("webhook נוקה בהצלחה")
    except Exception:
        pass

    offset = load_offset()
    log.info("בקרת טלגרם הופעלה. פקודות: /scan /scan_force /status")
    conflict_backoff = 5

    while True:
        try:
            updates = await asyncio.to_thread(fetch_updates, offset, 30)
            conflict_backoff = 5  # איפוס backoff אחרי הצלחה
            for upd in updates:
                try:
                    update_id = int(upd.get("update_id"))
                except Exception:
                    continue

                offset = max(offset, update_id + 1)
                save_offset(offset)

                msg = upd.get("message") or upd.get("edited_message")
                if not msg:
                    continue

                chat_id = msg.get("chat", {}).get("id")
                if chat_id is None:
                    continue

                try:
                    chat_id_int = int(chat_id)
                except Exception:
                    continue

                if chat_id_int not in allowed_chat_ids:
                    continue

                text = (msg.get("text") or "").strip()
                if not text:
                    continue

                first = text.split()[0].strip()
                cmd = first.split("@", 1)[0].lower()

                if cmd in ("/help",):
                    help_text = (
                        "פקודות:\n"
                        "/scan - סריקה עכשיו (מכבד שעות שקטות)\n"
                        "/scan_force - סריקה עכשיו (מתעלם משעות שקטות)\n"
                        "/status - סטטוס\n"
                        "\nניהול קבוצות:\n"
                        "/groups - הצג קבוצות פעילות\n"
                        "/add_group <url> - הוסף קבוצה\n"
                        "/remove_group <url> - הסר קבוצה\n"
                        "\nניהול מילות מפתח:\n"
                        "/keywords - הצג מילות מפתח\n"
                        "/add_keyword <מילה> - הוסף מילת סינון\n"
                        "/remove_keyword <מילה> - הסר מילת סינון\n"
                        "/block <מילה> - חסום מילה\n"
                        "/unblock <מילה> - בטל חסימת מילה"
                    )
                    await asyncio.to_thread(
                        send_message,
                        help_text,
                        chat_id=chat_id_int,
                        disable_web_page_preview=True,
                    )
                    continue

                if cmd in ("/status",):
                    stats = get_stats()
                    now = _now_local()
                    quiet_now = bool(quiet and _is_quiet_now(now, quiet))
                    quiet_desc = f"{QUIET_HOURS} ({TIMEZONE_NAME})" if QUIET_HOURS else "(disabled)"
                    last_started = state.get("last_scan_started")
                    last_finished = state.get("last_scan_finished")
                    in_progress = bool(state.get("scan_in_progress"))
                    block_desc = ", ".join(BLOCK_KEYWORDS) if BLOCK_KEYWORDS else "(ריק)"
                    from scraper import GROUPS
                    groups_count = len(GROUPS)
                    pf_count = len(PRE_FILTER_KEYWORDS)
                    msg_text = (
                        "סטטוס בוט:\n"
                        f"- שעה מקומית: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
                        f"- שעות שקטות: {quiet_desc} | עכשיו: {'פעיל' if quiet_now else 'לא'}\n"
                        f"- קבוצות פעילות: {groups_count}\n"
                        f"- מילות סינון: {pf_count} | מילים חסומות: {block_desc}\n"
                        f"- סריקה רצה: {'כן' if in_progress else 'לא'}\n"
                        f"- סריקה אחרונה התחילה: {last_started.strftime('%Y-%m-%d %H:%M:%S %Z') if last_started else '-'}\n"
                        f"- סריקה אחרונה הסתיימה: {last_finished.strftime('%Y-%m-%d %H:%M:%S %Z') if last_finished else '-'}\n"
                        f"- סך נראו: {stats['seen']} | סך נשלחו: {stats['sent']}\n"
                        "\n/help לרשימת פקודות מלאה"
                    )
                    await asyncio.to_thread(
                        send_message,
                        msg_text,
                        chat_id=chat_id_int,
                        disable_web_page_preview=True,
                    )
                    continue

                if cmd in ("/scan",):
                    now = _now_local()
                    if state.get("scan_in_progress"):
                        await asyncio.to_thread(
                            send_message,
                            "כבר יש סריקה שרצה כרגע. אעדכן כשתסתיים.",
                            chat_id=chat_id_int,
                            disable_web_page_preview=True,
                        )
                        continue

                    if quiet and _is_quiet_now(now, quiet):
                        await asyncio.to_thread(
                            send_message,
                            f"שעות שקטות פעילות עכשיו ({QUIET_HOURS}, {TIMEZONE_NAME}). אם בכל זאת צריך, השתמש /scan_force.",
                            chat_id=chat_id_int,
                            disable_web_page_preview=True,
                        )
                        continue

                    scan_now_event.set()
                    await asyncio.to_thread(
                        send_message,
                        "מתזמן סריקה עכשיו.",
                        chat_id=chat_id_int,
                        disable_web_page_preview=True,
                    )
                    continue

                if cmd in ("/scan_force",):
                    scan_force_event.set()
                    scan_now_event.set()
                    await asyncio.to_thread(
                        send_message,
                        "מתזמן סריקה עכשיו (forced).",
                        chat_id=chat_id_int,
                        disable_web_page_preview=True,
                    )
                    continue

                # ── ניהול קבוצות דינמי ──────────────────────────
                if cmd in ("/groups",):
                    from scraper import GROUPS
                    if GROUPS:
                        lines = [f"{i}. {g['name']}\n   {g['url']}" for i, g in enumerate(GROUPS, 1)]
                        msg_text = f"קבוצות פעילות ({len(GROUPS)}):\n\n" + "\n\n".join(lines)
                    else:
                        msg_text = "אין קבוצות מוגדרות."
                    await asyncio.to_thread(
                        send_message, msg_text, chat_id=chat_id_int,
                        disable_web_page_preview=True,
                    )
                    continue

                if cmd in ("/add_group",):
                    parts = text.split(maxsplit=1)
                    if len(parts) < 2 or not parts[1].strip():
                        await asyncio.to_thread(
                            send_message, "שימוש: /add_group <url>",
                            chat_id=chat_id_int, disable_web_page_preview=True,
                        )
                        continue
                    ok, result_msg = add_group(parts[1].strip())
                    if ok:
                        from scraper import reload_groups
                        reload_groups()
                    await asyncio.to_thread(
                        send_message, result_msg,
                        chat_id=chat_id_int, disable_web_page_preview=True,
                    )
                    continue

                if cmd in ("/remove_group",):
                    parts = text.split(maxsplit=1)
                    if len(parts) < 2 or not parts[1].strip():
                        await asyncio.to_thread(
                            send_message, "שימוש: /remove_group <url>",
                            chat_id=chat_id_int, disable_web_page_preview=True,
                        )
                        continue
                    ok, result_msg = remove_group(parts[1].strip())
                    if ok:
                        from scraper import reload_groups
                        reload_groups()
                    await asyncio.to_thread(
                        send_message, result_msg,
                        chat_id=chat_id_int, disable_web_page_preview=True,
                    )
                    continue

                # ── ניהול מילות מפתח דינמי ──────────────────────
                if cmd in ("/keywords",):
                    pf = PRE_FILTER_KEYWORDS
                    bl = BLOCK_KEYWORDS
                    pf_text = ", ".join(pf) if pf else "(ריק)"
                    bl_text = ", ".join(bl) if bl else "(ריק)"
                    msg_text = (
                        f"מילות מפתח לסינון ({len(pf)}):\n{pf_text}\n\n"
                        f"מילים חסומות ({len(bl)}):\n{bl_text}"
                    )
                    await asyncio.to_thread(
                        send_message, msg_text, chat_id=chat_id_int,
                        disable_web_page_preview=True,
                    )
                    continue

                if cmd in ("/add_keyword",):
                    parts = text.split(maxsplit=1)
                    if len(parts) < 2 or not parts[1].strip():
                        await asyncio.to_thread(
                            send_message, "שימוש: /add_keyword <מילה>",
                            chat_id=chat_id_int, disable_web_page_preview=True,
                        )
                        continue
                    ok, result_msg = add_keyword(parts[1].strip(), "pre_filter")
                    if ok:
                        reload_keywords()
                    await asyncio.to_thread(
                        send_message, result_msg,
                        chat_id=chat_id_int, disable_web_page_preview=True,
                    )
                    continue

                if cmd in ("/remove_keyword",):
                    parts = text.split(maxsplit=1)
                    if len(parts) < 2 or not parts[1].strip():
                        await asyncio.to_thread(
                            send_message, "שימוש: /remove_keyword <מילה>",
                            chat_id=chat_id_int, disable_web_page_preview=True,
                        )
                        continue
                    ok, result_msg = remove_keyword(parts[1].strip(), "pre_filter")
                    if ok:
                        reload_keywords()
                    await asyncio.to_thread(
                        send_message, result_msg,
                        chat_id=chat_id_int, disable_web_page_preview=True,
                    )
                    continue

                if cmd in ("/block",):
                    parts = text.split(maxsplit=1)
                    if len(parts) < 2 or not parts[1].strip():
                        await asyncio.to_thread(
                            send_message, "שימוש: /block <מילה>",
                            chat_id=chat_id_int, disable_web_page_preview=True,
                        )
                        continue
                    ok, result_msg = add_keyword(parts[1].strip(), "block")
                    if ok:
                        reload_keywords()
                    await asyncio.to_thread(
                        send_message, result_msg,
                        chat_id=chat_id_int, disable_web_page_preview=True,
                    )
                    continue

                if cmd in ("/unblock",):
                    parts = text.split(maxsplit=1)
                    if len(parts) < 2 or not parts[1].strip():
                        await asyncio.to_thread(
                            send_message, "שימוש: /unblock <מילה>",
                            chat_id=chat_id_int, disable_web_page_preview=True,
                        )
                        continue
                    ok, result_msg = remove_keyword(parts[1].strip(), "block")
                    if ok:
                        reload_keywords()
                    await asyncio.to_thread(
                        send_message, result_msg,
                        chat_id=chat_id_int, disable_web_page_preview=True,
                    )
                    continue

        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 409:
                # 409 Conflict = אינסטנס אחר עושה polling — ממתין עם backoff
                log.warning(f"409 Conflict — אינסטנס אחר פעיל. ממתין {conflict_backoff} שניות...")
                await asyncio.sleep(conflict_backoff)
                conflict_backoff = min(conflict_backoff * 2, 120)
            else:
                log.error(f"שגיאה בלולאת בקרת טלגרם: {e}", exc_info=True)
                await asyncio.sleep(5)
        except Exception as e:
            log.error(f"שגיאה בלולאת בקרת טלגרם: {e}", exc_info=True)
            await asyncio.sleep(5)

class _HealthHandler(BaseHTTPRequestHandler):
    """Healthcheck endpoint — מחזיר 200 OK לכל בקשת GET."""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format, *args):
        # השתקת לוג של http.server כדי לא להציף את הלוגים
        pass


def start_health_server(port: int = HEALTH_PORT):
    """מפעיל שרת HTTP פשוט לבדיקת חיוּת על daemon thread."""
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    log.info(f"Health server רץ על פורט {port}")
    return server


_shutting_down = False

def handle_signal(sig, frame):
    global _shutting_down
    log.info(f"קיבלנו סיגנל {sig} — יוצאים בצורה מסודרת")
    _shutting_down = True
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)

async def run_cycle():
    import gc
    # Lazy imports to keep startup light and allow running parts of the codebase
    # (like quiet-hours logic) without Playwright installed.
    from scraper import scrape_all
    from classifier import classify_batch
    from notifier import send_lead, send_error_alert

    log.info(f"===== סבב חדש: {_now_local().strftime('%Y-%m-%d %H:%M:%S %Z')} =====")

    # טעינה מחדש של מילות מפתח וקבוצות מ-DB
    reload_keywords()
    try:
        from scraper import reload_groups
        reload_groups()
    except Exception:
        pass

    # ניקוי פוסטים ישנים (מעל 30 יום) מטבלת seen_posts
    try:
        deleted = cleanup_old_posts()
        if deleted:
            log.info(f"נמחקו {deleted} פוסטים ישנים מטבלת seen_posts")
    except Exception as e:
        log.warning(f"ניקוי פוסטים ישנים נכשל (ממשיכים בסריקה): {e}")

    if not FB_EMAIL or not FB_PASSWORD:
        log.error("חסרים FB_EMAIL או FB_PASSWORD — לא ניתן לסרוק")
        return

    # שלב 1 — גרידה (דפדפן פתוח)
    try:
        posts = await scrape_all(FB_EMAIL, FB_PASSWORD, seen_checker=is_seen)
        log.info(f"סך הכל פוסטים שנמצאו: {len(posts)}")
    except Exception as e:
        log.error(f"שגיאה בגרידה: {e}", exc_info=True)
        try:
            await asyncio.to_thread(send_error_alert, f"שגיאה בגרידה: {e}")
        except Exception:
            pass
        return

    # הדפדפן כבר סגור כאן — משחררים זיכרון לפני הסיווג
    gc.collect()
    log.debug("זיכרון שוחרר אחרי סגירת דפדפן")

    # שלב 2 — סינון כפילויות (בלי דפדפן — זיכרון נמוך)
    new_posts = [p for p in posts if not is_seen(p["id"])]
    log.info(f"פוסטים חדשים (לא נראו קודם): {len(new_posts)}")

    # סימון כל הפוסטים כנראו (גם אלה שלא יעברו סינון מילות מפתח)
    for post in new_posts:
        mark_seen(post["id"], post["group"])

    # שלב 3א — סינון מילים חסומות (BLOCK_KEYWORDS)
    if BLOCK_KEYWORDS:
        before_block = len(new_posts)
        new_posts = [p for p in new_posts if not is_blocked(p["content"])]
        blocked_count = before_block - len(new_posts)
        if blocked_count:
            log.info(f"נחסמו {blocked_count} פוסטים לפי מילים חסומות (BLOCK_KEYWORDS)")

    # שלב 3ב — סינון מילות מפתח לפני שליחה ל-AI
    filtered_posts = [p for p in new_posts if passes_keyword_filter(p["content"])]
    skipped_by_filter = len(new_posts) - len(filtered_posts)
    if skipped_by_filter:
        log.info(f"סונן לפי מילות מפתח: {skipped_by_filter} פוסטים לא רלוונטיים דולגו")
    log.info(f"פוסטים שעוברים לסיווג AI: {len(filtered_posts)}")

    if not filtered_posts:
        log.info("אין פוסטים רלוונטיים — מדלג על סיווג")

    # סינון פוסטים שכבר נשלחו כלידים
    to_classify = [p for p in filtered_posts if not is_lead_sent(p["id"])]
    skipped_already_sent = len(filtered_posts) - len(to_classify)
    if skipped_already_sent:
        log.debug(f"דילוג על {skipped_already_sent} פוסטים שכבר נשלחו כלידים")

    leads_found = 0

    if to_classify:
        # סיווג באצ'ים — שליחת מספר פוסטים ל-AI בבקשה אחת
        results = classify_batch(to_classify)

        for post, result in zip(to_classify, results):
            if result.get("relevant"):
                reason = result.get("reason", "")
                send_lead(
                    group_name=post["group"],
                    content=post["content"],
                    post_url=post["url"],
                    reason=reason
                )
                save_lead(post["id"], post["group"], post["content"], reason)
                leads_found += 1
                log.info(f"ליד נשלח: {reason}")
            else:
                log.debug(f"לא רלוונטי: {result.get('reason', '')}")

    stats = get_stats()
    log.info(f"סבב הסתיים | לידים בסבב: {leads_found} | סך נראו: {stats['seen']} | סך נשלחו: {stats['sent']}")

async def main():
    log.info("מאתחל מסד נתונים...")
    init_db()
    start_health_server()
    log.info(
        f"מתחיל. סבב כל {INTERVAL_MINUTES} דקות. "
        f"LOG_LEVEL={os.environ.get('LOG_LEVEL', 'DEBUG')} "
        f"TIMEZONE={TIMEZONE_NAME} QUIET_HOURS={QUIET_HOURS or '(disabled)'} "
        f"BLOCK_KEYWORDS={', '.join(BLOCK_KEYWORDS) if BLOCK_KEYWORDS else '(disabled)'}"
    )

    quiet = None
    if QUIET_HOURS:
        try:
            quiet = _parse_quiet_hours(QUIET_HOURS)
        except Exception as e:
            log.error(f"QUIET_HOURS לא תקין ({QUIET_HOURS}) — מתעלם. שגיאה: {e}")
            quiet = None

    scan_now_event = asyncio.Event()
    scan_force_event = asyncio.Event()
    scan_lock = asyncio.Lock()
    state: dict = {
        "scan_in_progress": False,
        "last_scan_started": None,
        "last_scan_finished": None,
    }

    async def run_scan_guarded():
        async with scan_lock:
            state["scan_in_progress"] = True
            state["last_scan_started"] = _now_local()
            try:
                await run_cycle()
            finally:
                state["scan_in_progress"] = False
                state["last_scan_finished"] = _now_local()

    # שמירת רפרנס ל-task כדי למנוע garbage collection
    _control_task = None
    if TELEGRAM_CONTROL:
        _control_task = asyncio.create_task(
            _telegram_control_loop(
                scan_now_event=scan_now_event,
                scan_force_event=scan_force_event,
                quiet=quiet,
                state=state,
            )
        )

    while True:
        try:
            did_scan = False
            if scan_now_event.is_set():
                force = scan_force_event.is_set()
                scan_now_event.clear()
                scan_force_event.clear()

                if not force and quiet and _is_quiet_now(_now_local(), quiet):
                    # Should not happen (we don't schedule /scan during quiet hours),
                    # but guard anyway.
                    log.info("בקשת סריקה נדחתה בגלל שעות שקטות")
                else:
                    log.info(f"מריץ סריקה לפי פקודה (force={force})")
                    await run_scan_guarded()
                    did_scan = True

            if not did_scan:
                now = _now_local()
                if quiet and _is_quiet_now(now, quiet):
                    secs = _seconds_until_quiet_end(now, quiet)
                    sleep_for = max(60, min(int(secs) + 1, 12 * 60 * 60))
                    log.info(
                        f"שעות שקטות פעילות ({QUIET_HOURS}, {TIMEZONE_NAME}) — "
                        f"מדלג על סריקה. ישן {sleep_for//60} דקות (או /scan_force)."
                    )
                    try:
                        await asyncio.wait_for(scan_now_event.wait(), timeout=sleep_for)
                    except asyncio.TimeoutError:
                        pass
                    continue

                await run_scan_guarded()
        except Exception as e:
            log.error(f"שגיאה לא צפויה: {e}", exc_info=True)
            try:
                from notifier import send_error_alert
                await asyncio.to_thread(send_error_alert, f"שגיאה לא צפויה: {e}")
            except Exception:
                pass

        log.info(f"ממתין {INTERVAL_MINUTES} דקות לסבב הבא... (או /scan)")
        try:
            await asyncio.wait_for(scan_now_event.wait(), timeout=INTERVAL_MINUTES * 60)
        except asyncio.TimeoutError:
            pass

if __name__ == "__main__":
    asyncio.run(main())
