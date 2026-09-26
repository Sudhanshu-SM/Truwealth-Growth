"""Collect the data for the daily digest email (spec section 12)."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from radar import events as events_mod
from radar import hooks
from radar.config import BUCKETS, Config
from radar.models import Topic
from radar.phrases import active_emerging
from radar.timeutil import from_iso, ist, ist_date, to_iso


@dataclass
class DigestData:
    date_label: str
    top: list[dict] = field(default_factory=list)
    near_misses: list[dict] = field(default_factory=list)
    scoreboard: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    health: list[str] = field(default_factory=list)


def topic_catalog(conn: sqlite3.Connection, cfg: Config, now: datetime) -> dict[str, Topic]:
    """Static topics plus the live emerging ones."""
    catalog = dict(cfg.topic_map)
    for topic in active_emerging(conn, now, cfg.settings["phrases"]["emerging_ttl_hours"]):
        catalog[topic.id] = topic
    return catalog


def _label(catalog: dict[str, Topic], topic_id: str) -> tuple[str, str]:
    topic = catalog.get(topic_id)
    if topic:
        return topic.name, BUCKETS.get(topic.bucket, "Emerging")
    return topic_id.removeprefix("emerging:").replace("-", " ").capitalize(), "Emerging"


def build_digest(conn: sqlite3.Connection, cfg: Config, now: datetime) -> DigestData:
    d = cfg.settings["digest"]
    since = to_iso(now - timedelta(hours=24))
    catalog = topic_catalog(conn, cfg, now)
    peaks = conn.execute("SELECT topic_id, MAX(heat) AS peak FROM topic_heat WHERE run_at >= ? "
                         "GROUP BY topic_id ORDER BY peak DESC, topic_id", (since,)).fetchall()
    last_run = conn.execute("SELECT MAX(run_at) FROM runs").fetchone()[0]
    current = {r["topic_id"]: r["stage"]
               for r in conn.execute("SELECT topic_id, stage FROM topic_heat WHERE run_at = ?", (last_run,))}
    status: dict[str, str] = {}
    for r in conn.execute("SELECT topic_id, kind FROM alerts WHERE sent_at >= ? ORDER BY sent_at", (since,)):
        status[r["topic_id"]] = "sent" if r["kind"] == "hot" or status.get(r["topic_id"]) == "sent" else "capped"

    data = DigestData(date_label=ist(now).strftime("%d %b"))
    for r in peaks[: d["top_n"]]:
        name, bucket = _label(catalog, r["topic_id"])
        head = conn.execute(
            "SELECT i.title, i.url FROM items i JOIN item_topics it ON it.item_id = i.id "
            "WHERE it.topic_id = ? AND i.first_seen_at >= ? "
            "ORDER BY CASE i.source_type WHEN 'news' THEN 0 ELSE 1 END, i.first_seen_at DESC LIMIT 1",
            (r["topic_id"], since)).fetchone()
        data.top.append({"name": name, "bucket": bucket, "peak": round(r["peak"], 1),
                         "stage": current.get(r["topic_id"], "Quiet"), "status": status.get(r["topic_id"], "none"),
                         "evidence": head["title"] if head else "", "url": head["url"] if head else None})
    for r in peaks:
        if r["peak"] >= cfg.settings["scoring"]["watch_threshold"] and status.get(r["topic_id"]) != "sent":
            name, bucket = _label(catalog, r["topic_id"])
            data.near_misses.append({"name": name, "bucket": bucket, "peak": round(r["peak"], 1)})
    data.near_misses = data.near_misses[: d["near_miss_n"]]
    data.scoreboard = hooks.scoreboard(conn, now)[: d["scoreboard_n"]]
    for e in events_mod.upcoming(cfg.events, ist_date(now), d["events_days"]):
        label = e["date"].strftime("%d %b") + (f" to {e['date_end'].strftime('%d %b')}" if e.get("date_end") else "")
        ideas = [cfg.angles[a].name for a in cfg.topic_map[e["topic"]].angles[:2]]
        data.events.append({"date": label, "name": e["name"], "angles": ideas})
    stale = now - timedelta(hours=d["health_stale_hours"])
    for r in conn.execute("SELECT * FROM source_health ORDER BY source"):
        last_ok = from_iso(r["last_ok_at"]) if r["last_ok_at"] else None
        if r["consecutive_failures"] and (last_ok is None or last_ok < stale):
            when = ist(last_ok).strftime("%d %b %H:%M IST") if last_ok else "never succeeded"
            data.health.append(f"{r['source']}: failing, last success {when} ({r['last_error']})")
    if not data.health:
        data.health.append("All sources OK")
    return data
