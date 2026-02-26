import asyncio
import hashlib
import html as html_mod
import json
import os
import random
import re
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from logger import get_logger
from notifier import send_document

log = get_logger("Scraper")

SESSION_FILE = Path("data/fb_session.json")

# כותרות גנריות/שגויות שלא מייצגות שם קבוצה אמיתי
_BAD_TITLES = {"facebook", "content not found", "page not found",
               "error", "log in", "התחברות", "תוכן לא נמצא", "שגיאה"}


def _extract_name_from_title(page_title: str) -> str | None:
    """מחלץ שם קבוצה מכותרת דף פייסבוק. מחזיר None אם הכותרת לא תקינה."""
    if not page_title:
        return None
    # ניקוי תווי כיווניות (LRM/RLM) שפייסבוק מוסיף
    cleaned = page_title.replace("\u200e", "").replace("\u200f", "").strip()
    # פורמט נפוץ: "שם הקבוצה | Facebook" — לוקחים רק את החלק הראשון
    if " | " in cleaned:
        cleaned = cleaned.split(" | ")[0].strip()
    # פענוח HTML entities (למשל &amp;)
    cleaned = html_mod.unescape(cleaned)
    if (cleaned
            and len(cleaned) > 2
            and cleaned.lower() not in _BAD_TITLES
            and "אינו נתמך" not in cleaned):
        return cleaned
    return None


# שימוש ב-m.facebook.com — אתר מובייל קל בהרבה בזיכרון
DEFAULT_GROUPS = [
    {"name": "הכול על אוטומציות בינה מלאכותית AI - IL ישראל", "url": "https://m.facebook.com/groups/640894321475593/"},
    {"name": "דרושים מתכנתים ואנשי פיתוח", "url": "https://m.facebook.com/groups/1920854911477422"},
    {"name": "AI ISRAEL – בינה מלאכותית כלים ושימושים", "url": "https://m.facebook.com/groups/1934524236895744/"},
    {"name": "בינה מלאכותית AI ISRAEL", "url": "https://m.facebook.com/groups/2055437551629206"},
    {"name": "Vibe Coding - Israel", "url": "https://m.facebook.com/groups/1684554685829832"},
]

def load_groups() -> list[dict]:
    """טוען קבוצות מ-DB, עם fallback ל-FB_GROUPS / ברירת מחדל.
    סדר עדיפות: DB → FB_GROUPS → DEFAULT_GROUPS
    """
    # ניסיון ראשון — טעינה מ-DB
    # None = מעולם לא הוגדר → fallback.  [] = המשתמש רוקן הכל → רשימה ריקה.
    try:
        from database import get_db_groups
        db_groups = get_db_groups()
        if db_groups is not None:
            log.info(f"נטענו {len(db_groups)} קבוצות מ-DB")
            return db_groups
    except Exception as e:
        log.debug(f"לא ניתן לטעון קבוצות מ-DB: {e}")

    # fallback — משתנה סביבה
    env_groups = os.environ.get("FB_GROUPS")
    if env_groups:
        groups = []
        for raw_url in env_groups.split(","):
            raw_url = raw_url.strip()
            if not raw_url:
                continue
            # המרה לאתר מובייל
            url = raw_url.replace("www.facebook.com", "m.facebook.com")
            # חילוץ שם הקבוצה מה-URL
            match = re.search(r"/groups/([^/?]+)", url)
            name = match.group(1) if match else url
            groups.append({"name": name, "url": url})
        if groups:
            log.info(f"נטענו {len(groups)} קבוצות ממשתנה סביבה FB_GROUPS")
            return groups
        log.warning("FB_GROUPS מוגדר אבל ריק — משתמש ברשימת ברירת מחדל")
    return DEFAULT_GROUPS

def reload_groups():
    """טוען מחדש את רשימת הקבוצות (נקרא אחרי שינוי דרך טלגרם)."""
    global GROUPS
    GROUPS = load_groups()

GROUPS = load_groups()

async def random_delay(min_sec=1, max_sec=3):
    delay = random.uniform(min_sec, max_sec)
    log.debug(f"השהיה {delay:.1f} שניות")
    await asyncio.sleep(delay)

