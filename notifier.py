import os
import re
import requests
from logger import get_logger

log = get_logger("Notifier")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_message(
    text: str,
    *,
    chat_id: str | int | None = None,
    parse_mode: str | None = None,
    disable_web_page_preview: bool = False,
) -> bool:
    if not BOT_TOKEN or not (chat_id or CHAT_ID):
        log.error("חסרים TELEGRAM_BOT_TOKEN או TELEGRAM_CHAT_ID")
        return False

    target_chat = str(chat_id or CHAT_ID)

    payload: dict = {
        "chat_id": target_chat,
        "text": text,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        log.debug(f"שולח הודעה לטלגרם (chat_id={target_chat})...")
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=10,
        )
        if response.status_code == 200:
            log.info("הודעה נשלחה בהצלחה לטלגרם")
            return True

        log.error(f"טלגרם החזיר סטטוס {response.status_code}: {response.text}")
        return False
    except Exception as e:
        log.error(f"שגיאה בשליחה לטלגרם: {e}", exc_info=True)
        return False

def clean_facebook_icons(text: str) -> str:
    """מנקה תווי Unicode פרטיים של פייסבוק שמופיעים כ-X בטלגרם."""
    # הסרת תווים מ-Private Use Areas (U+E000–U+F8FF, U+F0000–U+10FFFF)
    text = re.sub(r'[\uE000-\uF8FF]', '', text)
    text = re.sub(r'[\U000F0000-\U0010FFFF]', '', text)
    # ניקוי שורות ריקות מיותרות שנשארו
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def send_lead(group_name: str, content: str, post_url: str, reason: str):
    if not BOT_TOKEN or not CHAT_ID:
        log.error("חסרים משתני סביבה של טלגרם (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
        return False

    content = clean_facebook_icons(content)
    short_content = content[:350] + "..." if len(content) > 350 else content

    text = (
        f"🎯 *ליד חדש*\n"
        f"📌 *קבוצה:* {group_name}\n\n"
        f"{short_content}\n\n"
        f"💡 *למה רלוונטי:* {reason}\n\n"
        f"🔗 [פתח פוסט]({post_url})"
    )
    return send_message(
        text,
        parse_mode="Markdown",
        disable_web_page_preview=False,
    )
