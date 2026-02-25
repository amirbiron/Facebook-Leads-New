import os
import requests
from logger import get_logger

log = get_logger("Notifier")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_lead(group_name: str, content: str, post_url: str, reason: str):
    if not BOT_TOKEN or not CHAT_ID:
        log.error("חסרים משתני סביבה של טלגרם (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
        return False

    short_content = content[:350] + "..." if len(content) > 350 else content

    text = (
        f"🎯 *ליד חדש*\n"
        f"📌 *קבוצה:* {group_name}\n\n"
        f"{short_content}\n\n"
        f"💡 *למה רלוונטי:* {reason}\n\n"
        f"🔗 [פתח פוסט]({post_url})"
    )

    try:
        log.debug(f"שולח הודעה לטלגרם (chat_id={CHAT_ID})...")
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False
            },
            timeout=10
        )
        if response.status_code == 200:
            log.info("הודעה נשלחה בהצלחה לטלגרם")
        else:
            log.error(f"טלגרם החזיר סטטוס {response.status_code}: {response.text}")
        return response.status_code == 200
    except Exception as e:
        log.error(f"שגיאה בשליחה לטלגרם: {e}", exc_info=True)
        return False
