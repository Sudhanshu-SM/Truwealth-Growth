# Truwealth Viral Content Radar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an in-house radar that polls free Indian finance signals every 15 minutes, detects spiking topics, and emails the founder briefs with evidence and LinkedIn/X/Instagram content angles, plus an 08:00 IST digest.

**Architecture:** A Python package (`radar/`) run by GitHub Actions cron. Isolated collectors fetch signals in parallel threads; the main thread stores them in SQLite (persisted through the Actions cache), matches them to 47 configured topics, detects new-phrase spikes, scores each topic's heat against its own 7-day baseline, and emails HOT briefs through Gmail SMTP. All tuning lives in `config/*.yaml`.

**Tech Stack:** Python 3.12, httpx, selectolax, PyYAML, Jinja2, SQLite (stdlib), smtplib (stdlib), pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-26-viral-content-radar-design.md`

**How this plan was checked:** every file below was written into a scratch prototype first. The full suite (102 tests) passes on Python 3.12 with httpx 0.28.1, selectolax 0.4.12, PyYAML 6.0.3, Jinja2 3.1.6 and pytest 9.1.1. The task order was replayed in an empty folder: each task's tests fail before its code exists and pass after. A live dry run against the real sources succeeded. Copy code exactly; if something differs from the expected output, stop and investigate rather than improvising.

## Global Constraints

- Python 3.12. Runtime dependencies are exactly httpx, selectolax, PyYAML and Jinja2; dev adds pytest. No other packages, no API keys.
- Free, keyless public sources only (spec section 7). No X API, no logged-in or cookie scraping, no LinkedIn or Instagram collection.
- Store every timestamp as an ISO-8601 UTC string (`to_iso`). IST is a fixed UTC+05:30 offset, used only for display and for hour/day buckets.
- No colour coding and no emoji in any output. Labels are plain text.
- No compliance or regulatory content anywhere. The tool is in-house; RBI and SEBI feeds are only news signals.
- Collectors never touch SQLite. All database writes happen in the main thread.
- Tests never touch the network: use `httpx.MockTransport` and the fixtures in `tests/fixtures/`.
- The repository is public: logs never print secrets, recipients or email bodies.
- Schedules: radar `4,19,34,49 * * * *`; digest `30 2 * * *` (08:00 IST).
- Line endings are LF (`.gitattributes`). The code must run on Windows (development) and Ubuntu (Actions).
- Thresholds, weights, caps, cooldowns and the warm-up live in `config/settings.yaml`, never hard-coded.
- End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## File Structure

| Path | Responsibility |
|---|---|
| `radar/timeutil.py` | UTC/IST helpers, tolerant date parsing |
| `radar/text.py` | Cleaning, normalisation, hashing, slugs |
| `radar/models.py` | Signal, Topic, Angle, TopicScore, Brief |
| `radar/config.py` | Load and validate `config/*.yaml` |
| `radar/store.py` | SQLite schema, items, kv, source health, pruning |
| `radar/matcher.py` | Text to topic ids |
| `radar/http.py` | Shared HTTP client with one retry |
| `radar/rss.py` | Stdlib RSS/Atom parser |
| `radar/collectors/__init__.py` | Context, `run_all`, `gather` |
| `radar/collectors/google_trends.py`, `google_news.py`, `news_feeds.py`, `regulators.py`, `x_trends.py`, `markets.py`, `reddit.py`, `youtube.py` | One source each |
| `radar/hooks.py` | Title to angle type; format scoreboard |
| `radar/phrases.py` | New-phrase spikes and emerging topics |
| `radar/scorer.py` | Values, baselines, heat, stages, alert rule |
| `radar/briefs.py` | Build a brief for a topic |
| `radar/events.py` | Upcoming dated events |
| `radar/digest.py` | Digest data and the topic catalog |
| `radar/emailer.py`, `radar/templates/*` | Render and send emails, dry-run previews |
| `radar/pipeline.py`, `radar/__main__.py` | One run, the digest, the CLI |
| `config/*.yaml` | Settings, topics, angles, sources, channels, events |
| `tests/` | pytest suite, `helpers.py`, `fixtures/` |
| `.github/workflows/*.yml` | radar (15 min), digest (daily), ci |

---


### Task 1: Project scaffold, time and text helpers

Sets up the repo layout, the virtualenv and two helper modules every other task uses. `.gitignore` already exists from the spec commit; replace it. `tests/helpers.py` starts small and gains `make_ctx` in Task 5.

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `pytest.ini`
- Create: `.gitattributes`
- Modify: `.gitignore`
- Create: `tests/test_timeutil_text.py`
- Create: `tests/helpers.py`
- Create: `radar/__init__.py`
- Create: `radar/timeutil.py`
- Create: `radar/text.py`

**Interfaces:**
- Consumes: nothing
- Produces: `radar.timeutil`: `IST`, `utcnow() -> datetime`, `to_iso(dt) -> str`, `from_iso(s) -> datetime`, `ist(dt)`, `ist_date(dt) -> date`, `ist_hour_bucket(dt) -> 'YYYY-MM-DDTHH'`, `ist_day_start_utc(dt) -> datetime`, `parse_date(s, default_tz=timezone.utc) -> datetime | None`. `radar.text`: `clean(s) -> str`, `normalize_title(title) -> str`, `sha1(*parts) -> str`, `slugify(s) -> str`. `tests/helpers.py`: `NOW` (2026-09-26 08:00 UTC), `FIXTURES`, `fixture_bytes(name)`, `fixture_text(name)`.

- [ ] **Step 1: Create the project files and the virtualenv**

`requirements.txt`

```text
httpx>=0.27,<1
selectolax>=0.3.21
PyYAML>=6.0.1
Jinja2>=3.1.4
```

`requirements-dev.txt`

```text
-r requirements.txt
pytest>=8.0
```

`pytest.ini`

```ini
[pytest]
testpaths = tests
pythonpath = .
```

`.gitattributes`

```text
* text=auto eol=lf
```

`.gitignore`

```text
radar.db
radar.db-*
*.db
*.corrupt
out/
__pycache__/
*.pyc
.venv/
.pytest_cache/
.env
```

Then, from the repository root (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
```

On Linux or macOS use `source .venv/bin/activate`. Every later command assumes the virtualenv is active and runs from the repository root.

- [ ] **Step 2: Write the failing tests**

`tests/test_timeutil_text.py`

```python
from datetime import datetime, timezone

from radar.text import clean, normalize_title, sha1, slugify
from radar.timeutil import IST, from_iso, ist_date, ist_day_start_utc, ist_hour_bucket, parse_date, to_iso


def test_parse_rfc822_with_offset():
    assert parse_date("Sat, 26 Sep 2026 06:50:00 -0700") == datetime(2026, 9, 26, 13, 50, tzinfo=timezone.utc)


def test_parse_mint_sept_month():
    assert parse_date("Sat, 26 Sept 2026 17:57:36 +0530") == datetime(2026, 9, 26, 12, 27, 36, tzinfo=timezone.utc)


def test_parse_missing_timezone_uses_default():
    assert parse_date("Fri, 25 Sep 2026 21:50:00", IST) == datetime(2026, 9, 25, 16, 20, tzinfo=timezone.utc)


def test_parse_sebi_date_only():
    assert parse_date("24 Sep, 2026 +0530") == datetime(2026, 9, 23, 18, 30, tzinfo=timezone.utc)


def test_parse_iso():
    assert parse_date("2026-09-26T12:43:44+00:00") == datetime(2026, 9, 26, 12, 43, 44, tzinfo=timezone.utc)


def test_parse_garbage_returns_none():
    assert parse_date("not a date") is None
    assert parse_date(None) is None


def test_iso_roundtrip():
    dt = datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc)
    assert to_iso(dt) == "2026-09-26T08:00:00+00:00"
    assert from_iso(to_iso(dt)) == dt


def test_ist_helpers():
    dt = datetime(2026, 9, 26, 20, 0, tzinfo=timezone.utc)  # 01:30 IST on 27 Sep
    assert ist_hour_bucket(dt) == "2026-09-27T01"
    assert ist_date(dt).isoformat() == "2026-09-27"
    assert ist_day_start_utc(dt) == datetime(2026, 9, 26, 18, 30, tzinfo=timezone.utc)


def test_clean_strips_tags_emoji_and_entities():
    assert clean("<p>Gold &amp; silver</p> \U0001F6A6 rally\n now") == "Gold & silver rally now"


def test_normalize_hash_slug():
    assert normalize_title("  Nifty  Hits RECORD ") == "nifty hits record"
    assert sha1("a", "b") != sha1("ab")
    assert slugify("UPI Charges!") == "upi-charges"
```

`tests/helpers.py`

```python
"""Shared test helpers. pytest puts tests/ on sys.path, so test modules can `from helpers import ...`."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc)  # 13:30 IST


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")
```

- [ ] **Step 3: Run the new tests and confirm they fail**

```powershell
python -m pytest tests/test_timeutil_text.py -q
```

Expected: collection error `ModuleNotFoundError: No module named 'radar'` (the module does not exist yet).

- [ ] **Step 4: Implement**

`radar/__init__.py`

```python
"""Truwealth viral content radar."""
```

`radar/timeutil.py`

```python
"""Time helpers. Everything is stored in UTC; IST is used for display and for day/hour buckets."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

IST = timezone(timedelta(hours=5, minutes=30), "IST")  # India has no DST

_MONTH_FIXES = (("Sept", "Sep"), ("June", "Jun"), ("July", "Jul"))
_DATE_ONLY = re.compile(r"^(\d{1,2}) ([A-Za-z]{3}),? (\d{4})(?: ([+-]\d{4}))?$")  # SEBI: "24 Sep, 2026 +0530"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def from_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def ist(dt: datetime) -> datetime:
    return dt.astimezone(IST)


def ist_date(dt: datetime) -> date:
    return ist(dt).date()


def ist_hour_bucket(dt: datetime) -> str:
    """'YYYY-MM-DDTHH' in IST; used for hourly phrase counts."""
    return ist(dt).strftime("%Y-%m-%dT%H")


def ist_day_start_utc(dt: datetime) -> datetime:
    """Midnight IST of dt's IST date, as a UTC datetime."""
    return ist(dt).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def parse_date(s: str | None, default_tz: timezone = timezone.utc) -> datetime | None:
    """Parse the RSS/Atom dates our feeds emit. Returns an aware UTC datetime, or None."""
    if not s:
        return None
    s = s.strip()
    for bad, good in _MONTH_FIXES:
        s = re.sub(rf"\b{bad}\b", good, s)
    m = _DATE_ONLY.match(s)
    if m:
        day, month, year, offset = m.groups()
        s = f"{day} {month} {year} 00:00:00 {offset or ''}".strip()
    try:
        dt = parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_tz)
    return dt.astimezone(timezone.utc)
```

`radar/text.py`

```python
"""Text cleaning shared by collectors, matcher, phrases and store."""
from __future__ import annotations

import hashlib
import html
import re
import unicodedata

_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")
_SLUG = re.compile(r"[^0-9a-zऀ-ॿ]+")


def clean(s: str | None) -> str:
    """Unescape entities, drop HTML tags and emoji, NFC-normalise, collapse whitespace."""
    if not s:
        return ""
    s = _TAGS.sub(" ", html.unescape(s))
    s = _EMOJI.sub("", unicodedata.normalize("NFC", s))
    return _WS.sub(" ", s).strip()


def normalize_title(title: str) -> str:
    return clean(title).lower()


def sha1(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()


def slugify(s: str) -> str:
    return _SLUG.sub("-", s.lower()).strip("-")[:60] or "topic"
```

- [ ] **Step 5: Run the whole suite**

```powershell
python -m pytest -q
```

Expected: `10 passed`.

- [ ] **Step 6: Commit**

```powershell
git add requirements.txt requirements-dev.txt pytest.ini .gitattributes .gitignore tests/test_timeutil_text.py tests/helpers.py radar/__init__.py radar/timeutil.py radar/text.py
git commit -m "chore: scaffold project with time and text helpers" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: Data models and configuration

All tunable behaviour lives in `config/*.yaml`; `radar/config.py` loads and cross-checks it. `channels.yaml` holds 91 channel ids that were verified on 2026-09-26 (handle resolved to a channel id, RSS fetched); copy it exactly. Stopwords are one space-separated string because YAML would turn words like `no` and `on` into booleans.

**Files:**
- Create: `tests/test_config.py`
- Create: `radar/models.py`
- Create: `radar/config.py`
- Create: `config/settings.yaml`
- Create: `config/topics.yaml`
- Create: `config/angles.yaml`
- Create: `config/sources.yaml`
- Create: `config/events.yaml`
- Create: `config/channels.yaml`

**Interfaces:**
- Consumes: `radar.timeutil`, `radar.text`
- Produces: `radar.models`: `Signal(source, source_type, feed, title, url, published_at, text='', lang='en', metrics={}, key='', topic_hint='')`, `Topic(id, name, bucket, keywords, angles, emerging=False)`, `Angle(id, name, formats, hooks)`, `TopicScore(topic_id, heat, stage, n_sources, values, z, mu, bonuses, prev_heat)`, `Brief(topic, score, urgency, headline, headline_url, evidence, phrases, angles, hooks_now)`. `radar.config`: `BUCKETS`, `EMERGING_ANGLES`, `DEFAULT_DIR`, `ConfigError`, `Config(settings, topics, topic_map, finance_vocab, angles, sources, channels, events)`, `load_config(config_dir=DEFAULT_DIR) -> Config`.

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`

```python
from pathlib import Path

import pytest

from radar.config import BUCKETS, ConfigError, load_config


def test_real_config_loads():
    cfg = load_config()
    assert len(cfg.topics) == 47
    assert {t.bucket for t in cfg.topics} == set(BUCKETS)
    assert len(cfg.angles) == 15
    assert len(cfg.channels) == 91
    assert all(c["id"].startswith("UC") and len(c["id"]) == 24 for c in cfg.channels)
    assert len({c["id"] for c in cfg.channels}) == len(cfg.channels)
    assert len(cfg.sources["google_news"]["queries"]) == 11
    assert len(cfg.sources["news_feeds"]) == 12
    assert "sensex" in cfg.finance_vocab
    assert "on" in cfg.settings["phrases"]["stopwords"].split()


def test_every_topic_has_keywords_and_three_angles():
    for t in load_config().topics:
        assert t.keywords, t.id
        assert len(t.angles) >= 3, t.id


def test_unknown_angle_reference_raises(tmp_path):
    src = Path(__file__).resolve().parent.parent / "config"
    for f in src.glob("*.yaml"):
        (tmp_path / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    topics = (tmp_path / "topics.yaml").read_text(encoding="utf-8")
    (tmp_path / "topics.yaml").write_text(topics.replace("angles: [myth_bust", "angles: [no_such_angle", 1),
                                          encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown angles"):
        load_config(tmp_path)
```

- [ ] **Step 2: Run the new tests and confirm they fail**

```powershell
python -m pytest tests/test_config.py -q
```

Expected: collection error `ModuleNotFoundError: No module named 'radar.config'` (the module does not exist yet).

- [ ] **Step 3: Implement**

`radar/models.py`

```python
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
```

`radar/config.py`

```python
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
```

`config/settings.yaml`

```yaml
# Radar tuning knobs. Spec: docs/superpowers/specs/2026-09-26-viral-content-radar-design.md

run:
  collector_workers: 8
  item_max_age_hours: 24
  breaker_failures: 3          # a collector failing this many runs in a row...
  breaker_retry_minutes: 60    # ...is retried at most this often

scoring:
  watch_threshold: 4.0
  hot_threshold: 6.0
  prior_weight: 4
  baseline_days: 7
  hour_window: 1
  z_clip: 6.0
  sources:
    news:  {mu0: 1.0, sigma0: 1.5, floor: 1.0, min_value: 3,   weight: 1.0}
    video: {mu0: 0.3, sigma0: 1.0, floor: 1.0, min_value: 1.5, weight: 0.8}
    forum: {mu0: 0.2, sigma0: 0.8, floor: 0.8, min_value: 2,   weight: 0.5}
  emerging_news_prior: {mu0: 0.5, sigma0: 1.0}
  bonus:
    search_trend: [[500000, 5], [100000, 4], [20000, 3], [0, 2]]
    x_trend: [[10, 4], [25, 3], [50, 2]]
    market: {base: 3, double: 4}
    regulator: 2
  bonus_window_hours: 6
  x_trend_max_age_minutes: 75
  episode_end_runs: 4
  emerging_stage_hours: 2

alerts:
  warmup_hours: 24
  cooldown_hours: 12
  daily_cap: 4
  urgency_hours: {Emerging: 3, Peaking: 1}

phrases:
  min_ratio: 4.0
  min_items: 3
  min_feeds: 2
  baseline_floor: 0.25
  finance_share: 0.5
  subsume_share: 0.8
  map_share: 0.6
  min_chars: 5
  emerging_ttl_hours: 48
  # A phrase is dropped if it contains any of these (daily boilerplate and routine company filings).
  blocklist: ["share price", "stock market today", "sensex today", "top gainers", "top losers", "market live",
              "trading window", "board meeting", "intimation"]
  # Space-separated so YAML never turns words like "no" or "on" into booleans.
  stopwords: >-
    a an the and or but if then else of to in on for with at by from as is are was were be been being
    it its into about up down out off over under not no nor so do does did doing done has have had having
    can could would should will may might must shall than too very just now new top day days week weeks
    today latest live update updates news check know here there why what how when where which who whom
    whose this that these those i me my we our us you your yours he she him her his they them their says
    said say amid after before again all any both each few more most other some such only own same big
    get gets got via vs full list details report reports things thing watch video shorts short breaking
    also still even much many one two three first last next year years month months crore lakh rs
    के का की में से को पर और है हैं ने भी तो ही या एक यह वह ये वो लिए क्या नहीं हो गया गई गए कर रहा रही
    रहे बाद साथ अब जानें आज कैसे क्यों सकते होगा होंगे किया जा था थी

youtube:
  rotation_groups: 3
  track_hours: 72
  per_channel_track: 20
  min_baseline_samples: 3
  min_sample_age_hours: 6
  outlier_min_signal: 1.5
  outlier_cap: 10
  signal_max_age_hours: 48
  hooks_now_min: 2.0
  hooks_now_hours: 72

reddit:
  spacing_seconds: 3

x_trends:
  min_interval_minutes: 55

retention:
  items_days: 3
  history_days: 8
  videos_days: 30
  alerts_days: 30

email:
  smtp_host: smtp.gmail.com
  smtp_port: 587
  sender_name: Truwealth Radar

digest:
  top_n: 10
  near_miss_n: 5
  scoreboard_n: 5
  events_days: 7
  health_stale_hours: 6
```

`config/topics.yaml`

```yaml
# Finance topics the radar scores. Matching rules (spec section 8):
# - keywords match whole words, case-insensitively;
# - ALL-CAPS keywords of 4 characters or fewer (SIP, UPI, F&O) match case-sensitively;
# - Devanagari keywords match as substrings.
# angles must be ids from angles.yaml, in order of preference.

topics:
  # Personal finance
  - id: sip_mutual_funds
    name: "Mutual funds & SIPs"
    bucket: personal_finance
    keywords: ["mutual fund", "mutual funds", "SIP", "SIPs", "systematic investment plan", "NFO", "index fund", "index funds", "ELSS", "AMFI", "NAV", "flexi cap fund", "small cap fund", "mid cap fund", "large cap fund", "म्यूचुअल फंड", "एसआईपी"]
    angles: [myth_bust, mistakes_list, data_compare, what_if_calculator, should_you, explainer, checklist, contrarian_take]
  - id: income_tax
    name: "Income tax & regimes"
    bucket: personal_finance
    keywords: ["income tax", "tax regime", "new regime", "old regime", "tax slab", "tax slabs", "80C", "80D", "standard deduction", "87A", "tax rebate", "TDS", "tax saving", "tax-saving", "advance tax", "आयकर", "इनकम टैक्स"]
    angles: [before_after_rule, what_if_calculator, explainer, mistakes_list, checklist, faq, myth_bust]
  - id: itr_filing
    name: "ITR filing & refunds"
    bucket: personal_finance
    keywords: ["ITR", "ITRs", "income tax return", "tax return", "tax refund", "income tax refund", "AIS", "Form 16", "Form 26AS", "e-filing", "belated return", "आईटीआर"]
    angles: [checklist, mistakes_list, faq, explainer, red_flags, before_after_rule]
  - id: capital_gains_tax
    name: "Capital gains tax"
    bucket: personal_finance
    keywords: ["capital gains", "LTCG", "STCG", "capital gains tax", "indexation", "grandfathering", "tax harvesting"]
    angles: [before_after_rule, what_if_calculator, explainer, myth_bust, faq]
  - id: insurance
    name: "Insurance"
    bucket: personal_finance
    keywords: ["term insurance", "health insurance", "life insurance", "insurance premium", "ULIP", "LIC", "claim settlement", "insurance claim", "IRDAI", "mediclaim", "बीमा"]
    angles: [myth_bust, mistakes_list, red_flags, checklist, should_you, data_compare]
  - id: loans_emi
    name: "Loans & EMIs"
    bucket: personal_finance
    keywords: ["home loan", "home loans", "personal loan", "car loan", "education loan", "loan rate", "loan rates", "EMI", "EMIs", "lending rate", "MCLR", "repo-linked", "loan prepayment", "होम लोन", "लोन"]
    angles: [what_if_calculator, should_you, mistakes_list, explainer, myth_bust]
  - id: credit_cards
    name: "Credit cards"
    bucket: personal_finance
    keywords: ["credit card", "credit cards", "reward points", "lounge access", "card devaluation", "credit card fee", "क्रेडिट कार्ड"]
    angles: [mistakes_list, red_flags, data_compare, myth_bust, checklist]
  - id: credit_score
    name: "Credit score"
    bucket: personal_finance
    keywords: ["credit score", "CIBIL", "CIBIL score", "credit report", "credit bureau", "सिबिल"]
    angles: [myth_bust, mistakes_list, checklist, faq]
  - id: retirement_pension
    name: "Retirement & pension"
    bucket: personal_finance
    keywords: ["NPS", "EPF", "EPFO", "PPF", "pension", "pensions", "retirement", "retire early", "FIRE", "UPS", "unified pension scheme", "gratuity", "provident fund", "पेंशन"]
    angles: [what_if_calculator, data_compare, mistakes_list, myth_bust, should_you, checklist]
  - id: fixed_income_savings
    name: "FDs & small savings"
    bucket: personal_finance
    keywords: ["fixed deposit", "fixed deposits", "FD", "FDs", "FD rate", "FD rates", "post office scheme", "small savings", "senior citizen savings", "SCSS", "Sukanya Samriddhi", "NSC", "recurring deposit", "savings account interest"]
    angles: [data_compare, what_if_calculator, should_you, myth_bust, explainer]
  - id: upi_payments
    name: "UPI & payments"
    bucket: personal_finance
    keywords: ["UPI", "UPI charges", "UPI limit", "NPCI", "MDR", "digital payments", "यूपीआई"]
    angles: [before_after_rule, explainer, faq, myth_bust, hot_take_news]
  - id: scams_fraud
    name: "Scams & fraud"
    bucket: personal_finance
    keywords: ["scam", "scams", "fraud", "frauds", "ponzi", "digital arrest", "cyber fraud", "fake app", "investment scam", "phishing", "ठगी", "धोखाधड़ी", "फ्रॉड"]
    angles: [red_flags, checklist, timeline, explainer, faq]
  - id: salary_budgeting
    name: "Salary & budgeting"
    bucket: personal_finance
    keywords: ["salary", "salaries", "salary hike", "appraisal", "budgeting", "emergency fund", "savings rate", "middle class", "50/30/20", "personal finance", "money management", "financial planning", "सैलरी"]
    angles: [mistakes_list, what_if_calculator, checklist, contrarian_take, myth_bust, poll]
  - id: home_buying
    name: "Home buying"
    bucket: personal_finance
    keywords: ["home buying", "buy a house", "rent vs buy", "property prices", "housing prices", "home prices", "house prices", "housing sales", "RERA", "stamp duty", "real estate prices", "प्रॉपर्टी"]
    angles: [should_you, data_compare, what_if_calculator, mistakes_list, myth_bust]

  # Markets & macro
  - id: market_moves
    name: "Nifty & Sensex moves"
    bucket: markets
    keywords: ["Sensex", "Nifty", "Nifty 50", "Bank Nifty", "stock market", "share market", "Dalal Street", "market crash", "market rally", "record high", "all-time high", "selloff", "sell-off", "bloodbath", "correction", "bear market", "bull run", "India VIX", "सेंसेक्स", "निफ्टी", "शेयर बाजार"]
    angles: [history_lesson, contrarian_take, myth_bust, data_compare, explainer, hot_take_news, poll]
  - id: rbi_policy
    name: "RBI policy & rates"
    bucket: markets
    keywords: ["RBI", "repo rate", "MPC", "monetary policy", "rate cut", "rate hike", "Reserve Bank", "CRR", "Sanjay Malhotra", "आरबीआई", "रेपो रेट"]
    angles: [explainer, what_if_calculator, before_after_rule, hot_take_news, history_lesson, faq]
  - id: inflation
    name: "Inflation"
    bucket: markets
    keywords: ["inflation", "CPI", "WPI", "retail inflation", "food inflation", "महंगाई"]
    angles: [explainer, what_if_calculator, data_compare, history_lesson, myth_bust]
  - id: union_budget
    name: "Union Budget"
    bucket: markets
    keywords: ["Union Budget", "Budget 2027", "Budget 2027-28", "Finance Minister", "Nirmala Sitharaman", "Sitharaman", "budget announcement", "बजट"]
    angles: [before_after_rule, what_if_calculator, explainer, hot_take_news, faq, checklist]
  - id: gst
    name: "GST"
    bucket: markets
    keywords: ["GST", "GST council", "GST rate", "GST rates", "GST cut", "goods and services tax", "जीएसटी"]
    angles: [before_after_rule, explainer, what_if_calculator, faq]
  - id: gold_price
    name: "Gold & silver prices"
    bucket: markets
    keywords: ["gold", "gold price", "gold prices", "gold rate", "gold rates", "silver price", "silver prices", "silver rate", "gold ETF", "sovereign gold bond", "SGB", "digital gold", "gold loan", "सोना", "सोने", "चांदी"]
    angles: [data_compare, history_lesson, myth_bust, should_you, explainer, contrarian_take]
  - id: rupee_forex
    name: "Rupee & forex"
    bucket: markets
    keywords: ["rupee", "USD/INR", "dollar vs rupee", "forex reserves", "INR", "रुपया"]
    angles: [explainer, what_if_calculator, history_lesson, myth_bust]
  - id: crude_oil
    name: "Crude oil & fuel prices"
    bucket: markets
    keywords: ["crude oil", "crude", "Brent", "oil prices", "petrol price", "petrol prices", "diesel price", "fuel prices", "OPEC", "कच्चा तेल", "पेट्रोल"]
    angles: [explainer, what_if_calculator, hot_take_news, data_compare]
  - id: us_fed_global
    name: "US Fed & global markets"
    bucket: markets
    keywords: ["Federal Reserve", "US Fed", "FOMC", "Fed rate", "Fed chair", "Wall Street", "S&P 500", "Nasdaq", "Dow Jones", "US recession", "US inflation", "Treasury yields", "US tariffs"]
    angles: [explainer, hot_take_news, history_lesson, what_if_calculator]
  - id: tariffs_trade
    name: "Tariffs & trade"
    bucket: markets
    keywords: ["tariff", "tariffs", "trade war", "trade deal", "import duty", "customs duty", "H-1B", "टैरिफ"]
    angles: [explainer, hot_take_news, timeline, what_if_calculator]
  - id: fii_dii_flows
    name: "FII/DII flows"
    bucket: markets
    keywords: ["FII", "FIIs", "FPI", "FPIs", "DII", "DIIs", "foreign investors", "foreign portfolio investors", "FPI selling", "FII selling"]
    angles: [explainer, data_compare, history_lesson, contrarian_take]
  - id: gdp_economy
    name: "GDP & economy"
    bucket: markets
    keywords: ["GDP", "economic growth", "Indian economy", "recession", "PMI", "IIP", "fiscal deficit", "jobs data", "unemployment", "जीडीपी", "अर्थव्यवस्था"]
    angles: [explainer, data_compare, history_lesson, myth_bust]
  - id: banking_news
    name: "Banking news"
    bucket: markets
    keywords: ["bank merger", "bank failure", "DICGC", "deposit insurance", "bank holiday", "banking sector", "NPA", "NPAs", "bad loans", "cooperative bank", "co-operative bank", "PSU bank", "PSU banks"]
    angles: [explainer, red_flags, faq, timeline]
  - id: sebi_regulation
    name: "SEBI rules"
    bucket: markets
    keywords: ["Sebi", "market regulator", "Tuhin Kanta Pandey", "सेबी"]
    angles: [before_after_rule, explainer, faq, hot_take_news, timeline]
  - id: ipo_buzz
    name: "IPO buzz"
    bucket: markets
    keywords: ["IPO", "IPOs", "GMP", "grey market premium", "IPO allotment", "listing gains", "SME IPO", "anchor investors", "आईपीओ"]
    angles: [checklist, mistakes_list, explainer, myth_bust, red_flags, should_you]

  # Wealth / HNI
  - id: pms_aif
    name: "PMS & AIFs"
    bucket: wealth
    keywords: ["PMS", "portfolio management service", "portfolio management services", "AIF", "AIFs", "alternative investment fund", "alternative investment funds"]
    angles: [explainer, data_compare, should_you, myth_bust]
  - id: estate_succession
    name: "Estate & succession planning"
    bucket: wealth
    keywords: ["estate planning", "succession planning", "writing a will", "nominee", "nomination", "inheritance", "family trust", "private trust", "succession law", "वसीयत"]
    angles: [checklist, mistakes_list, explainer, faq]
  - id: nri_investing
    name: "NRI investing"
    bucket: wealth
    keywords: ["NRI", "NRIs", "NRE", "NRO", "FEMA", "remittance", "remittances", "LRS", "GIFT City", "एनआरआई"]
    angles: [explainer, checklist, faq, before_after_rule]
  - id: real_estate_vs_equity
    name: "Real estate vs equity"
    bucket: wealth
    keywords: ["REIT", "REITs", "InvIT", "InvITs", "fractional ownership", "commercial real estate", "rental yield", "real estate vs"]
    angles: [data_compare, should_you, myth_bust, explainer]
  - id: global_investing
    name: "Global investing"
    bucket: wealth
    keywords: ["US stocks", "international fund", "international funds", "global investing", "overseas investment", "foreign stocks", "US ETF", "US ETFs"]
    angles: [explainer, data_compare, should_you, checklist]
  - id: bonds_debt
    name: "Bonds & debt"
    bucket: wealth
    keywords: ["bond", "bonds", "bond yield", "bond yields", "G-sec", "G-secs", "government securities", "corporate bonds", "RBI Retail Direct", "debt market", "10-year yield"]
    angles: [explainer, data_compare, should_you, myth_bust]
  - id: unlisted_esop
    name: "Unlisted shares & ESOPs"
    bucket: wealth
    keywords: ["unlisted shares", "pre-IPO", "ESOP", "ESOPs", "startup funding", "angel investor", "angel tax", "unicorn"]
    angles: [explainer, red_flags, what_if_calculator, faq]
  - id: rich_list_wealth
    name: "Rich lists & wealth"
    bucket: wealth
    keywords: ["billionaire", "billionaires", "richest", "rich list", "Hurun", "Forbes", "net worth", "family office", "ultra-rich", "HNI", "HNIs", "wealthiest"]
    angles: [data_compare, contrarian_take, myth_bust, history_lesson, poll]
  - id: hni_tax_planning
    name: "HNI tax planning"
    bucket: wealth
    keywords: ["surcharge", "wealth tax", "HUF", "54EC", "super rich tax", "inheritance tax", "estate duty"]
    angles: [explainer, what_if_calculator, before_after_rule, faq]

  # Trading & stocks
  - id: fno_trading
    name: "F&O trading"
    bucket: trading
    keywords: ["F&O", "futures and options", "options trading", "option trading", "derivatives", "expiry", "intraday", "weekly expiry", "lot size", "एफएंडओ"]
    angles: [myth_bust, mistakes_list, data_compare, red_flags, explainer, contrarian_take]
  - id: stock_moves
    name: "Big stock moves"
    bucket: trading
    keywords: ["shares surge", "shares jump", "shares rally", "shares fall", "shares crash", "shares tank", "shares slump", "stock surges", "stock jumps", "stock falls", "stock crashes", "upper circuit", "lower circuit", "52-week high", "52-week low", "multibagger", "target price", "buy rating", "sell rating"]
    angles: [explainer, timeline, history_lesson, myth_bust, mistakes_list]
  - id: smallcap_penny
    name: "Small caps & penny stocks"
    bucket: trading
    keywords: ["smallcap", "smallcaps", "small-cap", "small cap", "midcap", "midcaps", "mid-cap", "penny stock", "penny stocks", "SME stocks", "microcap"]
    angles: [red_flags, myth_bust, data_compare, mistakes_list, history_lesson]
  - id: corporate_actions
    name: "Dividends, bonuses & splits"
    bucket: trading
    keywords: ["dividend", "dividends", "bonus issue", "bonus shares", "stock split", "buyback", "record date", "rights issue", "ex-dividend"]
    angles: [explainer, checklist, faq, myth_bust]
  - id: earnings_results
    name: "Quarterly results"
    bucket: trading
    keywords: ["Q1 results", "Q2 results", "Q3 results", "Q4 results", "quarterly results", "net profit", "earnings", "profit jumps", "profit falls", "revenue growth"]
    angles: [explainer, data_compare, timeline, myth_bust]
  - id: trading_psychology
    name: "Retail trader behaviour"
    bucket: trading
    keywords: ["retail traders", "retail investors", "demat accounts", "demat account", "trading losses", "overtrading", "trading psychology", "lose money"]
    angles: [myth_bust, mistakes_list, contrarian_take, data_compare, poll, red_flags]
  - id: short_seller_fraud
    name: "Short sellers & market fraud"
    bucket: trading
    keywords: ["short seller", "short-seller", "Hindenburg", "promoter pledge", "accounting fraud", "forensic audit", "insider trading", "front running", "front-running", "market manipulation", "pump and dump"]
    angles: [timeline, explainer, red_flags, history_lesson]
  - id: finfluencers
    name: "Finfluencers & tips"
    bucket: trading
    keywords: ["finfluencer", "finfluencers", "stock tips", "Telegram tips", "trading course", "unregistered advisers", "unregistered advisors"]
    angles: [red_flags, myth_bust, checklist, contrarian_take]
  - id: crypto
    name: "Crypto"
    bucket: trading
    keywords: ["crypto", "cryptocurrency", "cryptocurrencies", "bitcoin", "ethereum", "crypto tax", "VDA", "WazirX", "CoinDCX", "क्रिप्टो", "बिटकॉइन"]
    angles: [explainer, myth_bust, red_flags, data_compare, history_lesson]

# Words that mark text as finance-related (lowercase; used by new-phrase detection).
finance_vocab: [market, markets, stock, stocks, share, shares, sensex, nifty, ipo, tax, taxes, rbi, sebi, loan, loans, bank, banks, fund, funds, invest, investing, investor, investors, investment, rupee, crore, lakh, price, prices, rate, rates, gold, silver, crypto, bitcoin, gdp, inflation, profit, earnings, dividend, insurance, salary, emi, upi, gst, budget, economy, finance, financial, money, wealth, trading, trader, traders, nse, bse, sip, mutual, शेयर, बाजार, निवेश, टैक्स, रुपया, सोना, बैंक]
```

`config/angles.yaml`

```yaml
# Content angle playbook. Hooks may use {topic} and {headline}; the first hook is used in briefs.

angles:
  - id: hot_take_news
    name: Fast reaction
    formats:
      linkedin: "Text post: what happened, what it means for the reader, your view (120-200 words)"
      x: "Single post with the key number, then a 3-post thread"
      instagram: "Reel 20-30 s talking head: here's what this news means for you"
    hooks:
      - "{headline}. Here's what it means for your money."
      - "Everyone is talking about {topic}. 3 things you should know."
  - id: explainer
    name: Plain-language explainer
    formats:
      linkedin: "Document carousel, 6-8 slides: what, why, who is affected, what to do"
      x: "Thread, 5-7 posts, one idea per post"
      instagram: "Reel 45-60 s explainer or 7-slide carousel"
    hooks:
      - "{topic}, explained in 60 seconds."
      - "What {topic} actually means for you."
  - id: before_after_rule
    name: Old rule vs new rule
    formats:
      linkedin: "Carousel with a before/after table, one change per slide"
      x: "Post with a two-column before/after image, details in replies"
      instagram: "Carousel: slide 1 'What changed', then before/after slides"
    hooks:
      - "{topic}: old rule vs new rule."
      - "This change affects your money. Here's what's different."
  - id: myth_bust
    name: Myth vs fact
    formats:
      linkedin: "Text post: 3 myths, one line each, plus the fact (150-250 words)"
      x: "Thread: one myth per post, 5-6 posts"
      instagram: "Reel 30-45 s 'Myth or fact?' or 7-slide carousel"
    hooks:
      - "Everyone's talking about {topic}. Here's what most people get wrong."
      - "3 myths about {topic} I hear every week."
  - id: data_compare
    name: Data comparison
    formats:
      linkedin: "Carousel or single chart comparing the options over time"
      x: "One chart plus a two-line takeaway"
      instagram: "Carousel: chart slide first, then 3 takeaway slides"
    hooks:
      - "{topic}: what the long-term data actually says."
      - "The numbers behind {topic} that nobody shows you."
  - id: history_lesson
    name: History lesson
    formats:
      linkedin: "Text post or carousel: the last few times this happened and what followed"
      x: "Thread with a timeline of past episodes"
      instagram: "Reel 30-45 s: 'The last 5 times this happened...'"
    hooks:
      - "The last 5 times this happened, here's what followed."
      - "We've seen {topic} before. History says this."
  - id: mistakes_list
    name: Common mistakes
    formats:
      linkedin: "Listicle post: 5 mistakes, one line each, with the fix"
      x: "Thread: one mistake per post"
      instagram: "Carousel: one mistake per slide"
    hooks:
      - "5 mistakes people make with {topic}."
      - "I see this {topic} mistake every week."
  - id: checklist
    name: Action checklist
    formats:
      linkedin: "Checklist post or carousel people can save"
      x: "Numbered thread, one step per post"
      instagram: "Save-worthy 6-slide checklist carousel"
    hooks:
      - "{topic}: a 5-point checklist before you do anything."
      - "Save this before you act on {topic}."
  - id: faq
    name: Top questions answered
    formats:
      linkedin: "Q&A post answering the 5 most-asked questions"
      x: "Thread: one question and answer per post"
      instagram: "Reel answering the top 3 questions, or a Q&A carousel"
    hooks:
      - "The 5 questions everyone is asking about {topic}, answered."
      - "Your {topic} questions, answered simply."
  - id: red_flags
    name: Red flags
    formats:
      linkedin: "Text post: 5 warning signs and what to do instead"
      x: "Thread: one red flag per post"
      instagram: "Reel 30 s red-flags countdown, or a carousel"
    hooks:
      - "{topic}: 5 red flags to watch out for."
      - "If someone pitches you {topic}, ask these questions first."
  - id: should_you
    name: Should you act?
    formats:
      linkedin: "Decision framework post: who should act, who should wait"
      x: "Post with a simple yes/no flow, details in the thread"
      instagram: "Reel 30-45 s: 'Should you...? It depends on these 3 things'"
    hooks:
      - "Should you act on {topic}? Ask these 3 questions first."
      - "{topic} is everywhere. Here's who should care and who shouldn't."
  - id: what_if_calculator
    name: Run the numbers
    formats:
      linkedin: "Worked example with real rupee numbers, as a carousel"
      x: "Post with one worked example, the calculation in the thread"
      instagram: "Reel with an on-screen calculation, or a 5-slide carousel"
    hooks:
      - "What {topic} means for someone earning ₹1 lakh a month."
      - "Let's run the numbers on {topic}."
  - id: contrarian_take
    name: Contrarian take
    formats:
      linkedin: "Opinion post: the popular view, why you disagree, the evidence"
      x: "Hot-take post, reasoning in the thread"
      instagram: "Reel 30 s 'Unpopular opinion'"
    hooks:
      - "Unpopular opinion on {topic}."
      - "Everyone's worried about {topic}. I'm not. Here's why."
  - id: timeline
    name: What happened, step by step
    formats:
      linkedin: "Carousel timeline of events with dates"
      x: "Thread in chronological order"
      instagram: "Carousel timeline or Reel 45 s 'The full story'"
    hooks:
      - "{topic}: the full story in 5 steps."
      - "How {topic} unfolded, and what comes next."
  - id: poll
    name: Audience poll
    formats:
      linkedin: "Poll with 3-4 options plus a short context line"
      x: "Poll with a one-line setup"
      instagram: "Story poll or quiz sticker, then share the results"
    hooks:
      - "Quick poll: how is {topic} affecting your plans?"
      - "Be honest: what are you doing about {topic}?"
```

`config/sources.yaml`

```yaml
# Endpoints the collectors read. All free, no keys. Checked 2026-09-26.

google_trends:
  url: "https://trends.google.com/trending/rss?geo=IN"

google_news:
  url: "https://news.google.com/rss/search"
  window: "when:1h"
  params_en: {hl: "en-IN", gl: "IN", ceid: "IN:en"}
  params_hi: {hl: "hi", gl: "IN", ceid: "IN:hi"}
  queries:
    - {id: mf, lang: en, q: '"mutual fund" OR SIP OR NFO OR "index fund" OR ELSS'}
    - {id: tax, lang: en, q: '"income tax" OR ITR OR "tax regime" OR "capital gains" OR TDS OR GST'}
    - {id: loans, lang: en, q: '"home loan" OR EMI OR "credit card" OR CIBIL OR "fixed deposit" OR insurance'}
    - {id: retire, lang: en, q: 'EPFO OR NPS OR PPF OR pension OR retirement OR UPI'}
    - {id: market, lang: en, q: 'Sensex OR Nifty OR "stock market" OR "Dalal Street"'}
    - {id: macro, lang: en, q: 'RBI OR "repo rate" OR inflation OR rupee OR "gold price" OR "crude oil"'}
    - {id: trading, lang: en, q: 'IPO OR GMP OR "F&O" OR SEBI OR multibagger'}
    - {id: wealth, lang: en, q: 'PMS OR AIF OR NRI OR "estate planning" OR "family office" OR REIT'}
    - {id: moneycontrol, lang: en, q: 'site:moneycontrol.com'}
    - {id: hi_market, lang: hi, q: 'शेयर बाजार OR सेंसेक्स OR निफ्टी OR आईपीओ'}
    - {id: hi_money, lang: hi, q: 'म्यूचुअल फंड OR आयकर OR आरबीआई OR सोना'}
  # Google News mixes in foreign outlets even for the India edition. Results are kept only from .in domains,
  # domains containing "india" (indiatimes.com, indianexpress.com, ...) and these Indian outlets.
  allowed_domains: [livemint.com, business-standard.com, moneycontrol.com, cnbctv18.com, ndtvprofit.com,
                    financialexpress.com, thehindubusinessline.com, thehindu.com, hindustantimes.com, news18.com,
                    ndtv.com, zeebiz.com, bhaskar.com, livehindustan.com, jagran.com, amarujala.com, abplive.com,
                    firstpost.com, deccanherald.com, telegraphindia.com, tribuneindia.com, newindianexpress.com,
                    timesnownews.com, republicworld.com, wionews.com, lokmat.com, mid-day.com, thequint.com,
                    etmoney.com, paisabazaar.com, bankbazaar.com, policybazaar.com, inc42.com, entrackr.com,
                    yourstory.com, medianama.com, vccircle.com, outlookbusiness.com, tv9hindi.com,
                    in.investing.com, linkedin.com]

news_feeds:
  - {id: et_markets, url: "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"}
  - {id: et_wealth, url: "https://economictimes.indiatimes.com/wealth/rssfeeds/837555174.cms"}
  - {id: et_mf, url: "https://economictimes.indiatimes.com/mf/rssfeeds/359241701.cms"}
  - {id: mint_markets, url: "https://www.livemint.com/rss/markets"}
  - {id: mint_money, url: "https://www.livemint.com/rss/money"}
  - {id: bs_markets, url: "https://www.business-standard.com/rss/markets-106.rss"}
  - {id: bs_finance, url: "https://www.business-standard.com/rss/finance-103.rss"}
  - {id: bs_economy, url: "https://www.business-standard.com/rss/economy-102.rss"}
  - {id: cnbctv18_market, url: "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml"}
  - {id: cnbctv18_economy, url: "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/economy.xml"}
  - {id: cnbctv18_pf, url: "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/personal-finance.xml"}
  - {id: ndtvprofit, url: "https://feeds.feedburner.com/ndtvprofit-latest"}

regulators:
  - {id: rbi, url: "https://rbi.org.in/pressreleases_rss.xml"}
  - {id: sebi, url: "https://www.sebi.gov.in/sebirss.xml"}

x_trends:
  primary: "https://trends24.in/india/"
  fallback: "https://getdaytrends.com/india/"

reddit:
  url_template: "https://www.reddit.com/r/{sub}/rising/.rss"
  subreddits: [IndiaInvestments, personalfinanceindia, IndianStockMarket, IndianStreetBets, FIREIndia, CreditCardsIndia, IndiaTax, StockMarketIndia]

markets:
  url_template: "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
  freshness_minutes: 30
  symbols:
    - {symbol: "^NSEI", name: "Nifty 50", threshold: 1.5, topic: market_moves}
    - {symbol: "^BSESN", name: "Sensex", threshold: 1.5, topic: market_moves}
    - {symbol: "^NSEBANK", name: "Bank Nifty", threshold: 2.0, topic: market_moves}
    - {symbol: "^INDIAVIX", name: "India VIX", threshold: 10.0, topic: market_moves, up_only: true}
    - {symbol: "GC=F", name: "Gold futures", threshold: 2.0, topic: gold_price}
    - {symbol: "INR=X", name: "USD/INR", threshold: 0.5, topic: rupee_forex}
    - {symbol: "^GSPC", name: "S&P 500", threshold: 2.0, topic: us_fed_global}

youtube:
  rss_template: "https://www.youtube.com/feeds/videos.xml?channel_id={id}"
```

`config/events.yaml`

```yaml
# Dated events shown in the digest's "Coming up" section. Events never change heat.
# topic must be a topic id from topics.yaml; date_end is optional.

events:
  - {date: 2026-10-07, name: "RBI MPC policy decision", topic: rbi_policy}
  - {date: 2026-10-10, date_end: 2026-11-14, name: "Q2 FY27 results season", topic: earnings_results}
  - {date: 2026-10-28, name: "US FOMC decision (result late night IST)", topic: us_fed_global}
  - {date: 2026-12-04, name: "RBI MPC policy decision", topic: rbi_policy}
  - {date: 2026-12-09, name: "US FOMC decision (result late night IST)", topic: us_fed_global}
  - {date: 2026-12-15, name: "Advance tax due (third instalment)", topic: income_tax}
  - {date: 2027-02-01, name: "Union Budget 2027-28 (expected)", topic: union_budget}
  - {date: 2027-02-05, name: "RBI MPC policy decision", topic: rbi_policy}
  - {date: 2027-03-15, name: "Advance tax due (final instalment)", topic: income_tax}
  - {date: 2027-03-31, name: "Financial year end and tax-saving deadline", topic: income_tax}
```

`config/channels.yaml`

```yaml
# YouTube channels watched by the radar. Verified 2026-09-26 (handle -> channel id -> RSS).
# Rotation splits this list into 3 groups by position, so order matters only for spreading load.
channels:
  - {id: "UCe3qdG0A_gr-sEdat5y2twQ", name: "CA Rachana Phadke Ranade"}
  - {id: "UCD-qZSqFPqyx43L6gAR8qfQ", name: "CA Rachana Ranade (Hindi)"}
  - {id: "UCwAdQUuPT6laN-AQR17fe1g", name: "Pranjal Kamra"}
  - {id: "UCVOTBwF0vnSxMRIbfSE_K_g", name: "Labour Law Advisor"}
  - {id: "UCRzYN32xtBf3Yxsx5BvJWJw", name: "warikoo"}
  - {id: "UCsNxHPbaCWL1tKw2hxGQD6g", name: "Asset Yogi"}
  - {id: "UCwVEhEzsjLym_u1he4XWFkg", name: "Finance With Sharan"}
  - {id: "UCBI57iTXtmJoaI6Ht7MgcfA", name: "1% Club"}
  - {id: "UCtnItzU7q_bA1eoEBjqcVrw", name: "Shankar Nath"}
  - {id: "UCqW8jxh4tH1Z1sWPbkGWL4g", name: "Akshat Shrivastava"}
  - {id: "UCzUgCORf79EjqlNHmGRHFkA", name: "Neha Nagar"}
  - {id: "UCt22CG7b9crZ0HDk1eTiJjA", name: "Neeraj Arora"}
  - {id: "UCTR1Tk8SaMO9qw930kIOMHQ", name: "Sagar Sinha"}
  - {id: "UCUMccND2H_CVS0dMZKCPCXA", name: "FinnovationZ by Prasad"}
  - {id: "UC2Nwwobsd0ctkzVieXZvyQA", name: "Ankit Inspires India"}
  - {id: "UCBqvATpjSubtNxpqUDj4_cA", name: "Anshuman Sharma"}
  - {id: "UC2MU9phoTYy5sigZCkrvwiw", name: "Rahul Jain"}
  - {id: "UCc6CmEbFkEIHJKzZYCshKEQ", name: "Rahul Jain - Hindi"}
  - {id: "UCSGTyCSQ50UUs1WkhfVbTZw", name: "Gurleen Kaur Tikku"}
  - {id: "UCsUNye3mMDmKjY7IlaqeukA", name: "Hindi Financial Education"}
  - {id: "UCmfl6VteCu880D8Txl4vEag", name: "Finance Boosan"}
  - {id: "UC7fQFl37yAOaPaoxQm-TqSA", name: "Money Pechu"}
  - {id: "UCkGjGT2B7LoDyL2T4pHsUqw", name: "Financially Free"}
  - {id: "UCRGMAIJlkL76zuzm5Z2l5kQ", name: "Money talks by Financially Free"}
  - {id: "UCf5H6aT6NzCQES8OJIhciTw", name: "freefincal"}
  - {id: "UCHXTbd8Av-HR3Yng65dfCZg", name: "CA Manoj Kumar Jain"}
  - {id: "UC-7YSvQqVPTR9quCJt0sZfA", name: "Tax Filing School"}
  - {id: "UCXn42NJPHDxbVrDCkUtBgBA", name: "Insurance Technical"}
  - {id: "UCyKj-yaTpbnWZY90ajxB8WQ", name: "Ditto Insurance"}
  - {id: "UCH7NDZ5HubXj4ygU_IYT4AQ", name: "Beshak Insurance"}
  - {id: "UC5Fx1wCcJq_lVhE6PYIDdUA", name: "Card Academy"}
  - {id: "UCK5A-hCfIug_cnLlYmNwDzA", name: "The Great Indian Points & Miles Show"}
  - {id: "UCa8MSxsDY8kaSasMB5GW6wQ", name: "The Mutual Fund Talk"}
  - {id: "UCg-0FHRCR2ziLX72abJYbIA", name: "The Money Podcast"}
  - {id: "UCPI-DJWmId3Y-Dd1yI8LDnw", name: "WTFinance"}
  - {id: "UCzwCEE_PchiBULMnAJqhGVg", name: "Raj Shamani"}
  - {id: "UCKZozRVHRYsYHGEyNKuhhdA", name: "Think School"}
  - {id: "UC6WzPg6yxF9dQx2_O6R4lww", name: "Nitish Rajput"}
  - {id: "UCM9JulVK4nShhpiMWlEuIGA", name: "Capitalmind"}
  - {id: "UCB7GnQlJPIL6rBBqEoX87vA", name: "SOIC"}
  - {id: "UCvqttS8EzhRq2YWg03qKRCQ", name: "Sanjay Kathuria"}
  - {id: "UCMec1m9iUC3agiEK-nsndSg", name: "Elearnmarkets Face2Face"}
  - {id: "UCmkNoDHBfKzPnXWTNoYQc7A", name: "StockEdge"}
  - {id: "UCBnG19e3YPT3OTMY7uFfu7A", name: "Vivek Bajaj"}
  - {id: "UCzw35O6toJtjqEAAt4LTjKQ", name: "Trade Brains"}
  - {id: "UCS8WLwuVszq1g2oeBzboUmQ", name: "Sunil Minglani"}
  - {id: "UCcanCrgSWVYW7ZFNKQZso0g", name: "Abhishek Kar"}
  - {id: "UCS2NdYUmv_PUyyKeDAo5zYA", name: "P R Sundar"}
  - {id: "UCZ56bfzgD7hIYGZ2k5SEtbA", name: "Vibhor Varshney"}
  - {id: "UCEAAzv2OBqxsSczKJ2QZyGQ", name: "Pushkar Raj Thakur"}
  - {id: "UCfYHvYyFICHwHVO9lHwmiig", name: "Neeraj joshi"}
  - {id: "UC_ldc-Mg7o9KlLWu4TDOZ0Q", name: "GTF - A Stock Market Institute"}
  - {id: "UCE5wDMNEZElnuRDk6TDPOYg", name: "Power of Stocks"}
  - {id: "UChneGqGy_lmvfcR1v_avL6g", name: "Stock Market ka Commando"}
  - {id: "UCN3DuDf9Abnksfkh8aXyLcw", name: "Art of Option Learning"}
  - {id: "UCCW6WdKJfqFUfoio0Lr0iHw", name: "Trading Cafe India"}
  - {id: "UCg3LNMpW2sgZc3nthsbsfzQ", name: "Stock Learners"}
  - {id: "UCY3cHUi4DFx-DyGBlH-tVjw", name: "Stock Market Classes"}
  - {id: "UC8AhWQSB09yTlNVp6Y4aACw", name: "Mahesh Chander Kaushik"}
  - {id: "UCf6PIMsGE2g0rSRbMSlA2oQ", name: "Learning Markets With Manish"}
  - {id: "UCUgUjyt6jcyxfM4FCmxZcgw", name: "Trading Chanakya"}
  - {id: "UCQIRijkQ8zNDe_jR0RhZpVA", name: "Stock Pro"}
  - {id: "UCZSgm98OLObgY3D7sn7z2Wg", name: "Be Sensibull"}
  - {id: "UCa3qap3VLxCwQjyxbS6s5OA", name: "Knowledge Jazz"}
  - {id: "UCbOkZlwRtOP3EGGAYd-Zi1Q", name: "IFMC Stock Market Institute"}
  - {id: "UCCLu5B_Ctsw4N20DJvDykOA", name: "Stock Market INDIA"}
  - {id: "UCM7yoOhnMcfrEZ-5i9m-WFA", name: "Sonia Shenoy"}
  - {id: "UC59YUBhNLMkS2Q8NBWBGHAA", name: "Zerodha"}
  - {id: "UCXbKJML9pVclFHLFzpvBgWw", name: "Markets by Zerodha"}
  - {id: "UCorKX0CAjQh0SnflWPnnI9w", name: "Markets by Zerodha Hindi"}
  - {id: "UCQXwgooTlP6tk2a-u6vgyUA", name: "Zerodha Varsity"}
  - {id: "UCw5TLrz3qADabwezTEcOmgQ", name: "Groww"}
  - {id: "UCbWW7i7KnwQfqp6HFg1diFw", name: "Mutual Funds with Groww"}
  - {id: "UCuA2G-T1WmPRCHwDb713pVQ", name: "Moneytalks by Groww"}
  - {id: "UCAQpvfptgfkFuFJI2_fmveA", name: "IPO Review by Groww"}
  - {id: "UCxv9T8da7658T9R8LQT_3PQ", name: "ET Money"}
  - {id: "UChftTVI0QJmyXkajQYt2tiQ", name: "moneycontrol"}
  - {id: "UCnhUiJ_-DRTP6w51LCQgJRQ", name: "MoneyControl Hindi"}
  - {id: "UCQIycDaLsBpMKjOCeaKUYVg", name: "CNBC Awaaz"}
  - {id: "UCmRbHAgG2k2vDUvb3xsEunQ", name: "CNBC-TV18"}
  - {id: "UCkXopQ3ubd-rnXnStZqCl2w", name: "Zee Business"}
  - {id: "UCI_mwTKUhicNzFrhm33MzBQ", name: "ET Now"}
  - {id: "UCD3CdwT8lTCe5ZGHbUBxmWA", name: "ET Now Swadesh"}
  - {id: "UC3uJIdRFTGgLWrUziaHbzrg", name: "NDTV Profit"}
  - {id: "UCaPHWiExfUWaKsUtENLCv5w", name: "Business Today"}
  - {id: "UCJFOER35ggIWwsXh2ZDnqyg", name: "The Economic Times"}
  - {id: "UCUI9vm69ZbAqRK3q3vKLWCQ", name: "Mint"}
  - {id: "UCQsob4fGjHWhYHW0OLb6rew", name: "Business Standard"}
  - {id: "UCmk6ZFMy1CT80orXca4tKew", name: "The Financial Express"}
  - {id: "UCSWSOS6YXUbNMzTH-tV7Pfw", name: "Biz Tak"}
  - {id: "UCKncvlaA3gRyWESh08Bo6lA", name: "Paisa LIVE"}
```

- [ ] **Step 4: Run the whole suite**

```powershell
python -m pytest -q
```

Expected: `13 passed`.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_config.py radar/models.py radar/config.py config/settings.yaml config/topics.yaml config/angles.yaml config/sources.yaml config/events.yaml config/channels.yaml
git commit -m "feat: data models and YAML configuration" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: SQLite store

`Store` owns the SQLite connection and the shared tables. Modules that own a table (phrases, scorer, youtube) run their own SQL on `store.conn`. All timestamps are ISO-8601 UTC strings from `to_iso`, so string comparison in SQL is time comparison. A corrupt database file is renamed to `*.corrupt` and a fresh one is created.

**Files:**
- Create: `tests/test_store.py`
- Create: `radar/store.py`

**Interfaces:**
- Consumes: `Signal`, `sha1`, `normalize_title`, `to_iso`, `ist_hour_bucket`
- Produces: `radar.store`: `SCHEMA`, `item_id(sig) -> str`, `Store(path)` with `.conn` (rows are `sqlite3.Row`), `add_items(signals, now) -> list[tuple[item_id, Signal]]` (new items only), `add_item_topics(item_id, topic_ids)`, `get_kv(key)`, `set_kv(key, value)`, `record_health(source, error_or_None, now)`, `health_rows()`, `prune(now, retention)`, `close()`.

- [ ] **Step 1: Write the failing tests**

`tests/test_store.py`

```python
from datetime import timedelta

from helpers import NOW

from radar.models import Signal
from radar.store import Store, item_id


def sig(title="Nifty hits record", source_type="news", **kw):
    fields = dict(source="test", source_type=source_type, feed="f1", title=title, url="https://x.test/1",
                  published_at=NOW)
    fields.update(kw)
    return Signal(**fields)


def test_news_ids_ignore_case_spacing_and_feed():
    assert item_id(sig("Nifty  hits RECORD")) == item_id(sig("nifty hits record", feed="other"))


def test_add_items_returns_only_new_and_refreshes_known(tmp_path):
    st = Store(tmp_path / "r.db")
    assert len(st.add_items([sig(), sig("Gold rallies")], NOW)) == 2
    later = NOW + timedelta(minutes=15)
    again = st.add_items([sig(metrics={"rank": 3.0}), sig("RBI cuts repo rate")], later)
    assert [s.title for _, s in again] == ["RBI cuts repo rate"]
    row = st.conn.execute("SELECT first_seen_at, last_seen_at, metrics_json FROM items WHERE id = ?",
                          (item_id(sig()),)).fetchone()
    assert row["first_seen_at"] == "2026-09-26T08:00:00+00:00"
    assert row["last_seen_at"] == "2026-09-26T08:15:00+00:00"
    assert row["metrics_json"] == '{"rank": 3.0}'


def test_duplicate_signals_in_one_call_insert_once(tmp_path):
    st = Store(tmp_path / "r.db")
    assert len(st.add_items([sig(), sig(feed="gn:et")], NOW)) == 1


def test_kv_and_health(tmp_path):
    st = Store(tmp_path / "r.db")
    assert st.get_kv("run_index") is None
    st.set_kv("run_index", "4")
    assert st.get_kv("run_index") == "4"
    st.record_health("reddit", "HTTPStatusError: 403", NOW)
    st.record_health("reddit", "HTTPStatusError: 403", NOW)
    assert st.health_rows()[0]["consecutive_failures"] == 2
    st.record_health("reddit", None, NOW)
    row = st.health_rows()[0]
    assert row["consecutive_failures"] == 0 and row["last_ok_at"] == "2026-09-26T08:00:00+00:00"


def test_prune_removes_old_rows(tmp_path):
    st = Store(tmp_path / "r.db")
    old = st.add_items([sig()], NOW - timedelta(days=4))
    st.add_item_topics(old[0][0], ["market_moves"])
    st.add_items([sig("fresh")], NOW)
    st.prune(NOW, {"items_days": 3, "history_days": 8, "videos_days": 30, "alerts_days": 30})
    assert [r["title"] for r in st.conn.execute("SELECT title FROM items")] == ["fresh"]
    assert st.conn.execute("SELECT COUNT(*) FROM item_topics").fetchone()[0] == 0


def test_reopen_keeps_data(tmp_path):
    path = tmp_path / "r.db"
    st = Store(path)
    st.add_items([sig()], NOW)
    st.close()
    assert Store(path).conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1


def test_corrupt_database_is_replaced(tmp_path):
    path = tmp_path / "r.db"
    path.write_bytes(b"this is not sqlite" * 100)
    st = Store(path)
    assert st.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0
    assert (tmp_path / "r.db.corrupt").exists()
```

- [ ] **Step 2: Run the new tests and confirm they fail**

```powershell
python -m pytest tests/test_store.py -q
```

Expected: collection error `ModuleNotFoundError: No module named 'radar.store'` (the module does not exist yet).

- [ ] **Step 3: Implement**

`radar/store.py`

```python
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
```

- [ ] **Step 4: Run the whole suite**

```powershell
python -m pytest -q
```

Expected: `20 passed`.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_store.py radar/store.py
git commit -m "feat: SQLite store" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4: Topic matcher

Keyword rules from spec section 8: whole-word and case-insensitive by default; ALL-CAPS keywords of 4 or fewer characters (SIP, UPI, F&O) are case-sensitive; Devanagari keywords match as substrings because regex word boundaries break on Devanagari vowel signs.

**Files:**
- Create: `tests/test_matcher.py`
- Create: `radar/matcher.py`

**Interfaces:**
- Consumes: `Topic`, `load_config` (tests)
- Produces: `radar.matcher.Matcher(topics).match(text) -> list[str]` (topic ids).

- [ ] **Step 1: Write the failing tests**

`tests/test_matcher.py`

```python
from radar.config import load_config
from radar.matcher import Matcher
from radar.models import Topic


def topic(topic_id, *keywords):
    return Topic(id=topic_id, name=topic_id, bucket="markets", keywords=keywords, angles=("explainer",))


def test_word_boundaries():
    m = Matcher([topic("ipo_buzz", "IPO")])
    assert m.match("Hippo sightings rise") == []
    assert m.match("LIC IPO opens today") == ["ipo_buzz"]


def test_short_all_caps_keywords_are_case_sensitive():
    m = Matcher([topic("sip", "SIP")])
    assert m.match("Take a sip of coffee") == []
    assert m.match("SIP inflows hit a record") == ["sip"]


def test_longer_keywords_are_case_insensitive():
    assert Matcher([topic("gold", "gold price")]).match("GOLD PRICE jumps") == ["gold"]


def test_devanagari_substring():
    assert Matcher([topic("market", "शेयर बाजार")]).match("आज शेयर बाजार में गिरावट") == ["market"]


def test_special_characters():
    m = Matcher([topic("fno", "F&O"), topic("us", "S&P 500")])
    assert m.match("SEBI tightens F&O rules") == ["fno"]
    assert m.match("S&P 500 falls 2%") == ["us"]


def test_real_topics_route_typical_headlines():
    m = Matcher(load_config().topics)
    assert "rbi_policy" in m.match("RBI keeps repo rate unchanged at 5.25%")
    assert "gold_price" in m.match("Gold rate today: yellow metal hits record high")
    assert "ipo_buzz" in m.match("J Infratech files IPO papers; eyes Rs 600 cr")
    assert "upi_payments" in m.match("नए UPI MDR नियम 15 अक्टूबर से लागू होंगे")
    assert m.match("Bangkok declares flood disaster in all 50 districts") == []
```

- [ ] **Step 2: Run the new tests and confirm they fail**

```powershell
python -m pytest tests/test_matcher.py -q
```

Expected: collection error `ModuleNotFoundError: No module named 'radar.matcher'` (the module does not exist yet).

- [ ] **Step 3: Implement**

`radar/matcher.py`

```python
"""Keyword matching of text to topics (spec section 8)."""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable

from radar.models import Topic

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def _case_sensitive(keyword: str) -> bool:
    return len(keyword) <= 4 and keyword.isupper()


def _alternation(words: list[str]) -> str:
    return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))


class Matcher:
    def __init__(self, topics: Iterable[Topic]):
        self._rules: list[tuple[str, re.Pattern[str] | None, re.Pattern[str] | None, tuple[str, ...]]] = []
        for topic in topics:
            insensitive: list[str] = []
            sensitive: list[str] = []
            devanagari: list[str] = []
            for kw in topic.keywords:
                kw = unicodedata.normalize("NFC", kw.strip())
                if _DEVANAGARI.search(kw):
                    devanagari.append(kw)
                elif _case_sensitive(kw):
                    sensitive.append(kw)
                else:
                    insensitive.append(kw)
            ci = re.compile(rf"(?<!\w)(?:{_alternation(insensitive)})(?!\w)", re.IGNORECASE) if insensitive else None
            cs = re.compile(rf"(?<!\w)(?:{_alternation(sensitive)})(?!\w)") if sensitive else None
            self._rules.append((topic.id, ci, cs, tuple(devanagari)))

    def match(self, text: str) -> list[str]:
        text = unicodedata.normalize("NFC", text or "")
        hits = []
        for topic_id, ci, cs, devanagari in self._rules:
            if (ci and ci.search(text)) or (cs and cs.search(text)) or any(d in text for d in devanagari):
                hits.append(topic_id)
        return hits
```

- [ ] **Step 4: Run the whole suite**

```powershell
python -m pytest -q
```

Expected: `26 passed`.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_matcher.py radar/matcher.py
git commit -m "feat: keyword topic matcher" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: HTTP client, RSS parser and collector plumbing

Plumbing shared by all collectors. Collectors run concurrently in threads and never touch SQLite. `gather` lets a collector with many sub-fetches (12 feeds, 30 channels) survive partial failure. The RSS parser is stdlib-only because live feeds use dates that common parsers reject: Mint writes `Sept`, SEBI omits the time, RBI omits the timezone.

**Files:**
- Create: `tests/test_plumbing.py`
- Modify: `tests/helpers.py`
- Create: `radar/http.py`
- Create: `radar/rss.py`
- Create: `radar/collectors/__init__.py`

**Interfaces:**
- Consumes: `Signal`, `clean`, `parse_date`, `load_config`
- Produces: `radar.http.Http(timeout=10.0, retry_wait=2.0, client=None)` with `.get(url, params=None) -> httpx.Response` and `.close()`. `radar.rss.Entry(title, link, summary, published, guid, source, source_url)`, `parse_feed(raw, default_tz=timezone.utc) -> list[Entry]`. `radar.collectors`: `Context(http, config, now, run_index)`, `Collector = Callable[[Context], list[Signal]]`, `run_all(collectors, ctx, workers=8) -> (signals, {name: error_or_None})`, `gather(tasks) -> list[Signal]`. `tests/helpers.make_ctx(handler, now=NOW, run_index=0, config=None) -> Context`.

- [ ] **Step 1: Write the failing tests**

`tests/test_plumbing.py`

```python
from datetime import datetime, timezone

import httpx
import pytest
from helpers import NOW

from radar.collectors import Context, gather, run_all
from radar.http import Http
from radar.models import Signal
from radar.rss import parse_feed
from radar.timeutil import IST


def make_http(handler):
    return Http(retry_wait=0, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_http_retries_once_on_5xx_then_succeeds():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, text="ok")

    assert make_http(handler).get("https://example.test/").text == "ok"
    assert len(calls) == 2


def test_http_raises_after_second_5xx():
    with pytest.raises(httpx.HTTPStatusError):
        make_http(lambda request: httpx.Response(500)).get("https://example.test/")


def test_http_does_not_retry_429():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429)

    with pytest.raises(httpx.HTTPStatusError):
        make_http(handler).get("https://example.test/")
    assert len(calls) == 1


def test_http_retries_transport_errors_once():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(httpx.ConnectError):
        make_http(handler).get("https://example.test/")
    assert len(calls) == 2


RSS = b"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>
<item><title>Nifty &amp; Sensex slip</title><link>https://ex.test/a</link>
<description>&lt;p&gt;Markets fell&lt;/p&gt;</description><pubDate>Sat, 26 Sep 2026 17:05:56 +0530</pubDate>
<guid>https://ex.test/a</guid><source url="https://et.test">The Economic Times</source></item>
<item><title>RBI release</title><link>https://ex.test/b</link><pubDate>Fri, 25 Sep 2026 21:50:00</pubDate></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Should I stop my SIP?</title><link href="https://www.reddit.com/r/IndiaInvestments/comments/abc/"/>
<id>t3_abc</id><updated>2026-09-26T07:30:00+00:00</updated><content type="html">&lt;p&gt;Question&lt;/p&gt;</content></entry>
</feed>"""


def test_rss_items():
    a, b = parse_feed(RSS, default_tz=IST)
    assert (a.title, a.summary, a.source) == ("Nifty & Sensex slip", "Markets fell", "The Economic Times")
    assert a.source_url == "https://et.test"
    assert a.published == datetime(2026, 9, 26, 11, 35, 56, tzinfo=timezone.utc)
    assert b.published == datetime(2026, 9, 25, 16, 20, tzinfo=timezone.utc)
    assert b.guid == "https://ex.test/b"


def test_atom_entries():
    (e,) = parse_feed(ATOM)
    assert e.link == "https://www.reddit.com/r/IndiaInvestments/comments/abc/"
    assert (e.guid, e.summary) == ("t3_abc", "Question")
    assert e.published == datetime(2026, 9, 26, 7, 30, tzinfo=timezone.utc)


def s(title):
    return Signal(source="t", source_type="news", feed="f", title=title, url=None, published_at=NOW)


def test_run_all_isolates_failures():
    def broken(ctx):
        raise ValueError("broken feed")

    signals, results = run_all({"ok": lambda ctx: [s("a")], "bad": broken},
                               Context(http=None, config=None, now=NOW, run_index=0), workers=2)
    assert [x.title for x in signals] == ["a"]
    assert results["ok"] is None
    assert results["bad"].startswith("ValueError")


def test_gather_tolerates_partial_failure():
    def boom():
        raise RuntimeError("x")

    assert [x.title for x in gather([("a", lambda: [s("a")]), ("b", boom)])] == ["a"]


def test_gather_raises_when_everything_fails():
    def boom():
        raise RuntimeError("all down")

    with pytest.raises(RuntimeError, match="all down"):
        gather([("a", boom), ("b", boom)])
    assert gather([]) == []
```

`tests/helpers.py`

```python
"""Shared test helpers. pytest puts tests/ on sys.path, so test modules can `from helpers import ...`."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx

from radar.collectors import Context
from radar.config import load_config
from radar.http import Http

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc)  # 13:30 IST


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_ctx(handler, now: datetime = NOW, run_index: int = 0, config=None) -> Context:
    """Collector context whose HTTP calls go to `handler(request) -> httpx.Response`."""
    http = Http(retry_wait=0, client=httpx.Client(transport=httpx.MockTransport(handler)))
    return Context(http=http, config=config or load_config(), now=now, run_index=run_index)
```

- [ ] **Step 2: Run the new tests and confirm they fail**

```powershell
python -m pytest tests/test_plumbing.py -q
```

Expected: collection error `ModuleNotFoundError: No module named 'radar.collectors'` (the module does not exist yet).

- [ ] **Step 3: Implement**

`radar/http.py`

```python
"""Shared HTTP client: 10 s timeout (5 s to connect), one retry on timeouts, connection errors and 5xx."""
from __future__ import annotations

import time

import httpx

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")


class Http:
    def __init__(self, timeout: float = 10.0, retry_wait: float = 2.0, client: httpx.Client | None = None):
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(timeout, connect=5.0), follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-IN,en;q=0.9"})
        self.retry_wait = retry_wait

    def get(self, url: str, params: dict | None = None) -> httpx.Response:
        for attempt in (1, 2):
            try:
                resp = self.client.get(url, params=params)
            except httpx.TransportError:
                if attempt == 2:
                    raise
                time.sleep(self.retry_wait)
                continue
            if resp.status_code >= 500 and attempt == 1:
                time.sleep(self.retry_wait)
                continue
            resp.raise_for_status()
            return resp
        raise AssertionError("unreachable")

    def close(self) -> None:
        self.client.close()
```

`radar/rss.py`

```python
"""Minimal RSS 2.0 / Atom parser (stdlib) that tolerates the date quirks in our feeds."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone

from radar.text import clean
from radar.timeutil import parse_date

ATOM = "{http://www.w3.org/2005/Atom}"


@dataclass
class Entry:
    title: str
    link: str | None
    summary: str
    published: datetime | None
    guid: str
    source: str = ""
    source_url: str = ""


def parse_feed(raw: bytes, default_tz: timezone = timezone.utc) -> list[Entry]:
    root = ET.fromstring(raw)
    entries: list[Entry] = []
    for it in root.iter("item"):
        source = it.find("source")
        entries.append(Entry(
            title=clean(it.findtext("title")),
            link=(it.findtext("link") or "").strip() or None,
            summary=clean(it.findtext("description")),
            published=parse_date(it.findtext("pubDate"), default_tz),
            guid=(it.findtext("guid") or it.findtext("link") or "").strip(),
            source=clean(source.text) if source is not None else "",
            source_url=(source.get("url") or "") if source is not None else "",
        ))
    for it in root.iter(f"{ATOM}entry"):
        link = it.find(f"{ATOM}link")
        entries.append(Entry(
            title=clean(it.findtext(f"{ATOM}title")),
            link=link.get("href") if link is not None else None,
            summary=clean(it.findtext(f"{ATOM}summary") or it.findtext(f"{ATOM}content")),
            published=parse_date(it.findtext(f"{ATOM}published") or it.findtext(f"{ATOM}updated"), default_tz),
            guid=(it.findtext(f"{ATOM}id") or "").strip(),
        ))
    return entries
```

`radar/collectors/__init__.py`

```python
"""Collector plumbing: the run context, isolated concurrent execution, partial-failure tolerance."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from radar.models import Signal

log = logging.getLogger(__name__)


@dataclass
class Context:
    http: Any       # radar.http.Http
    config: Any     # radar.config.Config
    now: datetime
    run_index: int


Collector = Callable[[Context], list[Signal]]


def run_all(collectors: dict[str, Collector], ctx: Context, workers: int = 8) -> tuple[list[Signal], dict[str, str | None]]:
    """Run collectors concurrently. One failing collector never stops the others."""
    signals: list[Signal] = []
    results: dict[str, str | None] = {}
    if not collectors:
        return signals, results
    with ThreadPoolExecutor(max_workers=min(workers, len(collectors))) as pool:
        futures = {name: pool.submit(fn, ctx) for name, fn in collectors.items()}
        for name, future in futures.items():
            try:
                got = future.result()
            except Exception as exc:  # noqa: BLE001 - isolating collectors is the point
                results[name] = f"{type(exc).__name__}: {str(exc)[:200]}"
                log.warning("collector %s failed: %s", name, type(exc).__name__)
                continue
            signals.extend(got)
            results[name] = None
            log.info("collector %s: %d signals", name, len(got))
    return signals, results


def gather(tasks: list[tuple[str, Callable[[], list[Signal]]]]) -> list[Signal]:
    """Run sub-fetches in order; tolerate partial failure, raise only if every one failed."""
    out: list[Signal] = []
    errors: list[Exception] = []
    for name, fn in tasks:
        try:
            out.extend(fn())
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
            log.warning("sub-fetch %s failed: %s", name, type(exc).__name__)
    if tasks and len(errors) == len(tasks):
        raise errors[-1]
    return out
```

- [ ] **Step 4: Run the whole suite**

```powershell
python -m pytest -q
```

Expected: `35 passed`.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_plumbing.py tests/helpers.py radar/http.py radar/rss.py radar/collectors/__init__.py
git commit -m "feat: HTTP client, RSS parser and collector plumbing" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 6: News collectors: Google Trends, Google News, news feeds, regulators

Four collectors over RSS. Google News results are kept only from Indian outlets, because the India edition mixes in foreign outlets (Motley Fool, BBC Pidgin) as the live test on 2026-09-26 showed. Fixtures are trimmed copies of the real formats sampled on 2026-09-26.

**Files:**
- Create: `tests/test_collectors_news.py`
- Create: `tests/fixtures/google_trends_in.xml`
- Create: `tests/fixtures/google_news.xml`
- Create: `tests/fixtures/news_feed.xml`
- Create: `tests/fixtures/sebi.xml`
- Create: `radar/collectors/google_trends.py`
- Create: `radar/collectors/google_news.py`
- Create: `radar/collectors/news_feeds.py`
- Create: `radar/collectors/regulators.py`

**Interfaces:**
- Consumes: `Context`, `gather`, `parse_feed`, `slugify`, `IST`, `ist_date`
- Produces: `google_trends.parse_traffic(s) -> float`, `google_trends.parse(raw)`, `google_news.indian_source(url, allowed_domains) -> bool`, `google_news.parse(raw, lang='en', allowed_domains=frozenset())`, `news_feeds.parse(raw, feed_id)`, `regulators.parse(raw, feed_id, now)`; each module has `collect(ctx) -> list[Signal]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_collectors_news.py`

```python
from datetime import datetime, timezone

import httpx
from helpers import NOW, fixture_bytes, make_ctx

from radar.collectors import google_news, google_trends, news_feeds, regulators


def test_google_trends_parse():
    sigs = google_trends.parse(fixture_bytes("google_trends_in.xml"))
    assert [s.title for s in sigs] == ["gold rate today", "lottery sambad"]
    gold = sigs[0]
    assert gold.source_type == "search_trend"
    assert gold.metrics["approx_traffic"] == 50_000
    assert gold.url == "https://example.test/gold-record"
    assert "Gold hits record high" in gold.text
    assert gold.published_at == datetime(2026, 9, 26, 8, 40, tzinfo=timezone.utc)
    assert sigs[1].metrics["approx_traffic"] == 10_000
    assert sigs[1].url is None


def test_parse_traffic():
    assert google_trends.parse_traffic("2M+") == 2_000_000
    assert google_trends.parse_traffic("500+") == 500
    assert google_trends.parse_traffic(None) == 0


def test_google_news_keeps_indian_outlets_and_strips_suffix():
    sigs = google_news.parse(fixture_bytes("google_news.xml"), lang="en", allowed_domains=frozenset({"bhaskar.com"}))
    assert [s.title for s in sigs] == ["Sensex falls 800 points as FPIs sell", "नए UPI MDR नियम 15 अक्टूबर से लागू होंगे"]
    assert [s.feed for s in sigs] == ["gn:the-economic-times", "gn:dainik-bhaskar"]
    assert sigs[0].source_type == "news"
    assert sigs[0].published_at == datetime(2026, 9, 26, 7, 51, 13, tzinfo=timezone.utc)


def test_indian_source_rules():
    allowed = frozenset({"livemint.com"})
    assert google_news.indian_source("https://www.livemint.com", allowed)
    assert google_news.indian_source("https://economictimes.indiatimes.com", allowed)
    assert google_news.indian_source("https://www.aajtak.in", allowed)
    assert not google_news.indian_source("https://www.fool.com", allowed)


def test_google_news_collect_runs_every_query_for_the_last_hour():
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(200, content=fixture_bytes("google_news.xml"))

    sigs = google_news.collect(make_ctx(handler))
    assert len(seen) == 11
    assert all(u.params["q"].endswith(" when:1h") for u in seen)
    assert len([u for u in seen if u.params["hl"] == "hi"]) == 2
    assert len(sigs) == 22


def test_news_feeds_parse():
    sigs = news_feeds.parse(fixture_bytes("news_feed.xml"), "et_markets")
    assert [s.feed for s in sigs] == ["et_markets", "et_markets"]
    assert sigs[0].text.startswith("J Infratech Ltd")
    assert sigs[1].published_at == datetime(2026, 9, 26, 12, 27, 36, tzinfo=timezone.utc)


def test_news_feeds_collect_survives_failing_feeds():
    def handler(request):
        if "livemint" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, content=fixture_bytes("news_feed.xml"))

    assert len(news_feeds.collect(make_ctx(handler))) == 2 * 10  # 12 feeds, the two Mint feeds fail


def test_regulators_keep_today_and_yesterday_only():
    sigs = regulators.parse(fixture_bytes("sebi.xml"), "sebi", NOW)
    assert [s.title for s in sigs] == ["Key decisions taken in the SEBI Board Meeting dated 24th September, 2026"]
    assert (sigs[0].source_type, sigs[0].feed) == ("regulator", "sebi")
```

`tests/fixtures/google_trends_in.xml`

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<rss xmlns:atom="http://www.w3.org/2005/Atom" xmlns:ht="https://trends.google.com/trending/rss" version="2.0">
<channel>
<title>Daily Search Trends</title>
<item>
<title>gold rate today</title>
<ht:approx_traffic>50K+</ht:approx_traffic>
<description></description>
<link>https://trends.google.com/trending/rss?geo=IN</link>
<pubDate>Sat, 26 Sep 2026 01:40:00 -0700</pubDate>
<ht:news_item>
<ht:news_item_title>Gold hits record high as rupee weakens</ht:news_item_title>
<ht:news_item_snippet></ht:news_item_snippet>
<ht:news_item_url>https://example.test/gold-record</ht:news_item_url>
<ht:news_item_source>Mint</ht:news_item_source>
</ht:news_item>
<ht:news_item>
<ht:news_item_title>Gold price today: 24K rate jumps</ht:news_item_title>
<ht:news_item_snippet></ht:news_item_snippet>
<ht:news_item_url>https://example.test/gold-rate</ht:news_item_url>
<ht:news_item_source>ET</ht:news_item_source>
</ht:news_item>
</item>
<item>
<title>lottery sambad</title>
<ht:approx_traffic>10000+</ht:approx_traffic>
<description></description>
<link>https://trends.google.com/trending/rss?geo=IN</link>
<pubDate>Sat, 26 Sep 2026 06:30:00 -0700</pubDate>
</item>
</channel>
</rss>
```

`tests/fixtures/google_news.xml`

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>
<title>"Sensex" - Google News</title>
<item><title>Sensex falls 800 points as FPIs sell - The Economic Times</title>
<link>https://news.google.com/rss/articles/CBMiAAA?oc=5</link><guid isPermaLink="false">CBMiAAA</guid>
<pubDate>Sat, 26 Sep 2026 07:51:13 GMT</pubDate>
<description>&lt;a href="https://news.google.com/rss/articles/CBMiAAA"&gt;Sensex falls&lt;/a&gt;</description>
<source url="https://economictimes.indiatimes.com">The Economic Times</source></item>
<item><title>A Stock Market Correction Is Coming Eventually - The Motley Fool</title>
<link>https://news.google.com/rss/articles/CBMiCCC?oc=5</link><guid isPermaLink="false">CBMiCCC</guid>
<pubDate>Sat, 26 Sep 2026 07:50:40 GMT</pubDate>
<source url="https://www.fool.com">The Motley Fool</source></item>
<item><title>नए UPI MDR नियम 15 अक्टूबर से लागू होंगे - Dainik Bhaskar</title>
<link>https://news.google.com/rss/articles/CBMiBBB?oc=5</link><guid isPermaLink="false">CBMiBBB</guid>
<pubDate>Sat, 26 Sep 2026 07:34:05 GMT</pubDate>
<source url="https://www.bhaskar.com">Dainik Bhaskar</source></item>
</channel></rss>
```

`tests/fixtures/news_feed.xml`

```xml
<?xml version="1.0" encoding="UTF-8"?><rss xmlns:atom="http://www.w3.org/2005/Atom" version="2.0"><channel><title>Markets</title>
<item><title>J Infratech files IPO papers; eyes Rs 600 cr via fresh issue</title>
<description>J Infratech Ltd has submitted preliminary papers for an initial public offering.</description>
<link>https://economictimes.indiatimes.com/markets/ipos/fpos/j-infratech/articleshow/1.cms</link>
<guid>https://economictimes.indiatimes.com/markets/ipos/fpos/j-infratech/articleshow/1.cms</guid>
<pubDate>Sat, 26 Sep 2026 15:48:10 +0530</pubDate></item>
<item><title>Buy Ideaforge stock for 27% upside, says Ashika</title>
<link>https://www.livemint.com/market/stock-market-news/ideaforge-1</link>
<description>Drone stock gets a buy rating.</description>
<pubDate>Sat, 26 Sept 2026 17:57:36 +0530</pubDate></item>
</channel></rss>
```

`tests/fixtures/sebi.xml`

```xml
<?xml version="1.0" encoding="UTF-8" standalone="no"?><rss version="2.0"><channel><ttl>60</ttl><title>SEBI RSS Feed</title>
<item><title>Key decisions taken in the SEBI Board Meeting dated 24th September, 2026</title>
<description>Key decisions taken in the SEBI Board Meeting dated 24th September, 2026</description>
<link>https://www.sebi.gov.in/media-and-notifications/press-releases/sep-2026/key-decisions_1.html</link>
<pubDate>25 Sep, 2026 +0530</pubDate></item>
<item><title>Order in the matter of Omaxe Limited</title>
<description>Order in the matter of Omaxe Limited</description>
<link>https://www.sebi.gov.in/enforcement/orders/sep-2026/omaxe_2.html</link>
<pubDate>20 Sep, 2026 +0530</pubDate></item>
</channel></rss>
```

- [ ] **Step 2: Run the new tests and confirm they fail**

```powershell
python -m pytest tests/test_collectors_news.py -q
```

Expected: collection error `ImportError: cannot import name 'google_news'` (the module does not exist yet).

- [ ] **Step 3: Implement**

`radar/collectors/google_trends.py`

```python
"""Google 'Trending now' RSS for India: searches spiking right now."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from radar.collectors import Context
from radar.models import Signal
from radar.text import clean
from radar.timeutil import parse_date

HT = "{https://trends.google.com/trending/rss}"


def parse_traffic(s: str | None) -> float:
    """'20K+' / '10000+' / '2M+' -> number."""
    m = re.match(r"\s*([\d.,]+)\s*([KkMm]?)", s or "")
    if not m:
        return 0.0
    return float(m.group(1).replace(",", "")) * {"k": 1e3, "m": 1e6}.get(m.group(2).lower(), 1.0)


def parse(raw: bytes) -> list[Signal]:
    out = []
    for it in ET.fromstring(raw).iter("item"):
        title = clean(it.findtext("title"))
        if not title:
            continue
        news = it.findall(f"{HT}news_item")
        out.append(Signal(
            source="google_trends", source_type="search_trend", feed="google_trends_in", title=title,
            url=news[0].findtext(f"{HT}news_item_url") if news else None,
            published_at=parse_date(it.findtext("pubDate")),
            text=" | ".join(clean(n.findtext(f"{HT}news_item_title")) for n in news),
            metrics={"approx_traffic": parse_traffic(it.findtext(f"{HT}approx_traffic"))}))
    return out


def collect(ctx: Context) -> list[Signal]:
    return parse(ctx.http.get(ctx.config.sources["google_trends"]["url"]).content)
```

`radar/collectors/google_news.py`

```python
"""Google News RSS searches limited to the last hour, in English and Hindi, Indian outlets only."""
from __future__ import annotations

from urllib.parse import urlparse

from radar.collectors import Context, gather
from radar.models import Signal
from radar.rss import parse_feed
from radar.text import slugify


def indian_source(url: str, allowed_domains: frozenset[str]) -> bool:
    """True for .in domains, domains containing 'india', and the allowlist in sources.yaml."""
    host = (urlparse(url).hostname or "").removeprefix("www.")
    return host.endswith(".in") or "india" in host or any(host == d or host.endswith("." + d) for d in allowed_domains)


def parse(raw: bytes, lang: str = "en", allowed_domains: frozenset[str] = frozenset()) -> list[Signal]:
    out = []
    for e in parse_feed(raw):
        if not e.title or (e.source_url and not indian_source(e.source_url, allowed_domains)):
            continue
        title = e.title
        suffix = f" - {e.source}" if e.source else ""
        if suffix and title.endswith(suffix):
            title = title[: -len(suffix)].strip()
        out.append(Signal(source="google_news", source_type="news", feed=f"gn:{slugify(e.source or 'unknown')}",
                          title=title, url=e.link, published_at=e.published, lang=lang))
    return out


def collect(ctx: Context) -> list[Signal]:
    cfg = ctx.config.sources["google_news"]
    allowed = frozenset(cfg["allowed_domains"])
    tasks = []
    for q in cfg["queries"]:
        params = dict(cfg["params_hi"] if q["lang"] == "hi" else cfg["params_en"])
        params["q"] = f"{q['q']} {cfg['window']}"
        tasks.append((q["id"], lambda p=params, lang=q["lang"]: parse(ctx.http.get(cfg["url"], params=p).content,
                                                                      lang, allowed)))
    return gather(tasks)
```

`radar/collectors/news_feeds.py`

```python
"""Finance-section RSS feeds of Indian news outlets."""
from __future__ import annotations

from radar.collectors import Context, gather
from radar.models import Signal
from radar.rss import parse_feed
from radar.timeutil import IST


def parse(raw: bytes, feed_id: str) -> list[Signal]:
    return [Signal(source="news_feeds", source_type="news", feed=feed_id, title=e.title, url=e.link,
                   published_at=e.published, text=e.summary[:500])
            for e in parse_feed(raw, default_tz=IST) if e.title]


def collect(ctx: Context) -> list[Signal]:
    return gather([(f["id"], lambda f=f: parse(ctx.http.get(f["url"]).content, f["id"]))
                   for f in ctx.config.sources["news_feeds"]])
```

`radar/collectors/regulators.py`

```python
"""RBI press releases and SEBI announcements (items dated today or yesterday, IST)."""
from __future__ import annotations

from datetime import datetime

from radar.collectors import Context, gather
from radar.models import Signal
from radar.rss import parse_feed
from radar.timeutil import IST, ist_date


def parse(raw: bytes, feed_id: str, now: datetime) -> list[Signal]:
    today = ist_date(now)
    out = []
    for e in parse_feed(raw, default_tz=IST):
        if not e.title or e.published is None or (today - ist_date(e.published)).days > 1:
            continue
        out.append(Signal(source="regulators", source_type="regulator", feed=feed_id, title=e.title, url=e.link,
                          published_at=e.published, text=e.summary[:500]))
    return out


def collect(ctx: Context) -> list[Signal]:
    return gather([(f["id"], lambda f=f: parse(ctx.http.get(f["url"]).content, f["id"], ctx.now))
                   for f in ctx.config.sources["regulators"]])
```

- [ ] **Step 4: Run the whole suite**

```powershell
python -m pytest -q
```

Expected: `43 passed`.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_collectors_news.py tests/fixtures/google_trends_in.xml tests/fixtures/google_news.xml tests/fixtures/news_feed.xml tests/fixtures/sebi.xml radar/collectors/google_trends.py radar/collectors/google_news.py radar/collectors/news_feeds.py radar/collectors/regulators.py
git commit -m "feat: news collectors" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: X trends, market moves and Reddit collectors

trends24 serves minified HTML with unquoted attributes; its first `div.list-container` is the latest hour. getdaytrends is the fallback (first `table.ranking`). Yahoo moves only count when the quote is under 30 minutes old, so weekend or stale data never creates a signal. Reddit is best-effort: it stops at the first 429 or connection failure.

**Files:**
- Create: `tests/test_collectors_social.py`
- Create: `tests/fixtures/trends24_india.html`
- Create: `tests/fixtures/getdaytrends_india.html`
- Create: `tests/fixtures/yahoo_chart.json`
- Create: `tests/fixtures/reddit_rising.xml`
- Create: `radar/collectors/x_trends.py`
- Create: `radar/collectors/markets.py`
- Create: `radar/collectors/reddit.py`

**Interfaces:**
- Consumes: `Context`, `gather`, `parse_feed`, `ist_date`
- Produces: `x_trends.parse_trends24(html)` and `parse_getdaytrends(html)` return `[(rank, name)]`; `x_trends.to_signals(trends, feed, now)`; `markets.parse(raw, spec, now, freshness_minutes) -> Signal | None` (key `symbol:direction:ist-date`, `topic_hint` from the spec); `reddit.parse(raw, sub)`; each module has `collect(ctx)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_collectors_social.py`

```python
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from helpers import fixture_bytes, fixture_text, make_ctx

from radar.collectors import markets, reddit, x_trends

NOW_M = datetime(2026, 9, 26, 8, 40, tzinfo=timezone.utc)  # 10 minutes after the fixture's market time
NIFTY = {"symbol": "^NSEI", "name": "Nifty 50", "threshold": 1.5, "topic": "market_moves"}


def test_trends24_uses_latest_hour_only():
    assert x_trends.parse_trends24(fixture_text("trends24_india.html")) == [
        (1, "#PlusGSTLaunched"), (2, "Sensex Crash"), (3, "#JioHotstar")]


def test_getdaytrends_uses_first_table():
    assert x_trends.parse_getdaytrends(fixture_text("getdaytrends_india.html")) == [(1, "#PlusGSTLaunched"), (2, "Nifty")]


def test_x_trends_falls_back_to_getdaytrends():
    def handler(request):
        if "trends24" in str(request.url):
            return httpx.Response(503)
        return httpx.Response(200, text=fixture_text("getdaytrends_india.html"))

    sigs = x_trends.collect(make_ctx(handler))
    assert [(s.title, s.metrics["rank"], s.feed) for s in sigs] == [
        ("#PlusGSTLaunched", 1.0, "getdaytrends"), ("Nifty", 2.0, "getdaytrends")]
    assert sigs[0].url == "https://x.com/search?q=%23PlusGSTLaunched"


def test_x_trends_raises_when_both_mirrors_are_empty():
    with pytest.raises(RuntimeError):
        x_trends.collect(make_ctx(lambda request: httpx.Response(200, text="<html></html>")))


def test_market_move_over_threshold_emits_signal():
    s = markets.parse(fixture_bytes("yahoo_chart.json"), NIFTY, NOW_M, freshness_minutes=30)
    assert s.title == "Nifty 50 down 2.0% today"
    assert s.metrics == {"pct_move": -2.01, "threshold": 1.5}
    assert s.key == "^NSEI:down:2026-09-26"
    assert s.topic_hint == "market_moves"


def test_market_stale_small_and_wrong_direction_are_ignored():
    raw = fixture_bytes("yahoo_chart.json")
    assert markets.parse(raw, NIFTY, NOW_M + timedelta(hours=2), freshness_minutes=30) is None
    assert markets.parse(raw, dict(NIFTY, threshold=2.5), NOW_M, freshness_minutes=30) is None
    assert markets.parse(raw, dict(NIFTY, up_only=True), NOW_M, freshness_minutes=30) is None


def test_reddit_parse_keeps_rising_rank():
    sigs = reddit.parse(fixture_bytes("reddit_rising.xml"), "IndiaInvestments")
    assert [(s.title, s.metrics["rising_rank"]) for s in sigs] == [
        ("UPI MDR charges from October 15 - how will it affect SIPs?", 1.0), ("Portfolio review please", 2.0)]
    assert (sigs[0].feed, sigs[0].key) == ("r/IndiaInvestments", "t3_1abcde")


def test_reddit_stops_after_429(monkeypatch):
    monkeypatch.setattr(reddit.time, "sleep", lambda seconds: None)
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(429)

    with pytest.raises(RuntimeError):
        reddit.collect(make_ctx(handler))
    assert len(calls) == 1


def test_reddit_keeps_partial_results(monkeypatch):
    monkeypatch.setattr(reddit.time, "sleep", lambda seconds: None)

    def handler(request):
        if "IndiaTax" in str(request.url):
            return httpx.Response(403)
        return httpx.Response(200, content=fixture_bytes("reddit_rising.xml"))

    assert len(reddit.collect(make_ctx(handler))) == 2 * 7  # 8 subreddits, one forbidden
```

`tests/fixtures/trends24_india.html`

```html
<!DOCTYPE html>
<html lang=en class="">
<head><meta charset=UTF-8><title>India — X (Twitter) trending topics and hashtags today | trends24.in</title></head>
<body>
<div id=timeline-container class="">
<div class="px-2 scroll-smooth flex gap-x-4 w-fit pt-8"><div class=list-container><h3 class=title data-timestamp=1790430023.69>Sat Sep 26 2026 13:40:23 GMT+0000 (Coordinated Universal Time)</h3><ol class=trend-card__list><li><span class=trend-name><a href="https://twitter.com/search?q=%23PlusGSTLaunched" class=trend-link>#PlusGSTLaunched</a><span class=tweet-count data-count=""></span></span></li><li><span class=trend-name><a href="https://twitter.com/search?q=Sensex%20Crash" class=trend-link>Sensex Crash</a><span class=tweet-count data-count="52000"></span></span></li><li><span class=trend-name><a href="https://twitter.com/search?q=%23JioHotstar" class=trend-link>#JioHotstar</a><span class=tweet-count data-count=""></span></span></li></ol></div><div class=list-container><h3 class=title data-timestamp=1790426423.00>Sat Sep 26 2026 12:40:23 GMT+0000 (Coordinated Universal Time)</h3><ol class=trend-card__list><li><span class=trend-name><a href="https://twitter.com/search?q=OldTrend" class=trend-link>Old Trend</a><span class=tweet-count data-count=""></span></span></li></ol></div></div>
</div>
</body>
</html>
```

`tests/fixtures/getdaytrends_india.html`

```html
<!DOCTYPE html>
<html><head><title>Twitter trends in India</title></head>
<body>
<div id="trends" class="inset"><script>
  currentDate = new Date(2026, 8, 26, 14);
</script><table class="table table-hover text-left clickable ranking trends wider mb-0"><tbody><tr><th scope="row" class="pos">1</th><td class="main"><a href="/india/trend/%23PlusGSTLaunched/">#PlusGSTLaunched</a></td><td class="graph"></td><td class="go"><span class="icon icon-go"><span class="sr-only">View details</span></span></td></tr><tr><th scope="row" class="pos">2</th><td class="main"><a href="/india/trend/Nifty/">Nifty</a></td><td class="graph"></td><td class="go"></td></tr></tbody></table>
<table class="table ranking trends"><tbody><tr><th scope="row" class="pos">1</th><td class="main"><a href="/india/trend/Other/">Other table</a></td></tr></tbody></table>
</div>
</body></html>
```

`tests/fixtures/yahoo_chart.json`

```json
{"chart":{"result":[{"meta":{"currency":"INR","symbol":"^NSEI","exchangeName":"NSI","exchangeTimezoneName":"Asia/Kolkata","regularMarketTime":1790411400,"regularMarketPrice":22600.0,"chartPreviousClose":23063.1,"previousClose":23063.1,"longName":"NIFTY 50","shortName":"NIFTY 50"},"timestamp":[],"indicators":{"quote":[{}]}}],"error":null}}
```

`tests/fixtures/reddit_rising.xml`

```xml
<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/"><category term="IndiaInvestments" label="r/IndiaInvestments"/><updated>2026-09-26T07:30:00+00:00</updated><id>/r/IndiaInvestments/rising/.rss</id><title>rising submissions : IndiaInvestments</title>
<entry><author><name>/u/someone</name><uri>https://www.reddit.com/user/someone</uri></author><category term="IndiaInvestments" label="r/IndiaInvestments"/><content type="html">&lt;p&gt;New UPI MDR rules from Oct 15. What changes?&lt;/p&gt;</content><id>t3_1abcde</id><link href="https://www.reddit.com/r/IndiaInvestments/comments/1abcde/upi_mdr/"/><updated>2026-09-26T07:10:00+00:00</updated><published>2026-09-26T07:05:00+00:00</published><title>UPI MDR charges from October 15 - how will it affect SIPs?</title></entry>
<entry><author><name>/u/other</name><uri>https://www.reddit.com/user/other</uri></author><category term="IndiaInvestments" label="r/IndiaInvestments"/><content type="html">&lt;p&gt;Portfolio review&lt;/p&gt;</content><id>t3_2fghij</id><link href="https://www.reddit.com/r/IndiaInvestments/comments/2fghij/review/"/><updated>2026-09-26T06:00:00+00:00</updated><published>2026-09-26T05:55:00+00:00</published><title>Portfolio review please</title></entry>
</feed>
```

- [ ] **Step 2: Run the new tests and confirm they fail**

```powershell
python -m pytest tests/test_collectors_social.py -q
```

Expected: collection error `ImportError: cannot import name 'markets'` (the module does not exist yet).

- [ ] **Step 3: Implement**

`radar/collectors/x_trends.py`

```python
"""X (Twitter) India trending list via public mirror sites; trends24 first, getdaytrends as fallback."""
from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from selectolax.parser import HTMLParser

from radar.collectors import Context
from radar.models import Signal


def parse_trends24(html: str) -> list[tuple[int, str]]:
    card = HTMLParser(html).css_first("div.list-container")
    if card is None:
        return []
    names = [a.text(strip=True) for a in card.css("ol.trend-card__list li a.trend-link")]
    return [(i + 1, name) for i, name in enumerate(names[:50]) if name]


def parse_getdaytrends(html: str) -> list[tuple[int, str]]:
    table = HTMLParser(html).css_first("table.ranking")
    if table is None:
        return []
    out = []
    for row in table.css("tr"):
        pos, link = row.css_first("th.pos"), row.css_first("td.main a")
        if pos is None or link is None or not pos.text(strip=True).isdigit():
            continue
        out.append((int(pos.text(strip=True)), link.text(strip=True)))
    return out[:50]


def to_signals(trends: list[tuple[int, str]], feed: str, now: datetime) -> list[Signal]:
    return [Signal(source="x_trends", source_type="x_trend", feed=feed, title=name,
                   url=f"https://x.com/search?q={quote(name)}", published_at=now, metrics={"rank": float(rank)})
            for rank, name in trends]


def collect(ctx: Context) -> list[Signal]:
    src = ctx.config.sources["x_trends"]
    try:
        trends, feed = parse_trends24(ctx.http.get(src["primary"]).text), "trends24"
    except Exception:  # noqa: BLE001 - any failure falls through to the second mirror
        trends, feed = [], "trends24"
    if not trends:
        trends, feed = parse_getdaytrends(ctx.http.get(src["fallback"]).text), "getdaytrends"
    if not trends:
        raise RuntimeError("no X trends parsed from either mirror")
    return to_signals(trends, feed, ctx.now)
```

`radar/collectors/markets.py`

```python
"""Big index, gold and currency moves from Yahoo Finance's chart endpoint."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from radar.collectors import Context, gather
from radar.models import Signal
from radar.timeutil import ist_date


def parse(raw: bytes, spec: dict, now: datetime, freshness_minutes: int) -> Signal | None:
    meta = json.loads(raw)["chart"]["result"][0]["meta"]
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    stamp = meta.get("regularMarketTime")
    if not price or not prev or not stamp:
        return None
    at = datetime.fromtimestamp(stamp, tz=timezone.utc)
    if now - at > timedelta(minutes=freshness_minutes):
        return None
    pct = (price - prev) / prev * 100
    threshold = spec["threshold"]
    if abs(pct) < threshold or (spec.get("up_only") and pct < 0):
        return None
    direction = "up" if pct > 0 else "down"
    return Signal(
        source="markets", source_type="market", feed=f"yahoo:{spec['symbol']}",
        title=f"{spec['name']} {direction} {abs(pct):.1f}% today",
        url=f"https://finance.yahoo.com/quote/{quote(spec['symbol'], safe='')}", published_at=at,
        metrics={"pct_move": round(pct, 2), "threshold": float(threshold)},
        key=f"{spec['symbol']}:{direction}:{ist_date(at).isoformat()}", topic_hint=spec["topic"])


def collect(ctx: Context) -> list[Signal]:
    cfg = ctx.config.sources["markets"]

    def one(spec: dict) -> list[Signal]:
        url = cfg["url_template"].format(symbol=quote(spec["symbol"], safe=""))
        sig = parse(ctx.http.get(url, params={"interval": "5m", "range": "1d"}).content, spec, ctx.now,
                    cfg["freshness_minutes"])
        return [sig] if sig else []

    return gather([(s["symbol"], lambda s=s: one(s)) for s in cfg["symbols"]])
```

`radar/collectors/reddit.py`

```python
"""Reddit 'rising' RSS for Indian finance subreddits. Best-effort: Reddit often blocks cloud IPs."""
from __future__ import annotations

import logging
import time

import httpx

from radar.collectors import Context
from radar.models import Signal
from radar.rss import parse_feed

log = logging.getLogger(__name__)


def parse(raw: bytes, sub: str) -> list[Signal]:
    return [Signal(source="reddit", source_type="forum", feed=f"r/{sub}", title=e.title, url=e.link,
                   published_at=e.published, text=e.summary[:500], metrics={"rising_rank": float(rank)}, key=e.guid)
            for rank, e in enumerate(parse_feed(raw), start=1) if e.title]


def collect(ctx: Context) -> list[Signal]:
    cfg = ctx.config.sources["reddit"]
    spacing = ctx.config.settings["reddit"]["spacing_seconds"]
    out: list[Signal] = []
    failures = 0
    for i, sub in enumerate(cfg["subreddits"]):
        if i:
            time.sleep(spacing)
        try:
            out.extend(parse(ctx.http.get(cfg["url_template"].format(sub=sub)).content, sub))
        except httpx.HTTPStatusError as exc:
            failures += 1
            if exc.response.status_code == 429:
                log.warning("reddit rate-limited; skipping the rest of this run")
                break
        except httpx.TransportError:
            failures += 1
            log.warning("reddit unreachable; skipping the rest of this run")
            break
    if failures and not out:
        raise RuntimeError(f"reddit: {failures} fetch(es) failed and nothing was collected")
    return out
```

- [ ] **Step 4: Run the whole suite**

```powershell
python -m pytest -q
```

Expected: `52 passed`.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_collectors_social.py tests/fixtures/trends24_india.html tests/fixtures/getdaytrends_india.html tests/fixtures/yahoo_chart.json tests/fixtures/reddit_rising.xml radar/collectors/x_trends.py radar/collectors/markets.py radar/collectors/reddit.py
git commit -m "feat: X trends, market and Reddit collectors" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 8: Hook classifier and format scoreboard

Regex rules that label a video title with an angle type, plus the format scoreboard (median outlier score per angle type and format over 7 days). Order matters: the first matching rule wins.

**Files:**
- Create: `tests/test_hooks.py`
- Create: `radar/hooks.py`

**Interfaces:**
- Consumes: `Store` schema (`videos` table), `to_iso`
- Produces: `radar.hooks`: `RULES`, `classify(title) -> str` ('other' when nothing matches), `scoreboard(conn, now, days=7, min_videos=3) -> list[{angle, format, median, count, example}]`, `angle_multipliers(conn, now, days=7, min_videos=3) -> dict[str, float]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_hooks.py`

```python
from datetime import timedelta

from helpers import NOW

from radar import hooks
from radar.store import Store
from radar.timeutil import to_iso


def test_classify_examples():
    assert hooks.classify("5 mistakes to avoid with credit cards") == "mistakes_list"
    assert hooks.classify("FD vs Debt Fund: which is better?") == "data_compare"
    assert hooks.classify("₹10,000 SIP for 20 years = ?") == "what_if_calculator"
    assert hooks.classify("New tax rules from April 1") == "before_after_rule"
    assert hooks.classify("Is this a SCAM? Red flags in stock tips") == "red_flags"
    assert hooks.classify("Market update") == "other"


def insert_video(st, vid, is_short, outlier, hook):
    st.conn.execute(
        "INSERT INTO videos (video_id, channel_id, channel_name, title, url, published_at, is_short, views, "
        "first_seen_at, last_seen_at, outlier, hook_type) VALUES (?, 'UC1', 'Chan', ?, ?, ?, ?, 1000, ?, ?, ?, ?)",
        (vid, f"title {vid}", f"https://yt.test/{vid}", to_iso(NOW - timedelta(days=1)), is_short,
         to_iso(NOW), to_iso(NOW), outlier, hook))


def test_scoreboard_and_multipliers(tmp_path):
    st = Store(tmp_path / "r.db")
    for vid, is_short, outlier, hook in [("a", 1, 3.0, "mistakes_list"), ("b", 1, 5.0, "mistakes_list"),
                                         ("c", 1, 4.0, "mistakes_list"), ("d", 0, 1.0, "explainer"),
                                         ("e", 0, 1.2, "explainer"), ("f", 0, 0.8, "explainer"),
                                         ("g", 0, 9.0, "myth_bust")]:
        insert_video(st, vid, is_short, outlier, hook)
    board = hooks.scoreboard(st.conn, NOW)
    assert [(b["angle"], b["format"], b["median"], b["count"], b["example"]) for b in board] == [
        ("mistakes_list", "Short", 4.0, 3, "title b"), ("explainer", "Long", 1.0, 3, "title e")]
    assert hooks.angle_multipliers(st.conn, NOW) == {"mistakes_list": 4.0, "explainer": 1.0}
```

- [ ] **Step 2: Run the new tests and confirm they fail**

```powershell
python -m pytest tests/test_hooks.py -q
```

Expected: collection error `ImportError: cannot import name 'hooks'` (the module does not exist yet).

- [ ] **Step 3: Implement**

`radar/hooks.py`

```python
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
```

- [ ] **Step 4: Run the whole suite**

```powershell
python -m pytest -q
```

Expected: `54 passed`.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_hooks.py radar/hooks.py
git commit -m "feat: hook classifier and format scoreboard" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 9: YouTube collector and outlier scoring

YouTube RSS gives view counts within about 5% of the live count, and marks Shorts with a `/shorts/` link, so no API key is needed. `update_videos` runs in the main thread after collection. The baseline for a channel is the median projected 72-hour views of its stored videos, and outlier = views / (baseline * maturity(age)).

**Files:**
- Create: `tests/test_youtube.py`
- Create: `tests/fixtures/youtube_channel.xml`
- Create: `radar/collectors/youtube.py`

**Interfaces:**
- Consumes: `hooks.classify`, `Context`, `gather`, `clean`, `parse_date`, `from_iso`, `to_iso`
- Produces: `youtube.parse(raw, channel_id) -> list[Signal]` (metrics: views, is_short), `rotation(channels, run_index, groups)`, `collect(ctx)`, `maturity(age_hours) -> float`, `update_videos(conn, signals, channel_names, now, settings) -> list[Signal]` (tracked videos; metrics gain `age_h`, `outlier`).

- [ ] **Step 1: Write the failing tests**

`tests/test_youtube.py`

```python
import httpx
from helpers import NOW, fixture_bytes, make_ctx

from radar.collectors import youtube
from radar.config import load_config
from radar.store import Store


def test_parse_detects_shorts_and_views():
    sigs = youtube.parse(fixture_bytes("youtube_channel.xml"), "UCtest")
    assert len(sigs) == 5
    assert (sigs[0].key, sigs[0].metrics["is_short"], sigs[0].metrics["views"]) == ("vidShort001", 1.0, 12000.0)
    assert sigs[1].metrics["is_short"] == 0.0
    assert sigs[0].feed == "yt:UCtest"
    assert sigs[0].text == "Insurance stocks fell sharply today."


def test_rotation_splits_channels_into_groups():
    chans = [{"id": str(i)} for i in range(7)]
    assert [c["id"] for c in youtube.rotation(chans, 0, 3)] == ["0", "3", "6"]
    assert [c["id"] for c in youtube.rotation(chans, 4, 3)] == ["1", "4"]


def test_maturity_curve():
    assert youtube.maturity(72) == 1.0
    assert youtube.maturity(200) == 1.0
    assert youtube.maturity(0) == 0.15
    assert round(youtube.maturity(18), 3) == 0.5


def test_update_videos_scores_recent_uploads_against_channel_baseline(tmp_path):
    st = Store(tmp_path / "r.db")
    sigs = youtube.parse(fixture_bytes("youtube_channel.xml"), "UCtest")
    tracked = youtube.update_videos(st.conn, sigs, {"UCtest": "Test Creator"}, NOW, load_config().settings)
    # baseline = median of the three old videos (20k); the Short is 2 h old, the long video 5 h old
    assert [(s.key, s.metrics["outlier"]) for s in tracked] == [("vidShort001", 3.6), ("vidLong0001", 0.57)]
    row = st.conn.execute("SELECT channel_name, hook_type, outlier FROM videos WHERE video_id = 'vidLong0001'").fetchone()
    assert (row["channel_name"], row["hook_type"], row["outlier"]) == ("Test Creator", "mistakes_list", 0.57)
    assert st.conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 5


def test_collect_fetches_one_rotation_group():
    urls = []

    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200, content=fixture_bytes("youtube_channel.xml"))

    cfg = load_config()
    youtube.collect(make_ctx(handler, run_index=1, config=cfg))
    assert len(urls) == len(youtube.rotation(cfg.channels, 1, 3)) == 30
```

`tests/fixtures/youtube_channel.xml`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
 <title>Test Creator</title>
 <entry>
  <id>yt:video:vidShort001</id>
  <yt:videoId>vidShort001</yt:videoId>
  <yt:channelId>UCtest</yt:channelId>
  <title>Why Insurance companies crashed today? #shorts</title>
  <link rel="alternate" href="https://www.youtube.com/shorts/vidShort001"/>
  <published>2026-09-26T06:00:00+00:00</published>
  <updated>2026-09-26T06:10:00+00:00</updated>
  <media:group>
   <media:title>Why Insurance companies crashed today? #shorts</media:title>
   <media:description>Insurance stocks fell sharply today.</media:description>
   <media:community><media:starRating count="91" average="5.00" min="1" max="5"/><media:statistics views="12000"/></media:community>
  </media:group>
 </entry>
 <entry>
  <id>yt:video:vidLong0001</id>
  <yt:videoId>vidLong0001</yt:videoId>
  <yt:channelId>UCtest</yt:channelId>
  <title>5 mistakes to avoid in SIP</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=vidLong0001"/>
  <published>2026-09-26T03:00:00+00:00</published>
  <updated>2026-09-26T05:00:00+00:00</updated>
  <media:group>
   <media:title>5 mistakes to avoid in SIP</media:title>
   <media:description>Common SIP mistakes.</media:description>
   <media:community><media:starRating count="40" average="5.00" min="1" max="5"/><media:statistics views="3000"/></media:community>
  </media:group>
 </entry>
 <entry>
  <id>yt:video:vidOld00001</id>
  <yt:videoId>vidOld00001</yt:videoId>
  <yt:channelId>UCtest</yt:channelId>
  <title>Old video one</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=vidOld00001"/>
  <published>2026-09-22T08:00:00+00:00</published>
  <updated>2026-09-23T08:00:00+00:00</updated>
  <media:group><media:title>Old video one</media:title><media:description>One</media:description>
   <media:community><media:statistics views="20000"/></media:community></media:group>
 </entry>
 <entry>
  <id>yt:video:vidOld00002</id>
  <yt:videoId>vidOld00002</yt:videoId>
  <yt:channelId>UCtest</yt:channelId>
  <title>Old video two</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=vidOld00002"/>
  <published>2026-09-21T08:00:00+00:00</published>
  <updated>2026-09-22T08:00:00+00:00</updated>
  <media:group><media:title>Old video two</media:title><media:description>Two</media:description>
   <media:community><media:statistics views="24000"/></media:community></media:group>
 </entry>
 <entry>
  <id>yt:video:vidOld00003</id>
  <yt:videoId>vidOld00003</yt:videoId>
  <yt:channelId>UCtest</yt:channelId>
  <title>Old video three</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=vidOld00003"/>
  <published>2026-09-20T08:00:00+00:00</published>
  <updated>2026-09-21T08:00:00+00:00</updated>
  <media:group><media:title>Old video three</media:title><media:description>Three</media:description>
   <media:community><media:statistics views="16000"/></media:community></media:group>
 </entry>
</feed>
```

- [ ] **Step 2: Run the new tests and confirm they fail**

```powershell
python -m pytest tests/test_youtube.py -q
```

Expected: collection error `ImportError: cannot import name 'youtube'` (the module does not exist yet).

- [ ] **Step 3: Implement**

`radar/collectors/youtube.py`

```python
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
```

- [ ] **Step 4: Run the whole suite**

```powershell
python -m pytest -q
```

Expected: `59 passed`.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_youtube.py tests/fixtures/youtube_channel.xml radar/collectors/youtube.py
git commit -m "feat: YouTube collector with outlier scoring" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 10: New-phrase spike detection and emerging topics

Finds phrases (2-3 word n-grams) spiking over the last 2 hours against a 7-day baseline that also compares the same hour of day. A spike attaches to a known topic when 60% or more of its items already match one; otherwise it becomes an `emerging:<slug>` topic that lives 48 hours after its last sighting.

**Files:**
- Create: `tests/test_phrases.py`
- Create: `radar/phrases.py`

**Interfaces:**
- Consumes: `Config`, `Signal`, `Topic`, `EMERGING_ANGLES`, `normalize_title`, `slugify`, `ist`, `ist_hour_bucket`, `to_iso`
- Produces: `radar.phrases`: `PhraseSpike(phrase, item_ids, ratio, feeds, topic_id, emerging)`, `extract(title, source_type, stop, blocklist, min_chars) -> set[str]`, `record_counts(conn, new_items, now, cfg)`, `detect(conn, cfg, new_items, now) -> list[PhraseSpike]`, `active_emerging(conn, now, ttl_hours) -> list[Topic]`, `link_emerging(conn, new_items, topics, now)`, `prune_singletons(conn, now)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_phrases.py`

```python
from datetime import timedelta

from helpers import NOW

from radar.config import load_config
from radar.models import Signal
from radar.phrases import active_emerging, detect, extract, link_emerging
from radar.store import Store
from radar.timeutil import ist_hour_bucket, to_iso

CFG = load_config()
P = CFG.settings["phrases"]
STOP = frozenset(P["stopwords"].split())
BLOCK = frozenset(P["blocklist"])


def news(title, feed, minutes_ago=10, source_type="news"):
    return Signal(source="t", source_type=source_type, feed=feed, title=title, url=None,
                  published_at=NOW - timedelta(minutes=minutes_ago))


def test_extract_chunks_at_stopwords_and_numbers():
    # "to", "from" and "on" are stopwords and "15" is a number, so only the first chunk yields phrases
    got = extract("UPI MDR charges to apply from October 15 on SIPs", "news", STOP, BLOCK, 5)
    assert got == {"upi mdr", "mdr charges", "upi mdr charges"}


def test_extract_drops_phrases_containing_blocklisted_terms():
    got = extract("ABC Ltd closes trading window for insiders", "news", STOP, BLOCK, 5)
    assert got == {"abc ltd", "ltd closes", "closes trading", "abc ltd closes", "ltd closes trading"}


def test_extract_keeps_whole_trend_names():
    assert "plusgstlaunched" in extract("#PlusGSTLaunched", "x_trend", STOP, BLOCK, 5)


def test_extract_handles_devanagari_and_ampersand():
    assert "f&o नियम बदले" in extract("सेबी ने F&O नियम बदले", "news", STOP, BLOCK, 5)


def test_unknown_spike_becomes_emerging_topic(tmp_path):
    st = Store(tmp_path / "r.db")
    new = st.add_items([news("Zeta Bank collapse shocks depositors", "et"),
                        news("Zeta Bank collapse: what depositors must know", "mint"),
                        news("RBI steps in after Zeta Bank collapse", "bs"),
                        news("Zeta Bank collapse explained", "cnbc")], NOW)
    spikes = detect(st.conn, CFG, new, NOW)
    assert [(s.phrase, s.emerging, s.topic_id, s.feeds, len(s.item_ids)) for s in spikes] == [
        ("zeta bank collapse", True, "emerging:zeta-bank-collapse", 4, 4)]
    (topic,) = active_emerging(st.conn, NOW, 48)
    assert (topic.id, topic.name, topic.bucket) == ("emerging:zeta-bank-collapse", "Zeta Bank collapse", "markets")


def test_spike_attaches_to_matching_topic(tmp_path):
    st = Store(tmp_path / "r.db")
    new = st.add_items([news("UPI MDR charges from October 15", "et"), news("UPI MDR charges: banks explain", "mint"),
                        news("What UPI MDR charges mean for you", "bs")], NOW)
    for iid, _ in new:
        st.add_item_topics(iid, ["upi_payments"])
    spikes = detect(st.conn, CFG, new, NOW)
    assert [(s.phrase, s.topic_id, s.emerging) for s in spikes] == [("upi mdr charges", "upi_payments", False)]


def test_phrase_common_last_week_is_not_a_spike(tmp_path):
    st = Store(tmp_path / "r.db")
    st.conn.execute("INSERT INTO phrase_counts (hour, phrase, items) VALUES (?, 'upi mdr charges', 400)",
                    (ist_hour_bucket(NOW - timedelta(days=1)),))
    new = st.add_items([news("UPI MDR charges from October 15", "et"), news("UPI MDR charges: banks explain", "mint"),
                        news("What UPI MDR charges mean for you", "bs")], NOW)
    assert "upi mdr charges" not in {s.phrase for s in detect(st.conn, CFG, new, NOW)}


def test_non_finance_trend_phrase_is_ignored(tmp_path):
    st = Store(tmp_path / "r.db")
    new = st.add_items([news("Rise and Fall season finale", "trends24", source_type="x_trend"),
                        news("Rise and Fall season finale date", "google_trends", source_type="search_trend"),
                        news("Rise and Fall season finale winner", "getdaytrends", source_type="x_trend")], NOW)
    assert detect(st.conn, CFG, new, NOW) == []


def test_link_emerging_tags_new_items_and_expiry(tmp_path):
    st = Store(tmp_path / "r.db")
    st.conn.execute("INSERT INTO emerging_topics VALUES ('emerging:zeta-bank-collapse', 'zeta bank collapse', "
                    "'Zeta Bank collapse', 'markets', ?, ?)", (to_iso(NOW), to_iso(NOW)))
    topics = active_emerging(st.conn, NOW, 48)
    new = st.add_items([news("Depositors queue after Zeta Bank collapse", "et")], NOW)
    link_emerging(st.conn, new, topics, NOW)
    assert st.conn.execute("SELECT topic_id FROM item_topics").fetchone()[0] == "emerging:zeta-bank-collapse"
    assert active_emerging(st.conn, NOW + timedelta(hours=49), 48) == []
```

- [ ] **Step 2: Run the new tests and confirm they fail**

```powershell
python -m pytest tests/test_phrases.py -q
```

Expected: collection error `ModuleNotFoundError: No module named 'radar.phrases'` (the module does not exist yet).

- [ ] **Step 3: Implement**

`radar/phrases.py`

```python
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
```

- [ ] **Step 4: Run the whole suite**

```powershell
python -m pytest -q
```

Expected: `68 passed`.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_phrases.py radar/phrases.py
git commit -m "feat: new-phrase spike detection" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 11: Scorer: values, baselines, heat, stages, alert rule

The heart of the radar (spec section 10). Pure functions (baseline, z_score, points, heat, episode, stage, alert rule) are tested directly; `score_run` wires them to the database. Baselines use runs from the last 7 days within +-1 IST hour of now, count missing runs as zero, and shrink toward the priors with weight 4.

**Files:**
- Create: `tests/test_scorer.py`
- Create: `radar/scorer.py`

**Interfaces:**
- Consumes: `Topic`, `TopicScore`, `from_iso`, `ist`, `ist_day_start_utc`, `to_iso`
- Produces: `radar.scorer`: `baseline(samples, n_runs, mu0, sigma0, prior_weight) -> (mu, sigma)`, `z_score(value, mu, sigma, floor, min_value)`, `search_points(traffic, table)`, `x_points(rank, table)`, `heat_of(z, bonuses, weights, clip) -> (heat, n_sources)`, `Episode(started_at=None, below_watch_runs=0)`, `next_episode(ep, heat, now, watch, end_runs)`, `stage_of(heat, prev1, prev2, ep, now, watch, emerging_hours)`, `alert_kind(score, last_alert, sent_today, now, settings) -> 'hot' | 'capped' | None`, `score_run(conn, topics, now, settings) -> list[TopicScore]`, `decide_alerts(conn, scores, now, settings) -> list[(TopicScore, kind)]`, `record_alert(conn, topic_id, kind, now, heat, subject)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_scorer.py`

```python
from datetime import timedelta

from helpers import NOW

from radar.config import load_config
from radar.models import Signal, TopicScore
from radar.scorer import (Episode, alert_kind, baseline, decide_alerts, next_episode, score_run, search_points,
                          stage_of, x_points, z_score)
from radar.store import Store

CFG = load_config()
S = CFG.settings


def test_baseline_without_history_equals_priors():
    assert baseline([], 0, 1.0, 1.5, 48) == (1.0, 1.5)


def test_baseline_counts_missing_runs_as_zero():
    assert baseline([4.0, 4.0], 4, 0.0, 0.0, 0) == (2.0, 2.0)


def test_z_score_floor_and_min_value():
    assert z_score(2, 0.0, 0.1, 1.0, 3) == 0.0
    assert z_score(5, 1.0, 0.5, 1.0, 3) == 4.0


def test_bonus_point_tables():
    b = S["scoring"]["bonus"]
    assert search_points(50_000, b["search_trend"]) == 3
    assert search_points(600_000, b["search_trend"]) == 5
    assert search_points(500, b["search_trend"]) == 2
    assert x_points(7, b["x_trend"]) == 4
    assert x_points(30, b["x_trend"]) == 2


def simulate(heats, n_sources=3, bonuses=None):
    """Feed a heat series (one value per 15-minute run) through the episode, stage and alert logic."""
    sc = S["scoring"]
    ep, prev, last, sent, out = Episode(), [0.0, 0.0], None, 0, []
    for i, heat in enumerate(heats):
        now = NOW + timedelta(minutes=15 * i)
        ep = next_episode(ep, heat, now, sc["watch_threshold"], sc["episode_end_runs"])
        stage = stage_of(heat, prev[0], prev[1], ep, now, sc["watch_threshold"], sc["emerging_stage_hours"])
        kind = alert_kind(TopicScore("t", heat, stage, n_sources, bonuses=bonuses or {}, prev_heat=prev[0]),
                          last, sent, now, S)
        if kind == "hot":
            last, sent = (now, heat), sent + 1
        out.append((stage, kind))
        prev = [heat, prev[0]]
    return out


def test_sharp_spike_alerts_exactly_once():
    kinds = [k for _, k in simulate([1, 2, 9, 11, 12, 12, 10, 8])]
    assert kinds.count("hot") == 1 and kinds[2] == "hot"


def test_slow_drift_never_alerts():
    assert all(k is None for _, k in simulate([1, 1.5, 2, 2.5, 3, 3.5, 3.8]))


def test_fading_topic_does_not_alert():
    assert simulate([12, 10, 8, 7])[2:] == [("Fading", None), ("Fading", None)]


def test_episode_ends_after_four_quiet_runs():
    assert [stage for stage, _ in simulate([9, 3, 3, 3, 3])] == ["Emerging", "Fading", "Fading", "Fading", "Quiet"]


def test_cooldown_blocks_repeat_unless_heat_doubles():
    last = (NOW - timedelta(hours=3), 7.0)
    assert alert_kind(TopicScore("t", 8.0, "Peaking", 3, prev_heat=7.0), last, 0, NOW, S) is None
    assert alert_kind(TopicScore("t", 14.5, "Peaking", 3, prev_heat=9.0), last, 0, NOW, S) == "hot"
    assert alert_kind(TopicScore("t", 8.0, "Peaking", 3, prev_heat=7.0),
                      (NOW - timedelta(hours=13), 7.0), 0, NOW, S) == "hot"


def test_single_strong_bonus_can_alert_alone():
    assert alert_kind(TopicScore("t", 6.5, "Emerging", 1, bonuses={"x_trend": 4.0}), None, 0, NOW, S) == "hot"
    assert alert_kind(TopicScore("t", 6.5, "Emerging", 1, bonuses={"regulator": 2.0}), None, 0, NOW, S) is None


def test_decide_alerts_caps_per_ist_day(tmp_path):
    st = Store(tmp_path / "r.db")
    scores = [TopicScore(f"t{i}", 10.0 + i, "Emerging", 3) for i in range(5)]
    assert [k for _, k in decide_alerts(st.conn, scores, NOW, S)] == ["hot", "hot", "hot", "hot", "capped"]


def test_score_run_gold_record_worked_example(tmp_path):
    st = Store(tmp_path / "r.db")
    sigs = [Signal(source="t", source_type="news", feed=f"f{i}", title=f"Gold hits record high {i}", url=None,
                   published_at=NOW - timedelta(minutes=20)) for i in range(14)]
    sigs.append(Signal(source="google_trends", source_type="search_trend", feed="google_trends_in",
                       title="gold rate today", url=None, published_at=NOW, metrics={"approx_traffic": 50000.0}))
    sigs.append(Signal(source="markets", source_type="market", feed="yahoo:GC=F", title="Gold futures up 2.3% today",
                       url=None, published_at=NOW, metrics={"pct_move": 2.3, "threshold": 2.0},
                       key="GC=F:up:2026-09-26", topic_hint="gold_price"))
    for iid, _ in st.add_items(sigs, NOW):
        st.add_item_topics(iid, ["gold_price"])
    scores = {s.topic_id: s for s in score_run(st.conn, list(CFG.topics), NOW, S)}
    gold = scores["gold_price"]
    assert gold.values["news"] == 14 and gold.z["news"] == 8.67
    assert gold.bonuses == {"search_trend": 3.0, "market": 3.0}
    assert (gold.heat, gold.n_sources, gold.stage) == (12.0, 3, "Emerging")
    assert [k for _, k in decide_alerts(st.conn, [gold], NOW, S)] == ["hot"]


def test_score_run_slow_drift_worked_example(tmp_path):
    st = Store(tmp_path / "r.db")
    sigs = [Signal(source="t", source_type="news", feed=f"f{i}", title=f"Gold edges up {i}", url=None,
                   published_at=NOW - timedelta(minutes=20)) for i in range(4)]
    for iid, _ in st.add_items(sigs, NOW):
        st.add_item_topics(iid, ["gold_price"])
    gold = {s.topic_id: s for s in score_run(st.conn, list(CFG.topics), NOW, S)}["gold_price"]
    assert (gold.heat, gold.stage) == (2.0, "Quiet")
    assert decide_alerts(st.conn, [gold], NOW, S) == []
```

- [ ] **Step 2: Run the new tests and confirm they fail**

```powershell
python -m pytest tests/test_scorer.py -q
```

Expected: collection error `ModuleNotFoundError: No module named 'radar.scorer'` (the module does not exist yet).

- [ ] **Step 3: Implement**

`radar/scorer.py`

```python
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
```

- [ ] **Step 4: Run the whole suite**

```powershell
python -m pytest -q
```

Expected: `81 passed`.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_scorer.py radar/scorer.py
git commit -m "feat: topic scoring and alert rule" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 12: Briefs, events and digest data

Turns a scored topic into a brief: headline, up to 6 evidence lines, 3 angles with filled hooks, and the creator videos beating their normal views. Also assembles the daily digest data and upcoming events.

**Files:**
- Create: `tests/test_briefs_digest.py`
- Create: `radar/briefs.py`
- Create: `radar/events.py`
- Create: `radar/digest.py`

**Interfaces:**
- Consumes: `Config`, `BUCKETS`, `Brief`, `Topic`, `TopicScore`, `hooks.scoreboard`, `phrases.active_emerging`
- Produces: `radar.briefs`: `STAGE_BOOST`, `select_angles(topic, stage, multipliers, n=3)`, `fill_hook(hook, topic, headline)`, `format_traffic(n)`, `build_brief(conn, cfg, topic, score, now, multipliers, spiking_phrases) -> Brief`. `radar.events.upcoming(events, today, days)`. `radar.digest`: `DigestData(date_label, top, near_misses, scoreboard, events, health)`, `topic_catalog(conn, cfg, now) -> dict[str, Topic]`, `build_digest(conn, cfg, now) -> DigestData`.

- [ ] **Step 1: Write the failing tests**

`tests/test_briefs_digest.py`

```python
from datetime import date, datetime, timedelta, timezone

from helpers import NOW

from radar.briefs import build_brief, fill_hook, format_traffic, select_angles
from radar.config import load_config
from radar.digest import build_digest
from radar.events import upcoming
from radar.models import Signal, Topic, TopicScore
from radar.store import Store
from radar.timeutil import to_iso

CFG = load_config()


def test_select_angles_prefers_scoreboard_then_stage_then_order():
    t = Topic("x", "X", "markets", ("x",), ("explainer", "myth_bust", "checklist", "hot_take_news"))
    assert select_angles(t, "Emerging", {}) == ["explainer", "hot_take_news", "myth_bust"]
    assert select_angles(t, "Peaking", {"checklist": 3.0}) == ["checklist", "myth_bust", "explainer"]


def test_fill_hook_avoids_double_punctuation():
    hook = "{headline}. Here's what it means for your money."
    assert fill_hook(hook, "Gold", "Is gold back at a record?") == "Is gold back at a record? Here's what it means for your money."
    assert fill_hook(hook, "Gold", "Gold hits record") == "Gold hits record. Here's what it means for your money."


def test_format_traffic():
    assert (format_traffic(50_000), format_traffic(2_000_000), format_traffic(500)) == ("50K+", "2M+", "500+")


def test_build_brief_collects_evidence_and_angles(tmp_path):
    st = Store(tmp_path / "r.db")
    sigs = [Signal(source="t", source_type="news", feed="et", title="Gold hits record high as rupee weakens",
                   url="https://n.test/1", published_at=NOW - timedelta(minutes=10)),
            Signal(source="google_trends", source_type="search_trend", feed="google_trends_in", title="gold rate today",
                   url="https://g.test/1", published_at=NOW - timedelta(minutes=80), metrics={"approx_traffic": 50000.0}),
            Signal(source="x_trends", source_type="x_trend", feed="trends24", title="#GoldPrice",
                   url="https://x.com/search?q=%23GoldPrice", published_at=NOW, metrics={"rank": 9.0})]
    for iid, _ in st.add_items(sigs, NOW):
        st.add_item_topics(iid, ["gold_price"])
    score = TopicScore("gold_price", 12.0, "Emerging", 3, values={"news": 1.0}, mu={"news": 2.0},
                       bonuses={"search_trend": 3.0, "x_trend": 4.0})
    b = build_brief(st.conn, CFG, CFG.topic_map["gold_price"], score, NOW, {}, ["gold record high"])
    assert (b.headline, b.urgency) == ("Gold hits record high as rupee weakens", "post within 3h")
    assert [e[0] for e in b.evidence] == [
        "Google Trends India: 'gold rate today' 50K+ searches, trending since 12:10 IST",
        "News: 1 article in the last hour (normally about 2)",
        "X India trending: #GoldPrice, rank 9"]
    assert [a["name"] for a in b.angles] == ["Plain-language explainer", "Data comparison", "History lesson"]
    assert b.angles[0]["hook"] == "Gold & silver prices, explained in 60 seconds."
    assert b.phrases == ["gold record high"]


def test_upcoming_events_window_and_ranges():
    evs = [{"date": date(2026, 10, 7), "name": "RBI", "topic": "rbi_policy"},
           {"date": date(2026, 9, 1), "date_end": date(2026, 9, 30), "name": "Season", "topic": "earnings_results"},
           {"date": date(2026, 12, 4), "name": "Later", "topic": "rbi_policy"}]
    assert [e["name"] for e in upcoming(evs, date(2026, 9, 30), 7)] == ["Season", "RBI"]


def test_build_digest_sections(tmp_path):
    now = datetime(2026, 10, 2, 3, 0, tzinfo=timezone.utc)  # 08:30 IST, 5 days before the RBI decision
    st = Store(tmp_path / "r.db")
    run = to_iso(now - timedelta(hours=1))
    st.conn.execute("INSERT INTO runs VALUES (?, 7)", (run,))
    st.conn.executemany("INSERT INTO topic_heat VALUES (?, ?, ?, ?, ?)",
                        [(run, "gold_price", 12.0, "Peaking", 3), (run, "rbi_policy", 4.5, "Emerging", 1)])
    st.conn.execute("INSERT INTO alerts (topic_id, kind, sent_at, heat, subject) VALUES ('gold_price', 'hot', ?, 12, 's')",
                    (run,))
    st.conn.commit()
    st.record_health("reddit", "HTTPStatusError: 403", now)
    d = build_digest(st.conn, CFG, now)
    assert d.date_label == "02 Oct"
    assert [(t["name"], t["status"], t["stage"]) for t in d.top] == [
        ("Gold & silver prices", "sent", "Peaking"), ("RBI policy & rates", "none", "Emerging")]
    assert [n["name"] for n in d.near_misses] == ["RBI policy & rates"]
    assert d.events == [{"date": "07 Oct", "name": "RBI MPC policy decision",
                         "angles": ["Plain-language explainer", "Run the numbers"]}]
    assert d.health == ["reddit: failing, last success never succeeded (HTTPStatusError: 403)"]
```

- [ ] **Step 2: Run the new tests and confirm they fail**

```powershell
python -m pytest tests/test_briefs_digest.py -q
```

Expected: collection error `ModuleNotFoundError: No module named 'radar.briefs'` (the module does not exist yet).

- [ ] **Step 3: Implement**

`radar/briefs.py`

```python
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
```

`radar/events.py`

```python
"""Upcoming dated events for the digest's "Coming up" section."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable


def upcoming(events: Iterable[dict[str, Any]], today: date, days: int) -> list[dict[str, Any]]:
    horizon = today + timedelta(days=days)
    return sorted((e for e in events if e.get("date_end", e["date"]) >= today and e["date"] <= horizon),
                  key=lambda e: e["date"])
```

`radar/digest.py`

```python
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
```

- [ ] **Step 4: Run the whole suite**

```powershell
python -m pytest -q
```

Expected: `87 passed`.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_briefs_digest.py radar/briefs.py radar/events.py radar/digest.py
git commit -m "feat: briefs, events and digest data" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 13: Email rendering and delivery

Jinja2 templates with neutral styling and no emoji. `send` uses Gmail SMTP with STARTTLS and retries once. `write_preview` is the dry-run path.

**Files:**
- Create: `tests/test_emailer.py`
- Create: `radar/emailer.py`
- Create: `radar/templates/hot.html`
- Create: `radar/templates/hot.txt`
- Create: `radar/templates/digest.html`
- Create: `radar/templates/digest.txt`

**Interfaces:**
- Consumes: `Brief`, `DigestData`, `BUCKETS`, `slugify`
- Produces: `radar.emailer`: `EmailError`, `hot_subject(brief)`, `render_hot(brief) -> (subject, text, html)`, `render_digest(data, angle_names) -> (subject, text, html)`, `send(subject, text, html, *, settings, env, smtp_factory=smtplib.SMTP)`, `write_preview(subject, html, *, out_dir, kind, slug, now) -> Path`.

- [ ] **Step 1: Write the failing tests**

`tests/test_emailer.py`

```python
import re
import smtplib

import pytest
from helpers import NOW

from radar.config import load_config
from radar.digest import DigestData
from radar.emailer import EmailError, hot_subject, render_digest, render_hot, send, write_preview
from radar.models import Brief, Topic, TopicScore

EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿]")
ENV = {"SMTP_USER": "radar@example.test", "SMTP_APP_PASSWORD": "app-pass",
       "ALERT_TO": "founder@example.test, team@example.test"}
SETTINGS = load_config().settings


def brief():
    topic = Topic("gold_price", "Gold & silver prices", "markets", ("gold",), ("explainer",))
    return Brief(topic=topic, score=TopicScore("gold_price", 12.0, "Emerging", 3), urgency="post within 3h",
                 headline="Gold hits record high as rupee weakens and investors rush to safety in a big way",
                 headline_url="https://n.test/1",
                 evidence=[("News: 14 articles in the last hour (normally about 2)", "https://n.test/1")],
                 phrases=["gold record high"],
                 angles=[{"name": "Plain-language explainer", "linkedin": "Carousel", "x": "Thread",
                          "instagram": "Reel", "hook": "Gold & silver prices, explained in 60 seconds."}],
                 hooks_now=[{"title": "Gold at record?", "creator": "Asset Yogi", "format": "Short", "score": "4.1x",
                             "url": "https://yt.test/1"}])


def test_hot_subject_format_and_truncation():
    subject = hot_subject(brief())
    assert subject == ("HOT [Markets & macro] Gold & silver prices: "
                       "Gold hits record high as rupee weakens and investors rush... — post within 3h")


def test_render_hot_has_every_section_and_no_emoji():
    subject, text, html = render_hot(brief())
    for part in ("Why now", "Angles", "Hooks working right now", "LinkedIn", "Instagram", "Gold &amp; silver prices"):
        assert part in html
    assert 'Hook: "Gold & silver prices, explained in 60 seconds."' in text
    assert not EMOJI.search(subject + text + html)


def test_render_digest_sections():
    d = DigestData(date_label="02 Oct", top=[{"name": "Gold & silver prices", "bucket": "Markets & macro", "peak": 12.0,
                                              "stage": "Peaking", "status": "sent", "evidence": "Gold hits record",
                                              "url": "https://n.test/1"}], health=["All sources OK"])
    subject, text, html = render_digest(d, {"mistakes_list": "Common mistakes"})
    assert subject == "Radar digest 02 Oct — 1 trends"
    for part in ("Top trends", "Near misses", "Format scoreboard", "Coming up", "Source health", "All sources OK"):
        assert part in html and part in text


class FakeSMTP:
    sent: list = []

    def __init__(self, host, port, timeout):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def test_send_builds_multipart_message():
    FakeSMTP.sent.clear()
    send("HOT subject", "text body", "<p>html</p>", settings=SETTINGS, env=ENV, smtp_factory=FakeSMTP)
    msg = FakeSMTP.sent[0]
    assert msg["To"] == "founder@example.test, team@example.test"
    assert msg["From"] == "Truwealth Radar <radar@example.test>"
    assert msg.get_body(("plain",)).get_content().strip() == "text body"


def test_send_retries_once_then_raises():
    class Broken(FakeSMTP):
        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    with pytest.raises(EmailError):
        send("s", "t", "<p>h</p>", settings=SETTINGS, env=ENV, smtp_factory=Broken)


def test_missing_credentials_raise():
    with pytest.raises(EmailError, match="SMTP_USER"):
        send("s", "t", "h", settings=SETTINGS, env={}, smtp_factory=FakeSMTP)


def test_write_preview(tmp_path):
    path = write_preview("HOT x", "<p>x</p>", out_dir=tmp_path, kind="hot", slug="gold_price", now=NOW)
    assert path.name == "20260926T080000Z-hot-gold-price.html"
    assert path.read_text(encoding="utf-8") == "<p>x</p>"
```

- [ ] **Step 2: Run the new tests and confirm they fail**

```powershell
python -m pytest tests/test_emailer.py -q
```

Expected: collection error `ModuleNotFoundError: No module named 'radar.emailer'` (the module does not exist yet).

- [ ] **Step 3: Implement**

`radar/emailer.py`

```python
"""Render and deliver HOT alerts and the digest (spec section 12)."""
from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Callable, Mapping

from jinja2 import Environment, FileSystemLoader, select_autoescape

from radar.config import BUCKETS
from radar.digest import DigestData
from radar.models import Brief
from radar.text import slugify

log = logging.getLogger(__name__)
_ENV = Environment(loader=FileSystemLoader(str(Path(__file__).resolve().parent / "templates")),
                   autoescape=select_autoescape(["html"]))


class EmailError(RuntimeError):
    pass


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 3].rstrip() + "..."


def hot_subject(brief: Brief) -> str:
    bucket = BUCKETS.get(brief.topic.bucket, "Emerging")
    if brief.headline and brief.headline != brief.topic.name:
        return f"HOT [{bucket}] {brief.topic.name}: {_truncate(brief.headline, 60)} — {brief.urgency}"
    return f"HOT [{bucket}] {brief.topic.name} — {brief.urgency}"


def render_hot(brief: Brief) -> tuple[str, str, str]:
    ctx = {"brief": brief, "bucket": BUCKETS.get(brief.topic.bucket, "Emerging")}
    return hot_subject(brief), _ENV.get_template("hot.txt").render(**ctx), _ENV.get_template("hot.html").render(**ctx)


def render_digest(data: DigestData, angle_names: Mapping[str, str]) -> tuple[str, str, str]:
    subject = f"Radar digest {data.date_label} — {len(data.top)} trends"
    ctx = {"d": data, "angle_names": dict(angle_names)}
    return subject, _ENV.get_template("digest.txt").render(**ctx), _ENV.get_template("digest.html").render(**ctx)


def _credentials(env: Mapping[str, str]) -> tuple[str, str, list[str]]:
    user, password, to = env.get("SMTP_USER"), env.get("SMTP_APP_PASSWORD"), env.get("ALERT_TO")
    if not (user and password and to):
        raise EmailError("SMTP_USER, SMTP_APP_PASSWORD and ALERT_TO must be set (or use --dry-run)")
    return user, password, [a.strip() for a in to.split(",") if a.strip()]


def send(subject: str, text: str, html: str, *, settings: dict, env: Mapping[str, str],
         smtp_factory: Callable[..., smtplib.SMTP] = smtplib.SMTP) -> None:
    """Send one email over STARTTLS, retrying once."""
    user, password, to = _credentials(env)
    cfg = settings["email"]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((cfg["sender_name"], user))
    msg["To"] = ", ".join(to)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    error: Exception | None = None
    for attempt in (1, 2):
        try:
            with smtp_factory(cfg["smtp_host"], cfg["smtp_port"], timeout=30) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(user, password)
                smtp.send_message(msg)
            return
        except (smtplib.SMTPException, OSError) as exc:
            error = exc
            log.warning("email send attempt %d failed: %s", attempt, type(exc).__name__)
    raise EmailError(f"email send failed: {type(error).__name__}") from error


def write_preview(subject: str, html: str, *, out_dir: Path, kind: str, slug: str, now: datetime) -> Path:
    """Dry-run delivery: write the HTML to out/ and print the subject."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{now.strftime('%Y%m%dT%H%M%SZ')}-{kind}-{slugify(slug)}.html"
    path.write_text(html, encoding="utf-8")
    print(f"[dry-run] {subject} -> {path}")
    return path
```

`radar/templates/hot.html`

```html
<!doctype html>
<html><body style="font-family: Arial, sans-serif; color: #111; max-width: 680px;">
<p style="color: #555; margin: 0;">{{ bucket }} &middot; {{ brief.score.stage }} &middot; {{ brief.urgency }}</p>
<h2 style="margin: 4px 0 12px;">{{ brief.topic.name }}</h2>
<p><strong>Headline:</strong> {% if brief.headline_url %}<a href="{{ brief.headline_url }}">{{ brief.headline }}</a>{% else %}{{ brief.headline }}{% endif %}</p>
<h3>Why now</h3>
<ul>{% for text, url in brief.evidence %}<li>{% if url %}<a href="{{ url }}">{{ text }}</a>{% else %}{{ text }}{% endif %}</li>{% endfor %}</ul>
{% if brief.phrases %}<p><strong>Spiking phrases:</strong> {{ brief.phrases | join(", ") }}</p>{% endif %}
<h3>Angles</h3>
{% for a in brief.angles %}
<p style="margin-bottom: 4px;"><strong>{{ loop.index }}. {{ a.name }}</strong><br>Hook: "{{ a.hook }}"</p>
<table cellpadding="4" style="border-collapse: collapse; margin-bottom: 12px;">
<tr><td style="color: #555;">LinkedIn</td><td>{{ a.linkedin }}</td></tr>
<tr><td style="color: #555;">X</td><td>{{ a.x }}</td></tr>
<tr><td style="color: #555;">Instagram</td><td>{{ a.instagram }}</td></tr>
</table>
{% endfor %}
{% if brief.hooks_now %}<h3>Hooks working right now</h3>
<ul>{% for h in brief.hooks_now %}<li><a href="{{ h.url }}">{{ h.title }}</a> by {{ h.creator }} ({{ h.format }}, {{ h.score }} normal views)</li>{% endfor %}</ul>{% endif %}
<p style="color: #777; font-size: 12px;">Heat {{ brief.score.heat }} from {{ brief.score.n_sources }} sources. Truwealth Radar.</p>
</body></html>
```

`radar/templates/hot.txt`

```text
{{ bucket }} | {{ brief.score.stage }} | {{ brief.urgency }}
{{ brief.topic.name }}

Headline: {{ brief.headline }}{% if brief.headline_url %}
{{ brief.headline_url }}{% endif %}

Why now:
{% for text, url in brief.evidence %}- {{ text }}{% if url %} ({{ url }}){% endif %}
{% endfor %}{% if brief.phrases %}
Spiking phrases: {{ brief.phrases | join(", ") }}
{% endif %}
Angles:
{% for a in brief.angles %}{{ loop.index }}. {{ a.name }}
   Hook: "{{ a.hook }}"
   LinkedIn: {{ a.linkedin }}
   X: {{ a.x }}
   Instagram: {{ a.instagram }}
{% endfor %}{% if brief.hooks_now %}
Hooks working right now:
{% for h in brief.hooks_now %}- {{ h.title }} by {{ h.creator }} ({{ h.format }}, {{ h.score }} normal views) {{ h.url }}
{% endfor %}{% endif %}
Heat {{ brief.score.heat }} from {{ brief.score.n_sources }} sources. Truwealth Radar.
```

`radar/templates/digest.html`

```html
<!doctype html>
<html><body style="font-family: Arial, sans-serif; color: #111; max-width: 680px;">
<h2 style="margin-bottom: 4px;">Radar digest, {{ d.date_label }}</h2>
<h3>Top trends, last 24 hours</h3>
{% if d.top %}<table cellpadding="4" style="border-collapse: collapse;">
<tr style="color: #555; text-align: left;"><th>Topic</th><th>Peak</th><th>Stage now</th><th>Alert</th><th>Evidence</th></tr>
{% for t in d.top %}<tr><td>{{ t.name }}<br><span style="color: #777; font-size: 12px;">{{ t.bucket }}</span></td><td>{{ t.peak }}</td><td>{{ t.stage }}</td><td>{{ t.status }}</td><td>{% if t.url %}<a href="{{ t.url }}">{{ t.evidence }}</a>{% else %}{{ t.evidence }}{% endif %}</td></tr>
{% endfor %}</table>{% else %}<p>No trending topics in the last 24 hours.</p>{% endif %}
<h3>Near misses</h3>
{% if d.near_misses %}<ul>{% for n in d.near_misses %}<li>{{ n.name }} ({{ n.bucket }}), peak {{ n.peak }}</li>{% endfor %}</ul>{% else %}<p>None.</p>{% endif %}
<h3>Format scoreboard, last 7 days</h3>
{% if d.scoreboard %}<ul>{% for s in d.scoreboard %}<li>{{ angle_names.get(s.angle, s.angle) }}, {{ s.format }}: {{ s.median }}x normal views over {{ s.count }} videos. Example: "{{ s.example }}"</li>{% endfor %}</ul>{% else %}<p>Not enough scored videos yet.</p>{% endif %}
<h3>Coming up, next 7 days</h3>
{% if d.events %}<ul>{% for e in d.events %}<li>{{ e.date }}: {{ e.name }}. Prep ideas: {{ e.angles | join(", ") }}</li>{% endfor %}</ul>{% else %}<p>No dated events.</p>{% endif %}
<h3>Source health</h3>
<ul>{% for h in d.health %}<li>{{ h }}</li>{% endfor %}</ul>
</body></html>
```

`radar/templates/digest.txt`

```text
Radar digest, {{ d.date_label }}

Top trends, last 24 hours:
{% for t in d.top %}- {{ t.name }} [{{ t.bucket }}] peak {{ t.peak }}, stage {{ t.stage }}, alert {{ t.status }}{% if t.evidence %}: {{ t.evidence }}{% endif %}{% if t.url %} ({{ t.url }}){% endif %}
{% else %}- No trending topics in the last 24 hours.
{% endfor %}
Near misses:
{% for n in d.near_misses %}- {{ n.name }} ({{ n.bucket }}), peak {{ n.peak }}
{% else %}- None.
{% endfor %}
Format scoreboard, last 7 days:
{% for s in d.scoreboard %}- {{ angle_names.get(s.angle, s.angle) }}, {{ s.format }}: {{ s.median }}x normal views over {{ s.count }} videos. Example: "{{ s.example }}"
{% else %}- Not enough scored videos yet.
{% endfor %}
Coming up, next 7 days:
{% for e in d.events %}- {{ e.date }}: {{ e.name }}. Prep ideas: {{ e.angles | join(", ") }}
{% else %}- No dated events.
{% endfor %}
Source health:
{% for h in d.health %}- {{ h }}
{% endfor %}
```

- [ ] **Step 4: Run the whole suite**

```powershell
python -m pytest -q
```

Expected: `94 passed`.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_emailer.py radar/emailer.py radar/templates/hot.html radar/templates/hot.txt radar/templates/digest.html radar/templates/digest.txt
git commit -m "feat: email rendering and delivery" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 14: Pipeline and CLI

Wires everything into one run. Includes the 24-hour warm-up (no HOT alerts right after the first run, because every busy topic looks unusual against the priors), the X-mirror 55-minute gap, and the circuit breaker (a collector that failed 3 runs in a row is retried at most hourly).

**Files:**
- Create: `tests/test_pipeline.py`
- Create: `radar/pipeline.py`
- Create: `radar/__main__.py`

**Interfaces:**
- Consumes: everything above
- Produces: `radar.pipeline`: `COLLECTORS`, `select_collectors(available, store, now, settings)`, `warming_up(store, now, settings) -> bool`, `fresh(signals, now, max_age_hours)`, `run(cfg, store, http, now, *, dry_run, out_dir, env, collectors=None) -> int` (exit code), `digest(cfg, store, now, *, dry_run, out_dir, env) -> int`. `radar.__main__.main(argv=None) -> int`.

- [ ] **Step 1: Write the failing tests**

`tests/test_pipeline.py`

```python
from datetime import timedelta

from helpers import NOW

from radar import pipeline
from radar.__main__ import main
from radar.config import load_config
from radar.models import Signal
from radar.store import Store

CFG = load_config()


def fake_collectors():
    def news(ctx):
        return [Signal(source="news_feeds", source_type="news", feed=f"feed{i}",
                       title=f"Gold hits record high as rupee weakens {i}", url=f"https://n.test/{i}",
                       published_at=ctx.now - timedelta(minutes=5)) for i in range(14)]

    def trends(ctx):
        return [Signal(source="google_trends", source_type="search_trend", feed="google_trends_in",
                       title="gold rate today", url="https://g.test/1", published_at=ctx.now - timedelta(minutes=30),
                       text="Gold price today: 24K rate jumps", metrics={"approx_traffic": 50000.0})]

    def market(ctx):
        return [Signal(source="markets", source_type="market", feed="yahoo:GC=F", title="Gold futures up 2.3% today",
                       url="https://y.test/1", published_at=ctx.now, metrics={"pct_move": 2.3, "threshold": 2.0},
                       key="GC=F:up:2026-09-26", topic_hint="gold_price")]

    def broken(ctx):
        raise RuntimeError("feed down")

    return {"news_feeds": news, "google_trends": trends, "markets": market, "reddit": broken}


def run_once(st, out, now=NOW, collectors=None):
    return pipeline.run(CFG, st, None, now, dry_run=True, out_dir=out, env={},
                        collectors=fake_collectors() if collectors is None else collectors)


def past_warmup(st):
    st.set_kv("first_run_at", "2026-09-24T00:00:00+00:00")
    return st


def test_first_day_is_warm_up_without_alerts(tmp_path):
    st = Store(tmp_path / "r.db")
    assert run_once(st, tmp_path / "out") == 0
    assert st.get_kv("first_run_at") == "2026-09-26T08:00:00+00:00"
    assert st.conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 0
    assert st.conn.execute("SELECT heat FROM topic_heat WHERE topic_id = 'gold_price'").fetchone()[0] == 12.0
    assert not (tmp_path / "out").exists()


def test_run_sends_one_hot_alert_in_dry_run(tmp_path):
    st = past_warmup(Store(tmp_path / "r.db"))
    assert run_once(st, tmp_path / "out") == 0
    (preview,) = (tmp_path / "out").glob("*-hot-gold-price.html")
    html = preview.read_text(encoding="utf-8")
    assert "Why now" in html and "Google Trends India" in html and "Market: Gold futures up 2.3% today" in html
    assert [(r["topic_id"], r["kind"]) for r in st.conn.execute("SELECT topic_id, kind FROM alerts")] == [
        ("gold_price", "hot")]
    health = {r["source"]: r["consecutive_failures"] for r in st.health_rows()}
    assert health == {"google_trends": 0, "markets": 0, "news_feeds": 0, "reddit": 1}
    assert st.get_kv("run_index") == "1"


def test_second_run_respects_cooldown(tmp_path):
    st = past_warmup(Store(tmp_path / "r.db"))
    run_once(st, tmp_path / "out")
    run_once(st, tmp_path / "out", now=NOW + timedelta(minutes=15))
    assert st.conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 1


def test_run_exits_1_when_every_collector_fails(tmp_path):
    def broken(ctx):
        raise RuntimeError("down")

    assert run_once(Store(tmp_path / "r.db"), tmp_path / "out", collectors={"reddit": broken}) == 1


def test_x_trends_is_skipped_within_55_minutes(tmp_path):
    st = Store(tmp_path / "r.db")
    st.set_kv("x_trends_last_fetch", "2026-09-26T07:30:00+00:00")
    assert "x_trends" not in pipeline.select_collectors(pipeline.COLLECTORS, st, NOW, CFG.settings)
    assert "x_trends" in pipeline.select_collectors(pipeline.COLLECTORS, st, NOW + timedelta(minutes=30), CFG.settings)


def test_failing_collector_is_retried_at_most_hourly(tmp_path):
    st = Store(tmp_path / "r.db")
    for minutes_ago in (50, 35, 20):
        st.record_health("reddit", "RuntimeError: down", NOW - timedelta(minutes=minutes_ago))
    assert "reddit" not in pipeline.select_collectors(pipeline.COLLECTORS, st, NOW, CFG.settings)
    assert "reddit" in pipeline.select_collectors(pipeline.COLLECTORS, st, NOW + timedelta(minutes=45), CFG.settings)


def test_digest_dry_run_writes_preview(tmp_path):
    assert pipeline.digest(CFG, Store(tmp_path / "r.db"), NOW, dry_run=True, out_dir=tmp_path / "out", env={}) == 0
    assert len(list((tmp_path / "out").glob("*-digest-daily.html"))) == 1


def test_cli_digest_dry_run(tmp_path):
    assert main(["digest", "--dry-run", "--db", str(tmp_path / "r.db"), "--out", str(tmp_path / "out")]) == 0
    assert list((tmp_path / "out").glob("*-digest-daily.html"))
```

- [ ] **Step 2: Run the new tests and confirm they fail**

```powershell
python -m pytest tests/test_pipeline.py -q
```

Expected: collection error `ImportError: cannot import name 'pipeline'` (the module does not exist yet).

- [ ] **Step 3: Implement**

`radar/pipeline.py`

```python
"""One radar run and the daily digest, wiring all modules together."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from radar import briefs, emailer, hooks, phrases, scorer
from radar import digest as digest_mod
from radar.collectors import Collector, Context, run_all
from radar.collectors import google_news, google_trends, markets, news_feeds, reddit, regulators, x_trends, youtube
from radar.config import Config
from radar.matcher import Matcher
from radar.models import Signal
from radar.store import Store
from radar.timeutil import from_iso, to_iso

log = logging.getLogger(__name__)

COLLECTORS: dict[str, Collector] = {
    "google_trends": google_trends.collect,
    "google_news": google_news.collect,
    "news_feeds": news_feeds.collect,
    "regulators": regulators.collect,
    "x_trends": x_trends.collect,
    "youtube": youtube.collect,
    "reddit": reddit.collect,
    "markets": markets.collect,
}


def select_collectors(available: Mapping[str, Collector], store: Store, now: datetime,
                      settings: dict) -> dict[str, Collector]:
    """All collectors, minus the X mirrors if fetched under 55 minutes ago, minus sources on circuit breaker."""
    selected = dict(available)
    last = store.get_kv("x_trends_last_fetch")
    gap = timedelta(minutes=settings["x_trends"]["min_interval_minutes"])
    if "x_trends" in selected and last and now - from_iso(last) < gap:
        del selected["x_trends"]
    run = settings["run"]
    for row in store.health_rows():
        if (row["source"] in selected and row["consecutive_failures"] >= run["breaker_failures"]
                and now - from_iso(row["last_error_at"]) < timedelta(minutes=run["breaker_retry_minutes"])):
            del selected[row["source"]]
    return selected


def warming_up(store: Store, now: datetime, settings: dict) -> bool:
    """True during the first `warmup_hours` after the very first run, while baselines are still empty."""
    first = store.get_kv("first_run_at")
    if first is None:
        store.set_kv("first_run_at", to_iso(now))
        first = to_iso(now)
    return now - from_iso(first) < timedelta(hours=settings["alerts"]["warmup_hours"])


def fresh(signals: list[Signal], now: datetime, max_age_hours: float) -> list[Signal]:
    return [s for s in signals if s.published_at is None or now - s.published_at <= timedelta(hours=max_age_hours)]


def run(cfg: Config, store: Store, http: Any, now: datetime, *, dry_run: bool, out_dir: Path,
        env: Mapping[str, str], collectors: Mapping[str, Collector] | None = None) -> int:
    """One radar cycle. Returns the process exit code."""
    s = cfg.settings
    run_index = int(store.get_kv("run_index") or 0)
    selected = select_collectors(COLLECTORS if collectors is None else collectors, store, now, s)
    signals, results = run_all(selected, Context(http=http, config=cfg, now=now, run_index=run_index),
                               workers=s["run"]["collector_workers"])
    for name, error in results.items():
        store.record_health(name, error, now)
    if "x_trends" in results and results["x_trends"] is None:
        store.set_kv("x_trends_last_fetch", to_iso(now))
    all_failed = bool(results) and all(error is not None for error in results.values())

    names = {c["id"]: c["name"] for c in cfg.channels}
    tracked = youtube.update_videos(store.conn, [x for x in signals if x.source_type == "video"], names, now, s)
    others = fresh([x for x in signals if x.source_type != "video"], now, s["run"]["item_max_age_hours"])
    new_items = store.add_items(others + tracked, now)

    matcher = Matcher(cfg.topics)
    for item_id, sig in new_items:
        topic_ids = set(matcher.match(f"{sig.title} {sig.text[:500]}"))
        if sig.topic_hint:
            topic_ids.add(sig.topic_hint)
        if topic_ids:
            store.add_item_topics(item_id, sorted(topic_ids))
    phrases.link_emerging(store.conn, new_items,
                          phrases.active_emerging(store.conn, now, s["phrases"]["emerging_ttl_hours"]), now)
    spikes = phrases.detect(store.conn, cfg, new_items, now)

    catalog = digest_mod.topic_catalog(store.conn, cfg, now)
    scores = scorer.score_run(store.conn, list(catalog.values()), now, s)
    if warming_up(store, now, s):
        log.info("warm-up: collecting history, HOT alerts start %d h after the first run", s["alerts"]["warmup_hours"])
        decisions = []
    else:
        decisions = scorer.decide_alerts(store.conn, scores, now, s)
    multipliers = hooks.angle_multipliers(store.conn, now)
    email_failed = False
    for score, kind in decisions:
        topic = catalog[score.topic_id]
        topic_phrases = sorted(sp.phrase for sp in spikes if sp.topic_id == topic.id)
        brief = briefs.build_brief(store.conn, cfg, topic, score, now, multipliers, topic_phrases)
        subject, text, html = emailer.render_hot(brief)
        if kind == "capped":
            scorer.record_alert(store.conn, topic.id, "capped", now, score.heat, subject)
            continue
        try:
            if dry_run:
                emailer.write_preview(subject, html, out_dir=out_dir, kind="hot", slug=topic.id, now=now)
            else:
                emailer.send(subject, text, html, settings=s, env=env)
        except emailer.EmailError as exc:
            log.error("HOT email for %s not sent: %s", topic.id, exc)
            email_failed = True
            continue
        scorer.record_alert(store.conn, topic.id, "hot", now, score.heat, subject)

    phrases.prune_singletons(store.conn, now)
    store.prune(now, s["retention"])
    store.set_kv("run_index", str(run_index + 1))
    log.info("run done: %d signals, %d new items, %d spikes, %d scored topics, %d alert decisions",
             len(signals), len(new_items), len(spikes), len(scores), len(decisions))
    return 1 if all_failed or email_failed else 0


def digest(cfg: Config, store: Store, now: datetime, *, dry_run: bool, out_dir: Path, env: Mapping[str, str]) -> int:
    data = digest_mod.build_digest(store.conn, cfg, now)
    subject, text, html = emailer.render_digest(data, {a.id: a.name for a in cfg.angles.values()})
    if dry_run:
        emailer.write_preview(subject, html, out_dir=out_dir, kind="digest", slug="daily", now=now)
    else:
        emailer.send(subject, text, html, settings=cfg.settings, env=env)
    store.set_kv("last_digest", to_iso(now))
    return 0
```

`radar/__main__.py`

```python
"""CLI: python -m radar run|digest [--dry-run]."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from radar import pipeline
from radar.config import DEFAULT_DIR, load_config
from radar.http import Http
from radar.store import Store
from radar.timeutil import utcnow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="radar", description="Truwealth viral content radar")
    parser.add_argument("command", choices=["run", "digest"])
    parser.add_argument("--dry-run", action="store_true", help="write emails to --out instead of sending them")
    parser.add_argument("--db", default=os.environ.get("RADAR_DB", "radar.db"))
    parser.add_argument("--out", default="out")
    parser.add_argument("--config", default=str(DEFAULT_DIR))
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(Path(args.config))
    store = Store(args.db)
    http = Http()
    try:
        if args.command == "run":
            return pipeline.run(cfg, store, http, utcnow(), dry_run=args.dry_run, out_dir=Path(args.out), env=os.environ)
        return pipeline.digest(cfg, store, utcnow(), dry_run=args.dry_run, out_dir=Path(args.out), env=os.environ)
    finally:
        http.close()
        store.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the whole suite**

```powershell
python -m pytest -q
```

Expected: `102 passed`.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_pipeline.py radar/pipeline.py radar/__main__.py
git commit -m "feat: pipeline and CLI" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 15: GitHub Actions workflows, README and live acceptance run

Scheduling, state persistence through the Actions cache, the monthly re-enable step, and a live acceptance run. Creating the public GitHub repository and adding secrets are outward-facing steps that belong to the user: stop and ask before doing them.

**Files:**
- Create: `.github/workflows/radar.yml`
- Create: `.github/workflows/digest.yml`
- Create: `.github/workflows/ci.yml`
- Create: `README.md`

**Interfaces:**
- Consumes: `python -m radar run|digest`
- Produces: Scheduled workflows and the README.

- [ ] **Step 1: Create the files**

`.github/workflows/radar.yml`

```yaml
name: radar

on:
  schedule:
    - cron: "4,19,34,49 * * * *"   # every 15 min, off the top of the hour to reduce GitHub delays
  workflow_dispatch: {}

concurrency:
  group: radar-state
  cancel-in-progress: false

permissions:
  contents: read

jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements.txt
      - name: Restore radar state
        uses: actions/cache/restore@v4
        with:
          path: radar.db
          key: radar-db-${{ github.run_id }}-${{ github.run_attempt }}
          restore-keys: radar-db-
      - name: Run radar
        env:
          SMTP_USER: ${{ secrets.SMTP_USER }}
          SMTP_APP_PASSWORD: ${{ secrets.SMTP_APP_PASSWORD }}
          ALERT_TO: ${{ secrets.ALERT_TO }}
        run: python -m radar run
      - name: Save radar state
        if: always()
        uses: actions/cache/save@v4
        with:
          path: radar.db
          key: radar-db-${{ github.run_id }}-${{ github.run_attempt }}
```

`.github/workflows/digest.yml`

```yaml
name: digest

on:
  schedule:
    - cron: "30 2 * * *"   # 02:30 UTC = 08:00 IST
  workflow_dispatch: {}

concurrency:
  group: radar-state
  cancel-in-progress: false

permissions:
  contents: read
  actions: write

jobs:
  digest:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements.txt
      - name: Restore radar state
        uses: actions/cache/restore@v4
        with:
          path: radar.db
          key: radar-db-${{ github.run_id }}-${{ github.run_attempt }}
          restore-keys: radar-db-
      - name: Send digest
        env:
          SMTP_USER: ${{ secrets.SMTP_USER }}
          SMTP_APP_PASSWORD: ${{ secrets.SMTP_APP_PASSWORD }}
          ALERT_TO: ${{ secrets.ALERT_TO }}
        run: python -m radar digest
      - name: Save radar state
        if: always()
        uses: actions/cache/save@v4
        with:
          path: radar.db
          key: radar-db-${{ github.run_id }}-${{ github.run_attempt }}
      - name: Keep scheduled workflows enabled
        # GitHub disables schedules in public repos after 60 days without activity; re-enable monthly.
        if: always()
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          if [ "$(date -u +%d)" = "01" ]; then
            gh workflow enable radar.yml --repo "$GITHUB_REPOSITORY"
            gh workflow enable digest.yml --repo "$GITHUB_REPOSITORY"
          fi
```

`.github/workflows/ci.yml`

```yaml
name: ci

on:
  push:
  pull_request:

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements-dev.txt
      - run: python -m pytest -q
```

`README.md`

````markdown
# Truwealth Viral Content Radar

In-house tool for the founder. Every 15 minutes it checks Google Trends, Indian finance news, X trends (through public mirror sites), about 90 Indian finance YouTube channels, Reddit and big market moves. When a finance topic spikes, it emails a brief: what is trending, the evidence, how urgent it is, and content angles for LinkedIn, X and Instagram. A digest arrives every day at 08:00 IST.

Design: `docs/superpowers/specs/2026-09-26-viral-content-radar-design.md`

## Setup (one time)

1. **Sender account.** Use a dedicated Google account. Turn on 2-Step Verification, then create an app password (Google Account > Security > App passwords) and keep the 16-character password.
2. **GitHub.** Push this repository to a public GitHub repository. In Settings > Secrets and variables > Actions, add:
   - `SMTP_USER`: the sender Gmail address
   - `SMTP_APP_PASSWORD`: the app password
   - `ALERT_TO`: recipient addresses, comma-separated
3. **Start.** In the Actions tab, enable workflows, then run `radar` and `digest` once with "Run workflow". After that they run on schedule. HOT alerts start 24 hours after the first run, once the radar has some history.
4. **Phone alerts.** In the founder's Gmail, create a filter for mail from the sender address: "Never send it to Spam" and "Always mark it as important". With the Gmail app set to notify for important mail, HOT alerts arrive as push notifications.

## Local use

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m pytest
python -m radar run --dry-run --db local.db
python -m radar digest --dry-run --db local.db
```

`--dry-run` writes the emails to `out/` instead of sending them.

## Tuning

- Thresholds, weights, caps, cooldowns and warm-up: `config/settings.yaml`
- Topics and keywords: `config/topics.yaml`; content angles: `config/angles.yaml`
- YouTube channels: `config/channels.yaml` (the `id` is the channel id that starts with `UC`)
- Dated events for the digest: `config/events.yaml`
- Feeds and queries: `config/sources.yaml`
````

- [ ] **Step 2: Run the whole suite**

```powershell
python -m pytest -q
```

Expected: `102 passed`.

- [ ] **Step 3: Live acceptance run against the real sources (dry run, fresh database)**

```powershell
python -m radar run --dry-run --db local.db
```

Expected:
- exit code 0, finishing in well under 2 minutes;
- a `collector <name>: <n> signals` log line for google_trends, google_news, news_feeds, regulators, x_trends, youtube and markets (markets may report 0 outside Indian market hours);
- `warm-up: collecting history, HOT alerts start 24 h after the first run`, because this is a fresh database;
- `reddit` may fail with `RuntimeError` on networks that block Reddit; that is expected and is retried hourly after 3 failures.

Reference result from the prototype on 2026-09-26: 1,613 signals, 429 new items, 22 scored topics, 0 alerts (warm-up), about 25 s without the Reddit timeout.

- [ ] **Step 4: Live digest preview**

```powershell
python -m radar digest --dry-run --db local.db
```

Expected: a line like `[dry-run] Radar digest 26 Sep — N trends -> out\<timestamp>-digest-daily.html`. Open the file and check that it has five sections: Top trends, Near misses, Format scoreboard, Coming up, Source health.

- [ ] **Step 5: Commit**

```powershell
git add .github/workflows/radar.yml .github/workflows/digest.yml .github/workflows/ci.yml README.md
git commit -m "ci: GitHub Actions workflows and README" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Hand over to the user for go-live (do not do these steps without the user)**

These steps publish the repository and store credentials, so they need the user's explicit go-ahead:

1. The user picks the repository name. With their confirmation, create the public repository and push: `gh repo create <name> --public --source . --push`.
2. The user adds three repository secrets in GitHub (Settings > Secrets and variables > Actions): `SMTP_USER`, `SMTP_APP_PASSWORD`, `ALERT_TO`. Never paste these values into chat or code.
3. In the Actions tab, run `radar` once and `digest` once with "Run workflow", then check that both succeed and that the digest email arrives.
4. Remind the user that HOT alerts begin 24 hours after the first scheduled run (warm-up).
