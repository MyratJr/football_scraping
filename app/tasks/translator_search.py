"""
English -> Turkmen through the translate widget at the top of Google Search.

Test:   python -m app.tasks.translator_search --headed --dump --file input.txt
"""
import argparse
import re
import sys
import time

from playwright.sync_api import Page, sync_playwright

# SEARCH_URL = "https://www.google.com/search?q=translate+english+to+turkmen&hl=en"
SEARCH_URL = "https://www.google.com/search?q=google+translate"   # your old URL

SEL_SL = "#tw-sl"
SEL_TL = "#tw-tl, #tw-t1"        # your pasted HTML has id="tw-t1"
SEL_SOURCE = "#tw-source-text-ta, textarea.tw-ta, #tw-source-text-container"
SEL_RESULT = "#tw-target-text"

PROFILE_DIR = "secrets/google_profile"
TARGET_NAME = "Turkmen"          # the page is in English because of hl=en
SOURCE_NAME = "English"
CONSENT_BUTTONS = ("Accept all", "Reject all", "I agree", "Принять все", "Отклонить все")

STABLE_READS = 3

# Unverified: these ids are from my memory of the widget. If the script fails, inspect the page
# (--headed --dump) and correct them.

SEL_TARGET_PICKER = "#tw-tl"
LABEL_RE = re.compile(r"^\s*(переведенный текст|translated text|terjime edilen tekst)\s*:\s*", re.I)


class SearchTranslationError(Exception):
    pass


