"""Indian finance YouTube channels via channel RSS (no API key): views, Shorts, outlier scores."""
from __future__ import annotations

import math
import sqlite3
import statistics
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta

from radar import hooks
from radar.collectors import Context, gather
from radar.models import Signal
from radar.text import clean
from radar.timeutil import from_iso, parse_date, to_iso

ATOM = "{http://www.w3.org/2005/Atom}"
YT = "{http://www.youtube.com/xml/schemas/2015}"
MEDIA = "{http://search.yahoo.com/mrss/}"


def parse(raw: bytes, channel_id: str) -> list[Signal]:
    out = []
    for e in ET.fromstring(raw).findall(f"{ATOM}entry"):
        video_id = e.findtext(f"{YT}videoId")
        published = parse_date(e.findtext(f"{ATOM}published"))
        if not video_id or published is None:
            continue
        link = e.find(f"{ATOM}link")
        url = link.get("href") if link is not None else f"https://www.youtube.com/watch?v={video_id}"
        stats = e.find(f"{MEDIA}group/{MEDIA}community/{MEDIA}statistics")
        out.append(Signal(
            source="youtube", source_type="video", feed=f"yt:{channel_id}",
            title=clean(e.findtext(f"{ATOM}title")), url=url, published_at=published,
            text=clean(e.findtext(f"{MEDIA}group/{MEDIA}description"))[:300],
            metrics={"views": float(stats.get("views", 0)) if stats is not None else 0.0,
                     "is_short": 1.0 if "/shorts/" in url else 0.0},
            key=video_id))
    return out


def rotation(channels, run_index: int, groups: int) -> list[dict]:
    return [c for i, c in enumerate(channels) if i % groups == run_index % groups]


def collect(ctx: Context) -> list[Signal]:
    groups = ctx.config.settings["youtube"]["rotation_groups"]
    template = ctx.config.sources["youtube"]["rss_template"]
    return gather([(c["id"], lambda c=c: parse(ctx.http.get(template.format(id=c["id"])).content, c["id"]))
                   for c in rotation(ctx.config.channels, ctx.run_index, groups)])


def maturity(age_hours: float) -> float:
    """Share of its 72-hour views a video typically has at this age (heuristic, spec section 7)."""
    return min(1.0, max(0.15, math.sqrt(max(age_hours, 0.0) / 72.0)))


def _samples(conn: sqlite3.Connection, channel_id: str, min_age_hours: float) -> list[tuple[str, bool, float]]:
    """(video_id, is_short, projected 72-hour views) for the channel's videos last seen at a usable age."""
    out = []
    for r in conn.execute("SELECT video_id, is_short, views, published_at, last_seen_at FROM videos "
                          "WHERE channel_id = ?", (channel_id,)):
        age = (from_iso(r["last_seen_at"]) - from_iso(r["published_at"])).total_seconds() / 3600
        if age >= min_age_hours:
            out.append((r["video_id"], bool(r["is_short"]), r["views"] / maturity(age)))
    return out


def _baseline(samples: list[tuple[str, bool, float]], exclude: str, is_short: bool, minimum: int) -> float | None:
    same = [v for vid, short, v in samples if vid != exclude and short == is_short]
    if len(same) >= minimum:
        return statistics.median(same)
    pool = [v for vid, _, v in samples if vid != exclude]
    return statistics.median(pool) if len(pool) >= minimum else None


def update_videos(conn: sqlite3.Connection, signals: list[Signal], channel_names: dict[str, str],
                  now: datetime, settings: dict) -> list[Signal]:
    """Store fetched videos, score recent ones, and return signals for videos inside the track window."""
    yt = settings["youtube"]
    now_iso = to_iso(now)
    by_channel: dict[str, list[Signal]] = defaultdict(list)
    for s in signals:
        channel_id = s.feed.removeprefix("yt:")
        by_channel[channel_id].append(s)
        conn.execute(
            "INSERT INTO videos (video_id, channel_id, channel_name, title, url, published_at, is_short, views, "
            "first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(video_id) DO UPDATE SET "
            "title = excluded.title, views = excluded.views, last_seen_at = excluded.last_seen_at",
            (s.key, channel_id, channel_names.get(channel_id, channel_id), s.title, s.url, to_iso(s.published_at),
             int(s.metrics["is_short"]), int(s.metrics["views"]), now_iso, now_iso))
    track_since = now - timedelta(hours=yt["track_hours"])
    tracked: list[Signal] = []
    for channel_id, sigs in by_channel.items():
        samples = _samples(conn, channel_id, yt["min_sample_age_hours"])
        recent = sorted((s for s in sigs if s.published_at >= track_since),
                        key=lambda s: s.published_at, reverse=True)[: yt["per_channel_track"]]
        for s in recent:
            age_h = (now - s.published_at).total_seconds() / 3600
            base = _baseline(samples, s.key, bool(s.metrics["is_short"]), yt["min_baseline_samples"])
            outlier = round(s.metrics["views"] / (base * maturity(age_h)), 2) if base else None
            conn.execute("UPDATE videos SET outlier = ?, hook_type = ? WHERE video_id = ?",
                         (outlier, hooks.classify(s.title), s.key))
            s.metrics.update({"age_h": round(age_h, 1), "outlier": outlier or 0.0})
            tracked.append(s)
    conn.commit()
    return tracked
