"""Core data types passed between radar modules."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

SOURCE_TYPES = ("news", "search_trend", "x_trend", "video", "forum", "market", "regulator")


@dataclass
class Signal:
    """One observation from a collector."""

    source: str
    source_type: str
    feed: str
    title: str
    url: str | None
    published_at: datetime | None
    text: str = ""
    lang: str = "en"
    metrics: dict[str, float] = field(default_factory=dict)
    key: str = ""
    topic_hint: str = ""


@dataclass(frozen=True)
class Topic:
    id: str
    name: str
    bucket: str
    keywords: tuple[str, ...]
    angles: tuple[str, ...]
    emerging: bool = False


@dataclass(frozen=True)
class Angle:
    id: str
    name: str
    formats: dict[str, str]
    hooks: tuple[str, ...]


@dataclass
class TopicScore:
    topic_id: str
    heat: float
    stage: str
    n_sources: int
    values: dict[str, float] = field(default_factory=dict)
    z: dict[str, float] = field(default_factory=dict)
    mu: dict[str, float] = field(default_factory=dict)
    bonuses: dict[str, float] = field(default_factory=dict)
    prev_heat: float = 0.0


@dataclass
class Brief:
    topic: Topic
    score: TopicScore
    urgency: str
    headline: str
    headline_url: str | None
    evidence: list[tuple[str, str | None]]
    phrases: list[str]
    angles: list[dict[str, str]]
    hooks_now: list[dict[str, str]]