async def block_heavy_resources(page):
    """חוסם תמונות, וידאו ופונטים כדי לחסוך זיכרון"""
    BLOCKED_TYPES = {"image", "media", "font"}

    async def handle_route(route):
        if route.request.resource_type in BLOCKED_TYPES:
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/*", handle_route)
    log.debug("חסימת משאבים כבדים הופעלה (תמונות, וידאו, פונטים)")

async def save_session(context):
    SESSION_FILE.parent.mkdir(exist_ok=True)
    cookies = await context.cookies()
    SESSION_FILE.write_text(json.dumps(cookies))
    log.info("סשן נשמר")

async def load_session(context):
    if SESSION_FILE.exists():
        cookies = json.loads(SESSION_FILE.read_text())
        await context.add_cookies(cookies)
        log.info(f"סשן נטען ({len(cookies)} cookies)")
        return True
    log.info("לא נמצא סשן שמור")
    return False

async def dismiss_cookie_dialog(page):
    """סוגר דיאלוג cookies אם מופיע"""
    cookie_selectors = [
        "button[data-cookiebanner='accept_button']",
        "button[data-cookiebanner='accept_only_essential_button']",
        "[aria-label='Allow all cookies']",
        "[aria-label='Allow essential and optional cookies']",
        "[aria-label='אישור כל קובצי ה-Cookie']",
        "[title='Allow all cookies']",
        "button[value='Accept All']",
    ]
    for selector in cookie_selectors:
        try:
            btn = await page.query_selector(selector)
            if btn:
                log.info(f"נמצא דיאלוג cookies — לוחץ: {selector}")
                await btn.click()
                await random_delay(1, 2)
                return True
        except Exception:
            continue
    return False

async def login(page, email: str, password: str):
    log.info("מתחבר לפייסבוק (מובייל)...")
    await page.goto("https://m.facebook.com/login", wait_until="domcontentloaded")
    await random_delay(1, 3)

    log.debug(f"URL אחרי ניווט: {page.url}")

    await dismiss_cookie_dialog(page)

    # שדות לוגין — זהים באתר מובייל
    email_selectors = ["#email", "input[name='email']", "input[type='email']"]
    pass_selectors = ["#pass", "input[name='pass']", "input[type='password']"]

    email_field = None
    for selector in email_selectors:
        try:
            email_field = await page.wait_for_selector(selector, timeout=10000)
            if email_field:
                log.debug(f"שדה אימייל נמצא עם: {selector}")
                break
        except Exception:
            continue

    if not email_field:
        try:
            await page.screenshot(path="data/debug_login_page.png")
        except Exception:
            pass
        page_title = await page.title()
        log.error(f"לא נמצא שדה אימייל בדף. כותרת: {page_title}, URL: {page.url}")
        raise Exception("לא נמצא שדה אימייל בדף הלוגין")

    await email_field.fill(email)
    await random_delay(0.5, 1)

    # --- ניסיון ראשון: שדה סיסמה באותו דף ---
    pass_field = None
    for selector in pass_selectors:
        try:
            pass_field = await page.wait_for_selector(selector, timeout=5000)
            if pass_field:
                log.debug(f"שדה סיסמה נמצא עם: {selector}")
                break
        except Exception:
            continue

    # --- לוגין דו-שלבי: אם אין שדה סיסמה, מחפשים כפתור Next ---
    if not pass_field:
        log.info("שדה סיסמה לא נמצא — מנסה לוגין דו-שלבי (Next)")
        next_btn_selectors = [
            "button[name='login']",
            "input[name='login']",
            "button[data-sigil='m_login_button']",
            "button[type='submit']",
            "input[type='submit']",
            "[data-sigil='touchable m_login_button']",
        ]
        next_btn = None
        for selector in next_btn_selectors:
            try:
                next_btn = await page.query_selector(selector)
                if next_btn:
                    log.debug(f"כפתור Next/Login נמצא עם: {selector}")
                    break
            except Exception:
                continue

        if next_btn:
            try:
                async with page.expect_navigation(timeout=15000):
                    await next_btn.click()
                log.debug("ניווט לשלב סיסמה התבצע בהצלחה")
            except Exception:
                log.debug("לא זוהה ניווט אחרי Next — ממתין...")
                await asyncio.sleep(3)
        else:
            # אין כפתור Next — ננסה Enter על שדה האימייל
            log.debug("לא נמצא כפתור Next — שולח Enter על שדה האימייל")
            try:
                async with page.expect_navigation(timeout=15000):
                    await email_field.press("Enter")
                log.debug("ניווט לשלב סיסמה התבצע בהצלחה (Enter)")
            except Exception:
                log.debug("לא זוהה ניווט אחרי Enter — ממתין...")
                await asyncio.sleep(3)

        await random_delay(1, 3)
        await dismiss_cookie_dialog(page)

        # חיפוש שדה סיסמה בדף החדש
        for selector in pass_selectors:
            try:
                pass_field = await page.wait_for_selector(selector, timeout=10000)
                if pass_field:
                    log.debug(f"שדה סיסמה נמצא בשלב 2 עם: {selector}")
                    break
            except Exception:
                continue

    if not pass_field:
        try:
            await page.screenshot(path="data/debug_no_password_field.png")
        except Exception:
            pass
        page_title = await page.title()
        log.error(f"לא נמצא שדה סיסמה. כותרת: {page_title}, URL: {page.url}")
        raise Exception("לא נמצא שדה סיסמה בדף הלוגין")

    await pass_field.fill(password)
    await random_delay(0.5, 1)

    # שולח טופס — מנסה כפתור login, אחרת Enter
    log.debug("שולח טופס לוגין...")
    try:
        login_btn = await page.query_selector("button[name='login'], input[name='login']")
        if login_btn:
            async with page.expect_navigation(timeout=15000):
                await login_btn.click()
            log.debug("ניווט התבצע בהצלחה (כפתור)")
        else:
            async with page.expect_navigation(timeout=15000):
                await pass_field.press("Enter")
            log.debug("ניווט התבצע בהצלחה (Enter)")
    except Exception:
        log.debug("לא זוהה ניווט — ממתין לטעינה ידנית...")
        await asyncio.sleep(5)

    await random_delay(2, 3)

    current_url = page.url
    log.debug(f"URL אחרי לוגין: {current_url}")

    if "/login" in current_url and "checkpoint" not in current_url:
        error_msg = None
        for selector in ["div[role='alert']", "#error_box", "div._9ay7", "div.login_error_box"]:
            try:
                el = await page.query_selector(selector)
                if el:
                    error_msg = await el.inner_text()
                    break
            except Exception:
                continue

        try:
            await page.screenshot(path="data/debug_login_failed.png")
        except Exception:
            pass

        if error_msg:
            log.error(f"פייסבוק מציג שגיאה: {error_msg.strip()}")
            raise Exception(f"התחברות נכשלה — פייסבוק אומר: {error_msg.strip()}")
        else:
            log.error(f"התחברות נכשלה — URL עדיין בדף לוגין: {current_url}")
            raise Exception("התחברות נכשלה — בדוק אימייל/סיסמה")

    if "checkpoint" in current_url:
        try:
            await page.screenshot(path="data/debug_checkpoint.png")
        except Exception:
            pass
        log.error(f"פייסבוק דורש אימות נוסף (checkpoint): {current_url}")
        raise Exception("פייסבוק דורש אימות נוסף — בדוק את החשבון ידנית")

    log.info(f"מחובר בהצלחה — URL: {current_url}")

def extract_post_id(url: str) -> str:
    patterns = [
        r"/posts/(\d+)",
        r"story_fbid=(\d+)",
        r"/permalink/(\d+)",
        r"pfbid(\w+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return url[-20:]

def _is_post_url(href: str) -> bool:
    """בודק אם URL הוא קישור לפוסט ספציפי (לא לקבוצה בלבד)."""
    post_patterns = ["/posts/", "/permalink/", "story_fbid", "/story.php", "multi_permalinks", "/p/", "pfbid"]
    return any(p in href for p in post_patterns)

def _extract_id_from_data_attrs(attrs_json: str) -> str | None:
    """מחלץ מזהה פוסט מתוך JSON של data attributes (data-ft, data-store)."""
    try:
        data = json.loads(attrs_json)
    except (json.JSONDecodeError, TypeError):
        return None
    # סדר עדיפות — מזהים מוכרים ב-data-ft של פייסבוק מובייל
    for key in ("mf_story_key", "top_level_post_id", "tl_objid"):
        val = data.get(key)
        if val and str(val).strip():
            return str(val).strip()
    return None


# תיקיית debug ל-HTML dumps של חילוצים שנכשלו
_DEBUG_DIR = Path("data/debug_html")
# מונה פנימי לסטטיסטיקת חילוץ URL
_extraction_stats: dict[str, int] = {"success": 0, "fallback": 0}
# מגבלת dumps שנשלחים לטלגרם בסבב (כדי לא להציף)
_MAX_TELEGRAM_DUMPS = 3
_telegram_dumps_sent = 0


def get_extraction_stats() -> dict[str, int]:
    """מחזיר עותק של סטטיסטיקת חילוץ URL (לשימוש בטסטים ולוגים)."""
    return dict(_extraction_stats)


def reset_extraction_stats():
    """מאפס סטטיסטיקת חילוץ URL."""
    _extraction_stats["success"] = 0
    _extraction_stats["fallback"] = 0


async def _extract_post_url(el, fallback_url: str, *, dump_on_fail: bool = True) -> str:
    """מחלץ URL לפוסט מתוך אלמנט — מנסה מספר אסטרטגיות.

    dump_on_fail — אם True ושום אסטרטגיה לא הצליחה, שומר HTML dump לניתוח.
    """
    # אסטרטגיה 1: סלקטורים ישירים לקישורי פוסטים
    direct_selectors = [
        "a[href*='/posts/']",
        "a[href*='story_fbid']",
        "a[href*='permalink']",
        "a[href*='/story.php']",
        "a[href*='multi_permalinks']",
        "a[href*='pfbid']",
        "a[href*='/p/']",
    ]
    for sel in direct_selectors:
        link = await el.query_selector(sel)
        if link:
            href = await link.get_attribute("href")
            if href:
                log.debug(f"חילוץ URL — אסטרטגיה 1 (סלקטור ישיר): {sel}")
                _extraction_stats["success"] += 1
                return href if href.startswith("http") else f"https://m.facebook.com{href}"

    # אסטרטגיה 2: סריקת כל הלינקים — מחפש כל URL שמכיל מזהה פוסט
    all_links = await el.query_selector_all("a[href]")
    for a in all_links:
        href = await a.get_attribute("href") or ""
        if _is_post_url(href):
            log.debug(f"חילוץ URL — אסטרטגיה 2 (סריקת לינקים): {href[:80]}")
            _extraction_stats["success"] += 1
            return href if href.startswith("http") else f"https://m.facebook.com{href}"

    # אסטרטגיה 3: לינק חותמת זמן — במובייל, הזמן ("12 שעות") הוא לינק לפוסט.
    # קישור timestamp בתוך קבוצה הוא כמעט תמיד קישור לפוסט הספציפי,
    # גם אם ה-URL לא מכיל מזהה פוסט מוכר (כמו pfbid, /posts/ וכו')
    for a in all_links:
        href = await a.get_attribute("href") or ""
        text = (await a.inner_text()).strip() if a else ""
        # חותמת זמן בעברית: "12 שעות", "3 ימים", "דקה", "אתמול" וכו'
        # חותמת זמן באנגלית: "12h", "3d", "1m", "Just now", "Yesterday"
        is_timestamp = (
            re.search(r'\d+\s*(שע|דק|יו|שני|חוד)', text)
            or text in ("עכשיו", "אתמול")
            or re.search(r'^\d+\s*[hdmwHDMW]$', text)
            or text.lower() in ("just now", "yesterday")
        )
        if is_timestamp and "/groups/" in href and href != fallback_url:
            full = href if href.startswith("http") else f"https://m.facebook.com{href}"
            # ודא שהקישור ארוך יותר מ-URL הקבוצה (כלומר מכיל מזהה נוסף)
            if len(full) > len(fallback_url) + 5:
                log.debug(f"חילוץ URL — אסטרטגיה 3 (timestamp): {full[:80]}")
                _extraction_stats["success"] += 1
                return full

    # אסטרטגיה 4: חילוץ מזהה פוסט מ-data attributes (data-ft, data-store)
    # ב-m.facebook.com, אלמנטים מכילים JSON עם מזהי פוסט
    group_id_match = re.search(r"/groups/([^/?]+)", fallback_url)
    if group_id_match:
        group_id = group_id_match.group(1)
        for attr in ("data-ft", "data-store"):
            try:
                attr_val = await el.get_attribute(attr)
                if attr_val:
                    post_id = _extract_id_from_data_attrs(attr_val)
                    if post_id:
                        url = f"https://m.facebook.com/groups/{group_id}/permalink/{post_id}/"
                        log.debug(f"חילוץ URL — אסטרטגיה 4 ({attr}): {url}")
                        _extraction_stats["success"] += 1
                        return url
            except Exception:
                continue

        # חיפוש data-ft/data-store גם באלמנטים פנימיים
        for attr in ("data-ft", "data-store"):
            try:
                inner = await el.query_selector(f"[{attr}]")
                if inner:
                    attr_val = await inner.get_attribute(attr)
                    if attr_val:
                        post_id = _extract_id_from_data_attrs(attr_val)
                        if post_id:
                            url = f"https://m.facebook.com/groups/{group_id}/permalink/{post_id}/"
                            log.debug(f"חילוץ URL — אסטרטגיה 4 ({attr} פנימי): {url}")
                            _extraction_stats["success"] += 1
                            return url
            except Exception:
                continue

    # אסטרטגיה 5: חיפוש מזהה פוסט ב-id/aria של האלמנט עצמו
    try:
        el_id = await el.get_attribute("id") or ""
        # פייסבוק לפעמים שם ID כמו "mall_post_123456" או "u_0_xx_yy"
        id_match = re.search(r'(\d{10,})', el_id)
        if id_match and group_id_match:
            post_id = id_match.group(1)
            url = f"https://m.facebook.com/groups/{group_id_match.group(1)}/permalink/{post_id}/"
            log.debug(f"חילוץ URL — אסטרטגיה 5 (element id): {url}")
            _extraction_stats["success"] += 1
            return url
    except Exception:
        pass

    # כל האסטרטגיות נכשלו — שמירת HTML dump לניתוח + שליחה לטלגרם
    global _telegram_dumps_sent
    _extraction_stats["fallback"] += 1
    if dump_on_fail:
        try:
            _DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            snippet = await el.inner_html()
            # חותכים ל-5000 תווים כדי לא לזרוק דיסק
            snippet = snippet[:5000]
            ts = re.sub(r'[:\s]', '_', str(asyncio.get_event_loop().time())[:10])
            filename = f"failed_{ts}_{_extraction_stats['fallback']}.html"
            dump_path = _DEBUG_DIR / filename
            dump_path.write_text(snippet, encoding="utf-8")
            log.debug(f"חילוץ URL נכשל — HTML dump נשמר: {dump_path}")

            # שליחת ה-dump לטלגרם (עד _MAX_TELEGRAM_DUMPS בסבב)
            if _telegram_dumps_sent < _MAX_TELEGRAM_DUMPS:
                group_name = fallback_url.rstrip("/").split("/")[-1]
                caption = f"🔍 HTML dump — חילוץ URL נכשל\nקבוצה: {group_name}"
                await asyncio.to_thread(
                    send_document,
                    snippet.encode("utf-8"),
                    filename,
                    caption,
                )
                _telegram_dumps_sent += 1
        except Exception as e:
            log.debug(f"לא הצלחתי לשמור HTML dump: {e}")

    log.debug(f"חילוץ URL נכשל — משתמש ב-fallback URL: {fallback_url[:60]}")
    return fallback_url

async def scrape_group(page, group: dict, seen_checker=None) -> list[dict]:
    posts = []
    reset_extraction_stats()
    group_name = group["name"]
    log.info(f">>> סורק קבוצה: {group_name}")
    log.debug(f"URL: {group['url']}")

    try:
        log.debug("ניווט לדף הקבוצה...")
        await page.goto(group["url"], wait_until="domcontentloaded", timeout=30000)
        current_url = page.url
        log.debug(f"הגענו ל: {current_url}")

        if "login" in current_url:
            log.warning("הועברנו לדף לוגין — ייתכן שהסשן פג!")
            return posts

        # חילוץ שם הקבוצה מכותרת הדף (אמין יותר מסלקטורים בתוך ה-DOM)
        group_name = group["name"]
        try:
            page_title = await page.title()
            extracted = _extract_name_from_title(page_title)
            if extracted:
                group_name = extracted
                # עדכון שם הקבוצה ב-DB כדי שישתמר לסבבים הבאים
                if group_name != group["name"]:
                    try:
                        from database import update_group_name
                        update_group_name(group["url"], group_name)
                        log.info(f"שם קבוצה עודכן: {group['name']} → {group_name}")
                    except Exception as e:
                        log.warning(f"נכשל עדכון שם קבוצה ב-DB: {e}")
            else:
                # warning רק אם השם עדיין לא עודכן (ספרות בלבד) — אחרת זה מצב רגיל
                if group["name"].isdigit():
                    log.warning(f"לא הצלחתי לחלץ שם קבוצה מכותרת הדף: '{page_title}'")
        except Exception as e:
            log.warning(f"שגיאה בחילוץ כותרת דף לקבוצה {group['url']}: {e}")

        await random_delay(2, 4)

        # גלילה חכמה — גוללים עד שמגיעים לפוסט שכבר נראה בסריקה קודמת
        MAX_SCROLLS = 10
        MAX_POSTS = 30
        SELECTORS = "article, div[data-ft], div[role='article']"
        FALLBACK_SELECTORS = "div[dir='auto']"

        reached_known = False
        consecutive_known = 0
        KNOWN_THRESHOLD = 3  # כמה פוסטים מוכרים ברצף לפני עצירה (מונע עצירה על פוסט מוצמד)
        seen_texts = set()
        skipped_short = 0

        log.debug("מתחיל גלילה חכמה...")

        for scroll_i in range(MAX_SCROLLS + 1):
            # בסיבוב הראשון לא גוללים — מעבדים מה שכבר נטען
            if scroll_i > 0:
                await page.evaluate("window.scrollBy(0, Math.random() * 300 + 200)")
                log.debug(f"גלילה {scroll_i}/{MAX_SCROLLS}")
                await random_delay(1, 2)

            post_elements = await page.query_selector_all(SELECTORS)
            if not post_elements:
                post_elements = await page.query_selector_all(FALLBACK_SELECTORS)

            if not post_elements and scroll_i == 0:
                log.warning(f"לא נמצאו אלמנטים בכלל בקבוצה: {group_name}")
                try:
                    await page.screenshot(path=f"data/debug_{group_name[:20]}.png")
                except Exception:
                    pass
                break

            # מעבדים את כל האלמנטים ומדלגים על כאלה שכבר ראינו לפי תוכן.
            # לא משתמשים במעקב לפי אינדקס כי ה-DOM יכול להשתנות בגלילה
            # (virtualization, החלפת selector) מה שגורם לדילוג על אלמנטים חדשים.
            prev_seen_count = len(seen_texts)

            for el in post_elements:
                try:
                    text = await asyncio.wait_for(el.inner_text(), timeout=5)
                    text = text.strip()

                    if text in seen_texts:
                        continue
                    seen_texts.add(text)

                    if len(text) < 50:
                        skipped_short += 1
                        continue

                    post_url = group["url"]
                    try:
                        post_url = await _extract_post_url(el, group["url"])
                    except Exception:
                        pass

                    has_real_url = post_url != group["url"]

                    if has_real_url:
                        post_id = extract_post_id(post_url)
                    else:
                        # fallback URL = URL הקבוצה → ID זהה לכל הפוסטים בקבוצה.
                        # משתמשים ב-hash של התוכן כ-ID ייחודי לכל פוסט,
                        # כדי למנוע סימון שגוי כ"נראה" לכל הפוסטים בקבוצה.
                        post_id = "c_" + hashlib.md5(text.encode()).hexdigest()[:16]

                    # בדיקה אם הגענו לפוסט מסריקה קודמת.
                    # רק אם יש URL אמיתי לפוסט — hash תוכן עלול להשתנות
                    # בגלל שינויי timestamp, ולא מתאים לזיהוי עצירת גלילה.
                    # דורשים רצף של KNOWN_THRESHOLD פוסטים מוכרים לפני עצירה,
                    # כדי למנוע עצירה מוקדמת בגלל פוסט מוצמד (pinned) בראש הפיד.
                    if has_real_url and seen_checker and seen_checker(post_id):
                        consecutive_known += 1
                        if consecutive_known >= KNOWN_THRESHOLD:
                            reached_known = True
                            log.info(f"הגענו ל-{KNOWN_THRESHOLD} פוסטים מוכרים ברצף — עוצרים גלילה (אחרי {scroll_i} גלילות)")
                            break
                        log.debug(f"פוסט מוכר ({consecutive_known}/{KNOWN_THRESHOLD}), ממשיכים")
                        continue
                    else:
                        consecutive_known = 0

                    posts.append({
                        "id": post_id,
                        "content": text,
                        "url": post_url,
                        "group": group_name,
                        "has_real_url": has_real_url,
                    })

                    if len(posts) >= MAX_POSTS:
                        log.debug(f"הגענו למקסימום {MAX_POSTS} פוסטים — עוצרים")
                        reached_known = True
                        break

                except Exception as e:
                    log.debug(f"שגיאה בעיבוד אלמנט: {e}")
                    continue

            if reached_known:
                break

            if scroll_i > 0 and len(seen_texts) == prev_seen_count:
                log.debug("אין אלמנטים חדשים אחרי גלילה — עוצרים")
                break

        if not reached_known:
            log.debug(f"לא הגענו לפוסט מוכר — נעצרנו אחרי {scroll_i} גלילות")

        log.debug(f"סטטיסטיקה — דולגו: {skipped_short} קצרים")

    except PlaywrightTimeout:
        log.error(f"טיימאאוט בקבוצה: {group['name']} (30 שניות)")
    except Exception as e:
        log.error(f"שגיאה בקבוצה {group['name']}: {e}", exc_info=True)

    # סטטיסטיקת חילוץ URL לקבוצה
    stats = get_extraction_stats()
    total_attempts = stats["success"] + stats["fallback"]
    if total_attempts > 0:
        rate = stats["success"] / total_attempts * 100
        real_url_posts = sum(1 for p in posts if p.get("has_real_url"))
        log.info(
            f"חילוץ URL — הצלחה: {stats['success']}/{total_attempts} ({rate:.0f}%) | "
            f"פוסטים עם URL אמיתי: {real_url_posts}/{len(posts)}"
        )
        if stats["fallback"] > 0:
            log.warning(
                f"חילוץ URL נכשל ב-{stats['fallback']} פוסטים — "
                f"בדוק HTML dumps בתיקייה {_DEBUG_DIR}"
            )

    log.info(f"<<< נמצאו {len(posts)} פוסטים ב-{group_name}")
    return posts

async def scrape_all(email: str, password: str, seen_checker=None) -> list[dict]:
    all_posts = []

    log.info(f"מתחיל סריקה של {len(GROUPS)} קבוצות (מובייל)")

    async with async_playwright() as p:
        log.debug("מפעיל דפדפן Chromium...")
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-default-apps",
                "--disable-sync",
                "--disable-translate",
                "--no-first-run",
                "--disable-component-update",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-software-rasterizer",
                "--renderer-process-limit=1",
                "--js-flags=--max-old-space-size=128",
            ]
        )
        log.debug("דפדפן הופעל בהצלחה")

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            viewport={"width": 360, "height": 640},
            locale="he-IL"
        )
        page = await context.new_page()
        await block_heavy_resources(page)

        session_loaded = await load_session(context)

        if session_loaded:
            log.debug("בודק תקינות סשן...")
            await page.goto("https://m.facebook.com", wait_until="domcontentloaded")
            await random_delay(1, 3)
            await dismiss_cookie_dialog(page)
            if "login" in page.url:
                log.warning("סשן פג — מתחבר מחדש")
                await login(page, email, password)
                await save_session(context)
            else:
                log.info("סשן תקין — ממשיך")
        else:
            await login(page, email, password)
            await save_session(context)

        global _telegram_dumps_sent
        _telegram_dumps_sent = 0

        for i, group in enumerate(GROUPS, 1):
            log.info(f"--- קבוצה {i}/{len(GROUPS)} ---")
            posts = await scrape_group(page, group, seen_checker=seen_checker)
            all_posts.extend(posts)

            # ניקוי זיכרון — מנווט לדף ריק כדי לשחרר את ה-DOM
            try:
                await page.goto("about:blank")
                log.debug("ניווט ל-about:blank לשחרור זיכרון")
            except Exception:
                pass

            if i < len(GROUPS):
                log.debug("השהיה בין קבוצות...")
                await random_delay(3, 8)

        await browser.close()
        log.debug("דפדפן נסגר")

    log.info(f"סריקה הסתיימה — סה\"כ {len(all_posts)} פוסטים מ-{len(GROUPS)} קבוצות")
    return all_posts
