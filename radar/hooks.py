"""Classify video titles into angle types and build the format scoreboard (spec section 11)."""
from __future__ import annotations

import re
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from radar.timeutil import to_iso

RULES: list[tuple[str, re.Pattern[str]]] = [
    ("red_flags", re.compile(r"red flags?|beware|warning|fraud|scam|dhokha|savdhan", re.I)),
    ("mistakes_list", re.compile(r"mistakes?|galti|avoid|never do|don'?t|mat karo", re.I)),
    ("myth_bust", re.compile(r"\bmyths?\b|\btruth\b|\bsach\b|\breality\b|\blies?\b", re.I)),
    ("data_compare", re.compile(r"\bvs\.?(?!\w)|versus|compar|better than", re.I)),
    ("before_after_rule", re.compile(r"new (?:\w+ )?rules?|naya niyam|rule change|niyam badal", re.I)),
    ("hot_take_news", re.compile(r"breaking|just in|big news|announced|badi khabar", re.I)),
    ("history_lesson", re.compile(r"history|last time|since (?:19|20)\d\d|years of data|\d+ saal", re.I)),
    ("what_if_calculator", re.compile(
        r"(?:(?:₹|\brs\.?|\binr)\s?[\d,.]+|\b\d+\s?(?:lakh|crore|k)\b).{0,40}?(?:month|year|salary|sip|emi|per)"
        r"|calculat|kitna", re.I)),
    ("should_you", re.compile(r"should (?:you|i)\b|kya .{0,30}chahiye|worth it|right time", re.I)),
    ("contrarian_take", re.compile(r"unpopular|nobody tells|no one tells|overrated|\bwrong\b", re.I)),
    ("checklist", re.compile(r"checklist|\bsteps\b|things to|\btips\b|before you", re.I)),
    ("faq", re.compile(r"questions|\bfaq\b|\basked\b|answered|sawal", re.I)),
    ("explainer", re.compile(r"explained|what is|kya hai|how .{0,20}works|kaise|basics|guide", re.I)),
    ("timeline", re.compile(r"what happened|timeline|story of|full story", re.I)),
]


def classify(title: str) -> str:
    for name, pattern in RULES:
        if pattern.search(title):
            return name
    return "other"


def _rows(conn: sqlite3.Connection, now: datetime, days: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT hook_type, is_short, outlier, title FROM videos WHERE published_at >= ? "
        "AND outlier IS NOT NULL AND hook_type IS NOT NULL AND hook_type != 'other'",
        (to_iso(now - timedelta(days=days)),)).fetchall()


def scoreboard(conn: sqlite3.Connection, now: datetime, days: int = 7, min_videos: int = 3) -> list[dict]:
    """Median outlier score per angle type and format over the last `days`, best first."""
    groups: dict[tuple[str, int], list[tuple[float, str]]] = defaultdict(list)
    for r in _rows(conn, now, days):
        groups[(r["hook_type"], r["is_short"])].append((r["outlier"], r["title"]))
    board = []
    for (hook, is_short), vals in groups.items():
        if len(vals) < min_videos:
            continue
        vals.sort(key=lambda v: v[0], reverse=True)
        board.append({"angle": hook, "format": "Short" if is_short else "Long",
                      "median": round(statistics.median(v[0] for v in vals), 2),
                      "count": len(vals), "example": vals[0][1]})
    return sorted(board, key=lambda b: b["median"], reverse=True)


def angle_multipliers(conn: sqlite3.Connection, now: datetime, days: int = 7, min_videos: int = 3) -> dict[str, float]:
    """Median outlier score per angle type across both formats (used to rank angles in briefs)."""
    groups: dict[str, list[float]] = defaultdict(list)
    for r in _rows(conn, now, days):
        groups[r["hook_type"]].append(r["outlier"])
    return {hook: statistics.median(v) for hook, v in groups.items() if len(v) >= min_videos}
