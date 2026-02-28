"""סריקת ערוץ טלגרם ציבורי של פיקוד העורף דרך web preview.

גישת Web Scraping — ללא צורך ב-Telethon או API credentials של טלגרם.
סורק את https://t.me/s/CHANNEL שמחזיר את ההודעות האחרונות כ-HTML.
"""
import re

import requests
from bs4 import BeautifulSoup

from logger import get_logger

log = get_logger("Scraper")

# ערוץ פיקוד העורף הציבורי
DEFAULT_CHANNEL = "PikudHaOref_all"
CHANNEL_URL_TEMPLATE = "https://t.me/s/{channel}"

# headers סבירים — t.me חוסם requests חשופים
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Mobile Safari/537.36"
    ),
    "Accept-Language": "he-IL,he;q=0.9,en;q=0.5",
}


def fetch_latest_messages(channel: str = DEFAULT_CHANNEL) -> list[dict]:
    """מביא את ההודעות האחרונות מערוץ טלגרם ציבורי.

    מחזיר רשימת dict עם:
      - id: מזהה ההודעה (str)
      - text: תוכן ההודעה
      - date: תאריך (str, אם קיים)
    """
    url = CHANNEL_URL_TEMPLATE.format(channel=channel)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        log.error(f"שגיאה בטעינת ערוץ {channel}: {e}")
        return []

    return _parse_messages(resp.text)


def _parse_messages(html: str) -> list[dict]:
    """מפרש HTML של t.me/s/channel ומחלץ הודעות."""
    soup = BeautifulSoup(html, "html.parser")
    messages = []

    # כל הודעה ב-t.me/s/ עטופה ב-div.tgme_widget_message
    for widget in soup.select(".tgme_widget_message"):
        msg_id = _extract_msg_id(widget)
        if not msg_id:
            continue

        # תוכן ההודעה
        text_el = widget.select_one(".tgme_widget_message_text")
        text = text_el.get_text(separator="\n", strip=True) if text_el else ""
        if not text:
            continue

        # תאריך
        time_el = widget.select_one("time[datetime]")
        date_str = time_el["datetime"] if time_el else ""

        messages.append({
            "id": msg_id,
            "text": text,
            "date": date_str,
        })

    log.debug(f"חולצו {len(messages)} הודעות")
    return messages


def _extract_msg_id(widget) -> str | None:
    """מחלץ message ID מ-data-post attribute."""
    # data-post="PikudHaOref_all/12345"
    data_post = widget.get("data-post", "")
    if "/" in data_post:
        return data_post.split("/")[-1]

    # fallback — href בלינק
    link = widget.select_one("a.tgme_widget_message_date")
    if link and link.get("href"):
        match = re.search(r'/(\d+)$', link["href"])
        if match:
            return match.group(1)

    return None
