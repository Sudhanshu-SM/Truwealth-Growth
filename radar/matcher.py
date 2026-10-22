"""Keyword matching of text to topics (spec section 8)."""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Sequence

from radar.models import Topic

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def genre_ok(topic_genres: Sequence[str], source_genres: Sequence[str], finance: frozenset[str]) -> bool:
    """May a story from a source with these genres count for a topic with those genres?

    Trend and market sources have no genre and may count for any topic. Otherwise the topic must share a genre with
    the source, and a source with any finance genre reaches every finance genre ("gold medal" from a sports search
    must not heat gold_price, but any finance feed may heat any finance topic)."""
    if not source_genres:
        return True
    reach = set(source_genres)
    if not finance.isdisjoint(reach):
        reach |= finance
    return not reach.isdisjoint(topic_genres)


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
