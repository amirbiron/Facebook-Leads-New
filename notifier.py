import os
import re
import requests
from logger import get_logger

log = get_logger("Notifier")

def _get_bot_token() -> str | None:
    return os.environ.get("TELEGRAM_BOT_TOKEN")

def _get_chat_id() -> str | None:
    return os.environ.get("TELEGRAM_CHAT_ID")

# backward compat — שומרים את השמות הישנים למי שקורא אותם ישירות
BOT_TOKEN = _get_bot_token()
CHAT_ID = _get_chat_id()
# chat ID נפרד להתראות שגיאה — אם מוגדר, שגיאות ילכו למפתח במקום ללקוח
ERROR_CHAT_ID = os.environ.get("ERROR_CHAT_ID")

def send_message(
    text: str,
    *,
    chat_id: str | int | None = None,
    parse_mode: str | None = None,
    disable_web_page_preview: bool = False,
) -> bool:
    bot_token = _get_bot_token()
    default_chat = _get_chat_id()
    if not bot_token or not (chat_id or default_chat):
        log.error("חסרים TELEGRAM_BOT_TOKEN או TELEGRAM_CHAT_ID")
        return False

    target_chat = str(chat_id or default_chat)

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
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
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
    # הסרת תגיות HTML שדלפו (כולל <img src="data:..."> עם base64)
    text = re.sub(r'<[^>]+>', '', text)

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
    disable_web_page_preview: bool = False,
) -> dict | None:
    """שולח הודעה עם InlineKeyboard.
    buttons — מערך דו-ממדי של כפתורים, כל dict: {"text": "...", "callback_data": "..."}.
    מחזיר dict של ההודעה שנשלחה (כולל message_id) או None בשגיאה.
    """
    bot_token = _get_bot_token()
    default_chat = _get_chat_id()
    if not bot_token or not (chat_id or default_chat):
        log.error("חסרים TELEGRAM_BOT_TOKEN או TELEGRAM_CHAT_ID")
        return None

    target_chat = str(chat_id or default_chat)

    payload: dict = {
        "chat_id": target_chat,
        "text": text,
        "reply_markup": {"inline_keyboard": buttons},
        "disable_web_page_preview": disable_web_page_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
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
    bot_token = _get_bot_token()
    if not bot_token:
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
            f"https://api.telegram.org/bot{bot_token}/editMessageText",
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
    bot_token = _get_bot_token()
    if not bot_token:
        return False
    payload: dict = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery",
            json=payload,
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def send_document(
    file_bytes: bytes,
    filename: str,
    caption: str = "",
    *,
    chat_id: str | int | None = None,
) -> bool:
    """שולח קובץ לטלגרם דרך sendDocument.

    file_bytes — תוכן הקובץ כ-bytes.
    filename — שם הקובץ שיוצג בטלגרם.
    caption — כיתוב אופציונלי (עד 1024 תווים).
    """
    bot_token = _get_bot_token()
    default_chat = _get_chat_id()
    if not bot_token or not (chat_id or default_chat):
        log.error("חסרים TELEGRAM_BOT_TOKEN או TELEGRAM_CHAT_ID")
        return False

    target_chat = str(chat_id or default_chat)

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendDocument",
            data={"chat_id": target_chat, "caption": caption[:1024]},
            files={"document": (filename, file_bytes)},
            timeout=15,
        )
        if response.status_code == 200:
            log.debug(f"קובץ {filename} נשלח לטלגרם")
            return True
        log.error(f"sendDocument נכשל: {response.status_code}: {response.text}")
        return False
    except Exception as e:
        log.error(f"שגיאה בשליחת קובץ לטלגרם: {e}", exc_info=True)
        return False


