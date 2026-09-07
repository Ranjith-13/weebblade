import re

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def clean_synopsis(text: str | None) -> str | None:
    """Strip HTML tags and collapse whitespace in a synopsis/description field.

    All three sources' synopsis text is mostly plain, but AniList's in particular can
    still carry stray tags (e.g. <br>) even with asHtml: false requested.
    """
    if not text:
        return None
    text = _TAG_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text or None
