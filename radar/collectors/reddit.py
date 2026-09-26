"""Reddit 'rising' RSS for Indian finance subreddits. Best-effort: Reddit often blocks cloud IPs."""
from __future__ import annotations

import logging
import time

import httpx

from radar.collectors import Context
from radar.models import Signal
from radar.rss import parse_feed

log = logging.getLogger(__name__)


def parse(raw: bytes, sub: str) -> list[Signal]:
    return [Signal(source="reddit", source_type="forum", feed=f"r/{sub}", title=e.title, url=e.link,
                   published_at=e.published, text=e.summary[:500], metrics={"rising_rank": float(rank)}, key=e.guid)
            for rank, e in enumerate(parse_feed(raw), start=1) if e.title]


def collect(ctx: Context) -> list[Signal]:
    cfg = ctx.config.sources["reddit"]
    spacing = ctx.config.settings["reddit"]["spacing_seconds"]
    out: list[Signal] = []
    failures = 0
    for i, sub in enumerate(cfg["subreddits"]):
        if i:
            time.sleep(spacing)
        try:
            out.extend(parse(ctx.http.get(cfg["url_template"].format(sub=sub)).content, sub))
        except httpx.HTTPStatusError as exc:
            failures += 1
            if exc.response.status_code == 429:
                log.warning("reddit rate-limited; skipping the rest of this run")
                break
        except httpx.TransportError:
            failures += 1
            log.warning("reddit unreachable; skipping the rest of this run")
            break
    if failures and not out:
        raise RuntimeError(f"reddit: {failures} fetch(es) failed and nothing was collected")
    return out
