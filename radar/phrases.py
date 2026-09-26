"""New-phrase spike detection and emerging topics (spec section 9)."""
from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from radar.config import EMERGING_ANGLES, Config
from radar.models import Signal, Topic
from radar.text import normalize_title, slugify
from radar.timeutil import ist, ist_hour_bucket, to_iso

TOKEN_RE = re.compile(r"[\wऀ-ॿ]+(?:&[\wऀ-ॿ]+)*|[^\w\sऀ-ॿ]")
WORD_RE = re.compile(r"[\wऀ-ॿ]")
VOCAB_RE = re.compile(r"[\wऀ-ॿ]+")
TREND_TYPES = ("search_trend", "x_trend")
FINANCE_ONLY_TYPES = ("news", "video", "forum", "regulator")


@dataclass
class PhraseSpike:
    phrase: str
    item_ids: set[str]
    ratio: float
    feeds: int
    topic_id: str
    emerging: bool


def extract(title: str, source_type: str, stop: frozenset[str], blocklist: frozenset[str], min_chars: int) -> set[str]:
    """2-3 word phrases inside stopword-free chunks of a title; whole titles for trend entries."""
    text = normalize_title(title)
    chunks: list[list[str]] = []
    current: list[str] = []
    for tok in TOKEN_RE.findall(text):
        if not WORD_RE.match(tok) or tok in stop or tok.isdigit() or len(tok) <= 1:
            if current:
                chunks.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        chunks.append(current)
    phrases = {" ".join(chunk[i:i + n]) for chunk in chunks for n in (2, 3) for i in range(len(chunk) - n + 1)}
    if source_type in TREND_TYPES:
        phrases.add(text.lstrip("#"))
    return {p for p in phrases if len(p) >= min_chars and not any(b in p for b in blocklist)}


def _settings(cfg: Config) -> tuple[dict, frozenset[str], frozenset[str]]:
    p = cfg.settings["phrases"]
    return p, frozenset(p["stopwords"].split()), frozenset(p["blocklist"])


def record_counts(conn: sqlite3.Connection, new_items: list[tuple[str, Signal]], now: datetime, cfg: Config) -> None:
    """Add each new item's phrases to phrase_counts, in the IST hour it was published."""
    p, stop, block = _settings(cfg)
    counts: Counter[tuple[str, str]] = Counter()
    for _, sig in new_items:
        if sig.source_type == "market":
            continue
        hour = ist_hour_bucket(sig.published_at or now)
        for phrase in extract(sig.title, sig.source_type, stop, block, p["min_chars"]):
            counts[(hour, phrase)] += 1
    conn.executemany(
        "INSERT INTO phrase_counts (hour, phrase, items) VALUES (?, ?, ?) "
        "ON CONFLICT(hour, phrase) DO UPDATE SET items = items + excluded.items",
        [(hour, phrase, n) for (hour, phrase), n in counts.items()])


def _has_vocab(title: str, text: str, vocab: frozenset[str]) -> bool:
    return "₹" in title or not vocab.isdisjoint(VOCAB_RE.findall(f"{title} {text}".lower()))


def _baselines(conn: sqlite3.Connection, phrases: list[str], now: datetime, floor: float) -> dict[str, float]:
    """max(7-day hourly average, same-IST-hour average, floor) over the 7 days before the 2-hour window."""
    until = ist_hour_bucket(now - timedelta(hours=2))
    since = ist_hour_bucket(now - timedelta(days=7, hours=2))
    hour = ist(now).hour
    out = {ph: floor for ph in phrases}
    for start in range(0, len(phrases), 500):
        chunk = phrases[start:start + 500]
        marks = ",".join("?" * len(chunk))
        rows = conn.execute(
            "SELECT phrase, SUM(items) AS total, "
            "SUM(CASE WHEN CAST(substr(hour, 12, 2) AS INTEGER) = ? THEN items ELSE 0 END) AS same_hour "
            f"FROM phrase_counts WHERE hour >= ? AND hour < ? AND phrase IN ({marks}) GROUP BY phrase",
            (hour, since, until, *chunk))
        for r in rows:
            out[r["phrase"]] = max(r["total"] / 168.0, r["same_hour"] / 7.0, floor)
    return out


def _subsume(cands: dict[str, set[str]], share: float) -> dict[str, set[str]]:
    """Collapse phrases that describe the same items: keep the longer phrase, else the one with more items."""
    alive = set(cands)
    ordered = sorted(cands)
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            if a not in alive or b not in alive:
                continue
            sa, sb = cands[a], cands[b]
            if len(sa & sb) < share * min(len(sa), len(sb)):
                continue
            if a in b:
                alive.discard(a)
            elif b in a:
                alive.discard(b)
            elif len(sa) != len(sb):
                alive.discard(a if len(sa) < len(sb) else b)
            else:
                alive.discard(a if len(a) < len(b) else b)
    return {ph: cands[ph] for ph in alive}


