"""Per-topic values, baselines, heat, stages and alert decisions (spec section 10)."""
from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from radar.models import Topic, TopicScore
from radar.timeutil import from_iso, ist, ist_day_start_utc, to_iso

Z_SOURCES = ("news", "video", "forum")


def baseline(samples: list[float], n_runs: int, mu0: float, sigma0: float, prior_weight: float) -> tuple[float, float]:
    """Mean and std over n_runs (runs without a sample count as zero), shrunk toward the priors."""
    n = max(n_runs, len(samples))
    if n:
        m = sum(samples) / n
        v = max(sum(x * x for x in samples) / n - m * m, 0.0)
    else:
        m = v = 0.0
    mu = (n * m + prior_weight * mu0) / (n + prior_weight)
    var = (n * v + prior_weight * sigma0 ** 2) / (n + prior_weight)
    return mu, math.sqrt(var)


def z_score(value: float, mu: float, sigma: float, floor: float, min_value: float) -> float:
    if value < min_value:
        return 0.0
    return (value - mu) / max(sigma, floor)


def search_points(traffic: float, table: list[list[float]]) -> float:
    for threshold, points in table:
        if traffic >= threshold:
            return float(points)
    return 0.0


def x_points(rank: float, table: list[list[float]]) -> float:
    for max_rank, points in table:
        if rank <= max_rank:
            return float(points)
    return 0.0


def heat_of(z: dict[str, float], bonuses: dict[str, float], weights: dict[str, float], clip: float) -> tuple[float, int]:
    heat = sum(weights[s] * min(max(z.get(s, 0.0), 0.0), clip) for s in Z_SOURCES) + sum(bonuses.values())
    n_sources = sum(1 for s in Z_SOURCES if z.get(s, 0.0) >= 2) + sum(1 for b in bonuses.values() if b > 0)
    return round(heat, 2), n_sources


@dataclass
class Episode:
    started_at: datetime | None = None
    below_watch_runs: int = 0


def next_episode(ep: Episode, heat: float, now: datetime, watch: float, end_runs: int) -> Episode:
    if ep.started_at is None:
        return Episode(now, 0) if heat >= watch else ep
    below = ep.below_watch_runs + 1 if heat < watch else 0
    return Episode() if below >= end_runs else Episode(ep.started_at, below)


def stage_of(heat: float, prev1: float, prev2: float, ep: Episode, now: datetime, watch: float,
             emerging_hours: float) -> str:
    if ep.started_at is None:
        return "Quiet"
    if heat < watch or heat < prev1 < prev2:
        return "Fading"
    if heat >= prev1 and now - ep.started_at <= timedelta(hours=emerging_hours):
        return "Emerging"
    return "Peaking"


def alert_kind(score: TopicScore, last_alert: tuple[datetime, float] | None, sent_today: int, now: datetime,
               settings: dict) -> str | None:
    """'hot', 'capped' or None for one topic (spec section 10, HOT alert rule)."""
    sc, al = settings["scoring"], settings["alerts"]
    if score.heat < sc["hot_threshold"] or score.heat < score.prev_heat:
        return None
    if score.n_sources < 2 and max(score.bonuses.values(), default=0.0) < 3:
        return None
    if score.stage not in ("Emerging", "Peaking"):
        return None
    if last_alert is not None:
        at, heat_then = last_alert
        if now - at < timedelta(hours=al["cooldown_hours"]) and score.heat < 2 * heat_then:
            return None
    return "capped" if sent_today >= al["daily_cap"] else "hot"


def compute_values(conn: sqlite3.Connection, now: datetime, run_at: str, settings: dict) -> dict[str, dict[str, float]]:
    yt = settings["youtube"]
    values: dict[str, dict[str, float]] = defaultdict(dict)
    for r in conn.execute(
            "SELECT it.topic_id AS t, COUNT(*) AS n FROM items i JOIN item_topics it ON it.item_id = i.id "
            "WHERE i.source_type = 'news' AND COALESCE(i.published_at, i.first_seen_at) >= ? GROUP BY it.topic_id",
            (to_iso(now - timedelta(minutes=60)),)):
        values[r["t"]]["news"] = float(r["n"])
    for r in conn.execute(
            "SELECT it.topic_id AS t, COUNT(*) AS n FROM items i JOIN item_topics it ON it.item_id = i.id "
            "WHERE i.source_type = 'forum' AND i.last_seen_at = ? GROUP BY it.topic_id", (run_at,)):
        values[r["t"]]["forum"] = float(r["n"])
    for r in conn.execute(
            "SELECT it.topic_id AS t, SUM(MIN(v.outlier, ?)) AS s FROM videos v "
            "JOIN item_topics it ON it.item_id = 'yt:' || v.video_id "
            "WHERE v.published_at >= ? AND v.outlier >= ? GROUP BY it.topic_id",
            (yt["outlier_cap"], to_iso(now - timedelta(hours=yt["signal_max_age_hours"])), yt["outlier_min_signal"])):
        values[r["t"]]["video"] = round(float(r["s"]), 2)
    return values


