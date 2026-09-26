"""Text cleaning shared by collectors, matcher, phrases and store."""
from __future__ import annotations

import hashlib
import html
import re
import unicodedata

_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")
_SLUG = re.compile(r"[^0-9a-zऀ-ॿ]+")


def clean(s: str | None) -> str:
    """Unescape entities, drop HTML tags and emoji, NFC-normalise, collapse whitespace."""
    if not s:
        return ""
    s = _TAGS.sub(" ", html.unescape(s))
    s = _EMOJI.sub("", unicodedata.normalize("NFC", s))
    return _WS.sub(" ", s).strip()


def normalize_title(title: str) -> str:
    return clean(title).lower()


def sha1(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()


def slugify(s: str) -> str:
    return _SLUG.sub("-", s.lower()).strip("-")[:60] or "topic"
