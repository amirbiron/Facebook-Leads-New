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

def clean_post_content(text: str) -> str:
    """מנקה תוכן פוסט מ-Unicode פרטי של פייסבוק ורעשי UI."""
    # הסרת תווים מ-Private Use Areas (U+E000–U+F8FF, U+F0000–U+10FFFF)
    text = re.sub(r'[\uE000-\uF8FF]', '', text)
    text = re.sub(r'[\U000F0000-\U0010FFFF]', '', text)

    # הסרת שורות רעש של פייסבוק (לייקים, תגובות, שיתופים)
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # דילוג על שורות שהן רק מספרים (ספירת לייקים/תגובות)
        if re.match(r'^\d+$', stripped):
            continue
        # דילוג על "ו-עוד X אחרים" (רשימת מגיבים)
        if re.search(r'ו-עוד \d+ אחרי', stripped):
            continue
        # דילוג על שורות ריקות לגמרי (אחרי ניקוי Unicode)
        if not stripped:
            cleaned.append('')
            continue
        cleaned.append(line)

    text = '\n'.join(cleaned)
    # ניקוי שורות ריקות מיותרות שנשארו
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def send_message_with_buttons(
    text: str,
    buttons: list[list[dict]],
    *,
    chat_id: str | int | None = None,
    parse_mode: str | None = None,
) -> dict | None:
    """שולח הודעה עם InlineKeyboard.
    buttons — מערך דו-ממדי של כפתורים, כל dict: {"text": "...", "callback_data": "..."}.
    מחזיר dict של ההודעה שנשלחה (כולל message_id) או None בשגיאה.
    """
    if not BOT_TOKEN or not (chat_id or CHAT_ID):
        log.error("חסרים TELEGRAM_BOT_TOKEN או TELEGRAM_CHAT_ID")
        return None

    target_chat = str(chat_id or CHAT_ID)

    payload: dict = {
        "chat_id": target_chat,
        "text": text,
        "reply_markup": {"inline_keyboard": buttons},
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=10,
        )
        if response.status_code == 200:
            data = response.json()
            return data.get("result")
        log.error(f"טלגרם החזיר סטטוס {response.status_code}: {response.text}")
        return None
    except Exception as e:
        log.error(f"שגיאה בשליחת הודעה עם כפתורים: {e}", exc_info=True)
        return None


def edit_message_text(
    chat_id: int | str,
    message_id: int,
    text: str,
    buttons: list[list[dict]] | None = None,
    *,
    parse_mode: str | None = None,
) -> bool:
    """עורך הודעה קיימת (טקסט + כפתורים אופציונליים)."""
    if not BOT_TOKEN:
        return False

    payload: dict = {
        "chat_id": str(chat_id),
        "message_id": message_id,
        "text": text,
    }
    if buttons is not None:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText",
            json=payload,
            timeout=10,
        )
        if response.status_code == 200:
            return True
        log.error(f"editMessageText נכשל: {response.status_code}: {response.text}")
        return False
    except Exception as e:
        log.error(f"שגיאה בעריכת הודעה: {e}", exc_info=True)
        return False


def answer_callback_query(callback_query_id: str, text: str = "") -> bool:
    """עונה ל-callback query (מסיר את אנימציית הטעינה מהכפתור)."""
    if not BOT_TOKEN:
        return False
    payload: dict = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery",
            json=payload,
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def send_error_alert(error: str) -> bool:
    """שולח שגיאה קריטית כהודעת טלגרם (חתוך ל-500 תווים)."""
    truncated = error[:500]
    return send_message(
        f"⚠️ שגיאה בבוט:\n{truncated}",
        disable_web_page_preview=True,
    )


def _to_desktop_url(url: str) -> str:
    """ממיר URL מובייל ל-URL דסקטופ (m.facebook.com → www.facebook.com)."""
    return url.replace("://m.facebook.com", "://www.facebook.com")

def send_lead(group_name: str, content: str, post_url: str, reason: str):
    if not BOT_TOKEN or not CHAT_ID:
        log.error("חסרים משתני סביבה של טלגרם (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
        return False

    content = clean_post_content(content)
    short_content = content[:350] + "..." if len(content) > 350 else content

    # המרת URL מובייל לדסקטופ — נוח יותר למשתמשים
    desktop_url = _to_desktop_url(post_url)

    text = (
        f"🎯 *ליד חדש*\n"
        f"📌 *קבוצה:* {group_name}\n\n"
        f"{short_content}\n\n"
        f"💡 *למה רלוונטי:* {reason}\n\n"
        f"🔗 [פתח פוסט]({desktop_url})"
    )
    return send_message(
        text,
        parse_mode="Markdown",
        disable_web_page_preview=False,
    )