def _map_topic(conn: sqlite3.Connection, ids: set[str], topics: dict[str, Topic], share: float) -> tuple[str | None, str]:
    """Static topic the phrase belongs to (or None) and the bucket to use."""
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT item_id, topic_id FROM item_topics WHERE item_id IN ({marks}) AND topic_id NOT LIKE 'emerging:%' "
        "ORDER BY item_id, topic_id", tuple(sorted(ids))).fetchall()
    per_topic = Counter(r["topic_id"] for r in rows)
    if per_topic:
        topic_id, n = per_topic.most_common(1)[0]
        if n >= share * len(ids) and topic_id in topics:
            return topic_id, topics[topic_id].bucket
    buckets = Counter(topics[r["topic_id"]].bucket for r in rows if r["topic_id"] in topics)
    return None, buckets.most_common(1)[0][0] if buckets else "markets"


def _display_name(phrase: str, titles: Iterable[str]) -> str:
    for title in titles:
        i = title.lower().find(phrase)
        if i >= 0:
            return title[i:i + len(phrase)]
    return phrase


def detect(conn: sqlite3.Connection, cfg: Config, new_items: list[tuple[str, Signal]], now: datetime) -> list[PhraseSpike]:
    """Count this run's phrases, then report phrases spiking over the last 2 hours."""
    p, stop, block = _settings(cfg)
    record_counts(conn, new_items, now, cfg)
    rows = conn.execute(
        "SELECT id, source_type, feed, title, text FROM items "
        "WHERE COALESCE(published_at, first_seen_at) >= ? AND source_type != 'market'",
        (to_iso(now - timedelta(hours=2)),)).fetchall()
    info = {r["id"]: r for r in rows}
    phrase_items: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        for phrase in extract(r["title"], r["source_type"], stop, block, p["min_chars"]):
            phrase_items[phrase].add(r["id"])
    cands = {ph: ids for ph, ids in phrase_items.items() if len(ids) >= p["min_items"]}
    base = _baselines(conn, sorted(cands), now, p["baseline_floor"])
    kept: dict[str, set[str]] = {}
    stats: dict[str, tuple[float, int]] = {}
    for ph, ids in cands.items():
        ratio = (len(ids) / 2.0) / base[ph]
        feeds = len({info[i]["feed"] for i in ids})
        if ratio < p["min_ratio"] or feeds < p["min_feeds"]:
            continue
        finance_src = sum(info[i]["source_type"] in FINANCE_ONLY_TYPES for i in ids) / len(ids)
        finance_words = sum(_has_vocab(info[i]["title"], info[i]["text"], cfg.finance_vocab) for i in ids) / len(ids)
        if max(finance_src, finance_words) < p["finance_share"]:
            continue
        kept[ph] = ids
        stats[ph] = (round(ratio, 1), feeds)
    spikes = []
    for ph, ids in sorted(_subsume(kept, p["subsume_share"]).items()):
        topic_id, bucket = _map_topic(conn, ids, cfg.topic_map, p["map_share"])
        emerging = topic_id is None
        if topic_id is None:
            topic_id = "emerging:" + slugify(ph)
            name = _display_name(ph, (info[i]["title"] for i in sorted(ids)))
            conn.execute(
                "INSERT INTO emerging_topics (topic_id, phrase, name, bucket, created_at, last_seen_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(topic_id) DO UPDATE SET last_seen_at = excluded.last_seen_at",
                (topic_id, ph, name, bucket, to_iso(now), to_iso(now)))
            conn.executemany("INSERT OR IGNORE INTO item_topics (item_id, topic_id) VALUES (?, ?)",
                             [(i, topic_id) for i in sorted(ids)])
        spikes.append(PhraseSpike(ph, set(ids), stats[ph][0], stats[ph][1], topic_id, emerging))
    conn.commit()
    return spikes


def active_emerging(conn: sqlite3.Connection, now: datetime, ttl_hours: float) -> list[Topic]:
    """Drop expired emerging topics and return the live ones as Topic objects."""
    conn.execute("DELETE FROM emerging_topics WHERE last_seen_at < ?", (to_iso(now - timedelta(hours=ttl_hours)),))
    conn.commit()
    return [Topic(id=r["topic_id"], name=r["name"], bucket=r["bucket"], keywords=(r["phrase"],),
                  angles=EMERGING_ANGLES, emerging=True)
            for r in conn.execute("SELECT topic_id, phrase, name, bucket FROM emerging_topics ORDER BY topic_id")]


def link_emerging(conn: sqlite3.Connection, new_items: list[tuple[str, Signal]], topics: list[Topic], now: datetime) -> None:
    """Tag new items whose title contains a live emerging phrase, and keep that topic alive."""
    for item_id, sig in new_items:
        title = normalize_title(sig.title)
        for topic in topics:
            if topic.keywords[0] in title:
                conn.execute("INSERT OR IGNORE INTO item_topics (item_id, topic_id) VALUES (?, ?)", (item_id, topic.id))
                conn.execute("UPDATE emerging_topics SET last_seen_at = ? WHERE topic_id = ?", (to_iso(now), topic.id))
    conn.commit()


def prune_singletons(conn: sqlite3.Connection, now: datetime) -> None:
    conn.execute("DELETE FROM phrase_counts WHERE items = 1 AND hour < ?", (ist_hour_bucket(now - timedelta(hours=3)),))
    conn.commit()
