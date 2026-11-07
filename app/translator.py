"""
English -> Turkmen through the Google Translate website (Playwright).

Run:    python translator_browser.py "Harry Kane's new Bayern contract, incoming very soon!"
Debug:  python translator_browser.py --headed --dump "Hello"     (shows the browser, saves debug_translate.html)
Use:    from translator_browser import BrowserTranslator
        with BrowserTranslator() as t:
            print(t.translate("Here we go!"))
"""
import argparse
import sys
import time
from urllib.parse import quote

from playwright.sync_api import Page, sync_playwright

SOURCE, TARGET = "en", "tk"
MAX_URL_CHARS = 1800        # text travels in the URL, keep it short; longer text is split by lines/words
CONSENT_BUTTONS = ("Accept all", "Reject all", "I agree")

# Result selectors, tried in order. Google changes these attributes, so they are
# the first thing to fix if translation stops working (use --dump to inspect the page).
RESULT_SELECTORS = (
    'span[jsname="W297wb"]',                              # one span per translated sentence
    f'c-wiz[role="region"] span[lang="{TARGET}"]',        # fallback: results carry lang="tk"
)


class BrowserTranslationError(Exception):
    pass


def _split(text: str) -> list[str]:
    """Split text into pieces below MAX_URL_CHARS, on line breaks first, then on spaces."""
    pieces: list[str] = []
    for line in text.split("\n"):
        if len(line) <= MAX_URL_CHARS:
            pieces.append(line)
            continue
        cur = ""
        for word in line.split(" "):
            if len(cur) + len(word) + 1 > MAX_URL_CHARS:
                pieces.append(cur)
                cur = word
            else:
                cur = f"{cur} {word}".strip()
        pieces.append(cur)
    return pieces


class BrowserTranslator:
    def __init__(self, headless: bool = True, timeout_s: float = 20.0, dump: bool = False) -> None:
        self._headless = headless
        self._timeout = timeout_s
        self._dump = dump

    def __enter__(self) -> "BrowserTranslator":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        self._ctx = self._browser.new_context(
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        return self

    def __exit__(self, *exc) -> None:
        self._browser.close()
        self._pw.stop()

    # ------------------------------------------------------------------ page helpers
    def _dismiss_consent(self, page: Page) -> None:
        for label in CONSENT_BUTTONS:
            try:
                btn = page.get_by_role("button", name=label)
                if btn.count():
                    btn.first.click(timeout=2000)
                    page.wait_for_timeout(500)
                    return
            except Exception:
                pass

    def _read_result(self, page: Page) -> str:
        for sel in RESULT_SELECTORS:
            spans = page.locator(sel)
            if spans.count():
                text = " ".join(s.inner_text().strip() for s in spans.all()).strip()
                if text:
                    return text
        return ""

    def _translate_piece(self, piece: str) -> str:
        url = (
            f"https://translate.google.com/?sl={SOURCE}&tl={TARGET}"
            f"&text={quote(piece)}&op=translate"
        )
        page = self._ctx.new_page()   # fresh page per piece, so an old result is never read
        try:
            page.goto(url, wait_until="domcontentloaded")
            self._dismiss_consent(page)

            # wait until the result is non-empty and stable for 2 reads in a row
            deadline = time.monotonic() + self._timeout
            last, stable = "", 0
            while time.monotonic() < deadline:
                cur = self._read_result(page)
                if cur and cur == last:
                    stable += 1
                    if stable >= 2:
                        return cur
                else:
                    stable = 0
                last = cur
                page.wait_for_timeout(500)

            if self._dump:
                open("debug_translate.html", "w", encoding="utf-8").write(page.content())
                page.screenshot(path="debug_translate.png", full_page=True)
            if last:
                return last   # never stabilised, but we have something
            raise BrowserTranslationError(
                "no translation found. Google may have changed its markup or shown a CAPTCHA; "
                "run with --headed --dump and inspect debug_translate.html"
            )
        finally:
            page.close()

    # ------------------------------------------------------------------ public API
    def translate(self, text: str) -> str:
        """Translate text keeping its line breaks."""
        if not text or not text.strip():
            return text
        out = []
        for piece in _split(text):
            out.append(piece if not piece.strip() else self._translate_piece(piece))
            time.sleep(1)   # be gentle, avoids rate limits
        return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="English -> Turkmen via the Google Translate website")
    ap.add_argument("text", nargs="*", help="text to translate (omit for interactive mode)")
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    ap.add_argument("--dump", action="store_true", help="save debug_translate.html/.png when it fails")
    args = ap.parse_args()

    try:
        with BrowserTranslator(headless=not args.headed, dump=args.dump) as t:
            if args.text:
                print(t.translate(" ".join(args.text)))
                return
            print("Type English text, empty line to quit.")
            while True:
                line = input("> ").strip()
                if not line:
                    break
                print(t.translate(line), "\n")
    except BrowserTranslationError as exc:
        sys.exit(f"Error: {exc}")


if __name__ == "__main__":
    main()