class SearchTranslator:
    def __init__(self, headless: bool = True, timeout_s: float = 30.0, dump: bool = False) -> None:
        self._headless, self._timeout, self._dump = headless, timeout_s, dump
        self._page: Page | None = None

    def __enter__(self) -> "SearchTranslator":
        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=self._headless,
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        self._page = self._open()
        return self

    def __exit__(self, *exc) -> None:
        self._ctx.close()
        self._pw.stop()

    # ------------------------------------------------------------------ page setup
    def _debug(self, page: Page, why: str) -> None:
        if self._dump:
            open("debug_search.html", "w", encoding="utf-8").write(page.content())
            page.screenshot(path="debug_search.png", full_page=True)
        raise SearchTranslationError(why + " (run with --headed --dump and inspect debug_search.html)")

    def _langs(self, page: Page) -> list[str]:
        """[source, target] as displayed text, lower-cased (e.g. ['english', 'turkmen'])."""
        return page.evaluate(
            """() => ['#tw-sl', '#tw-tl, #tw-t1'].map(s => {
                const e = document.querySelector(s);
                return e ? e.innerText.trim().toLowerCase() : '';
            })"""
        )

    def _pair_ok(self, page: Page) -> bool:
        src, tgt = self._langs(page)
        return src.startswith("english") and tgt.startswith("turkmen")

    def _wait_pair(self, page: Page, seconds: float = 4.0) -> bool:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self._pair_ok(page):
                return True
            page.wait_for_timeout(300)
        return False

    def _pick(self, page: Page, opener_sel: str, name: str) -> None:
        """Open a language dropdown and click the list item (not the label in the bar)."""
        page.locator(opener_sel).first.click(timeout=3000)
        page.wait_for_timeout(600)
        found = page.evaluate(
            """(name) => {
                const bar = [...document.querySelectorAll('#tw-sl, #tw-tl, #tw-t1')];
                const els = [...document.querySelectorAll('body *')].filter(e =>
                    e.textContent.trim() === name
                    && !bar.some(b => b.contains(e))
                    && e.getClientRects().length
                    && getComputedStyle(e).visibility !== 'hidden');
                if (!els.length) return false;
                // take the innermost element so we click the actual item
                const el = els[els.length - 1];
                el.setAttribute('data-pick', '1');
                return true;
            }""",
            name,
        )
        if not found:
            raise SearchTranslationError(f"'{name}' not found in the dropdown")
        page.locator('[data-pick="1"]').first.click(timeout=3000)
        page.evaluate("document.querySelectorAll('[data-pick]').forEach(e => e.removeAttribute('data-pick'))")
        page.wait_for_timeout(600)


    
    def _choose(self, page: Page, opener, name: str) -> None:
        opener.click(timeout=3000)
        page.get_by_text(name, exact=True).first.click(timeout=3000)
        page.wait_for_timeout(600)

    def _set_target(self, page: Page) -> None:
        if self._pair_ok(page):
            return

        # 1) Turkmen -> English: just swap
        src, tgt = self._langs(page)
        if src.startswith("turkmen") and tgt.startswith("english"):
            try:
                page.locator("#tw-swap").click(timeout=3000, force=True)
            except Exception:
                page.evaluate("document.querySelector('#tw-swap')?.click()")
            if self._wait_pair(page):
                return

        # 2) any other pair: pick each language from its dropdown
        try:
            if not self._langs(page)[0].startswith("english"):
                self._pick(page, SEL_SL, "English")
            if not self._langs(page)[1].startswith("turkmen"):
                self._pick(page, SEL_TL, "Turkmen")
            if self._wait_pair(page):
                return
        except Exception:
            pass

        if self._headless:
            self._debug(page, "could not set English -> Turkmen")
        print("Set the languages to English -> Turkmen in the browser window (60 s)...")
        if self._wait_pair(page, 60):
            return
        self._debug(page, "languages were not set in time")

    def _read_result(self) -> str:
        loc = self._page.locator(SEL_RESULT)
        if not loc.count():
            return ""
        return LABEL_RE.sub("", loc.first.inner_text()).strip()
    
    def _open(self) -> Page:
        page = self._ctx.new_page()
        page.goto(SEARCH_URL, wait_until="domcontentloaded")
        for label in CONSENT_BUTTONS:                       # consent page, if any
            btn = page.get_by_role("button", name=label)
            if btn.count():
                btn.first.click(timeout=2000)
                page.wait_for_load_state("domcontentloaded")
                break
        if "/sorry/" in page.url or page.locator('iframe[src*="recaptcha"]').count():
            if self._headless:
                self._debug(page, "Google shows a CAPTCHA (unusual traffic)")
            print("CAPTCHA: solve it in the browser window (you have 3 minutes)...")
            try:
                page.wait_for_selector(SEL_SOURCE, timeout=180_000)
            except Exception:
                self._debug(page, "CAPTCHA was not solved in time")
        try:
            page.wait_for_selector(SEL_SOURCE, timeout=15_000)
        except Exception:
            self._debug(page, "translate widget not found")

        self._set_target(page)
        return page


    def _type_source(self, text: str) -> None:
        page = self._page
        # the real input is a textarea inside the wrapper, if the page has one
        ta = page.locator("textarea#tw-source-text-ta, #tw-source-text-container textarea")
        if ta.count():
            try:
                ta.first.fill(text, timeout=3000)
                return
            except Exception:
                pass
        # otherwise click the box so it gets the focus, clear it and paste the text
        page.locator("#tw-source-text-container").click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        page.keyboard.insert_text(text)        # keeps line breaks and emojis

    def _translate_chunk(self, text: str) -> str:
        page = self._page
        prev = self._read_result()          # result of the previous chunk (or placeholder)
        self._type_source(text)

        deadline = time.monotonic() + self._timeout
        last, stable = "", 0
        while time.monotonic() < deadline:
            cur = self._read_result()
            changed = cur != prev           # ignore the stale previous result
            if cur and changed and cur == last:
                stable += 1
                if stable >= STABLE_READS:
                    return cur
            else:
                stable = 0
            last = cur
            page.wait_for_timeout(600)
        if last and last != prev:
            return last
        self._debug(page, "no translation appeared")

        
    def translate(self, text: str) -> str:
        """Translate text, keeping its line breaks. The text is sent as it is (no letter cleanup)."""
        if not text or not text.strip():
            return text
        if not re.search(r"[^\W\d_]", re.sub(r"[@#]\w+", "", text)):   # no letters at all: keep as it is
            return text
        out = self._translate_chunk(text[:4900])    # the widget accepts about 5,000 characters
        if len(text) > 4900:
            out += "\n" + self._translate_chunk(text[4900:9800])
        time.sleep(1)
        return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="*")
    ap.add_argument("--file")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--dump", action="store_true")
    args = ap.parse_args()
    text = open(args.file, encoding="utf-8").read() if args.file else " ".join(args.text)
    try:
        with SearchTranslator(headless=not args.headed, dump=args.dump) as t:
            result = t.translate(text)
    except SearchTranslationError as exc:
        sys.exit(f"Error: {exc}")
    open("translation.txt", "w", encoding="utf-8").write(result)
    print("saved translation.txt")


if __name__ == "__main__":
    main()