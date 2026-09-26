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
    finance_vocab: frozenset[str]
    angles: dict[str, Angle]
    sources: dict[str, Any]
    channels: tuple[dict[str, str], ...]
    events: tuple[dict[str, Any], ...]


def _load(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


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

    topics_raw = _load(config_dir / "topics.yaml")
    topics: list[Topic] = []
    for t in topics_raw["topics"]:
        if t["bucket"] not in BUCKETS:
            raise ConfigError(f"topic {t['id']}: unknown bucket {t['bucket']}")
        unknown = [a for a in t["angles"] if a not in angles]
        if unknown:
            raise ConfigError(f"topic {t['id']}: unknown angles {unknown}")
        topics.append(Topic(id=t["id"], name=t["name"], bucket=t["bucket"],
                            keywords=tuple(str(k) for k in t["keywords"]), angles=tuple(t["angles"])))
    topic_map = {t.id: t for t in topics}
    if len(topic_map) != len(topics):
        raise ConfigError("duplicate topic ids in topics.yaml")

    sources = _load(config_dir / "sources.yaml")
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
        finance_vocab=frozenset(str(w).lower() for w in topics_raw["finance_vocab"]),
        angles=angles,
        sources=sources,
        channels=tuple(_load(config_dir / "channels.yaml")["channels"] or ()),
        events=events,
    )
