# הצעות לשיפורים ופיצ'רים חדשים

## סקירת מצב נוכחי

הבוט כרגע הוא כלי יעיל ומתוכנן היטב — סורק קבוצות פייסבוק, מסווג לידים עם Claude AI, ושולח התראות בטלגרם. הקוד נקי, קל (~1,200 שורות), ומוכן לפרודקשן.

להלן הצעות מסודרות לפי קטגוריות, מהמשפיעות ביותר לפחות:

---

## 1. פיצ'רים חדשים בעלי ערך גבוה

### 1.1 דירוג לידים (Lead Scoring)
**מה:** במקום סיווג בינארי (רלוונטי/לא), לדרג כל ליד ב-1-5 כוכבים.

**למה:** לא כל הלידים שווים — מישהו עם תקציב מוגדר וזמנים ברורים שווה יותר מ"אולי אצטרך מתכנת".

**איך:** לעדכן את ה-System Prompt בקובץ `classifier.py` לבקש גם `score` (1-5), ולהציג את הדירוג בהודעת הטלגרם עם כוכבים.

```python
# classifier.py — שינוי ב-SYSTEM_PROMPT:
# הוספה לתבנית JSON:
# {"relevant": true, "score": 4, "reason": "בעל עסק מחפש בוט טלגרם, ציין תקציב"}

# notifier.py — הצגת הדירוג:
stars = "⭐" * result.get("score", 3)
```

### 1.2 תגובה אוטומטית על פוסטים (Auto-Reply)
**מה:** אפשרות לכתוב תגובה אוטומטית על פוסטים רלוונטיים בפייסבוק.

**למה:** לידים שמגיבים עליהם מהר יותר — סוגרים יותר. במקום לחכות שתראה את ההתראה, הבוט יכול להגיב מיד.

**איך:** להוסיף פונקציה ב-`scraper.py` שמנווטת לפוסט וכותבת תגובה מוכנה מראש. לשלוט בזה עם `AUTO_REPLY_ENABLED` ו-`AUTO_REPLY_TEMPLATE`.

**חשוב:** לשים לב — פייסבוק עלול לחסום חשבונות שמגיבים יותר מדי. להוסיף מגבלת תגובות יומית ודיליי אקראי.

### 1.3 מעקב אחרי קבוצות חדשות אוטומטית
**מה:** לתת לבוט לחפש קבוצות פייסבוק רלוונטיות חדשות ולהציע להוסיף אותן.

**למה:** קבוצות חדשות נפתחות כל הזמן — במיוחד בנושאי AI ו-Vibe Coding.

**איך:** חיפוש פייסבוק לפי מילות מפתח כמו "בינה מלאכותית ישראל", "דרושים מפתחים" וכו'. לשלוח הודעת טלגרם עם הצעה להוסיף קבוצה.

### 1.4 דוח יומי/שבועי מסכם
**מה:** שליחת סיכום תקופתי בטלגרם עם סטטיסטיקות.

**למה:** לדעת אם הבוט עובד טוב, איזה קבוצות הכי פרודוקטיביות, ומה המגמה.

**איך:** להוסיף פקודה `/report` ו-task מתוזמן יומי שישלח:
```
📊 דוח יומי — 26/02/2026
━━━━━━━━━━━━━━━━
✅ פוסטים שנסרקו: 127
🎯 לידים שנשלחו: 4
📌 קבוצה מובילה: "דרושים מתכנתים" (2 לידים)
🔍 סינון AI: 18 נשלחו לסיווג, 4 עברו
📈 יחס המרה: 22%
```

### 1.5 ניהול קבוצות דינמי מטלגרם
**מה:** לאפשר הוספה והסרה של קבוצות ישירות מטלגרם.

**למה:** היום צריך לשנות משתנה סביבה ולעשות deploy מחדש.

**איך:** פקודות חדשות:
- `/add_group <url>` — הוסף קבוצה
- `/remove_group <url>` — הסר קבוצה
- `/groups` — הצג רשימת קבוצות פעילות

לשמור את הקבוצות ב-SQLite במקום רק ב-env var.

---

## 2. שיפורי Scraping ואמינות

### 2.1 Retry מובנה לגרידה
**מה:** אם גרידת קבוצה נכשלת (טיימאאוט, שגיאת רשת), לנסות שוב.

**למה:** כרגע קבוצה שנכשלת פשוט מדולגת — ייתכן שיהיו לידים שם.

**איך ב-`scraper.py`:**
```python
async def scrape_group_with_retry(page, group, max_retries=2):
    for attempt in range(max_retries + 1):
        try:
            return await scrape_group(page, group)
        except Exception as e:
            if attempt < max_retries:
                log.warning(f"ניסיון {attempt+1} נכשל, מנסה שוב...")
                await random_delay(5, 10)
            else:
                log.error(f"כל הניסיונות נכשלו: {e}")
                return []
```

### 2.2 זיהוי סשן שפג תוך כדי סריקה
**מה:** אם באמצע הסריקה פייסבוק מפנה לדף לוגין, לעשות re-login ולהמשיך.

**למה:** כרגע (`scraper.py:283-285`) הבוט רק מחזיר רשימה ריקה כשזה קורה, ומפסיד את כל הקבוצות שנותרו.

