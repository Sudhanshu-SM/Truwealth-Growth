"""Minimal RSS 2.0 / Atom parser (stdlib) that tolerates the date quirks in our feeds."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone

from radar.text import clean
from radar.timeutil import parse_date

ATOM = "{http://www.w3.org/2005/Atom}"


@dataclass
class Entry:
    title: str
    link: str | None
    summary: str
    published: datetime | None
    guid: str
    source: str = ""
    source_url: str = ""


def parse_feed(raw: bytes, default_tz: timezone = timezone.utc) -> list[Entry]:
    root = ET.fromstring(raw)
    entries: list[Entry] = []
    for it in root.iter("item"):
        source = it.find("source")
        entries.append(Entry(
            title=clean(it.findtext("title")),
            link=(it.findtext("link") or "").strip() or None,
            summary=clean(it.findtext("description")),
            published=parse_date(it.findtext("pubDate"), default_tz),
            guid=(it.findtext("guid") or it.findtext("link") or "").strip(),
            source=clean(source.text) if source is not None else "",
            source_url=(source.get("url") or "") if source is not None else "",
        ))
    for it in root.iter(f"{ATOM}entry"):
        link = it.find(f"{ATOM}link")
        entries.append(Entry(
            title=clean(it.findtext(f"{ATOM}title")),
            link=link.get("href") if link is not None else None,
            summary=clean(it.findtext(f"{ATOM}summary") or it.findtext(f"{ATOM}content")),
            published=parse_date(it.findtext(f"{ATOM}published") or it.findtext(f"{ATOM}updated"), default_tz),
            guid=(it.findtext(f"{ATOM}id") or "").strip(),
        ))
    return entries
