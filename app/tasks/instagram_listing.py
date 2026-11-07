import logging
import re

from playwright.sync_api import sync_playwright

from app.core.config import get_settings

settings = get_settings()

logger = logging.getLogger(__name__)

SHORTCODE_RE = re.compile(r"/(p|reel|reels)/([A-Za-z0-9_-]+)/")

GRID_LINKS = 'a[href*="/reel/"], a[href*="/p/"], a[href*="/reels/"]'

MAX_SCROLL_STEPS = 25


def fetch_profile_posts(limit: int = 12) -> list[tuple[str, str, str, str]]:
    """Return up to `limit` (shortcode, kind, alt, cover_url) tuples."""
    found: dict[str, tuple[str, str, str]] = {}  # shortcode -> (kind, alt, cover_url)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            storage_state=settings.IG_STORAGE_STATE,
            viewport={"width": 1280, "height": 1800},  # tall viewport = more rows rendered
        )
        page = ctx.new_page()
        try:
            page.goto(f"https://www.instagram.com/{settings.IG_PROFILE}/", wait_until="domcontentloaded")
            page.wait_for_selector(GRID_LINKS, timeout=20_000)

            stale = 0
            for _ in range(MAX_SCROLL_STEPS):
                rows = page.eval_on_selector_all(
                    GRID_LINKS,
                    "els => els.map(e => [e.getAttribute('href'), (e.querySelector('img') || {}).alt || '', (e.querySelector('img') || {}).src || ''])",
                )
                before = len(found)
                for href, alt, src in rows:
                    m = SHORTCODE_RE.search(href or "")
                    if m and m.group(2) not in found:
                        kind = "reel" if m.group(1) in ("reel", "reels") else "post"
                        found[m.group(2)] = (kind, alt, src)

                if len(found) >= limit:
                    break
                stale = stale + 1 if len(found) == before else 0
                if stale >= 4:  # grid stopped growing
                    break

                page.mouse.move(640, 600)  # cursor over the page so wheel events land on it
                page.locator(GRID_LINKS).last.scroll_into_view_if_needed()
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(2500)
        finally:
            browser.close()

    logger.info("listing found %d posts (limit %d)", len(found), limit)
    return [(sc, kind, alt, src) for sc, (kind, alt, src) in list(found.items())[:limit]]