**איך:** במקום `return posts`, לבצע login מחדש ולנסות שוב את הקבוצה.

### 2.3 גלילה חכמה יותר
**מה:** במקום גלילה קבועה של 2 פעמים, לגלול עד שמופיעים פוסטים חדשים (או עד מגבלה).

**למה:** בקבוצות פעילות, 2 גלילות לא תמיד מספיקות לראות פוסטים מהשעות האחרונות.

**איך ב-`scraper.py`:**
```python
async def smart_scroll(page, max_scrolls=5, target_posts=15):
    """גלילה עד שמספיק פוסטים נטענו, או עד מקסימום גלילות."""
    for i in range(max_scrolls):
        post_count = await page.evaluate(
            "document.querySelectorAll('article, div[data-ft]').length"
        )
        if post_count >= target_posts:
            break
        await page.evaluate("window.scrollBy(0, 800)")
        await random_delay(1, 2)
```

### 2.4 תמיכה בריבוי דפדפנים (Multi-Page)
**מה:** לפתוח מספר tabs/pages במקביל ולסרוק קבוצות בו-זמנית.

**למה:** סריקה סדרתית של 5+ קבוצות לוקחת זמן רב. סריקה מקבילית יכולה לקצר ב-60%.

**איך:** `asyncio.gather()` עם 2-3 pages. צריך לשים לב לצריכת זיכרון.

---

## 3. שיפורי AI וסיווג

### 3.1 מילות מפתח דינמיות מטלגרם
**מה:** אפשרות לעדכן את `PRE_FILTER_KEYWORDS` ו-`BLOCK_KEYWORDS` מטלגרם.

**למה:** כרגע צריך deploy חדש לכל שינוי במילות מפתח.

**איך:** פקודות חדשות:
- `/keywords` — הצג מילות מפתח נוכחיות
- `/add_keyword <word>` — הוסף מילת מפתח
- `/block <word>` — הוסף מילה חסומה
- `/unblock <word>` — הסר מילה חסומה

לשמור ב-SQLite עם fallback למשתני סביבה.

### 3.2 למידה מפידבק (Feedback Loop)
**מה:** כפתורי "טוב" / "לא רלוונטי" בכל הודעת ליד בטלגרם, והבוט ילמד.

**למה:** עם הזמן, הבוט יסווג טוב יותר כי הוא יבין איזה לידים באמת רלוונטיים עבורך.

**איך:**
1. להוסיף InlineKeyboard לכל הודעת ליד: `[👍 רלוונטי] [👎 לא רלוונטי]`
2. לשמור את הפידבק ב-DB
3. להוסיף ל-System Prompt דוגמאות מלידים שסומנו כטובים/רעים (few-shot learning)

```python
# notifier.py — הוספת כפתורים:
reply_markup = {
    "inline_keyboard": [[
        {"text": "👍 רלוונטי", "callback_data": f"good_{post_id}"},
        {"text": "👎 לא רלוונטי", "callback_data": f"bad_{post_id}"}
    ]]
}
```

### 3.3 סיווג batch במקום אחד-אחד
**מה:** לשלוח כמה פוסטים ל-Claude בבקשה אחת.

**למה:** חוסך API calls ומזרז את הסיווג. עם 20 פוסטים — במקום 20 קריאות, 4 קריאות של 5.

**איך:**
```python
# classifier.py — batch classification:
async def classify_batch(posts: list[dict], batch_size=5) -> list[dict]:
    """מסווג כמה פוסטים בבקשה אחת."""
    prompt = "סווג את הפוסטים הבאים. החזר JSON array:\n\n"
    for i, post in enumerate(posts):
        prompt += f"[{i+1}] קבוצה: {post['group']}\n{post['content'][:500]}\n\n"
    # ...
```

### 3.4 Prompt בדיקת עצמי (Self-Verification)
**מה:** ברגע שליד מסומן כרלוונטי, לעשות בדיקה שנייה עם prompt אחר לוודא.

**למה:** מפחית false positives — לידים שנשלחים אבל לא רלוונטיים באמת.

**איך:** רק על לידים שעברו — לשלוח עוד קריאה עם prompt שמנסה למצוא סיבות שזה *לא* רלוונטי. אם שתי הקריאות מסכימות, לשלוח.

---

## 4. שיפורי מסד נתונים

### 4.1 ניקוי אוטומטי של פוסטים ישנים
**מה:** מחיקת רשומות מ-`seen_posts` שישנות מ-30 יום.

**למה:** בלי זה, הטבלה תגדל ללא הגבלה ותאט את ה-lookups.

**איך ב-`database.py`:**
```python
def cleanup_old_posts(days=30):
    """מוחק פוסטים ישנים מטבלת seen_posts."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        deleted = conn.execute(
            "DELETE FROM seen_posts WHERE seen_at < ?", (cutoff,)
        ).rowcount
        conn.commit()
    log.info(f"נוקו {deleted} פוסטים ישנים (> {days} ימים)")
```

### 4.2 אינדקסים על שדות חיפוש
**מה:** להוסיף אינדקס על `seen_at` ו-`group_name`.

**למה:** ככל שהמסד יגדל, שאילתות כמו "כמה לידים השבוע מקבוצה X" יהיו איטיות בלי אינדקס.

