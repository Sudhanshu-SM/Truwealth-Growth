"""Assemble the brief for one topic (spec section 11)."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta

from radar.config import Config
from radar.models import Brief, Topic, TopicScore
from radar.timeutil import from_iso, ist, to_iso

STAGE_BOOST = {
    "Emerging": {"hot_take_news", "explainer", "before_after_rule"},
    "Peaking": {"myth_bust", "data_compare", "contrarian_take", "mistakes_list"},
}


def select_angles(topic: Topic, stage: str, multipliers: dict[str, float], n: int = 3) -> list[str]:
    boosted = STAGE_BOOST.get(stage, set())

    def rank(item: tuple[int, str]) -> tuple[float, int]:
        index, angle = item
        return -(multipliers.get(angle, 1.0) * (1.3 if angle in boosted else 1.0)), index

    return [angle for _, angle in sorted(enumerate(topic.angles), key=rank)[:n]]


def fill_hook(hook: str, topic: str, headline: str) -> str:
    """Fill a hook template; drop the template's '.' when the headline already ends a sentence."""
    return re.sub(r"([?!.])\.", r"\1", hook.format(topic=topic, headline=headline))


def format_traffic(n: float) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:g}M+"
    if n >= 1_000:
        return f"{n / 1_000:g}K+"
    return f"{int(n)}+"


def _items(conn: sqlite3.Connection, topic_id: str, source_type: str, where: str, params: tuple) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT i.* FROM items i JOIN item_topics it ON it.item_id = i.id "
        f"WHERE it.topic_id = ? AND i.source_type = ? AND {where}", (topic_id, source_type, *params)).fetchall()


def build_brief(conn: sqlite3.Connection, cfg: Config, topic: Topic, score: TopicScore, now: datetime,
                multipliers: dict[str, float], spiking_phrases: list[str]) -> Brief:
    s = cfg.settings
    run_at = to_iso(now)
    window = (to_iso(now - timedelta(hours=s["scoring"]["bonus_window_hours"])),)
    news = _items(conn, topic.id, "news", "COALESCE(i.published_at, i.first_seen_at) >= ? "
                  "ORDER BY COALESCE(i.published_at, i.first_seen_at) DESC", window)
    trends = _items(conn, topic.id, "search_trend", "i.last_seen_at = ? "
                    "ORDER BY json_extract(i.metrics_json, '$.approx_traffic') DESC", (run_at,))
    xs = _items(conn, topic.id, "x_trend", "i.last_seen_at >= ? ORDER BY json_extract(i.metrics_json, '$.rank')",
                (to_iso(now - timedelta(minutes=s["scoring"]["x_trend_max_age_minutes"])),))
    forum = _items(conn, topic.id, "forum", "i.last_seen_at = ?", (run_at,))
    market = _items(conn, topic.id, "market", "i.first_seen_at >= ? ORDER BY i.first_seen_at DESC", window)
    regs = _items(conn, topic.id, "regulator", "i.first_seen_at >= ? ORDER BY i.first_seen_at DESC", window)
    videos = conn.execute(
        "SELECT v.* FROM videos v JOIN item_topics it ON it.item_id = 'yt:' || v.video_id "
        "WHERE it.topic_id = ? AND v.published_at >= ? AND v.outlier >= ? ORDER BY v.outlier DESC LIMIT 3",
        (topic.id, to_iso(now - timedelta(hours=s["youtube"]["hooks_now_hours"])),
         s["youtube"]["hooks_now_min"])).fetchall()

    evidence: list[tuple[str, str | None]] = []
    if trends:
        t = trends[0]
        traffic = json.loads(t["metrics_json"]).get("approx_traffic", 0)
        since = f", trending since {ist(from_iso(t['published_at'])).strftime('%H:%M')} IST" if t["published_at"] else ""
        evidence.append((f"Google Trends India: '{t['title']}' {format_traffic(traffic)} searches{since}", t["url"]))
    hour_ago = to_iso(now - timedelta(minutes=60))
    recent = [n for n in news if (n["published_at"] or n["first_seen_at"]) >= hour_ago]
    if recent:
        noun = "article" if len(recent) == 1 else "articles"
        evidence.append((f"News: {len(recent)} {noun} in the last hour (normally about {score.mu.get('news', 0):.0f})",
                         recent[0]["url"]))
    if xs:
        rank = int(json.loads(xs[0]["metrics_json"]).get("rank", 0))
        evidence.append((f"X India trending: {xs[0]['title']}, rank {rank}", xs[0]["url"]))
    if videos:
        v = videos[0]
        fmt = "Short" if v["is_short"] else "Long"
        evidence.append((f"YouTube: '{v['title']}' by {v['channel_name']}, {v['outlier']:.1f}x their normal views ({fmt})",
                         v["url"]))
    if forum:
        subs = ", ".join(sorted({f["feed"] for f in forum}))
        evidence.append((f"Reddit: {len(forum)} posts rising in {subs}", forum[0]["url"]))
    if market:
        evidence.append((f"Market: {market[0]['title']}", market[0]["url"]))
    if regs:
        evidence.append((f"Regulator: {regs[0]['feed'].upper()}, {regs[0]['title']}", regs[0]["url"]))

    if news:
        headline, headline_url = news[0]["title"], news[0]["url"]
    elif trends:
        headline, headline_url = trends[0]["title"], trends[0]["url"]
    elif xs:
        headline, headline_url = xs[0]["title"], xs[0]["url"]
    else:
        headline, headline_url = topic.name, None

    angles = []
    for angle_id in select_angles(topic, score.stage, multipliers):
        a = cfg.angles[angle_id]
        angles.append({"name": a.name, "linkedin": a.formats["linkedin"], "x": a.formats["x"],
                       "instagram": a.formats["instagram"], "hook": fill_hook(a.hooks[0], topic.name, headline)})
    hooks_now = [{"title": v["title"], "creator": v["channel_name"], "format": "Short" if v["is_short"] else "Long",
                  "score": f"{v['outlier']:.1f}x", "url": v["url"]} for v in videos]
    urgency = f"post within {s['alerts']['urgency_hours'].get(score.stage, 1)}h"
    return Brief(topic=topic, score=score, urgency=urgency, headline=headline, headline_url=headline_url,
                 evidence=evidence[:6], phrases=spiking_phrases, angles=angles, hooks_now=hooks_now)
