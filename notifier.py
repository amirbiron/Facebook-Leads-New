import os
import re
from urllib.parse import quote

import requests
from logger import get_logger

log = get_logger("Notifier")


# ── קריאות ל-API של טלגרם — נקודת הרכבה אחת לכתובת שמכילה את הטוקן ──
# טלגרם דורש את הטוקן בתוך נתיב ה-URL, ואין לו חלופה בכותרת.
# מקור, מילולית: https://core.telegram.org/bots/api#making-requests —
#   "All queries to the Telegram Bot API must be served over HTTPS and need
#    to be presented in this form: https://api.telegram.org/bot<token>/METHOD_NAME"
# ו-requests מכניס את הכתובת להודעות השגיאה שלו: שגיאת רשת ("Max retries
# exceeded with url: /bot<token>/...") וגם HTTPError של raise_for_status
# ("... for url: {self.url}", ‏requests/models.py ב-2.32.3). כל `log.error(f"...{e}")`
# כתב את הטוקן ללוג (באג #24). לכן הכתובת נבנית רק כאן, וכל שגיאה יוצאת מכאן
# מנוקה — בנקודת ההרכבה ולא אצל הצרכנים (K13).
_TELEGRAM_API_BASE = "https://api.telegram.org"

# שגיאות רשת חולפות — הלולאה של getUpdates רושמת אותן כ-WARNING בשורה אחת.
# ProxyError ו-SSLError הן תת-מחלקות של ConnectionError (requests/exceptions.py).
_TRANSIENT_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)

# מקטע הטוקן בנתיב: "/bot" ואחריו הכל עד ה-"/" הבא, רווח או מירכאה.
_BOT_PATH_RE = re.compile(r"/bot[^/\s'\"]+")

_REDACTED_MESSAGE = "<הודעת השגיאה הוסתרה כי הכילה את הטוקן>"