```python
# database.py — ב-init_db():
conn.execute("CREATE INDEX IF NOT EXISTS idx_seen_at ON seen_posts(seen_at)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_group ON sent_leads(group_name)")
```

### 4.3 Connection Pool
**מה:** במקום לפתוח חיבור חדש ל-SQLite בכל פונקציה, לשמור חיבור אחד פתוח.

**למה:** פחות overhead, במיוחד כשבודקים `is_seen` על עשרות פוסטים ברצף.

```python
# database.py:
import threading

_local = threading.local()

def _get_conn():
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(DB_PATH)
    return _local.conn
```

---

## 5. שיפורי טלגרם

### 5.1 הודעות עם InlineKeyboard אינטראקטיביות
**מה:** כפתורים בהודעות במקום פקודות טקסט.

**למה:** חוויית משתמש טובה יותר — לחיצה על כפתור במקום הקלדת פקודה.

**איך:** לשלוח תפריט עם `/menu`:
```
[🔍 סרוק עכשיו]  [📊 סטטוס]
[📋 דוח יומי]    [⚙️ הגדרות]
```

### 5.2 פקודת `/search`
**מה:** חיפוש בתוך לידים שנשלחו.

**למה:** לפעמים רוצים למצוא ליד ישן שנשלח לפני שבוע.

**איך:** `/search בוט טלגרם` — מחפש בתוכן הלידים השמורים ומחזיר תוצאות.

### 5.3 שליחה לכמה משתמשים
**מה:** תמיכה בשליחת לידים ליותר ממשתמש אחד, עם העדפות שונות.

**למה:** אם יש צוות של כמה פרילנסרים, כל אחד יכול לקבל לידים בהתאם למומחיות שלו.

### 5.4 פקודת `/pause` ו-`/resume`
**מה:** להשהות ולחדש סריקה בלי לעצור את הבוט.

**למה:** לפעמים רוצים לעצור זמנית (למשל בחופשה) בלי לשנות deployment.

---

## 6. אבטחה ויציבות

### 6.1 הצפנת Session
**מה:** להצפין את קובץ ה-cookies (`fb_session.json`) במקום JSON פתוח.

**למה:** אם מישהו מגיע לקובץ, יש לו גישה מלאה לחשבון הפייסבוק.

**איך:** להשתמש ב-`cryptography.fernet` עם מפתח מ-env var.

### 6.2 Rate Limiting על API Calls
**מה:** להגביל את מספר הקריאות ל-Claude ולטלגרם ליחידת זמן.

**למה:** מניעת חריגה ממכסות ועלויות מיותרות.

```python
# classifier.py:
import time

_last_call = 0
MIN_INTERVAL = 0.5  # שנייה בין קריאות

def classify_post(content, group_name):
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_call = time.time()
    # ...
```

### 6.3 Healthcheck Endpoint
**מה:** להוסיף endpoint פשוט שמאשר שהבוט חי.

**למה:** לשלב עם Render.com health checks ולקבל התראה אם הבוט קרס.

**איך:** להריץ שרת HTTP קטן ב-thread נפרד:
```python
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def start_health_server(port=8080):
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
```

---

## 7. שיפורי Monitoring ולוגים

### 7.1 מעקב שגיאות (Error Tracking)
**מה:** שליחת שגיאות קריטיות כהודעת טלגרם.

**למה:** כרגע שגיאות נכתבות רק ללוג — אם הבוט נתקע, אתה לא יודע.

**איך:** ב-`main.py`, כשנתפסת שגיאה בלתי צפויה, לשלוח הודעה:
```python
except Exception as e:
    log.error(f"שגיאה לא צפויה: {e}", exc_info=True)
    try:
        send_message(f"⚠️ שגיאה בבוט:\n{str(e)[:500]}")
    except:
        pass
```

### 7.2 מטריקות מפורטות
**מה:** לשמור מטריקות על כל סבב — זמן סריקה, פוסטים לכל קבוצה, שגיאות.

**למה:** לזהות בעיות ומגמות, למשל אם קבוצה מסוימת תמיד חוזרת ריקה.

**איך:** טבלה חדשה `scan_metrics`:
```sql
CREATE TABLE scan_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT,
    finished_at TEXT,
    groups_scanned INTEGER,
    posts_found INTEGER,
    posts_classified INTEGER,
    leads_sent INTEGER,
    errors TEXT
)
```

### 7.3 Structured Logging (JSON)
**מה:** לוגים בפורמט JSON.

**למה:** קל יותר לפרסר, לחפש ולסנן בכלים כמו Render.com logs, Grafana, או Datadog.

---

## 8. שיפורי קוד ותשתית

### 8.1 טסטים
**מה:** להוסיף טסטים בסיסיים.

**למה:** כרגע אין אף טסט — כל שינוי עלול לשבור דברים בלי שתדע.

**מה לבדוק קודם:**
- `passes_keyword_filter()` — בדיקת סינון מילות מפתח
- `is_blocked()` — בדיקת מילים חסומות
- `_parse_quiet_hours()` / `_is_quiet_now()` — לוגיקת שעות שקטות
- `clean_post_content()` — ניקוי תוכן
- `extract_post_id()` — חילוץ ID מ-URLs שונים
- `classify_post()` — mock של API ובדיקת parsing

