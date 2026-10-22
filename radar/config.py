"""Load and validate the YAML configuration in config/."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from radar.models import Angle, Topic

BUCKETS = {
    "personal_finance": "Personal finance",
    "markets": "Markets & macro",
    "wealth": "Wealth/HNI",
    "trading": "Trading & stocks",
}
EMERGING_ANGLES = ("hot_take_news", "explainer", "timeline", "myth_bust", "faq")
DEFAULT_DIR = Path(__file__).resolve().parent.parent / "config"


class ConfigError(ValueError):
    """Raised when the config files are inconsistent."""


@dataclass(frozen=True)
class Config:
    settings: dict[str, Any]
    topics: tuple[Topic, ...]
    topic_map: dict[str, Topic]
    angles: dict[str, Angle]
    sources: dict[str, Any]
    channels: tuple[dict[str, str], ...]
    events: tuple[dict[str, Any], ...]
    genres: dict[str, str]              # id -> name, in genres.yaml order
    finance_genres: frozenset[str]

    def is_finance(self, topic: Topic | None) -> bool:
        """A topic with at least one finance genre is a finance topic (the only kind the Sheet and HOT emails get)."""
        return topic is not None and not self.finance_genres.isdisjoint(topic.genres)


def _load(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _check_genres(owner: str, genre_ids: Any, known: dict[str, str]) -> tuple[str, ...]:
    """The genres of a topic or source: a non-empty list of ids from genres.yaml."""
    if not genre_ids:
        raise ConfigError(f"{owner}: no genres")
    unknown = [g for g in genre_ids if g not in known]
    if unknown:
        raise ConfigError(f"{owner}: unknown genres {unknown}")
    return tuple(genre_ids)


def load_config(config_dir: Path = DEFAULT_DIR) -> Config:
    angles = {
        a["id"]: Angle(id=a["id"], name=a["name"], formats=dict(a["formats"]), hooks=tuple(a["hooks"]))
        for a in _load(config_dir / "angles.yaml")["angles"]
    }
    for angle in angles.values():
        missing = {"linkedin", "x", "instagram"} - set(angle.formats)
        if missing:
            raise ConfigError(f"angle {angle.id}: missing formats {sorted(missing)}")
    for angle_id in EMERGING_ANGLES:
        if angle_id not in angles:
            raise ConfigError(f"emerging angle {angle_id} is not defined in angles.yaml")

    genres_raw = _load(config_dir / "genres.yaml")["genres"]
    genres = {g["id"]: g["name"] for g in genres_raw}
    finance_genres = frozenset(g["id"] for g in genres_raw if g.get("finance"))

    topics_raw = _load(config_dir / "topics.yaml")
    topics: list[Topic] = []
    for t in topics_raw["topics"]:
        topic_genres = _check_genres(f"topic {t['id']}", t.get("genres"), genres)
        # A finance bucket is explicit; any other topic's bucket is its first genre.
        bucket = t.get("bucket", topic_genres[0])
        if "bucket" in t and bucket not in BUCKETS:
            raise ConfigError(f"topic {t['id']}: unknown bucket {bucket}")
        if bucket in BUCKETS and finance_genres.isdisjoint(topic_genres):
            raise ConfigError(f"topic {t['id']}: finance bucket without a finance genre")
        unknown = [a for a in t["angles"] if a not in angles]
        if unknown:
            raise ConfigError(f"topic {t['id']}: unknown angles {unknown}")
        topics.append(Topic(id=t["id"], name=t["name"], bucket=bucket, keywords=tuple(str(k) for k in t["keywords"]),
                            angles=tuple(t["angles"]), genres=topic_genres))
    topic_map = {t.id: t for t in topics}
    if len(topic_map) != len(topics):
        raise ConfigError("duplicate topic ids in topics.yaml")

    sources = _load(config_dir / "sources.yaml")
    for entry in (*sources["google_news"]["queries"], *sources["news_feeds"], *sources["regulators"]):
        _check_genres(f"source {entry['id']}", entry.get("genres"), genres)
    for name in ("reddit", "youtube"):
        _check_genres(f"source {name}", sources[name].get("genres"), genres)
    for symbol in sources["markets"]["symbols"]:
        if symbol["topic"] not in topic_map:
            raise ConfigError(f"market symbol {symbol['symbol']}: unknown topic {symbol['topic']}")
    events = tuple(_load(config_dir / "events.yaml")["events"] or ())
    for event in events:
        if event["topic"] not in topic_map:
            raise ConfigError(f"event {event['name']}: unknown topic {event['topic']}")

    return Config(
        settings=_load(config_dir / "settings.yaml"),
        topics=tuple(topics),
        topic_map=topic_map,
        angles=angles,
        sources=sources,
        channels=tuple(_load(config_dir / "channels.yaml")["channels"] or ()),
        events=events,
        genres=genres,
        finance_genres=finance_genres,
    )
