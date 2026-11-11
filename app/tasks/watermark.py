from functools import lru_cache
from pathlib import Path

from PIL import Image

from app.core.config import get_settings

settings = get_settings()


@lru_cache
def _logo() -> Image.Image | None:
    p = Path(settings.LOGO_PATH)
    return Image.open(p).convert("RGBA") if p.exists() else None

def apply_logo(path: str) -> None:
    """Draw the logo in the top-left corner, sized as a percentage of the image width."""
    logo = _logo()
    if logo is None:
        return
    with Image.open(path) as im:
        base = im.convert("RGBA")

    w = max(1, round(base.width * settings.LOGO_WIDTH_PCT / 100))
    h = round(w * logo.height / logo.width)
    margin = round(base.width * settings.LOGO_MARGIN_PCT / 100)

    mark = logo.resize((w, h), Image.LANCZOS)
    base.alpha_composite(mark, (margin, margin))
    base.convert("RGB").save(path, "JPEG", quality=95)