import re

# Instagram's auto-generated alt text, not a real caption
AUTO_ALT = re.compile(r"^(photo|video)( shared)? by |^may be an image|^may be a", re.I)


def split_caption(raw: str | None) -> tuple[str | None, str | None]:
    """First paragraph -> title, the rest -> description."""
    if not raw:
        return None, None
    text = raw.replace("\r\n", "\n").strip()
    if not text or AUTO_ALT.match(text):
        return None, None
    parts = re.split(r"\n\s*\n", text, maxsplit=1)
    title = parts[0].strip() or None
    desc = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
    return title, desc


def caption_from_og(og: str | None) -> str | None:
    """og:description looks like: 'N likes, M comments - user on <date>: "caption".'"""
    if not og:
        return None
    m = re.search(r':\s*["“](.*)["”]\.?\s*$', og, re.S)
    return m.group(1) if m else None