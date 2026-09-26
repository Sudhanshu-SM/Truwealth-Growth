"""RBI press releases and SEBI announcements (items dated today or yesterday, IST)."""
from __future__ import annotations

from datetime import datetime

from radar.collectors import Context, gather
from radar.models import Signal
from radar.rss import parse_feed
from radar.timeutil import IST, ist_date


def parse(raw: bytes, feed_id: str, now: datetime) -> list[Signal]:
    today = ist_date(now)
    out = []
    for e in parse_feed(raw, default_tz=IST):
        if not e.title or e.published is None or (today - ist_date(e.published)).days > 1:
            continue
        out.append(Signal(source="regulators", source_type="regulator", feed=feed_id, title=e.title, url=e.link,
                          published_at=e.published, text=e.summary[:500]))
    return out


def collect(ctx: Context) -> list[Signal]:
    return gather([(f["id"], lambda f=f: parse(ctx.http.get(f["url"]).content, f["id"], ctx.now))
                   for f in ctx.config.sources["regulators"]])
