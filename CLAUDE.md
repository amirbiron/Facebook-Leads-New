# CLAUDE.md — כללי עבודה לפרויקט Facebook Leads Bot

## סקירה
בוט שסורק קבוצות פייסבוק, מסנן לידים רלוונטיים באמצעות Claude API, ושולח אותם לטלגרם.
רץ על VM עם **512MB RAM** — כל שינוי חייב להתחשב במגבלת זיכרון.

## קבצים עיקריים

| קובץ | תפקיד |
|-------|--------|
| `scraper.py` | גלישה בפייסבוק עם Playwright (אתר מובייל) |
| `main.py` | אורקסטרציה, לולאת טלגרם, שעות שקטות |
| `classifier.py` | סיווג פוסטים עם OpenAI gpt-5-nano — תומך סיווג באצ'ים (`classify_batch`) + auto-fallback למודל הבא |
| `notifier.py` | שליחת הודעות טלגרם |
| `database.py` | SQLite — seen_posts, sent_leads, groups, keywords, _config |
| `logger.py` | לוגר |
| `tests.py` | טסטים עם pytest |

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

### 6. בדיקת "טבלה מוגדרת" ברמת טבלה במקום ברמת סוג
**הבעיה:** `_table_was_configured("keywords")` בדקה ב-`sqlite_sequence` ברמת הטבלה. pre_filter ו-block חולקים את אותה טבלה, אז הוספת block סימנה את הטבלה כמוגדרת → `get_db_keywords("pre_filter")` החזיר `[]` במקום `None` → fallback ל-defaults אבד → הבוט הפסיק למצוא לידים.
**הכלל:** לעולם לא לבדוק configuration ברמת טבלה כשיש סוגים שונים באותה טבלה. להשתמש בטבלת `_config` עם מפתח **לכל סוג** (`keywords_pre_filter`, `keywords_block`, `groups`).

### 7. נרמול URL ללא סכמה שובר דומיינים מוכרים
**הבעיה:** `www.facebook.com/groups/123` בלי `https://` → ה-replace ל-`m.` רץ ראשון → בדיקת `http` נכשלת → prefix כפול: `https://m.facebook.com/groups/m.facebook.com/groups/123`.
**הכלל:** ב-`_normalize_group_url`, תמיד **להוסיף סכמה לפני** החלפת דומיין. לזכור לטפל גם ב-`facebook.com` חשוף (ללא `www`).

### 8. רשימת מילות מפתח ריקה חוסמת כל הפוסטים
**הבעיה:** `passes_keyword_filter` לא בדק רשימה ריקה. `any()` על `[]` מחזיר `False` → כל הפוסטים נדחים בשקט.
**הכלל:** פונקציות סינון חייבות guard על רשימה ריקה. הדפוס: **רשימה ריקה = אין סינון = מעביר הכל**. (ראו `is_blocked` כדוגמה נכונה.)

### 9. סיווג באצ'ים — תוצאות חלקיות גורמות ל-misalignment
**הבעיה:** ב-`classify_batch`, אם אלמנט בתשובת JSON לא תקין (למשל `null`), הלולאה שמוסיפה תוצאות ל-`all_results` זורקת exception אחרי הוספה חלקית. ה-fallback מוסיף את כל הבאצ' שוב → `all_results` ארוך מ-`posts` → `zip()` ב-`main.py` מתאים לידים לפוסטים לא נכונים.
**הכלל:** לאסוף תוצאות באצ' ברשימה זמנית (`batch_results`) ולהוסיף ל-`all_results` רק אחרי הצלחה מלאה.

### 10. זיהוי wui אגרסיבי מדי גורם ל-false positive ושובר סריקה
**הבעיה:** `_is_wui_page` בדק אם ≥50% מהלינקים הם `/wui/`. פייסבוק מובייל מוסיף כמה לינקי wui גם בדפים תקינים (באנר "פתח באפליקציה"), ובזמן רינדור הם מהווים רוב הלינקים → false positive → re-login → נכשל → 0 פוסטים מכל הקבוצות.
**הכלל:**
  - **סף מחמיר**: לפחות 3 לינקי wui + לפחות 75% מכלל הלינקים.
  - **בדיקה כפולה**: גם אם יחס wui גבוה, אם יש אלמנטי פוסטים בדף (`article`, `div[data-ft]`) — לא wui-only.
  - **כלל רוחב**: מנגנוני זיהוי סשן חייבים להיות שמרניים — false positive שובר את כל הסריקה, false negative רק מפספס סבב אחד.