### 8.2 קובץ `.env.example`
**מה:** קובץ דוגמה עם כל משתני הסביבה הנדרשים.

**למה:** מקל על הגדרה ראשונית ומונע שכחת משתנה.

### 8.3 Docker Compose לפיתוח מקומי
**מה:** `docker-compose.yml` להרצה מקומית.

**למה:** קל יותר לפתח ולבדוק מאשר להריץ ישירות.

### 8.4 Type Hints מלאים
**מה:** להוסיף type hints לכל הפונקציות (חלקן כבר עם, חלקן בלי).

**למה:** IDE support טוב יותר, פחות באגים, קל יותר לתחזק.

---

## 9. פיצ'רים מתקדמים (לטווח ארוך)

### 9.1 תמיכה בפלטפורמות נוספות
**מה:** לסרוק גם לינקדאין, קבוצות ווטסאפ, או ערוצי טלגרם.

**למה:** לידים לא מגיעים רק מפייסבוק.

### 9.2 CRM פנימי בסיסי
**מה:** מעקב אחרי סטטוס כל ליד — חדש, נפגשנו, הצעת מחיר, סגרנו.

**למה:** לדעת מה קורה עם כל ליד ולא לאבד מעקב.

**איך:** כפתורי סטטוס בטלגרם + טבלת DB:
```
[📞 יצרתי קשר] [💰 הצעת מחיר] [✅ סגרנו] [❌ לא רלוונטי]
```

### 9.3 Dashboard (ווב)
**מה:** ממשק ווב פשוט לצפייה בלידים, סטטיסטיקות וניהול.

**למה:** טלגרם מוגבל — ממשק ווב מאפשר חיפוש, סינון, וגרפים.

### 9.4 AI Summary יומי
**מה:** סיכום AI של המגמות: "היום ראינו הרבה ביקוש לבוטים לווטסאפ, ופחות ביקוש לאתרים".

**למה:** להבין מגמות שוק ולהתאים את ההצעה שלך.

---

## סדר עדיפויות מומלץ

| עדיפות | שיפור | מאמץ | השפעה |
|---------|--------|------|--------|
| 🔴 1 | דירוג לידים (1.1) | נמוך | גבוהה |
| 🔴 2 | Retry בגרידה (2.1) | נמוך | גבוהה |
| 🔴 3 | ניקוי DB אוטומטי (4.1) | נמוך | בינונית |
| 🔴 4 | התראות שגיאה בטלגרם (7.1) | נמוך | גבוהה |
| 🟡 5 | דוח יומי (1.4) | בינוני | גבוהה |
| 🟡 6 | פידבק על לידים (3.2) | בינוני | גבוהה |
| 🟡 7 | טסטים בסיסיים (8.1) | בינוני | בינונית |
| 🟡 8 | גלילה חכמה (2.3) | נמוך | בינונית |
| 🟡 9 | ניהול קבוצות מטלגרם (1.5) | בינוני | בינונית |
| 🟢 10 | CRM בסיסי (9.2) | גבוה | גבוהה |
| 🟢 11 | Dashboard ווב (9.3) | גבוה | בינונית |
| 🟢 12 | פלטפורמות נוספות (9.1) | גבוה | גבוהה |

**מקרא:** 🔴 לעשות עכשיו | 🟡 שלב שני | 🟢 טווח ארוך

---

## 10. זיהוי כפילויות חוצות-קבוצות (Cross-Group Deduplication)

### 10.1 מניעת שליחת ליד כפול מקבוצות שונות
**מה:** אותו אדם מפרסם פוסט זהה (או דומה מאוד) ב-3 קבוצות → הבוט שולח ליד אחד בלבד, עם ציון שהפוסט הופיע גם בקבוצות אחרות.

**למה:** היום כל פוסט מקבל `post_id` שונה לפי URL, כך שאם מישהו מפרסם באותו נוסח ב-3 קבוצות — מקבלים 3 הודעות טלגרם על אותו ליד. זה יוצר רעש ומבזבז זמן.

**איך:**
```python
# main.py — לפני שליחה ל-AI, לבדוק דמיון תוכן:
import hashlib

def _content_fingerprint(text: str) -> str:
    """יוצר 'טביעת אצבע' לתוכן — מנרמל רווחים, מוריד סימני פיסוק, ולוקח hash."""
    normalized = re.sub(r'\s+', ' ', text.lower().strip())
    normalized = re.sub(r'[^\w\s]', '', normalized)
    # לוקח רק 200 תווים ראשונים (מספיק לזיהוי דמיון, מתעלם מ-footer שונה)
    return hashlib.md5(normalized[:200].encode()).hexdigest()

# בסבב — לפני סיווג:
seen_fingerprints = {}
unique_posts = []
for post in to_classify:
    fp = _content_fingerprint(post["content"])
    if fp in seen_fingerprints:
        # פוסט כפול — מוסיף את שם הקבוצה לליד המקורי
        seen_fingerprints[fp]["also_in"].append(post["group"])
    else:
        post["also_in"] = []
        seen_fingerprints[fp] = post
        unique_posts.append(post)
```

