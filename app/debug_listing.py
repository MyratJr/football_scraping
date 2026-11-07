# debug_listing.py
from playwright.sync_api import sync_playwright
from app.core.config import get_settings
from app.tasks.instagram_listing import GRID_LINKS

settings = get_settings()

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(storage_state=settings.IG_STORAGE_STATE, viewport={"width": 1280, "height": 1800})
    page = ctx.new_page()
    page.goto(f"https://www.instagram.com/{settings.IG_PROFILE}/", wait_until="domcontentloaded")
    page.wait_for_selector(GRID_LINKS)
    for i in range(5):
        n = page.locator(GRID_LINKS).count()
        h = page.evaluate("document.documentElement.scrollHeight")
        y = page.evaluate("window.scrollY")
        print(f"step {i}: links={n} scrollHeight={h} scrollY={y}")
        page.locator(GRID_LINKS).last.scroll_into_view_if_needed()
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(2500)
    page.screenshot(path="debug_profile.png")
    b.close()