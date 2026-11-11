"""
English -> Turkmen through the Google Translate website (Playwright).

Easiest use:  paste your English text into TEXT below, then run:  python translator_browser.py
Other ways:   python translator_browser.py "Some text"
              python translator_browser.py --file input.txt
Debug:        python translator_browser.py --headed --dump
"""
import argparse
import re
import sys
import time
import unicodedata
from urllib.parse import quote

from playwright.sync_api import Page, sync_playwright

# ======================= PUT YOUR ENGLISH TEXT HERE =======================
TEXT = """𝐕𝐎𝐙𝐈𝐍𝐇𝐀 🇨🇻 𝐀𝐍𝐃 𝐂𝐎𝐋𝐎-𝐂𝐎𝐋𝐎 𝐀𝐑𝐄 𝐂𝐇𝐀𝐌𝐏𝐈𝐎𝐍𝐒 𝐎𝐅 𝐂𝐇𝐈𝐋𝐄 🏆🇨🇱

What an incredible few months for Cape Verde’s World Cup hero Vozinha 🥹 Just four months ago, the 40-year-old goalkeeper was representing his country at the World Cup. His performances earned him a move to Chilean giants Colo-Colo, where he’s now celebrating a league title alongside Arturo Vidal 🌍🏆

Colo-Colo secured their 𝟯𝟱𝗧𝗛 𝗟𝗘𝗔𝗚𝗨𝗘 𝗧𝗜𝗧𝗟𝗘 with a dramatic 𝟮-𝟭 win over Ñublense, sealed by a stoppage-time winner and a 97th-minute save from Vozinha! 🧤🤯

After the match, he dedicated the title to those closest to his heart: “𝙁𝙤𝙧 𝙢𝙮 𝙛𝙖𝙢𝙞𝙡𝙮, 𝘾𝙖𝙥𝙚 𝙑𝙚𝙧𝙙𝙚, 𝙢𝙮 𝙩𝙚𝙖𝙢𝙢𝙖𝙩𝙚𝙨 𝙖𝙣𝙙 𝙩𝙝𝙚 𝘾𝙤𝙡𝙤-𝘾𝙤𝙡𝙤 𝙛𝙖𝙣𝙨.” ❤️

From making his country 𝒑𝒓𝒐𝒖𝒅 to making 𝒉𝒊𝒔𝒕𝒐𝒓𝒚 in Chile 🥹🇨🇻🇨🇱"""
# ==========================================================================

SOURCE, TARGET = "en", "tk"
MAX_ENCODED_CHARS = 1800    # limit for the URL-ENCODED text (emojis/fancy letters are ~12 chars each)
CONSENT_BUTTONS = ("Accept all", "Reject all", "I agree")
STABLE_READS = 3            # result must be identical this many reads in a row

RESULT_SELECTORS = (
    'span[jsname="W297wb"]',                              # one span per translated sentence
    f'c-wiz[role="region"] span[lang="{TARGET}"]',        # fallback
)

# ALL-CAPS cleanup (Google translates "LEAGUE TITLE" worse than "League Title")
KEEP_CAPS = {"FIFA", "UEFA", "CAF", "NASA", "NBA", "NFL", "NHL", "MLB", "UFC", "VAR", "USA", "UAE", "AFC", "CONMEBOL"}
SMALL_WORDS = {"AND", "ARE", "OF", "THE", "IN", "ON", "FOR", "TO", "A", "AN", "AT", "BY", "OR", "IS", "AS", "WITH", "FROM"}


class BrowserTranslationError(Exception):
    pass


# ---------------------------------------------------------------- text cleanup
def _fix_caps_word(m: re.Match) -> str:
    w = m.group(0)
    letters = re.sub(r"[^A-Za-z]", "", w)
    if len(letters) < 2 or w != w.upper() or w in KEEP_CAPS:
        return w
    if any(c.isdigit() for c in w):
        return w.lower()                                  # 35TH -> 35th
    if w in SMALL_WORDS:
        return w.lower()                                  # AND -> and
    if len(letters) < 4 and len(w) <= 3:
        return w                                          # short unknowns (e.g. "PSG") stay
    return "-".join(p.capitalize() for p in w.split("-"))  # COLO-COLO -> Colo-Colo


def clean_text(text: str) -> str:
    """Turn 𝐅𝐚𝐧𝐜𝐲 𝗨𝗻𝗶𝗰𝗼𝗱𝗲 letters into normal ones, and fix ALL-CAPS words."""
    text = unicodedata.normalize("NFKC", text)           # 𝐕𝐎𝐙𝐈𝐍𝐇𝐀 -> VOZINHA, 𝟮-𝟭 -> 2-1
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = re.sub(r"[A-Z0-9][A-Z0-9'’\-]*", _fix_caps_word, text)
    return text


# ---------------------------------------------------------------- splitting
def _enc_len(s: str) -> int:
    return len(quote(s))


