import os
import json
import anthropic
from logger import get_logger

log = get_logger("Classifier")

client = anthropic.Anthropic(api_key=os.environ.get("CLAUDE_API_KEY"))

# קריטריוני סיווג — ברירת מחדל (ניתן לעדכן דרך הפאנל)
_CLASSIFICATION_CRITERIA_DEFAULT = """אתה מסנן לידים לפרילנסר מפתח ישראלי.
תפקידך: לזהות פוסטים בקבוצות פייסבוק שבהם עסק קטן או בעל עסק קטן מחפש מפתח שיבנה לו משהו.

רלוונטי = כן אם:
- עסק קטן מחפש מפתח / פרילנסר / מתכנת לפרויקט
- בעל עסק קטן מחפש מישהו לבנות לו אתר, בוט, אוטומציה, כלי AI, אפליקציה
- יש תקציב או כוונה ברורה לשלם
- הצעת עבודה מעסק קטן לפרילנסר

רלוונטי = לא אם:
- מישהו מחפש עבודה (הם המועמד, לא הלקוח)
- חברה גדולה או סטארטאפ מגויס מחפשים עובד שכיר
- שאלה טכנית כללית ללא כוונת שכירה
- שיתוף מאמר / כלי / תוכן
- דיון כללי על AI או פיתוח"""


def _get_classification_criteria() -> str:
    """טוען קריטריוני סיווג מ-DB עם fallback לברירת מחדל."""
    try:
        from database import get_config
        custom = get_config("classification_criteria")
        if custom.strip():
            return custom
    except Exception:
        pass
    return _CLASSIFICATION_CRITERIA_DEFAULT


def _build_system_prompt() -> str:
    return _get_classification_criteria() + """

החזר JSON בלבד, ללא טקסט נוסף:
{"relevant": true/false, "reason": "משפט קצר בעברית"}"""


def _build_batch_system_prompt() -> str:
    return _get_classification_criteria() + """

תקבל מספר פוסטים ממוספרים. החזר מערך JSON בלבד, ללא טקסט נוסף.
כל איבר במערך מתאים לפוסט לפי הסדר:
[{"relevant": true/false, "reason": "משפט קצר בעברית"}, ...]"""


def classify_post(content: str, group_name: str) -> dict:
    try:
        log.debug(f"שולח לסיווג: {content[:80]}...")
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system=_build_system_prompt(),
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

        result = _parse_json_response(raw_text)
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


def _parse_json_response(raw_text: str):
    """חילוץ JSON (אובייקט או מערך) מתשובת API, כולל עטיפת markdown."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def classify_batch(posts: list[dict], batch_size: int = 5) -> list[dict]:
    """סיווג מספר פוסטים בבקשה אחת ל-API.

    Args:
        posts: רשימת מילונים עם מפתחות 'content' ו-'group'.
        batch_size: כמה פוסטים לשלוח בכל בקשה (ברירת מחדל: 5).

    Returns:
        רשימה באותו סדר, כל איבר {'relevant': bool, 'reason': str}.
    """
    if not posts:
        return []

    all_results: list[dict] = []

    for start in range(0, len(posts), batch_size):
        batch = posts[start : start + batch_size]
        log.info(f"סיווג באצ' {start // batch_size + 1}: {len(batch)} פוסטים (מתוך {len(posts)})")

        # בניית prompt מרובה פוסטים
        parts = []
        for idx, post in enumerate(batch, 1):
            content = post.get("content", "")[:1000]
            group = post.get("group", "")
            parts.append(f"--- פוסט {idx} ---\nקבוצה: {group}\n\n{content}")
        user_message = "\n\n".join(parts)

        try:
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=150 * len(batch),
                system=_build_batch_system_prompt(),
                messages=[{"role": "user", "content": user_message}],
            )

            raw_text = message.content[0].text if message.content else ""
            log.debug(f"תשובה באצ' ({message.stop_reason}): {raw_text[:300]}")

            if not raw_text.strip():
                log.warning("API החזיר תשובה ריקה בבאצ' — fallback לסיווג בודד")
                for post in batch:
                    all_results.append(classify_post(post["content"], post["group"]))
                continue

            parsed = _parse_json_response(raw_text)

            # אם API החזיר אובייקט בודד במקום מערך (באצ' של 1)
            if isinstance(parsed, dict):
                parsed = [parsed]

            if not isinstance(parsed, list) or len(parsed) != len(batch):
                log.warning(
                    f"אורך תשובה ({len(parsed) if isinstance(parsed, list) else 'N/A'}) "
                    f"לא תואם לבאצ' ({len(batch)}) — fallback לסיווג בודד"
                )
                for post in batch:
                    all_results.append(classify_post(post["content"], post["group"]))
                continue

            # אוספים תוצאות לרשימה זמנית — אם אלמנט לא תקין, ה-exception
            # ייתפס לפני שמוסיפים תוצאות חלקיות ל-all_results
            batch_results = []
            for idx, result in enumerate(parsed):
                log.debug(
                    f"פוסט {start + idx + 1}: "
                    f"relevant={result.get('relevant')} reason={result.get('reason', '')}"
                )
                batch_results.append(result)
            all_results.extend(batch_results)

        except json.JSONDecodeError as e:
            log.error(f"שגיאה בפירוש JSON בבאצ': {e} — fallback לסיווג בודד")
            for post in batch:
                all_results.append(classify_post(post["content"], post["group"]))
        except anthropic.APIError as e:
            log.error(f"שגיאת API בבאצ': {e.status_code} {e.message} — fallback לסיווג בודד")
            for post in batch:
                all_results.append(classify_post(post["content"], post["group"]))
        except Exception as e:
            log.error(f"שגיאה בסיווג באצ': {e} — fallback לסיווג בודד", exc_info=True)
            for post in batch:
                all_results.append(classify_post(post["content"], post["group"]))

    return all_results
