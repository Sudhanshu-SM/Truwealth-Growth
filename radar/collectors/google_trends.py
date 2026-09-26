"""Google 'Trending now' RSS for India: searches spiking right now."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from radar.collectors import Context
from radar.models import Signal
from radar.text import clean
from radar.timeutil import parse_date

HT = "{https://trends.google.com/trending/rss}"


def parse_traffic(s: str | None) -> float:
    """'20K+' / '10000+' / '2M+' -> number."""
    m = re.match(r"\s*([\d.,]+)\s*([KkMm]?)", s or "")
    if not m:
        return 0.0
    return float(m.group(1).replace(",", "")) * {"k": 1e3, "m": 1e6}.get(m.group(2).lower(), 1.0)


def parse(raw: bytes) -> list[Signal]:
    out = []
    for it in ET.fromstring(raw).iter("item"):
        title = clean(it.findtext("title"))
        if not title:
            continue
        news = it.findall(f"{HT}news_item")
        out.append(Signal(
            source="google_trends", source_type="search_trend", feed="google_trends_in", title=title,
            url=news[0].findtext(f"{HT}news_item_url") if news else None,
            published_at=parse_date(it.findtext("pubDate")),
            text=" | ".join(clean(n.findtext(f"{HT}news_item_title")) for n in news),
            metrics={"approx_traffic": parse_traffic(it.findtext(f"{HT}approx_traffic"))}))
    return out


def collect(ctx: Context) -> list[Signal]:
    return parse(ctx.http.get(ctx.config.sources["google_trends"]["url"]).content)
