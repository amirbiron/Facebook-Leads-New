import asyncio
import json
import os
import random
import re
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from logger import get_logger

log = get_logger("Scraper")

SESSION_FILE = Path("data/fb_session.json")

# שימוש ב-m.facebook.com — אתר מובייל קל בהרבה בזיכרון
DEFAULT_GROUPS = [
    {"name": "הכול על אוטומציות בינה מלאכותית AI - IL ישראל", "url": "https://m.facebook.com/groups/640894321475593/"},
    {"name": "דרושים מתכנתים ואנשי פיתוח", "url": "https://m.facebook.com/groups/1920854911477422"},
    {"name": "AI ISRAEL – בינה מלאכותית כלים ושימושים", "url": "https://m.facebook.com/groups/1934524236895744/"},
    {"name": "בינה מלאכותית AI ISRAEL", "url": "https://m.facebook.com/groups/2055437551629206"},
    {"name": "Vibe Coding - Israel", "url": "https://m.facebook.com/groups/1684554685829832"},
]

def load_groups() -> list[dict]:
    """טוען קבוצות מ-FB_GROUPS או מהרשימה המובנית.
    פורמט FB_GROUPS: לינקים מופרדים בפסיק, למשל:
    https://www.facebook.com/groups/123,https://www.facebook.com/groups/456
    השם נגזר אוטומטית מה-URL (מזהה הקבוצה).
    www.facebook.com מומר אוטומטית ל-m.facebook.com.
    """
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

    pass_field = None
    for selector in pass_selectors:
        try:
            pass_field = await page.query_selector(selector)
            if pass_field:
                log.debug(f"שדה סיסמה נמצא עם: {selector}")
                break
        except Exception:
            continue

    if not pass_field:
        log.error("לא נמצא שדה סיסמה")
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
    post_patterns = ["/posts/", "/permalink/", "story_fbid", "/story.php", "multi_permalinks", "/p/"]
    return any(p in href for p in post_patterns)

async def _extract_post_url(el, fallback_url: str) -> str:
    """מחלץ URL לפוסט מתוך אלמנט — מנסה מספר אסטרטגיות."""
    # אסטרטגיה 1: סלקטורים ישירים לקישורי פוסטים
    direct_selectors = [
        "a[href*='/posts/']",
        "a[href*='story_fbid']",
        "a[href*='permalink']",
        "a[href*='/story.php']",
        "a[href*='multi_permalinks']",
    ]
    for sel in direct_selectors:
        link = await el.query_selector(sel)
        if link:
            href = await link.get_attribute("href")
            if href:
                return href if href.startswith("http") else f"https://m.facebook.com{href}"

    # אסטרטגיה 2: סריקת כל הלינקים — מחפש כל URL שמכיל מזהה פוסט
    all_links = await el.query_selector_all("a[href]")
    for a in all_links:
        href = await a.get_attribute("href") or ""
        if _is_post_url(href):
            return href if href.startswith("http") else f"https://m.facebook.com{href}"

    # אסטרטגיה 3: לינק חותמת זמן — במובייל, הזמן ("12 שעות") הוא לינק לפוסט
    for a in all_links:
        href = await a.get_attribute("href") or ""
        text = (await a.inner_text()).strip() if a else ""
        # חותמת זמן: "12 שעות", "3 ימים", "דקה", "אתמול" וכו'
        if re.search(r'\d+\s*(שע|דק|יו|שני|חוד)', text) or text in ("עכשיו", "אתמול"):
            if "/groups/" in href:
                return href if href.startswith("http") else f"https://m.facebook.com{href}"

    return fallback_url

async def scrape_group(page, group: dict, seen_checker=None) -> list[dict]:
    posts = []
    log.info(f">>> סורק קבוצה: {group['name']}")
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
            # כותרת דף בפייסבוק: "שם הקבוצה | Facebook" או "שם הקבוצה"
            if page_title and " | " in page_title:
                extracted = page_title.split(" | ")[0].strip()
                if extracted and "אינו נתמך" not in extracted and len(extracted) > 2:
                    group_name = extracted
                    log.debug(f"שם קבוצה מכותרת הדף: {group_name}")
        except Exception:
            pass

        await random_delay(2, 4)

        # גלילה חכמה — גוללים עד שמגיעים לפוסט שכבר נראה בסריקה קודמת
        MAX_SCROLLS = 10
        MAX_POSTS = 30
        SELECTORS = "article, div[data-ft], div[role='article']"
        FALLBACK_SELECTORS = "div[dir='auto']"

        reached_known = False
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

                    post_id = extract_post_id(post_url)
                    has_real_url = post_url != group["url"]

                    # בדיקה אם הגענו לפוסט מסריקה קודמת — אם כן, עוצרים.
                    # רק אם יש URL אמיתי לפוסט — fallback ל-URL הקבוצה מייצר
                    # ID זהה לכל הפוסטים שנכשלים בחילוץ, ויגרום לעצירה מוקדמת שגויה.
                    if has_real_url and seen_checker and seen_checker(post_id):
                        reached_known = True
                        log.info(f"הגענו לפוסט שכבר נראה — עוצרים גלילה (אחרי {scroll_i} גלילות)")
                        break

                    posts.append({
                        "id": post_id,
                        "content": text,
                        "url": post_url,
                        "group": group_name
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
