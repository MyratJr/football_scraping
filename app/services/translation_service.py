from app.tasks.translator_browser import BrowserTranslator


class TranslationService:
    """English -> Turkmen through the Google Translate website."""

    def __init__(self, headless: bool = True) -> None:
        self._headless = headless

    def translate_fields(self, title: str | None, caption: str | None) -> tuple[str | None, str | None]:
        """Translate both fields with one browser. Raises on failure, so the caller decides what to do."""
        if not title and not caption:
            return None, None
        with BrowserTranslator(headless=self._headless) as tr:
            title_tk = tr.translate(title) if title else None
            caption_tk = tr.translate(caption) if caption else None
        return title_tk, caption_tk