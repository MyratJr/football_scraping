from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=False)
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto("https://www.instagram.com/accounts/login/")
    input("Log in in the browser window, then press Enter here...")
    ctx.storage_state(path="secrets/instagram_state.json")
    browser.close()