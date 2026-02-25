import os
import requests

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_lead(group_name: str, content: str, post_url: str, reason: str):
    if not BOT_TOKEN or not CHAT_ID:
        print("[Notifier] חסרים משתני סביבה של טלגרם")
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
        return response.status_code == 200
    except Exception as e:
        print(f"[Notifier] שגיאה: {e}")
        return False
