import asyncio
import json
import random
import re
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from logger import get_logger

log = get_logger("Scraper")

SESSION_FILE = Path("data/fb_session.json")

GROUPS = [
    {"name": "הכול על אוטומציות בינה מלאכותית AI - IL ישראל", "url": "https://www.facebook.com/groups/640894321475593/"},
    {"name": "דרושים מתכנתים ואנשי פיתוח", "url": "https://www.facebook.com/groups/1920854911477422"},
    {"name": "AI ISRAEL – בינה מלאכותית כלים ושימושים", "url": "https://www.facebook.com/groups/1934524236895744/"},
    {"name": "בינה מלאכותית AI ISRAEL", "url": "https://www.facebook.com/groups/2055437551629206"},
    {"name": "Vibe Coding - Israel", "url": "https://www.facebook.com/groups/1684554685829832"},
]

async def random_delay(min_sec=2, max_sec=6):
    delay = random.uniform(min_sec, max_sec)
    log.debug(f"השהיה {delay:.1f} שניות")
    await asyncio.sleep(delay)

async def block_heavy_resources(page):
    """חוסם תמונות, וידאו, פונטים ומדיה כדי לחסוך זיכרון"""
    await page.route("**/*.{png,jpg,jpeg,gif,svg,webp,ico,bmp}", lambda route: route.abort())
    await page.route("**/*.{mp4,webm,ogg,avi,mov}", lambda route: route.abort())
    await page.route("**/*.{woff,woff2,ttf,otf,eot}", lambda route: route.abort())
    await page.route("**/video/**", lambda route: route.abort())
    await page.route("**/videoplayback*", lambda route: route.abort())
    log.debug("חסימת משאבים כבדים הופעלה (תמונות, וידאו, פונטים)")

async def human_scroll(page, times=3):
    for i in range(times):
        await page.evaluate("window.scrollBy(0, Math.random() * 400 + 200)")
        log.debug(f"גלילה {i+1}/{times}")
        await random_delay(1, 3)

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
    log.info("מתחבר לפייסבוק...")
    await page.goto("https://www.facebook.com/login", wait_until="domcontentloaded")
    await random_delay(2, 4)

    log.debug(f"URL אחרי ניווט: {page.url}")

    # סוגר דיאלוג cookies אם מופיע
    await dismiss_cookie_dialog(page)

    # מחפש את שדה האימייל עם כמה סלקטורים
    email_selectors = ["#email", "input[name='email']", "input[type='email']", "input[id='email']"]
    pass_selectors = ["#pass", "input[name='pass']", "input[type='password']", "input[id='pass']"]

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
        # צילום מסך לדיבוג
        try:
            await page.screenshot(path="data/debug_login_page.png")
            log.debug("צילום מסך דף לוגין נשמר: data/debug_login_page.png")
        except Exception:
            pass
        page_title = await page.title()
        log.error(f"לא נמצא שדה אימייל בדף. כותרת: {page_title}, URL: {page.url}")
        raise Exception("לא נמצא שדה אימייל בדף הלוגין — ייתכן שפייסבוק חוסם או שהדף השתנה")

    await email_field.fill(email)
    await random_delay(0.5, 1.5)

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
    await random_delay(0.5, 1.5)

    # שולח את הטופס ע"י Enter — יותר אמין מחיפוש כפתור
    log.debug("שולח טופס לוגין (Enter)...")

    # מחכה לניווט בפועל אחרי שליחת הטופס
    try:
        async with page.expect_navigation(timeout=15000):
            await pass_field.press("Enter")
        log.debug("ניווט התבצע בהצלחה")
    except Exception:
        log.debug("לא זוהה ניווט — ממתין לטעינה ידנית...")
        await asyncio.sleep(5)

    await random_delay(2, 4)

    current_url = page.url
    log.debug(f"URL אחרי לוגין: {current_url}")

    # בדיקות שהלוגין הצליח
    if "/login" in current_url and "checkpoint" not in current_url:
        # בודק אם יש הודעת שגיאה בדף
        error_msg = None
        for selector in ["div[role='alert']", "#error_box", "div._9ay7"]:
            try:
                el = await page.query_selector(selector)
                if el:
                    error_msg = await el.inner_text()
                    break
            except Exception:
                continue

        try:
            await page.screenshot(path="data/debug_login_failed.png")
            log.info("צילום מסך נשמר: data/debug_login_failed.png")
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

