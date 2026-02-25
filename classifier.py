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
        result = json.loads(message.content[0].text)
        log.debug(f"תוצאה: relevant={result.get('relevant')} reason={result.get('reason', '')}")
        return result
    except Exception as e:
        log.error(f"שגיאה בסיווג: {e}", exc_info=True)
        return {"relevant": False, "reason": "שגיאה בסיווג"}