**בהודעת הטלגרם:**
```
🎯 ליד חדש
📌 קבוצה: דרושים מתכנתים (+ 2 קבוצות נוספות)
```

---

## 11. זיהוי דחיפות ותזמון (Urgency Detection)

### 11.1 תיוג דחיפות לידים
**מה:** זיהוי אוטומטי של לידים דחופים — "צריך עד מחר", "דחוף", "ASAP", "השבוע" — ושליחת התראה מיוחדת.

**למה:** ליד דחוף ששולחים עליו הצעה אחרי שעתיים כבר לא רלוונטי. אם הבוט מזהה דחיפות, אפשר לשים לב מיד.

**איך:**
```python
# main.py או classifier.py:
URGENCY_PATTERNS = [
    r'\bדחוף\b', r'\bASAP\b', r'\bבהקדם\b',
    r'\bעד מחר\b', r'\bהשבוע\b', r'\bעד יום\b',
    r'\bצריך עכשיו\b', r'\bמיידי\b', r'\burgent\b',
]

def detect_urgency(text: str) -> bool:
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in URGENCY_PATTERNS)

# בהודעת ליד:
# 🚨 ליד דחוף!  (במקום 🎯 ליד חדש)
```

**אפשר גם:** לבקש מה-AI להעריך דחיפות כחלק מהסיווג:
```json
{"relevant": true, "reason": "...", "urgent": true}
```

---

## 12. ניטור בריאות קבוצות (Group Health Monitor)

### 12.1 זיהוי קבוצות שלא מחזירות פוסטים
**מה:** מעקב אחרי כמה פוסטים כל קבוצה מייצרת. אם קבוצה מחזירה 0 פוסטים בכמה סבבים ברצף — שליחת התראה.

**למה:** קבוצה עלולה להיסגר, להפוך לפרטית, או שהחשבון הורחק ממנה — והבוט ממשיך "לסרוק" אותה לשווא בכל סבב. בלי ניטור, אתה לא יודע שזה קורה.

**איך:**
```python
# database.py — טבלה חדשה:
# CREATE TABLE IF NOT EXISTS group_health (
#     group_url TEXT PRIMARY KEY,
#     last_posts_count INTEGER DEFAULT 0,
#     consecutive_empty INTEGER DEFAULT 0,
#     last_lead_at TEXT,
#     updated_at TEXT
# )

# main.py — אחרי סריקה:
for group in GROUPS:
    group_posts = [p for p in posts if p["group_url"] == group["url"]]
    update_group_health(group["url"], len(group_posts))

# התראה:
if consecutive_empty >= 5:
    send_message(f"⚠️ הקבוצה '{group_name}' לא מחזירה פוסטים כבר {consecutive_empty} סבבים — כדאי לבדוק")
```

**בונוס:** פקודת `/health` שמציגה סטטיסטיקות לכל קבוצה:
```
📊 בריאות קבוצות:
✅ דרושים מתכנתים — 12 פוסטים/סבב, ליד אחרון: לפני שעתיים
✅ AI Israel — 8 פוסטים/סבב, ליד אחרון: אתמול
⚠️ Vibe Coding — 0 פוסטים (3 סבבים ברצף!)
```

---

## 13. אינטגרציה עם Webhook (Zapier / Make / n8n)

### 13.1 שליחת לידים ל-Webhook חיצוני
**מה:** בנוסף להודעת טלגרם, לשלוח כל ליד גם ל-webhook URL. מאפשר אינטגרציה עם Google Sheets, Notion, CRM, ועוד.

**למה:** טלגרם טוב להתראות מיידיות, אבל לידים צריכים להיכנס גם למקום מרוכז (טבלה, CRM, Notion). Webhook מאפשר חיבור לכל כלי בלי לכתוב קוד.

**איך ב-`notifier.py`:**
```python
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

def send_to_webhook(group_name: str, content: str, post_url: str, reason: str) -> bool:
    if not WEBHOOK_URL:
        return True  # לא מוגדר — לא שולחים
    payload = {
        "event": "new_lead",
        "group": group_name,
        "content": content[:500],
        "url": post_url,
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
    }
    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        return resp.status_code < 400
    except Exception as e:
        log.warning(f"Webhook failed: {e}")
        return False
```

**תרחישי שימוש:**
- **Google Sheets** (דרך Make.com): טבלת לידים שמתעדכנת אוטומטית
- **Notion DB**: כל ליד נכנס כעמוד עם סטטוס
- **Monday.com / Trello**: כרטיס חדש לכל ליד

---

## 14. תזמון סריקה אדפטיבי (Adaptive Scan Intervals)

### 14.1 סריקה תכופה יותר בשעות פעילות
**מה:** במקום `INTERVAL_MINUTES=10` קבוע, להגדיר תזמון שונה לשעות עומס ושעות שקט.

**למה:** בין 9:00-18:00 קבוצות פייסבוק הכי פעילות — כדאי לסרוק כל 5 דקות. אחרי 22:00 מספיק פעם בחצי שעה. חוסך משאבים ומגיב מהר יותר בשעות חמות.

