import os
import json
import anthropic
from logger import get_logger

log = get_logger("Classifier")

client = anthropic.Anthropic(api_key=os.environ.get("CLAUDE_API_KEY"))

SYSTEM_PROMPT = """אתה מסנן לידים לפרילנסר מפתח ישראלי.
תפקידך: לזהות פוסטים בקבוצות פייסבוק שבהם מישהו מחפש מישהו לבנות לו משהו ומוכן לשלם.

רלוונטי = כן אם:
- מחפשים מפתח / פרילנסר / מתכנת לפרויקט
- מחפשים מישהו לבנות אתר, בוט, אוטומציה, כלי AI, אפליקציה
- יש תקציב או כוונה ברורה לשלם
- הצעת עבודה לפרילנסר

רלוונטי = לא אם:
- מישהו מחפש עבודה (הם המועמד, לא הלקוח)
- שאלה טכנית כללית ללא כוונת שכירה
- שיתוף מאמר / כלי / תוכן
- דיון כללי על AI או פיתוח

החזר JSON בלבד, ללא טקסט נוסף:
{"relevant": true/false, "reason": "משפט קצר בעברית"}"""

def classify_post(content: str, group_name: str) -> dict:
    try:
        log.debug(f"שולח לסיווג: {content[:80]}...")
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"קבוצה: {group_name}\n\nפוסט:\n{content[:1000]}"
                }
            ]
        )

        raw_text = message.content[0].text if message.content else ""
        log.debug(f"תשובה גולמית מ-API ({message.stop_reason}): {raw_text[:200]}")

        if not raw_text.strip():
            log.warning("API החזיר תשובה ריקה")
            return {"relevant": False, "reason": "תשובה ריקה מ-API"}

        # מנסה לחלץ JSON גם אם עטוף ב-markdown
        text = raw_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        result = json.loads(text)
        log.debug(f"תוצאה: relevant={result.get('relevant')} reason={result.get('reason', '')}")
        return result
    except json.JSONDecodeError as e:
        log.error(f"שגיאה בפירוש JSON: {e} | תשובה: {raw_text[:300]}")
        return {"relevant": False, "reason": "שגיאה בפירוש תשובה"}
    except anthropic.APIError as e:
        log.error(f"שגיאת API: {e.status_code} {e.message}")
        return {"relevant": False, "reason": f"שגיאת API: {e.status_code}"}
    except Exception as e:
        log.error(f"שגיאה בסיווג: {e}", exc_info=True)
        return {"relevant": False, "reason": "שגיאה בסיווג"}
