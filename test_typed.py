# test_typed.py  (python -m app.test_typed)
from playwright.sync_api import sync_playwright

TEXT = """Bellingham x2 in England training today! 🤩

All smiles for Jude and Jobe Bellingham, playing together for the very first time at professional level for England NT 🫂✨

Proud moment for the whole family. 🫲🏽🫱🏽"""

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=False)
    page = b.new_context(locale="en-US", viewport={"width": 1280, "height": 900}).new_page()
    page.goto("https://translate.google.com/?sl=en&tl=tk&op=translate")
    page.wait_for_timeout(2000)
    box = page.locator('textarea[aria-label="Source text"], textarea').first   # unverified selector
    box.click()
    box.fill(TEXT)
    page.wait_for_timeout(6000)
    page.screenshot(path="typed.png", full_page=True)
    res = page.locator('span[jsname="W297wb"]')
    out = "\n".join(s.inner_text() for s in res.all())
    open("typed.txt", "w", encoding="utf-8").write(out)
    print("saved typed.txt and typed.png")
    input("Look at the window, then press Enter to close...")
    b.close()