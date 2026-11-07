# debug_session.py  (run: python -m app.debug_session)
import json
from playwright.sync_api import sync_playwright
from app.core.config import get_settings

settings = get_settings()
state = json.load(open(settings.IG_STORAGE_STATE))
names = {c["name"] for c in state["cookies"] if "instagram.com" in c["domain"]}
print("sessionid present:", "sessionid" in names, "| ds_user_id:", "ds_user_id" in names)

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(storage_state=settings.IG_STORAGE_STATE, viewport={"width": 1280, "height": 1800})
    page = ctx.new_page()
    page.goto(f"https://www.instagram.com/{settings.IG_PROFILE}/", wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    print("dialogs:", page.locator('div[role="dialog"]').count())
    print("login form:", page.locator('input[name="username"]').count())
    print("logged-in nav (Home link):", page.locator('a[href="/"]').count())
    print("overflow:", page.evaluate("getComputedStyle(document.body).overflow"))
    page.screenshot(path="debug_session.png")
    b.close()