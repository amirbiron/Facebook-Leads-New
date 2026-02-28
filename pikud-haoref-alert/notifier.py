"""שליחת התראות לטלגרם."""
import os

import requests

from logger import get_logger

log = get_logger("Notifier")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send_message(text: str, *, chat_id: str | None = None) -> bool:
    """שולח הודעת טקסט לטלגרם. מחזיר True בהצלחה."""
    target = chat_id or CHAT_ID
    if not BOT_TOKEN or not target:
        log.error("חסרים TELEGRAM_BOT_TOKEN או TELEGRAM_CHAT_ID")
        return False

    try:
        resp = requests.post(
            f"{_API}/sendMessage",
            json={
                "chat_id": target,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            log.info(f"הודעה נשלחה ל-{target}")
            return True
        log.error(f"טלגרם החזיר {resp.status_code}: {resp.text[:200]}")
        return False
    except Exception as e:
        log.error(f"שגיאה בשליחה לטלגרם: {e}")
        return False


def send_alert(content: str, *, chat_id: str | None = None) -> bool:
    """שולח התראת פיקוד העורף מפורמטת."""
    text = (
        "🔔 התראת פיקוד העורף\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{content}\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )
    return send_message(text, chat_id=chat_id)
