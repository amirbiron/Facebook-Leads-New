import asyncio
import json
import random
import re
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

SESSION_FILE = Path("data/fb_session.json")

GROUPS = [
    {"name": "הכול על אוטומציות בינה מלאכותית AI - IL ישראל", "url": "https://www.facebook.com/groups/640894321475593/"},
    {"name": "דרושים מתכנתים ואנשי פיתוח", "url": "https://www.facebook.com/groups/1920854911477422"},
    {"name": "AI ISRAEL – בינה מלאכותית כלים ושימושים", "url": "https://www.facebook.com/groups/1934524236895744/"},
    {"name": "בינה מלאכותית AI ISRAEL", "url": "https://www.facebook.com/groups/2055437551629206"},
    {"name": "Vibe Coding - Israel", "url": "https://www.facebook.com/groups/1684554685829832"},
]

async def random_delay(min_sec=2, max_sec=6):
    await asyncio.sleep(random.uniform(min_sec, max_sec))

async def human_scroll(page, times=3):
    for _ in range(times):
        await page.evaluate("window.scrollBy(0, Math.random() * 400 + 200)")
        await random_delay(1, 3)

async def save_session(context):
    SESSION_FILE.parent.mkdir(exist_ok=True)
    cookies = await context.cookies()
    SESSION_FILE.write_text(json.dumps(cookies))
    print("[Scraper] סשן נשמר")

async def load_session(context):
    if SESSION_FILE.exists():
        cookies = json.loads(SESSION_FILE.read_text())
        await context.add_cookies(cookies)
        print("[Scraper] סשן נטען")
        return True
    return False

async def login(page, email: str, password: str):
    print("[Scraper] מתחבר לפייסבוק...")
    await page.goto("https://www.facebook.com/login", wait_until="networkidle")
    await random_delay(2, 4)

    await page.fill("#email", email)
    await random_delay(0.5, 1.5)
    await page.fill("#pass", password)
    await random_delay(0.5, 1.5)
    await page.click("[name='login']")
    await page.wait_for_load_state("networkidle")
    await random_delay(3, 5)

    if "login" in page.url:
        raise Exception("התחברות נכשלה — בדוק אימייל/סיסמה")
    
    print("[Scraper] מחובר בהצלחה")

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
    print(f"[Scraper] סורק: {group['name']}")

    try:
        await page.goto(group["url"], wait_until="domcontentloaded", timeout=30000)
        await random_delay(3, 6)
        await human_scroll(page, times=4)

        # מחפש אלמנטים של פוסטים
        post_elements = await page.query_selector_all("[data-ad-preview='message'], [data-testid='post_message'], div[dir='auto']")
        
        # גישה אלטרנטיבית — לפי role
        if not post_elements:
            post_elements = await page.query_selector_all("div[role='article']")

        seen_texts = set()
        
        for el in post_elements[:30]:
            try:
                text = await el.inner_text()
                text = text.strip()
                
                if len(text) < 50 or text in seen_texts:
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

            except Exception:
                continue

        await random_delay(5, 15)

    except PlaywrightTimeout:
        print(f"[Scraper] טיימאאוט בקבוצה: {group['name']}")
    except Exception as e:
        print(f"[Scraper] שגיאה בקבוצה {group['name']}: {e}")

    print(f"[Scraper] נמצאו {len(posts)} פוסטים ב-{group['name']}")
    return posts

async def scrape_all(email: str, password: str) -> list[dict]:
    all_posts = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="he-IL"
        )
        page = await context.new_page()

        session_loaded = await load_session(context)

        # בודק אם הסשן עדיין תקף
        if session_loaded:
            await page.goto("https://www.facebook.com", wait_until="domcontentloaded")
            await random_delay(2, 4)
            if "login" in page.url:
                print("[Scraper] סשן פג — מתחבר מחדש")
                await login(page, email, password)
                await save_session(context)
        else:
            await login(page, email, password)
            await save_session(context)

        for group in GROUPS:
            posts = await scrape_group(page, group)
            all_posts.extend(posts)
            await random_delay(8, 20)  # השהיה בין קבוצות

        await browser.close()

    return all_posts