def compute_bonuses(conn: sqlite3.Connection, now: datetime, run_at: str, settings: dict) -> dict[str, dict[str, float]]:
    sc = settings["scoring"]
    table = sc["bonus"]
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for r in conn.execute(
            "SELECT it.topic_id AS t, MAX(json_extract(i.metrics_json, '$.approx_traffic')) AS v FROM items i "
            "JOIN item_topics it ON it.item_id = i.id WHERE i.source_type = 'search_trend' AND i.last_seen_at = ? "
            "GROUP BY it.topic_id", (run_at,)):
        out[r["t"]]["search_trend"] = search_points(r["v"] or 0.0, table["search_trend"])
    for r in conn.execute(
            "SELECT it.topic_id AS t, MIN(json_extract(i.metrics_json, '$.rank')) AS v FROM items i "
            "JOIN item_topics it ON it.item_id = i.id WHERE i.source_type = 'x_trend' AND i.last_seen_at >= ? "
            "GROUP BY it.topic_id", (to_iso(now - timedelta(minutes=sc["x_trend_max_age_minutes"])),)):
        out[r["t"]]["x_trend"] = x_points(r["v"] or 99.0, table["x_trend"])
    window = to_iso(now - timedelta(hours=sc["bonus_window_hours"]))
    for r in conn.execute(
            "SELECT it.topic_id AS t, MAX(ABS(json_extract(i.metrics_json, '$.pct_move')) "
            "/ json_extract(i.metrics_json, '$.threshold')) AS v FROM items i JOIN item_topics it ON it.item_id = i.id "
            "WHERE i.source_type = 'market' AND i.first_seen_at >= ? GROUP BY it.topic_id", (window,)):
        out[r["t"]]["market"] = float(table["market"]["double"] if (r["v"] or 0) >= 2 else table["market"]["base"])
    for r in conn.execute(
            "SELECT DISTINCT it.topic_id AS t FROM items i JOIN item_topics it ON it.item_id = i.id "
            "WHERE i.source_type = 'regulator' AND i.first_seen_at >= ?", (window,)):
        out[r["t"]]["regulator"] = float(table["regulator"])
    return out


def window_samples(conn: sqlite3.Connection, now: datetime, settings: dict) -> tuple[int, dict[tuple[str, str], list[float]]]:
    """Runs in the last 7 days whose IST hour is within +-1 of now, and the non-zero values they stored."""
    sc = settings["scoring"]
    hour = ist(now).hour
    hours = sorted({(hour + d) % 24 for d in range(-sc["hour_window"], sc["hour_window"] + 1)})
    marks = ",".join("?" * len(hours))
    where = f"run_at >= ? AND run_at < ? AND ist_hour IN ({marks})"
    params = (to_iso(now - timedelta(days=sc["baseline_days"])), to_iso(now), *hours)
    n_runs = conn.execute(f"SELECT COUNT(*) FROM runs WHERE {where}", params).fetchone()[0]
    samples: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in conn.execute(f"SELECT topic_id, source_type, value FROM topic_values "
                          f"WHERE run_at IN (SELECT run_at FROM runs WHERE {where})", params):
        samples[(r["topic_id"], r["source_type"])].append(r["value"])
    return n_runs, samples


def _save_episode(conn: sqlite3.Connection, topic_id: str, ep: Episode) -> None:
    if ep.started_at is None:
        conn.execute("DELETE FROM episodes WHERE topic_id = ?", (topic_id,))
    else:
        conn.execute(
            "INSERT INTO episodes (topic_id, started_at, below_watch_runs) VALUES (?, ?, ?) ON CONFLICT(topic_id) "
            "DO UPDATE SET started_at = excluded.started_at, below_watch_runs = excluded.below_watch_runs",
            (topic_id, to_iso(ep.started_at), ep.below_watch_runs))


