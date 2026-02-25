import asyncio
import os
import signal
import sys
from datetime import datetime
from database import init_db, is_seen, mark_seen, save_lead, get_stats
from scraper import scrape_all
from classifier import classify_post
from notifier import send_lead
from logger import get_logger

log = get_logger("Main")

INTERVAL_MINUTES = int(os.environ.get("INTERVAL_MINUTES", "10"))

FB_EMAIL = os.environ.get("FB_EMAIL")
FB_PASSWORD = os.environ.get("FB_PASSWORD")

_shutting_down = False

def handle_signal(sig, frame):
    global _shutting_down
    log.info(f"קיבלנו סיגנל {sig} — יוצאים בצורה מסודרת")
    _shutting_down = True
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)

async def run_cycle():
    log.info(f"===== סבב חדש: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====")

    if not FB_EMAIL or not FB_PASSWORD:
        log.error("חסרים FB_EMAIL או FB_PASSWORD — לא ניתן לסרוק")
        return

    # שלב 1 — גרידה
    try:
        posts = await scrape_all(FB_EMAIL, FB_PASSWORD)
        log.info(f"סך הכל פוסטים שנמצאו: {len(posts)}")
    except Exception as e:
        log.error(f"שגיאה בגרידה: {e}", exc_info=True)
        return

    # שלב 2 — סינון כפילויות + סיווג
    new_posts = [p for p in posts if not is_seen(p["id"])]
    log.info(f"פוסטים חדשים (לא נראו קודם): {len(new_posts)}")

    if not new_posts:
        log.info("אין פוסטים חדשים — מדלג על סיווג")

    leads_found = 0

    for i, post in enumerate(new_posts, 1):
        log.debug(f"מסווג פוסט {i}/{len(new_posts)} מקבוצה: {post['group']}")
        mark_seen(post["id"], post["group"])

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
    log.info(f"מתחיל. סבב כל {INTERVAL_MINUTES} דקות. LOG_LEVEL={os.environ.get('LOG_LEVEL', 'DEBUG')}")

    while True:
        try:
            await run_cycle()
        except Exception as e:
            log.error(f"שגיאה לא צפויה: {e}", exc_info=True)

        log.info(f"ממתין {INTERVAL_MINUTES} דקות לסבב הבא...")
        await asyncio.sleep(INTERVAL_MINUTES * 60)

if __name__ == "__main__":
    asyncio.run(main())