def send_error_alert(error: str) -> bool:
    """שולח שגיאה קריטית כהודעת טלגרם (חתוך ל-500 תווים).
    אם ERROR_CHAT_ID מוגדר — שולח למפתח. אחרת — ל-CHAT_ID הרגיל.
    """
    truncated = error[:500]
    return send_message(
        f"⚠️ שגיאה בבוט:\n{truncated}",
        chat_id=ERROR_CHAT_ID,
        disable_web_page_preview=True,
    )


def _to_desktop_url(url: str) -> str:
    """ממיר URL מובייל ל-URL דסקטופ (m.facebook.com → www.facebook.com)."""
    return url.replace("://m.facebook.com", "://www.facebook.com")

def _utf16_len(s: str) -> int:
    """מחזיר אורך מחרוזת ביחידות UTF-16 (כמו ש-Telegram API מצפה)."""
    return len(s.encode("utf-16-le")) // 2


def _build_hot_lead_entities(hot_line: str) -> list[dict] | None:
    """בונה entities עבור custom emoji בשורת ליד חם.

    HOT_LEAD_CUSTOM_EMOJI_ID — מזהה custom emoji של טלגרם פרימיום.
    כדי לקבל את ה-ID: שלח הודעה עם ה-custom emoji לבוט, ובקוד:
        entity = update.message.entities[0]
        custom_emoji_id = entity.custom_emoji_id  # ← זה ה-ID לשמור ב-env

    אם מוגדר, ה-custom emoji מחליף את שני ה-🚨 (לפני ואחרי "ליד חם!").
    """
    custom_emoji_id = os.environ.get("HOT_LEAD_CUSTOM_EMOJI_ID", "").strip()
    if not custom_emoji_id:
        return None

    # שורת ליד חם: "🚨 ליד חם! 🚨" — מחליפים את שני ה-🚨 ב-custom emoji
    placeholder = "\U0001f6a8"
    emoji_utf16_len = _utf16_len(placeholder)

    # offset של האמוג'י השני (בסוף השורה) ביחידות UTF-16
    last_emoji_offset = _utf16_len(hot_line) - emoji_utf16_len

    return [
        {
            "type": "custom_emoji",
            "offset": 0,
            "length": emoji_utf16_len,
            "custom_emoji_id": custom_emoji_id,
        },
        {
            "type": "custom_emoji",
            "offset": last_emoji_offset,
            "length": emoji_utf16_len,
            "custom_emoji_id": custom_emoji_id,
        },
    ]


def _build_full_entities(group_label: str, reason_label: str,
                         link_label: str, link_url: str,
                         text: str, hot_entities: list[dict]) -> list[dict]:
    """בונה את כל ה-entities של ההודעה (custom emoji + bold + text_link).

    Telegram API: parse_mode ו-entities סותרים — כשיש custom emoji
    צריך לבנות את כל הפורמט ידנית כ-entities.

    משתמש ב-rfind כדי למצוא את הלייבלים שמופיעים **אחרי** תוכן הפוסט,
    ולא בטעות לתפוס מחרוזת זהה בתוך תוכן המשתמש.
    """
    entities = list(hot_entities)  # מתחילים עם custom emoji entities

    # bold על "ליד חדש" — מופיע לפני התוכן, find בטוח כאן
    lead_title = "\U0001f3af ליד חדש"
    idx = text.find(lead_title)
    if idx >= 0:
        entities.append({
            "type": "bold",
            "offset": _utf16_len(text[:idx]),
            "length": _utf16_len(lead_title),
        })

    # bold על "קבוצה:" — מופיע לפני התוכן, find בטוח כאן
    idx = text.find(group_label)
    if idx >= 0:
        entities.append({
            "type": "bold",
            "offset": _utf16_len(text[:idx]),
            "length": _utf16_len(group_label),
        })

    # bold על "למה רלוונטי:" — מופיע אחרי התוכן, rfind כדי לא לתפוס תוכן משתמש
    reason_marker = f"\U0001f4a1 {reason_label}"
    idx = text.rfind(reason_marker)
    if idx >= 0:
        entities.append({
            "type": "bold",
            "offset": _utf16_len(text[:idx]),
            "length": _utf16_len(reason_marker),
        })

    # text_link על "פתח פוסט/קבוצה" — תמיד בסוף, rfind בטוח
    link_marker = f"\U0001f517 {link_label}"
    idx = text.rfind(link_marker)
    if idx >= 0:
        entities.append({
            "type": "text_link",
            "offset": _utf16_len(text[:idx]),
            "length": _utf16_len(link_marker),
            "url": link_url,
        })

    return entities


