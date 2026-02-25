import asyncio
import os
import signal
import sys
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from database import init_db, is_seen, mark_seen, save_lead, get_stats
from logger import get_logger

log = get_logger("Main")

INTERVAL_MINUTES = int(os.environ.get("INTERVAL_MINUTES", "10"))
TIMEZONE_NAME = os.environ.get("TIMEZONE", "UTC")
QUIET_HOURS = os.environ.get("QUIET_HOURS", "").strip()

FB_EMAIL = os.environ.get("FB_EMAIL")
FB_PASSWORD = os.environ.get("FB_PASSWORD")

# מילות מפתח לסינון מוקדם — רק פוסטים שמכילים לפחות מילה אחת יעברו ל-AI
PRE_FILTER_KEYWORDS = [
    "בוט", "אוטומציה", "סקריפט", "מתכנת", "פיתוח", "מחפש מפתח",
    "דרוש מפתח", "צריך עזרה", "מישהו יכול", "לבנות מערכת",
    "טלגרם", "אינטגרציה", "אוטומטי", "ווטסאפ", "בהתנדבות",
    "צ'אטבוט", "צאטבוט",
]

def passes_keyword_filter(text: str) -> bool:
    """בודק אם הפוסט מכיל לפחות מילת מפתח אחת."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in PRE_FILTER_KEYWORDS)

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
    from classifier import classify_post
    from notifier import send_lead

    log.info(f"===== סבב חדש: {_now_local().strftime('%Y-%m-%d %H:%M:%S %Z')} =====")

    if not FB_EMAIL or not FB_PASSWORD:
        log.error("חסרים FB_EMAIL או FB_PASSWORD — לא ניתן לסרוק")
        return

    # שלב 1 — גרידה (דפדפן פתוח)
    try:
        posts = await scrape_all(FB_EMAIL, FB_PASSWORD)
        log.info(f"סך הכל פוסטים שנמצאו: {len(posts)}")
    except Exception as e:
        log.error(f"שגיאה בגרידה: {e}", exc_info=True)
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

    # שלב 3 — סינון מילות מפתח לפני שליחה ל-AI
    filtered_posts = [p for p in new_posts if passes_keyword_filter(p["content"])]
    skipped_by_filter = len(new_posts) - len(filtered_posts)
    if skipped_by_filter:
        log.info(f"סונן לפי מילות מפתח: {skipped_by_filter} פוסטים לא רלוונטיים דולגו")
    log.info(f"פוסטים שעוברים לסיווג AI: {len(filtered_posts)}")

    if not filtered_posts:
        log.info("אין פוסטים רלוונטיים — מדלג על סיווג")

    leads_found = 0

    for i, post in enumerate(filtered_posts, 1):
        log.debug(f"מסווג פוסט {i}/{len(filtered_posts)} מקבוצה: {post['group']}")

        result = classify_post(post["content"], post["group"])

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
    log.info(
        f"מתחיל. סבב כל {INTERVAL_MINUTES} דקות. "
        f"LOG_LEVEL={os.environ.get('LOG_LEVEL', 'DEBUG')} "
        f"TIMEZONE={TIMEZONE_NAME} QUIET_HOURS={QUIET_HOURS or '(disabled)'}"
    )

    quiet = None
    if QUIET_HOURS:
        try:
            quiet = _parse_quiet_hours(QUIET_HOURS)
        except Exception as e:
            log.error(f"QUIET_HOURS לא תקין ({QUIET_HOURS}) — מתעלם. שגיאה: {e}")
            quiet = None

    while True:
        try:
            now = _now_local()
            if quiet and _is_quiet_now(now, quiet):
                secs = _seconds_until_quiet_end(now, quiet)
                sleep_for = max(60, min(int(secs) + 1, 12 * 60 * 60))
                log.info(
                    f"שעות שקטות פעילות ({QUIET_HOURS}, {TIMEZONE_NAME}) — "
                    f"מדלג על סריקה. ישן {sleep_for//60} דקות."
                )
                await asyncio.sleep(sleep_for)
                continue

            await run_cycle()
        except Exception as e:
            log.error(f"שגיאה לא צפויה: {e}", exc_info=True)

        log.info(f"ממתין {INTERVAL_MINUTES} דקות לסבב הבא...")
        await asyncio.sleep(INTERVAL_MINUTES * 60)

if __name__ == "__main__":
    asyncio.run(main())
