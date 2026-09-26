"""Keyword matching of text to topics (spec section 8)."""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable

from radar.models import Topic

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def _case_sensitive(keyword: str) -> bool:
    return len(keyword) <= 4 and keyword.isupper()


def _alternation(words: list[str]) -> str:
    return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))


class Matcher:
    def __init__(self, topics: Iterable[Topic]):
        self._rules: list[tuple[str, re.Pattern[str] | None, re.Pattern[str] | None, tuple[str, ...]]] = []
        for topic in topics:
            insensitive: list[str] = []
            sensitive: list[str] = []
            devanagari: list[str] = []
            for kw in topic.keywords:
                kw = unicodedata.normalize("NFC", kw.strip())
                if _DEVANAGARI.search(kw):
                    devanagari.append(kw)
                elif _case_sensitive(kw):
                    sensitive.append(kw)
                else:
                    insensitive.append(kw)
            ci = re.compile(rf"(?<!\w)(?:{_alternation(insensitive)})(?!\w)", re.IGNORECASE) if insensitive else None
            cs = re.compile(rf"(?<!\w)(?:{_alternation(sensitive)})(?!\w)") if sensitive else None
            self._rules.append((topic.id, ci, cs, tuple(devanagari)))

    def match(self, text: str) -> list[str]:
        text = unicodedata.normalize("NFC", text or "")
        hits = []
        for topic_id, ci, cs, devanagari in self._rules:
            if (ci and ci.search(text)) or (cs and cs.search(text)) or any(d in text for d in devanagari):
                hits.append(topic_id)
        return hits