# שורת ברירת מחדל לליד חם — קבועה, לא ניתנת לשינוי
_HOT_LEAD_LINE = "\U0001f6a8 ליד חם! \U0001f6a8"


def send_lead(group_name: str, content: str, post_url: str, reason: str,
              has_real_url: bool = True, also_in: list[str] | None = None,
              is_hot: bool = False):
    if not _get_bot_token() or not _get_chat_id():
        log.error("חסרים משתני סביבה של טלגרם (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
        return False

    content = clean_post_content(content)
    short_content = content[:350] + "..." if len(content) > 350 else content

    # המרת URL מובייל לדסקטופ — נוח יותר למשתמשים
    desktop_url = _to_desktop_url(post_url)

    # טקסט הלינק משתנה לפי סוג ה-URL — פוסט ספציפי או קבוצה בלבד
    link_label = "פתח פוסט" if has_real_url else "פתח קבוצה"

    # תצוגת קבוצה — אם הפוסט הופיע גם בקבוצות נוספות, מציג אותן
    group_label = "קבוצה:"
    group_line = f"\U0001f4cc {group_label} {group_name}"
    if also_in:
        group_line += f" (+ {len(also_in)} קבוצות נוספות)"

    reason_label = "למה רלוונטי:"

    # שורת ליד חם — מופיעה בראש ההודעה אם הפוסט מכיל מילה חמה
    hot_line = ""
    hot_entities = None
    if is_hot:
        hot_line = f"{_HOT_LEAD_LINE}\n\n"
        hot_entities = _build_hot_lead_entities(_HOT_LEAD_LINE)

    # אם יש custom emoji — טקסט בלי markdown, פורמט דרך entities בלבד
    if hot_entities:
        text = (
            f"{hot_line}"
            f"\U0001f3af ליד חדש\n"
            f"{group_line}\n\n"
            f"{short_content}\n\n"
            f"\U0001f4a1 {reason_label} {reason}\n\n"
            f"\U0001f517 {link_label}"
        )
        all_entities = _build_full_entities(
            group_label, reason_label,
            link_label, desktop_url, text, hot_entities,
        )
        bot_token = _get_bot_token()
        chat_id = _get_chat_id()
        payload = {
            "chat_id": chat_id,
            "text": text,
            "entities": all_entities,
            "disable_web_page_preview": False,
        }
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json=payload,
                timeout=10,
            )
            if response.status_code == 200:
                log.info("הודעת ליד חם נשלחה בהצלחה (custom emoji)")
                return True
            # fallback — אם custom emoji נכשל (חשבון לא פרימיום), שולח בלי entities
            log.warning(f"שליחת custom emoji נכשלה ({response.status_code}), שולח ללא custom emoji")
        except Exception as e:
            log.warning(f"שליחת custom emoji נכשלה ({e}), שולח ללא custom emoji")

    # נתיב רגיל (ללא custom emoji, או fallback) — markdown
    text = (
        f"{hot_line}"
        f"\U0001f3af *ליד חדש*\n"
        f"\U0001f4cc *{group_label}* {group_name}"
        + (f" (+ {len(also_in)} קבוצות נוספות)" if also_in else "")
        + f"\n\n{short_content}\n\n"
        f"\U0001f4a1 *{reason_label}* {reason}\n\n"
        f"\U0001f517 [{link_label}]({desktop_url})"
    )
    return send_message(
        text,
        parse_mode="Markdown",
        disable_web_page_preview=False,
    )