def _split_long(line: str) -> list[str]:
    parts, cur = [], ""
    for sent in re.split(r"(?<=[.!?…])\s+", line):
        for part in ([sent] if _enc_len(sent) <= MAX_ENCODED_CHARS else sent.split(" ")):
            cand = f"{cur} {part}".strip()
            if cur and _enc_len(cand) > MAX_ENCODED_CHARS:
                parts.append(cur)
                cur = part
            else:
                cur = cand
    if cur:
        parts.append(cur)
    return parts


def _split(text: str) -> list[str]:
    """Pack whole lines into chunks that fit in the URL, so Google sees as much context as possible."""
    chunks, cur = [], ""
    for line in text.split("\n"):
        for piece in ([line] if _enc_len(line) <= MAX_ENCODED_CHARS else _split_long(line)):
            cand = f"{cur}\n{piece}" if cur else piece
            if cur and _enc_len(cand) > MAX_ENCODED_CHARS:
                chunks.append(cur)
                cur = piece
            else:
                cur = cand
    if cur:
        chunks.append(cur)
    return chunks


class BrowserTranslator:
    def __init__(self, headless: bool = True, timeout_s: float = 25.0, dump: bool = False) -> None:
        self._headless = headless
        self._timeout = timeout_s
        self._dump = dump

    def __enter__(self) -> "BrowserTranslator":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        self._ctx = self._browser.new_context(locale="en-US", viewport={"width": 1280, "height": 900})
        return self

    def __exit__(self, *exc) -> None:
        self._browser.close()
        self._pw.stop()

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
        joined = ""
        for sel in RESULT_SELECTORS:
            spans = page.locator(sel)
            if spans.count():
                joined = " ".join(s.inner_text().strip() for s in spans.all()).strip()
                if joined:
                    break
        if not joined:
            return ""
        # the outer result element has the same text with the line breaks kept
        outer = page.locator(f'c-wiz[role="region"] span[lang="{TARGET}"]')
        if outer.count():
            t = outer.first.inner_text().strip()
            if len(re.sub(r"\s+", "", t)) >= len(re.sub(r"\s+", "", joined)):
                return t
        return joined

    def _translate_piece(self, piece: str) -> str:
        url = (
            f"https://translate.google.com/?sl={SOURCE}&tl={TARGET}"
            f"&text={quote(piece)}&op=translate"
        )
        page = self._ctx.new_page()   # fresh page per piece, so an old result is never read
        try:
            page.goto(url, wait_until="domcontentloaded")
            self._dismiss_consent(page)

            deadline = time.monotonic() + self._timeout
            last, stable = "", 0
            while time.monotonic() < deadline:
                cur = self._read_result(page)
                if cur and cur == last:
                    stable += 1
                    if stable >= STABLE_READS:
                        return cur
                else:
                    stable = 0
                last = cur
                page.wait_for_timeout(600)

            if self._dump:
                open("debug_translate.html", "w", encoding="utf-8").write(page.content())
                page.screenshot(path="debug_translate.png", full_page=True)
            if last:
                return last
            raise BrowserTranslationError(
                "no translation found. Google may have changed its markup or shown a CAPTCHA; "
                "run with --headed --dump and inspect debug_translate.html"
            )
        finally:
            page.close()

    def _translate_chunk(self, chunk: str) -> str:
        if not chunk.strip():
            return chunk
        result = self._translate_piece(chunk)
        want = sum(1 for l in chunk.split("\n") if l.strip())
        got = sum(1 for l in result.split("\n") if l.strip())
        if want <= 1 or want == got:
            return result
        # the line structure was lost: translate line by line instead (less context, safe layout)
        return "\n".join(l if not l.strip() else self._translate_piece(l) for l in chunk.split("\n"))

    def translate(self, text: str, clean: bool = True) -> str:
        """Translate text, keeping its line breaks."""
        if not text or not text.strip():
            return text
        if clean:
            text = clean_text(text)
        out = []
        for chunk in _split(text):
            out.append(self._translate_chunk(chunk))
            time.sleep(1)   # be gentle, avoids rate limits
        return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="English -> Turkmen via the Google Translate website")
    ap.add_argument("text", nargs="*", help="text to translate (default: the TEXT variable in this file)")
    ap.add_argument("--file", help="read English text from this UTF-8 file")
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    ap.add_argument("--dump", action="store_true", help="save debug_translate.html/.png when it fails")
    ap.add_argument("--raw", action="store_true", help="do not clean fancy Unicode / ALL-CAPS")
    args = ap.parse_args()

    if args.file:
        text = open(args.file, encoding="utf-8").read()
    elif args.text:
        text = " ".join(args.text)
    else:
        text = TEXT

    try:
        with BrowserTranslator(headless=not args.headed, dump=args.dump) as t:
            result = t.translate(text, clean=not args.raw)
    except BrowserTranslationError as exc:
        sys.exit(f"Error: {exc}")

    print(result)
    with open("translation.txt", "w", encoding="utf-8") as f:
        f.write(result)


if __name__ == "__main__":
    main()