### 11. חילוץ URL מפוסטים — מגבלה מובנית של m.facebook.com
**המצב:** `m.facebook.com` לא תמיד מכניס `<a href>` עם קישור לפוסט בודד ב-HTML. בחלק מהקבוצות/דפים כל הלינקים הם `/wui/action/` בלבד.
**הכלל:**
  - זו **לא שגיאה בקוד** — זו מגבלה של אתר המובייל. לא לנסות "לתקן" חילוץ URL כשאין לינקים ב-HTML.
  - ה-fallback (URL הקבוצה) הוא ההתנהגות הנכונה.
  - ה-`has_real_url` flag מבטיח ש-`seen_checker` לא ישתמש ב-fallback URL כ-post ID (ראו באג #3).

## כללי עבודה על session/auth detection
- **false positive שובר הכל**: זיהוי שגוי של "סשן פג" → re-login → נכשל → 0 פוסטים. לכן **סף גבוה + בדיקה כפולה**.
- **לפני שמניחים שפייסבוק שינה משהו** — לבדוק אם **הקוד עצמו השתנה** (רגרסיה). לפרוס גרסה ישנה ידועה כעובדת ולהשוות.
- **wui detection**: חייב גם יחס גבוה של לינקי wui (≥75%) **וגם** היעדר אלמנטי פוסטים. אחד לבד לא מספיק.
- **re-login flow**: Enter על שדה אימייל אמין יותר מחיפוש `button[type='submit']` (סלקטור גנרי שיכול לתפוס כפתור לא נכון).

## כללי scraping
- **אתר מובייל בלבד** (`m.facebook.com`) — חוסך ~60% זיכרון.
- **חסימת משאבים כבדים** — תמונות, וידאו, פונטים נחסמים ב-route handler.
- **`about:blank` בין קבוצות** — לשחרר DOM בזיכרון.
- **`gc.collect()`** אחרי סיום scraping ולפני סיווג.
- **גלילה חכמה** — לא מספר גלילות קבוע. גוללים עד רצף פוסטים מוכרים או `MAX_SCROLLS`.
- **חילוץ URL** — 7 אסטרטגיות (סלקטורים ישירים → סריקת לינקים → timestamp → data-attributes → element ID → DOM climbing → page-level scan). Fallback ל-URL קבוצה אם הכל נכשל. **שים לב:** `m.facebook.com` לא תמיד מכיל לינקים לפוסטים בודדים — ה-fallback הוא התנהגות צפויה, לא באג (ראו באג #11).

## סיווג (classifier.py)
- משתמש ב-OpenAI Chat Completions API (מודל `gpt-5-nano`). משתנה סביבה: `OPENAI_API_KEY`.
- `classify_post()` — סיווג פוסט בודד (fallback).
- `classify_batch()` — סיווג מספר פוסטים בבקשה אחת (ברירת מחדל: 5 לבאצ').
- `_chat_completion()` — פונקציית עזר לקריאת API עם auto-fallback למודל הבא אם הנוכחי deprecated (404/410).
- `_MODEL_PRIORITY` — רשימת מודלים לפי סדר עדיפות. כשמודל נכשל, עובר אוטומטית לבא ושומר ב-DB.
- פונקציית עזר `_parse_json_response()` — חילוץ JSON כולל unwrap של markdown. **חייבים להשתמש בה בכל פירוש תשובה מ-API** (לא לשכפל את הלוגיקה).
- fallback חכם: אם באצ' נכשל (שגיאת API, JSON לא תקין, אורך שגוי, אלמנט null) — נופל לסיווג בודד פוסט-פוסט.

## async
- כל הקוד async. Playwright משתמש ב-async API.
- קריאות סינכרוניות (requests, sqlite) חייבות `asyncio.to_thread()`.
- task של טלגרם נשמר במשתנה (`_control_task`) כדי שלא ייאסף ע"י GC.

## טסטים
```bash
python -m pytest tests.py -v
```
263 טסטים ב-`tests.py` מכסים:
- `passes_keyword_filter()` — סינון לפי מילות מפתח (כולל רשימה ריקה)
- `is_blocked()` — חסימת מילים אסורות
- `extract_post_id()` — חילוץ ID מ-URLs בפורמטים שונים
- `_is_quiet_now()` — לוגיקת שעות שקטות (כולל מעבר חצות)
- `clean_post_content()` — ניקוי תוכן פוסטים
- `classify_post()` — סיווג בודד (עם מוקים)
- `classify_batch()` — סיווג באצ'ים (חלוקה, fallback, null elements, markdown)
- Groups CRUD — הוספה, מחיקה, נרמול URLs, fallback ל-None
- Keywords CRUD — הוספה, מחיקה, הפרדת סוגים, fallback ל-defaults
- `reload_keywords()` — טעינה מ-DB עם fallback

## התאמה ללקוח (`client_checklist.md`)
- קובץ `client_checklist.md` מפרט את כל המקומות בקוד שצריך לערוך כשמשכפלים את הפרויקט ללקוח חדש.
- **בכל שינוי בקובץ שנוגע בשורות/הגדרות המפורטות בצ'קליסט — לעדכן גם את `client_checklist.md`** (מספרי שורות, שמות משתנים, תבניות הודעות וכו').
- הקבצים הרלוונטיים: `classifier.py` (קריטריוני סיווג), `scraper.py` (קבוצות ברירת מחדל), `main.py` (מילות מפתח, הודעות טלגרם), `notifier.py` (תבנית הודעת ליד), `render.yaml` (ברירות מחדל deploy).

## שפה ונוהלי עבודה
- **תיאורי PR**: בעברית
- **הערות בקוד**: בעברית
- **commit messages**: באנגלית (conventional commits)

## פקודות הרצה
```bash
docker build -t fb-leads .
docker run --env-file .env fb-leads
```