**איך:**
```python
# main.py:
PEAK_HOURS = os.environ.get("PEAK_HOURS", "8:00-20:00")
PEAK_INTERVAL = int(os.environ.get("PEAK_INTERVAL_MINUTES", "5"))
OFFPEAK_INTERVAL = int(os.environ.get("OFFPEAK_INTERVAL_MINUTES", "20"))

def _get_adaptive_interval() -> int:
    """מחזיר אינטרוול מותאם לפי שעה ביום."""
    try:
        peak = _parse_quiet_hours(PEAK_HOURS)  # אותו פורמט כמו שעות שקטות
        if peak and _is_quiet_now(_now_local(), peak):
            # "שקט" כאן = בטווח השעות = שעות שיא
            return PEAK_INTERVAL
    except Exception:
        pass
    return OFFPEAK_INTERVAL
```

---

## 15. מעקב עלויות API (API Cost Tracking)

### 15.1 ספירת טוקנים ותצוגת עלויות
**מה:** לספור כמה טוקנים נצרכו בכל קריאה ל-OpenAI, לשמור ב-DB, ולהציג ב-`/status`.

**למה:** gpt-5-nano זול, אבל עם 6 סבבים בשעה × 20 פוסטים × 30 יום — העלויות מצטברות. חשוב לדעת כמה הבוט עולה.

**איך:**
```python
# classifier.py — אחרי כל קריאה:
usage = response.usage
total_tokens = usage.total_tokens if usage else 0

# database.py:
# CREATE TABLE api_usage (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     model TEXT,
#     prompt_tokens INTEGER,
#     completion_tokens INTEGER,
#     total_tokens INTEGER,
#     estimated_cost_usd REAL,
#     created_at TEXT
# )

# /status — תצוגה:
# 💰 עלות API החודש: ~$0.42 (83,500 tokens)
```

---

## 16. ייצוא לידים (Lead Export)

### 16.1 פקודת `/export` לייצוא CSV
**מה:** פקודת טלגרם ששולחת קובץ CSV עם כל הלידים מתקופה נתונה.

**למה:** לפעמים צריך לראות את כל הלידים בטבלה, לשלוח ללקוח, או לנתח במחשב. CSV פותח בכל כלי.

**איך:**
```python
# main.py — פקודה חדשה:
if cmd == "/export":
    import csv, io
    conn = _get_conn()
    rows = conn.execute(
        "SELECT group_name, content, reason, sent_at FROM sent_leads ORDER BY sent_at DESC LIMIT 100"
    ).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["קבוצה", "תוכן", "סיבה", "תאריך"])
    for row in rows:
        writer.writerow(row)

    # שליחה כקובץ דרך Telegram sendDocument API
    requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendDocument",
        data={"chat_id": chat_id},
        files={"document": ("leads.csv", buf.getvalue().encode("utf-8-sig"), "text/csv")},
    )
```

---

## 17. דייג'סט לידים (Lead Digest Mode)

### 17.1 איסוף לידים ושליחה כסיכום
**מה:** מצב שבו במקום לשלוח כל ליד מיד, הבוט אוסף אותם ושולח דייג'סט (סיכום) כל X שעות או לפי פקודה.

**למה:** לפעמים יש 10 לידים בשעה וזה מציף. מצב דייג'סט נותן שקט ומרכז הכל להודעה אחת מסודרת.

**איך:**
```python
# main.py:
DIGEST_MODE = os.environ.get("DIGEST_MODE", "0").lower() in ("1", "true")
DIGEST_INTERVAL_HOURS = int(os.environ.get("DIGEST_INTERVAL_HOURS", "4"))

# במקום לשלוח מיד — לשמור בטבלה pending_digest:
# כל X שעות, או כשהמשתמש שולח /digest:
def _send_digest():
    pending = get_pending_leads()
    if not pending:
        send_message("📭 אין לידים חדשים מאז הדייג'סט האחרון")
        return
    header = f"📋 *דייג'סט — {len(pending)} לידים חדשים*\n\n"
    items = []
    for i, lead in enumerate(pending, 1):
        items.append(f"{i}. *{lead['group']}*\n{lead['content'][:100]}...\n🔗 [פתח]({lead['url']})")
    send_message(header + "\n\n".join(items))
```

---

## 18. תבניות תגובה מהירות (Quick Reply Templates)

### 18.1 שמירת תגובות מוכנות לכל סוג ליד
**מה:** הגדרת תבניות תגובה (למשל: הצעה ללקוח שמחפש בוט, הצעה ללקוח שמחפש אתר). עם כל ליד נשלח כפתור "העתק תגובה" שמייצר טקסט מותאם.

**למה:** כשמגיע ליד, צריך להגיב מהר. במקום לכתוב מאפס כל פעם, תבנית מוכנה חוסכת זמן ומגדילה את הסיכוי לסגירה.

**איך:**
```python
# database.py — טבלה חדשה:
# CREATE TABLE reply_templates (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     name TEXT NOT NULL,
#     template TEXT NOT NULL,
#     created_at TEXT
# )

# פקודות טלגרם:
# /templates — הצג תבניות
# /add_template <שם> <תוכן> — הוסף תבנית
# /remove_template <שם> — מחק תבנית

# בהודעת ליד — כפתור InlineKeyboard:
reply_markup = {
    "inline_keyboard": [[
        {"text": "📋 העתק תגובה", "callback_data": f"reply_{post_id}"}
    ]]
}
# callback שולח הודעה עם התבנית ופרטי הליד
```

