# debug_video.py  (python -m app.debug_video)
from playwright.sync_api import sync_playwright
from app.core.config import get_settings

settings = get_settings()

URL = "https://www.instagram.com/p/Dfh81upEd1r/"

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(storage_state=settings.IG_STORAGE_STATE, viewport={"width": 1280, "height": 1800})
    page = ctx.new_page()

    def on_response(r):
        ct = r.headers.get("content-type", "")
        if "video" in ct or "audio" in ct or ".mp4" in r.url:
            print("NET", r.status, ct, r.headers.get("content-range", ""), r.url[:150])

    page.on("response", on_response)
    page.goto(URL, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)

    for _ in range(6):                       # step forward until a video is mounted
        if page.locator("video").count():
            break
        nxt = page.locator('button[aria-label="Next"]')
        if not nxt.count():
            break
        try:
            nxt.first.click(timeout=3000)
        except Exception:
            page.keyboard.press("ArrowRight")
        page.wait_for_timeout(1500)

    print("videos on page:", page.locator("video").count())
    page.evaluate("() => { const v = document.querySelector('video'); if (v) { v.muted = true; v.play(); } }")
    page.wait_for_timeout(6000)

    print("BLOB:", page.evaluate("""async () => {
        const v = document.querySelector('video');
        if (!v) return 'no video';
        try { const r = await fetch(v.src); const bl = await r.blob(); return 'ok ' + bl.size + ' bytes ' + bl.type; }
        catch (e) { return 'fail ' + e; }
    }"""))
    b.close()