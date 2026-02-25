import asyncio
import os
from datetime import datetime
from database import init_db, is_seen, mark_seen, save_lead, get_stats
from scraper import scrape_all
from classifier import classify_post
from notifier import send_lead

INTERVAL_MINUTES = int(os.environ.get("INTERVAL_MINUTES", "10"))

FB_EMAIL = os.environ.get("FB_EMAIL")
FB_PASSWORD = os.environ.get("FB_PASSWORD")

async def run_cycle():
    print(f"\n[Main] ===== סבב חדש: {datetime.now().strftime('%H:%M:%S')} =====")

    if not FB_EMAIL or not FB_PASSWORD:
        print("[Main] שגיאה: חסרים FB_EMAIL או FB_PASSWORD")
        return

    # שלב 1 — גרידה
    try:
        posts = await scrape_all(FB_EMAIL, FB_PASSWORD)
        print(f"[Main] סך הכל פוסטים שנמצאו: {len(posts)}")
    except Exception as e:
        print(f"[Main] שגיאה בגרידה: {e}")
        return

    # שלב 2 — סינון כפילויות + סיווג
    new_posts = [p for p in posts if not is_seen(p["id"])]
    print(f"[Main] פוסטים חדשים (לא נראו קודם): {len(new_posts)}")

    leads_found = 0

    for post in new_posts:
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
            print(f"[Main] ✅ ליד נשלח: {reason}")
        else:
            print(f"[Main] ⏭ לא רלוונטי: {result.get('reason', '')}")

    stats = get_stats()
    print(f"[Main] סבב הסתיים | לידים בסבב זה: {leads_found} | סך נראו: {stats['seen']} | סך נשלחו: {stats['sent']}")

async def main():
    print("[Main] מאתחל מסד נתונים...")
    init_db()
    print(f"[Main] מתחיל. סבב כל {INTERVAL_MINUTES} דקות.")

    while True:
        try:
            await run_cycle()
        except Exception as e:
            print(f"[Main] שגיאה לא צפויה: {e}")
        
        print(f"[Main] ממתין {INTERVAL_MINUTES} דקות...")
        await asyncio.sleep(INTERVAL_MINUTES * 60)

if __name__ == "__main__":
    asyncio.run(main())
