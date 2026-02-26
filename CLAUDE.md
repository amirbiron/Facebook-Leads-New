# CLAUDE.md — כללי עבודה לפרויקט Facebook Leads Bot

## סקירה
בוט שסורק קבוצות פייסבוק, מסנן לידים רלוונטיים באמצעות Claude API, ושולח אותם לטלגרם.
רץ על VM עם **512MB RAM** — כל שינוי חייב להתחשב במגבלת זיכרון.

## קבצים עיקריים
| קובץ | תפקיד |
|-------|--------|
| `scraper.py` | גלישה בפייסבוק עם Playwright (אתר מובייל) |
| `main.py` | אורקסטרציה, לולאת טלגרם, שעות שקטות |
| `classifier.py` | סיווג פוסטים עם Claude Haiku |
| `notifier.py` | שליחת הודעות טלגרם |
| `database.py` | SQLite — seen_posts, sent_leads |
| `logger.py` | לוגר |

## באגים שתוקנו — לא לחזור עליהם

### 1. עצירה מוקדמת בגלל פוסט מוצמד (pinned)
**הבעיה:** פוסט מוצמד בראש הפיד כבר ב-DB → `seen_checker` מחזיר `True` → גלילה נעצרת מיד עם 0 פוסטים.
**הכלל:** תמיד לדרוש **רצף** של פוסטים מוכרים לפני עצירה (`KNOWN_THRESHOLD`), לא פוסט בודד.

### 2. מעקב לפי אינדקס שובר DOM וירטואלי
**הבעיה:** שימוש ב-`post_elements[index:]` נשבר כשפייסבוק מסיר/מוסיף אלמנטים בגלילה (virtualization).
**הכלל:** תמיד לעקוב לפי **תוכן** (`seen_texts` set), לא לפי אינדקס.

### 3. fallback URL יוצר post_id זהה לכל הפוסטים
**הבעיה:** כשחילוץ URL נכשל, ה-fallback הוא URL הקבוצה → כל הפוסטים מקבלים אותו ID → `seen_checker` עוצר הכל.
**הכלל:** לבדוק `seen_checker` רק כש-`has_real_url == True`.

### 4. חסימת event loop עם קריאות סינכרוניות
**הבעיה:** `requests.post()` חוסם את הלולאה האסינכרונית.
**הכלל:** כל קריאת רשת סינכרונית חייבת להיות עטופה ב-`asyncio.to_thread()`.

### 5. טלגרם 409 Conflict בין instances
**הבעיה:** שתי instances שעושות polling → 409 Conflict חוזר.
**הכלל:** backoff מעריכי על שגיאות 409.

## כללי scraping

- **אתר מובייל בלבד** (`m.facebook.com`) — חוסך ~60% זיכרון.
- **חסימת משאבים כבדים** — תמונות, וידאו, פונטים נחסמים ב-route handler.
- **`about:blank` בין קבוצות** — לשחרר DOM בזיכרון.
- **`gc.collect()`** אחרי סיום scraping ולפני סיווג.
- **גלילה חכמה** — לא מספר גלילות קבוע. גוללים עד רצף פוסטים מוכרים או `MAX_SCROLLS`.
- **חילוץ URL** — 3 אסטרטגיות (סלקטורים ישירים → סריקת כל הלינקים → לינק timestamp). Fallback ל-URL קבוצה אם הכל נכשל.

## async

- כל הקוד async. Playwright משתמש ב-async API.
- קריאות סינכרוניות (requests, sqlite) חייבות `asyncio.to_thread()`.
- task של טלגרם נשמר במשתנה (`_control_task`) כדי שלא ייאסף ע"י GC.

## טסטים

כרגע אין טסטים. בכל שינוי ללוגיקה, לוודא ידנית:
- `passes_keyword_filter()` — מסנן לפי מילות מפתח
- `is_blocked()` — חוסם מילים אסורות
- `extract_post_id()` — מחלץ ID מ-URLs בפורמטים שונים
- `_is_quiet_now()` — לוגיקת שעות שקטות (כולל מעבר חצות)

## פקודות הרצה
```bash
docker build -t fb-leads .
docker run --env-file .env fb-leads
```
