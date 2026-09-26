"""SQLite persistence: schema, shared tables (items, item_topics, kv, source_health) and pruning.

Modules run their own SQL on `store.conn` for the tables they own (phrases, scorer, youtube).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from radar.models import Signal
from radar.text import normalize_title, sha1
from radar.timeutil import ist_hour_bucket, to_iso

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_type TEXT NOT NULL,
    feed TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    published_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    lang TEXT NOT NULL DEFAULT 'en',
    text TEXT NOT NULL DEFAULT '',
    metrics_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_items_type_seen ON items (source_type, last_seen_at);
CREATE TABLE IF NOT EXISTS item_topics (
    item_id TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    PRIMARY KEY (item_id, topic_id)
);
CREATE INDEX IF NOT EXISTS idx_item_topics_topic ON item_topics (topic_id);
CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    channel_name TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    published_at TEXT NOT NULL,
    is_short INTEGER NOT NULL,
    views INTEGER NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    outlier REAL,
    hook_type TEXT
);
CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos (channel_id);
CREATE TABLE IF NOT EXISTS runs (
    run_at TEXT PRIMARY KEY,
    ist_hour INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS topic_values (
    run_at TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (run_at, topic_id, source_type)
);
CREATE TABLE IF NOT EXISTS topic_heat (
    run_at TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    heat REAL NOT NULL,
    stage TEXT NOT NULL,
    n_sources INTEGER NOT NULL,
    PRIMARY KEY (run_at, topic_id)
);
CREATE TABLE IF NOT EXISTS episodes (
    topic_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    below_watch_runs INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    heat REAL NOT NULL,
    subject TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS phrase_counts (
    hour TEXT NOT NULL,
    phrase TEXT NOT NULL,
    items INTEGER NOT NULL,
    PRIMARY KEY (hour, phrase)
);
CREATE TABLE IF NOT EXISTS emerging_topics (
    topic_id TEXT PRIMARY KEY,
    phrase TEXT NOT NULL,
    name TEXT NOT NULL,
    bucket TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_health (
    source TEXT PRIMARY KEY,
    last_ok_at TEXT,
    last_error_at TEXT,
    last_error TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def item_id(sig: Signal) -> str:
    """Stable id per item (spec section 6, item identity)."""
    if sig.source_type == "news":
        return sha1("news", normalize_title(sig.title))
    if sig.source_type == "video":
        return "yt:" + sig.key
    if sig.source_type in ("search_trend", "x_trend"):
        return sha1(sig.source_type, normalize_title(sig.title))
    if sig.source_type == "market":
        return sha1("market", sig.key)
    return sha1(sig.source_type, sig.key or sig.url or normalize_title(sig.title))


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        try:
            self._open()
        except sqlite3.DatabaseError:
            log.warning("database %s is unreadable; starting a fresh one", self.path.name)
            self.conn.close()
            self.path.replace(self.path.with_name(self.path.name + ".corrupt"))
            self._open()

    def _open(self) -> None:
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    def add_items(self, signals: Iterable[Signal], now: datetime) -> list[tuple[str, Signal]]:
        """Insert unseen items; refresh title, metrics and last_seen_at of known ones. Returns the new ones."""
        now_iso = to_iso(now)
        new: list[tuple[str, Signal]] = []
        seen: set[str] = set()
        for sig in signals:
            iid = item_id(sig)
            if iid in seen:
                continue
            seen.add(iid)
            metrics = json.dumps(sig.metrics, sort_keys=True)
            updated = self.conn.execute(
                "UPDATE items SET title = ?, metrics_json = ?, last_seen_at = ? WHERE id = ?",
                (sig.title, metrics, now_iso, iid)).rowcount
            if updated:
                continue
            self.conn.execute(
                "INSERT INTO items (id, source, source_type, feed, title, url, published_at, first_seen_at, "
                "last_seen_at, lang, text, metrics_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (iid, sig.source, sig.source_type, sig.feed, sig.title, sig.url,
                 to_iso(sig.published_at) if sig.published_at else None, now_iso, now_iso,
                 sig.lang, sig.text, metrics))
            new.append((iid, sig))
        self.conn.commit()
        return new

    def add_item_topics(self, item_id: str, topic_ids: Iterable[str]) -> None:
        self.conn.executemany("INSERT OR IGNORE INTO item_topics (item_id, topic_id) VALUES (?, ?)",
                              [(item_id, t) for t in topic_ids])
        self.conn.commit()

    def get_kv(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_kv(self, key: str, value: str) -> None:
        self.conn.execute("INSERT INTO kv (key, value) VALUES (?, ?) "
                          "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
        self.conn.commit()

    def record_health(self, source: str, error: str | None, now: datetime) -> None:
        now_iso = to_iso(now)
        if error is None:
            self.conn.execute(
                "INSERT INTO source_health (source, last_ok_at, consecutive_failures) VALUES (?, ?, 0) "
                "ON CONFLICT(source) DO UPDATE SET last_ok_at = excluded.last_ok_at, consecutive_failures = 0",
                (source, now_iso))
        else:
            self.conn.execute(
                "INSERT INTO source_health (source, last_error_at, last_error, consecutive_failures) "
                "VALUES (?, ?, ?, 1) ON CONFLICT(source) DO UPDATE SET last_error_at = excluded.last_error_at, "
                "last_error = excluded.last_error, consecutive_failures = source_health.consecutive_failures + 1",
                (source, now_iso, error[:300]))
        self.conn.commit()

    def health_rows(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM source_health ORDER BY source").fetchall()

    def prune(self, now: datetime, retention: dict) -> None:
        items_cut = to_iso(now - timedelta(days=retention["items_days"]))
        history = now - timedelta(days=retention["history_days"])
        self.conn.execute("DELETE FROM item_topics WHERE item_id IN (SELECT id FROM items WHERE last_seen_at < ?)",
                          (items_cut,))
        self.conn.execute("DELETE FROM items WHERE last_seen_at < ?", (items_cut,))
        for table in ("runs", "topic_values", "topic_heat"):
            self.conn.execute(f"DELETE FROM {table} WHERE run_at < ?", (to_iso(history),))
        self.conn.execute("DELETE FROM phrase_counts WHERE hour < ?", (ist_hour_bucket(history),))
        self.conn.execute("DELETE FROM videos WHERE published_at < ?",
                          (to_iso(now - timedelta(days=retention["videos_days"])),))
        self.conn.execute("DELETE FROM alerts WHERE sent_at < ?",
                          (to_iso(now - timedelta(days=retention["alerts_days"])),))
        self.conn.commit()