def score_run(conn: sqlite3.Connection, topics: list[Topic], now: datetime, settings: dict) -> list[TopicScore]:
    """Score every topic for this run, persist history, and return the topics with heat or an open episode."""
    sc = settings["scoring"]
    run_at = to_iso(now)
    n_runs, samples = window_samples(conn, now, settings)
    prev_runs = [r[0] for r in conn.execute("SELECT run_at FROM runs WHERE run_at < ? ORDER BY run_at DESC LIMIT 2",
                                            (run_at,))]
    conn.execute("INSERT OR IGNORE INTO runs (run_at, ist_hour) VALUES (?, ?)", (run_at, ist(now).hour))
    values = compute_values(conn, now, run_at, settings)
    bonuses = compute_bonuses(conn, now, run_at, settings)
    prev: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for i, past in enumerate(prev_runs):
        for r in conn.execute("SELECT topic_id, heat FROM topic_heat WHERE run_at = ?", (past,)):
            prev[r["topic_id"]][i] = r["heat"]
    episodes = {r["topic_id"]: Episode(from_iso(r["started_at"]), r["below_watch_runs"])
                for r in conn.execute("SELECT topic_id, started_at, below_watch_runs FROM episodes")}
    weights = {s: sc["sources"][s]["weight"] for s in Z_SOURCES}
    scores = []
    for topic in topics:
        vals = values.get(topic.id, {})
        z: dict[str, float] = {}
        mu: dict[str, float] = {}
        for s in Z_SOURCES:
            cfg = dict(sc["sources"][s])
            if topic.emerging and s == "news":
                cfg.update(sc["emerging_news_prior"])
            m, sd = baseline(samples.get((topic.id, s), []), n_runs, cfg["mu0"], cfg["sigma0"], sc["prior_weight"])
            mu[s] = round(m, 2)
            z[s] = round(z_score(vals.get(s, 0.0), m, sd, cfg["floor"], cfg["min_value"]), 2)
        bon = dict(bonuses.get(topic.id, {}))
        heat, n_sources = heat_of(z, bon, weights, sc["z_clip"])
        ep = next_episode(episodes.get(topic.id, Episode()), heat, now, sc["watch_threshold"], sc["episode_end_runs"])
        p1, p2 = prev[topic.id]
        stage = stage_of(heat, p1, p2, ep, now, sc["watch_threshold"], sc["emerging_stage_hours"])
        _save_episode(conn, topic.id, ep)
        for source, value in vals.items():
            if value:
                conn.execute("INSERT OR REPLACE INTO topic_values (run_at, topic_id, source_type, value) "
                             "VALUES (?, ?, ?, ?)", (run_at, topic.id, source, value))
        if heat > 0:
            conn.execute("INSERT OR REPLACE INTO topic_heat (run_at, topic_id, heat, stage, n_sources) "
                         "VALUES (?, ?, ?, ?, ?)", (run_at, topic.id, heat, stage, n_sources))
        if heat > 0 or stage != "Quiet":
            scores.append(TopicScore(topic.id, heat, stage, n_sources, values=dict(vals), z=z, mu=mu,
                                     bonuses=bon, prev_heat=p1))
    conn.commit()
    return scores


def decide_alerts(conn: sqlite3.Connection, scores: list[TopicScore], now: datetime,
                  settings: dict) -> list[tuple[TopicScore, str]]:
    """Apply the alert rule to all scores, hottest first, respecting the daily cap."""
    sent_today = conn.execute("SELECT COUNT(*) FROM alerts WHERE kind = 'hot' AND sent_at >= ?",
                              (to_iso(ist_day_start_utc(now)),)).fetchone()[0]
    decisions = []
    for score in sorted(scores, key=lambda s: s.heat, reverse=True):
        row = conn.execute("SELECT sent_at, heat FROM alerts WHERE topic_id = ? ORDER BY sent_at DESC LIMIT 1",
                           (score.topic_id,)).fetchone()
        kind = alert_kind(score, (from_iso(row["sent_at"]), row["heat"]) if row else None, sent_today, now, settings)
        if kind:
            decisions.append((score, kind))
        if kind == "hot":
            sent_today += 1
    return decisions


def record_alert(conn: sqlite3.Connection, topic_id: str, kind: str, now: datetime, heat: float, subject: str) -> None:
    conn.execute("INSERT INTO alerts (topic_id, kind, sent_at, heat, subject) VALUES (?, ?, ?, ?, ?)",
                 (topic_id, kind, to_iso(now), heat, subject))
    conn.commit()