class TelegramAPIError(Exception):
    """שגיאה בקריאה ל-API של טלגרם. ההודעה לא מכילה את הטוקן.

    status_code — קוד ה-HTTP כשהתקבלה תשובה (למשל 409), None בשגיאת רשת.
    transient — ניתוק רשת חולף, שאפשר פשוט לנסות שוב.
    cause — שם המחלקה של החריגה המקורית, לאבחון.
    החריגה לא שומרת את אובייקט התשובה או את החריגה המקורית: שניהם מחזיקים
    את הכתובת המלאה עם הטוקן (HTTPError.response.url).
    """

    def __init__(self, message: str, *, status_code: int | None = None,
                 transient: bool = False, cause: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.transient = transient
        self.cause = cause


def _redact_token(text: str, bot_token: str) -> str:
    """מסיר את הטוקן מטקסט של הודעת שגיאה. נכשל-סגור (K13).

    מחליף את מקטע הנתיב /bot<token> ואת הטוקן עצמו בכל מקום. אם אחרי זה
    עדיין נשאר זכר לחלק הסודי (למשל בקידוד URL) — מחזיר הודעה קבועה
    במקום הטקסט, כי עדיף לאבד פרטי אבחון מאשר לכתוב את הטוקן ללוג.
    """
    text = _BOT_PATH_RE.sub("/bot<TOKEN>", text)
    if bot_token:
        text = text.replace(bot_token, "<TOKEN>")
        secret = bot_token.split(":", 1)[-1]
        if secret and (secret in text or quote(secret, safe="") in text):
            return _REDACTED_MESSAGE
    return text


def telegram_request(api_method: str, *, bot_token: str, http_method: str = "post",
                     raise_for_status: bool = True, **kwargs) -> requests.Response:
    """קריאה ל-API של טלגרם. הדרך היחידה בקוד לפנות לטלגרם.

    kwargs עוברים כמו שהם ל-requests (json, params, data, files, timeout).
    raise_for_status — ברירת מחדל True: תשובה שאינה 2xx הופכת ל-TelegramAPIError
    עם status_code, ומגיעה ל-except של הקורא. כך קורא ששכח לבדוק את הסטטוס לא
    מתייחס לשגיאת HTTP כאל הצלחה. קורא שבודק את הסטטוס בעצמו (ורושם את
    response.text של טלגרם) מעביר False במפורש.
    כל חריגה מכל סוג הופכת ל-TelegramAPIError עם הודעה מנוקה. החריגה נזרקת
    **אחרי** בלוק ה-except, כדי שלא תישא את המקורית כ-__context__ — שם הטוקן
    היה מודפס ב-traceback של exc_info.
    """
    url = f"{_TELEGRAM_API_BASE}/bot{bot_token}/{api_method}"
    send = requests.get if http_method == "get" else requests.post
    try:
        response = send(url, **kwargs)
        if raise_for_status:
            response.raise_for_status()
        return response
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        error = TelegramAPIError(
            _redact_token(f"{api_method}: HTTPError: {e}", bot_token),
            status_code=status, cause="HTTPError",
        )
    except Exception as e:
        error = TelegramAPIError(
            _redact_token(f"{api_method}: {type(e).__name__}: {e}", bot_token),
            transient=isinstance(e, _TRANSIENT_ERRORS), cause=type(e).__name__,
        )
    raise error

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
        # raise_for_status=False: הסטטוס נבדק כאן, והתיאור של טלגרם נרשם ללוג
        response = telegram_request(
            "sendMessage", bot_token=bot_token, json=payload, timeout=10,
            raise_for_status=False,
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
        response = telegram_request(
            "sendMessage", bot_token=bot_token, json=payload, timeout=10,
            raise_for_status=False,
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
        response = telegram_request(
            "editMessageText", bot_token=bot_token, json=payload, timeout=10,
            raise_for_status=False,
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
        response = telegram_request(
            "answerCallbackQuery", bot_token=bot_token, json=payload, timeout=10,
        )
        return response.status_code == 200
    except Exception as e:
        # לא קריטי: רק עוצר את אנימציית הטעינה על הכפתור. נרשם כדי שכשל
        # חוזר ייראה בלוג (K11) — גם שגיאת HTTP, כי raise_for_status פעיל
        # כברירת מחדל. ההודעה מנוקה מהטוקן ב-telegram_request.
        log.warning(f"answerCallbackQuery נכשל: {e}")
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
        response = telegram_request(
            "sendDocument", bot_token=bot_token,
            data={"chat_id": target_chat, "caption": caption[:1024]},
            files={"document": (filename, file_bytes)},
            timeout=15, raise_for_status=False,
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


# תווים שיש להם משמעות ב-Markdown הישן של טלגרם (parse_mode="Markdown").
# מקור, מילולית: https://core.telegram.org/bots/api#markdown-style —
#   "To escape characters '_', '*', '`', '[' outside of an entity,
#    prepend the character '\' before them."
#   "Escaping inside entities is not allowed"
_MARKDOWN_SPECIAL_RE = re.compile(r"([_*`\[])")


def _escape_markdown(text: str) -> str:
    """מוסיף '\\' לפני כל תו מיוחד של Markdown הישן של טלגרם.

    חובה על כל טקסט שמגיע מבחוץ ומשובץ בהודעה עם parse_mode="Markdown":
    תוכן הפוסט, שם הקבוצה וסיבת הסיווג. בלי זה, קו תחתון בכתובת מייל או
    כוכבית בתוכן נקראים כעיצוב, והעיצוב שבתבנית שלנו (*ליד חדש*) נשבר.
    רק מחוץ לישויות — URL בתוך [טקסט](url) לא עובר דרך כאן, כי בתוך
    ישות אסור לעשות escape (ראו המקור למעלה).
    """
    return _MARKDOWN_SPECIAL_RE.sub(r"\\\1", text)

def send_lead(group_name: str, content: str, post_url: str, reason: str,
              has_real_url: bool = True, also_in: list[str] | None = None,
              is_hot: bool = False, author_url: str = ""):
    if not _get_bot_token() or not _get_chat_id():
        log.error("חסרים משתני סביבה של טלגרם (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
        return False

    content = clean_post_content(content)
    short_content = content[:350] + "..." if len(content) > 350 else content
    # escape אחרי החיתוך ולא לפניו: חיתוך אחרי escape יכול להשאיר '\' יתום
    # בסוף, שיברח מהתו הבא בתבנית במקום מהתו שנחתך.
    short_content = _escape_markdown(short_content)

    # המרת URL מובייל לדסקטופ — נוח יותר למשתמשים
    desktop_url = _to_desktop_url(post_url)

    # טקסט הלינק משתנה לפי סוג ה-URL — פוסט ספציפי או קבוצה בלבד
    link_label = "פתח פוסט" if has_real_url else "פתח קבוצה"

    # תצוגת קבוצה — אם הפוסט הופיע גם בקבוצות נוספות, מציג אותן
    group_line = f"\U0001f4cc *קבוצה:* {_escape_markdown(group_name)}"
    if also_in:
        group_line += f" (+ {len(also_in)} קבוצות נוספות)"

    # שורת ליד חם — מופיעה בראש ההודעה אם הפוסט מכיל מילה חמה
    hot_line = ""
    if is_hot:
        hot_line = "\U0001f6a8 ליד חם! \U0001f6a8\n\n"

    # שורת פרופיל — מוצגת רק אם יש קישור לפרופיל המחבר
    profile_line = ""
    if author_url:
        desktop_author = _to_desktop_url(author_url)
        profile_line = f"\n\U0001f464 [פרופיל המפרסם]({desktop_author})"

    text = (
        f"{hot_line}"
        f"\U0001f3af *ליד חדש*\n"
        f"{group_line}\n\n"
        f"{short_content}\n\n"
        f"\U0001f4a1 *למה רלוונטי:* {_escape_markdown(reason)}\n\n"
        f"\U0001f517 [{link_label}]({desktop_url})"
        f"{profile_line}"
    )
    return send_message(
        text,
        parse_mode="Markdown",
        disable_web_page_preview=False,
    )
