"""X (Twitter) India trending list via public mirror sites; trends24 first, getdaytrends as fallback."""
from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from selectolax.parser import HTMLParser

from radar.collectors import Context
from radar.models import Signal


def parse_trends24(html: str) -> list[tuple[int, str]]:
    card = HTMLParser(html).css_first("div.list-container")
    if card is None:
        return []
    names = [a.text(strip=True) for a in card.css("ol.trend-card__list li a.trend-link")]
    return [(i + 1, name) for i, name in enumerate(names[:50]) if name]


def parse_getdaytrends(html: str) -> list[tuple[int, str]]:
    table = HTMLParser(html).css_first("table.ranking")
    if table is None:
        return []
    out = []
    for row in table.css("tr"):
        pos, link = row.css_first("th.pos"), row.css_first("td.main a")
        if pos is None or link is None or not pos.text(strip=True).isdigit():
            continue
        out.append((int(pos.text(strip=True)), link.text(strip=True)))
    return out[:50]


def to_signals(trends: list[tuple[int, str]], feed: str, now: datetime) -> list[Signal]:
    return [Signal(source="x_trends", source_type="x_trend", feed=feed, title=name,
                   url=f"https://x.com/search?q={quote(name)}", published_at=now, metrics={"rank": float(rank)})
            for rank, name in trends]


def collect(ctx: Context) -> list[Signal]:
    src = ctx.config.sources["x_trends"]
    try:
        trends, feed = parse_trends24(ctx.http.get(src["primary"]).text), "trends24"
    except Exception:  # noqa: BLE001 - any failure falls through to the second mirror
        trends, feed = [], "trends24"
    if not trends:
        trends, feed = parse_getdaytrends(ctx.http.get(src["fallback"]).text), "getdaytrends"
    if not trends:
        raise RuntimeError("no X trends parsed from either mirror")
    return to_signals(trends, feed, ctx.now)