async def scrape_group(page, group: dict) -> list[dict]:
    posts = []
    log.info(f">>> סורק קבוצה: {group['name']}")
    log.debug(f"URL: {group['url']}")

    try:
        log.debug("ניווט לדף הקבוצה...")
        await page.goto(group["url"], wait_until="domcontentloaded", timeout=30000)
        current_url = page.url
        log.debug(f"הגענו ל: {current_url}")

        # בדיקה אם הועברנו לדף לוגין
        if "login" in current_url:
            log.warning("הועברנו לדף לוגין — ייתכן שהסשן פג!")
            return posts

        await random_delay(3, 6)
        log.debug("מתחיל גלילה...")
        await human_scroll(page, times=3)

        # מחפש אלמנטים של פוסטים
        log.debug("מחפש אלמנטים של פוסטים (סלקטור ראשי)...")
        post_elements = await page.query_selector_all("[data-ad-preview='message'], [data-testid='post_message'], div[dir='auto']")
        log.debug(f"סלקטור ראשי מצא {len(post_elements)} אלמנטים")

        # גישה אלטרנטיבית — לפי role
        if not post_elements:
            log.debug("מנסה סלקטור חלופי (div[role='article'])...")
            post_elements = await page.query_selector_all("div[role='article']")
            log.debug(f"סלקטור חלופי מצא {len(post_elements)} אלמנטים")

        if not post_elements:
            log.warning(f"לא נמצאו אלמנטים בכלל בקבוצה: {group['name']}")
            # שמור צילום מסך לדיבוג
            try:
                screenshot_path = f"data/debug_{group['name'][:20]}.png"
                await page.screenshot(path=screenshot_path)
                log.debug(f"צילום מסך נשמר: {screenshot_path}")
            except Exception:
                pass

        seen_texts = set()
        skipped_short = 0
        skipped_dup = 0

        for el in post_elements[:30]:
            try:
                text = await el.inner_text()
                text = text.strip()

                if len(text) < 50:
                    skipped_short += 1
                    continue
                if text in seen_texts:
                    skipped_dup += 1
                    continue

                seen_texts.add(text)

                # מנסה לחלץ URL של הפוסט
                post_url = group["url"]
                try:
                    link = await el.query_selector("a[href*='/posts/'], a[href*='story_fbid'], a[href*='permalink']")
                    if link:
                        href = await link.get_attribute("href")
                        if href:
                            post_url = href if href.startswith("http") else f"https://www.facebook.com{href}"
                except:
                    pass

                post_id = extract_post_id(post_url)

                posts.append({
                    "id": post_id,
                    "content": text,
                    "url": post_url,
                    "group": group["name"]
                })

            except Exception as e:
                log.debug(f"שגיאה בעיבוד אלמנט: {e}")
                continue

        log.debug(f"סטטיסטיקה — דולגו: {skipped_short} קצרים, {skipped_dup} כפולים")
        await random_delay(5, 15)

    except PlaywrightTimeout:
        log.error(f"טיימאאוט בקבוצה: {group['name']} (30 שניות)")
    except Exception as e:
        log.error(f"שגיאה בקבוצה {group['name']}: {e}", exc_info=True)

    log.info(f"<<< נמצאו {len(posts)} פוסטים ב-{group['name']}")
    return posts

async def scrape_all(email: str, password: str) -> list[dict]:
    all_posts = []

    log.info(f"מתחיל סריקה של {len(GROUPS)} קבוצות")

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
                "--renderer-process-limit=1",
                "--js-flags=--max-old-space-size=128",
            ]
        )
        log.debug("דפדפן הופעל בהצלחה")

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="he-IL"
        )
        page = await context.new_page()
        await block_heavy_resources(page)

        session_loaded = await load_session(context)

        # בודק אם הסשן עדיין תקף
        if session_loaded:
            log.debug("בודק תקינות סשן...")
            await page.goto("https://www.facebook.com", wait_until="domcontentloaded")
            await random_delay(2, 4)
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
            posts = await scrape_group(page, group)
            all_posts.extend(posts)

            # ניקוי זיכרון בין קבוצות
            try:
                await page.evaluate("window.gc && window.gc()")
            except Exception:
                pass

            if i < len(GROUPS):
                log.debug("השהיה בין קבוצות...")
                await random_delay(8, 20)

        await browser.close()
        log.debug("דפדפן נסגר")

    log.info(f"סריקה הסתיימה — סה\"כ {len(all_posts)} פוסטים מ-{len(GROUPS)} קבוצות")
    return all_posts
