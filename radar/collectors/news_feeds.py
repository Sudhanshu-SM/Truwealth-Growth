"""Finance-section RSS feeds of Indian news outlets."""
from __future__ import annotations

from radar.collectors import Context, gather
from radar.models import Signal
from radar.rss import parse_feed
from radar.timeutil import IST


def parse(raw: bytes, feed_id: str) -> list[Signal]:
    return [Signal(source="news_feeds", source_type="news", feed=feed_id, title=e.title, url=e.link,
                   published_at=e.published, text=e.summary[:500])
            for e in parse_feed(raw, default_tz=IST) if e.title]


def collect(ctx: Context) -> list[Signal]:
    return gather([(f["id"], lambda f=f: parse(ctx.http.get(f["url"]).content, f["id"]))
                   for f in ctx.config.sources["news_feeds"]])