---

## 19. סיכום AI של הליד (Lead Summary)

### 19.1 סיכום אוטומטי של פוסטים ארוכים
**מה:** לפוסטים ארוכים (מעל 200 תווים), לבקש מה-AI סיכום של 2-3 שורות במקום לשלוח את הטקסט הגולמי.

**למה:** פוסטים בפייסבוק ארוכים ומלאים רעש (אימוג'ים, hashtags, הקדמות). סיכום AI נותן את התמצית: מה מחפשים, מה התקציב, מה הלו"ז.

**איך:**
```python
# classifier.py — הרחבת הפרומפט:
# במקום רק relevant/reason, גם:
# {"relevant": true, "reason": "...", "summary": "בעל מסעדה מחפש מפתח לבוט הזמנות בווטסאפ, תקציב 5000₪, צריך תוך שבועיים"}

# notifier.py — שימוש בסיכום:
summary = result.get("summary", short_content)
text = (
    f"🎯 *ליד חדש*\n"
    f"📌 *קבוצה:* {group_name}\n\n"
    f"📝 *תקציר:* {summary}\n\n"
    f"💡 *למה רלוונטי:* {reason}\n\n"
    f"🔗 [פתח פוסט]({post_url})"
)
```

**הערה:** מוסיף ~20 טוקנים לכל תשובה, עלות זניחה.

---

## 20. Notification Throttle (הגבלת קצב התראות)

### 20.1 מניעת הצפה של הודעות
**מה:** הגבלת מספר הלידים שנשלחים בשעה (למשל: מקסימום 10). לידים מעבר למגבלה נשמרים ונשלחים בסבב הבא.

**למה:** אם יש פרסומת ויראלית על "מי מכיר מתכנת" — עשרות פוסטים עוברים את הסינון. 30 הודעות טלגרם בדקה אחת זה לא שימושי.

**איך:**
```python
# main.py:
MAX_LEADS_PER_HOUR = int(os.environ.get("MAX_LEADS_PER_HOUR", "15"))

def _leads_sent_last_hour() -> int:
    cutoff = (datetime.now() - timedelta(hours=1)).isoformat()
    return _get_conn().execute(
        "SELECT COUNT(*) FROM sent_leads WHERE sent_at > ?", (cutoff,)
    ).fetchone()[0]

# לפני שליחת ליד:
if _leads_sent_last_hour() >= MAX_LEADS_PER_HOUR:
    log.info("הגבלת לידים לשעה הושגה — הליד יישלח בסבב הבא")
    # שומרים ב-DB כ-"pending" ושולחים בסבב הבא
```

---

## 21. תמיכה במספר חשבונות פייסבוק (Multi-Account Rotation)

### 21.1 סיבוב בין חשבונות לצמצום סיכון חסימה
**מה:** הגדרת 2-3 חשבונות פייסבוק וסיבוב ביניהם בין סבבים.

**למה:** פייסבוק מגביל scraping — חשבון בודד שגולש ב-5 קבוצות כל 10 דקות עלול להיחסם. סיבוב בין חשבונות מפזר את העומס ומקטין סיכון.

**איך:**
```python
# scraper.py:
FB_ACCOUNTS = []  # רשימת {email, password} ממשתני סביבה
# FB_ACCOUNTS_JSON = '[{"email":"a@x.com","password":"..."}, ...]'

_current_account_idx = 0

def _get_next_account() -> dict:
    global _current_account_idx
    if not FB_ACCOUNTS:
        return {"email": FB_EMAIL, "password": FB_PASSWORD}
    account = FB_ACCOUNTS[_current_account_idx % len(FB_ACCOUNTS)]
    _current_account_idx += 1
    return account
```

**חשוב:** כל חשבון צריך session file נפרד (`fb_session_0.json`, `fb_session_1.json`...).

---

## 22. זמני תגובה ו-KPIs (Response Time Tracking)

### 22.1 מדידת זמן מפרסום הפוסט עד שליחת ליד
**מה:** חילוץ זמן הפרסום מפייסבוק ומדידת הפער עד שהליד נשלח.

**למה:** ליד שמגיע אחרי 5 דקות שווה הרבה יותר מליד שמגיע אחרי שעתיים. אם ה-KPI הזה גבוה מדי — צריך לסרוק יותר תכוף או לצמצם קבוצות.

**איך:**
```python
# scraper.py — חילוץ timestamp מפוסט:
# באתר מובייל, הזמן מופיע בלינק ("12 שעות", "3 דקות" וכו')
# או ב-ARIA label של חותמת הזמן

# database.py — שדה חדש ב-sent_leads:
# post_published_at TEXT  (ISO format, אם הצלחנו לחלץ)

# /status — תצוגה:
# ⏱ זמן תגובה ממוצע: 12 דקות
```

---

## 23. מצב Debug בטלגרם (Telegram Debug Mode)

### 23.1 פקודת `/debug` לאבחון בעיות
**מה:** פקודה שמציגה מידע טכני מפורט — גרסת דפדפן, מצב סשן, שימוש בזיכרון, לוגים אחרונים.

**למה:** כשמשהו לא עובד, היום צריך גישה SSH לשרת. פקודת debug בטלגרם מאפשרת אבחון מרחוק.

**איך:**
```python
if cmd == "/debug":
    import psutil, sys
    process = psutil.Process()
    mem = process.memory_info()
    msg = (
        f"🔧 Debug Info:\n"
        f"- Python: {sys.version.split()[0]}\n"
        f"- RAM: {mem.rss / 1024 / 1024:.1f}MB\n"
        f"- DB size: {DB_PATH.stat().st_size / 1024:.0f}KB\n"
        f"- Session: {'קיים' if SESSION_FILE.exists() else 'חסר'}\n"
        f"- Model: {_get_active_model()}\n"
        f"- Uptime: {datetime.now() - start_time}\n"
        f"- Last 5 errors: ..."
    )
```

**הערה:** `psutil` כבר מותקן ברוב Docker images. אם לא — אפשר להשתמש ב-`resource` module.

---

## 24. גיבוי אוטומטי של מסד הנתונים (Auto Backup)

### 24.1 גיבוי DB יומי
**מה:** פעם ביום, העתקת קובץ ה-SQLite לנתיב גיבוי. שמירת 7 גיבויים אחרונים.

**למה:** אם DB נפגם (קריסה באמצע כתיבה, דיסק מלא) — אתה מאבד את כל ההיסטוריה. גיבוי יומי = מקסימום יום אחד אבוד.

**איך:**
```python
# database.py:
import shutil

BACKUP_DIR = Path("data/backups")

def backup_db():
    """גיבוי יומי של מסד הנתונים — שומר 7 גיבויים אחרונים."""
    BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d")
    dest = BACKUP_DIR / f"leads_{timestamp}.db"
    if dest.exists():
        return  # כבר גובה היום
    shutil.copy2(DB_PATH, dest)
    # מחיקת גיבויים ישנים (שומר 7 אחרונים)
    backups = sorted(BACKUP_DIR.glob("leads_*.db"))
    for old in backups[:-7]:
        old.unlink()
    log.info(f"DB backed up: {dest}")

# main.py — קריאה בתחילת כל סבב:
backup_db()
```

---

## 25. סינון לפי גיל פוסט (Post Age Filter)

### 25.1 התעלמות מפוסטים ישנים
**מה:** הגדרת `MAX_POST_AGE_HOURS` — פוסטים שפורסמו לפני יותר מ-X שעות לא יסווגו, גם אם הם חדשים לבוט.

**למה:** אם הבוט היה כבוי יום שלם ואז הופעל, הוא רואה 100+ פוסטים "חדשים". רובם כבר לא רלוונטיים — מישהו כבר ענה. סינון לפי גיל חוסך API calls מיותרים.

**איך:** לחלץ את הזמן מהפוסט (אסטרטגיית timestamp שכבר קיימת ב-scraper) ולהשוות:
```python
# scraper.py — הרחבה של _extract_post_url:
# מחזיר גם timestamp אם הצליח לחלץ
# {"url": "...", "age_text": "3 שעות"}

MAX_POST_AGE_HOURS = int(os.environ.get("MAX_POST_AGE_HOURS", "24"))

def _parse_age_text(age_text: str) -> int | None:
    """ממיר 'X שעות' / 'X ימים' לשעות."""
    m = re.search(r'(\d+)\s*(שע|דק|יו|שני|חוד)', age_text)
    if not m:
        return None
    num = int(m.group(1))
    unit = m.group(2)
    if "דק" in unit: return 0
    if "שע" in unit: return num
    if "יו" in unit: return num * 24
    return num * 24 * 30  # חודשים
```

---

## סדר עדיפויות — הצעות חדשות

| עדיפות | שיפור | מאמץ | השפעה |
|---------|--------|------|--------|
| 🔴 1 | כפילויות חוצות-קבוצות (10.1) | נמוך | גבוהה |
| 🔴 2 | זיהוי דחיפות (11.1) | נמוך | גבוהה |
| 🔴 3 | סיכום AI של הליד (19.1) | נמוך | גבוהה |
| 🔴 4 | הגבלת קצב התראות (20.1) | נמוך | בינונית |
| 🟡 5 | בריאות קבוצות (12.1) | בינוני | גבוהה |
| 🟡 6 | Webhook חיצוני (13.1) | בינוני | גבוהה |
| 🟡 7 | ייצוא CSV (16.1) | נמוך | בינונית |
| 🟡 8 | Debug בטלגרם (23.1) | נמוך | בינונית |
| 🟡 9 | גיבוי DB (24.1) | נמוך | בינונית |
| 🟡 10 | סינון לפי גיל פוסט (25.1) | בינוני | בינונית |
| 🟢 11 | תזמון אדפטיבי (14.1) | בינוני | בינונית |
| 🟢 12 | עלויות API (15.1) | בינוני | נמוכה |
| 🟢 13 | דייג'סט לידים (17.1) | גבוה | בינונית |
| 🟢 14 | תבניות תגובה (18.1) | גבוה | בינונית |
| 🟢 15 | סיבוב חשבונות (21.1) | גבוה | גבוהה |
| 🟢 16 | זמני תגובה (22.1) | בינוני | נמוכה |

**מקרא:** 🔴 לעשות עכשיו | 🟡 שלב שני | 🟢 טווח ארוך
