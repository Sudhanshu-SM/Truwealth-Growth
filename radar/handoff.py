"""Hand radar topics to the LinkedIn ghostwriter: one row each in the "Radar topics" tab of its Google Sheet, and
in the shared `radar_topics` table of its Supabase project. Both run side by side until the Sheet is retired.

Each is optional: the Sheet needs GHOST_SHEET_ID and RADAR_SA_JSON, Supabase needs SUPABASE_URL and
SUPABASE_SERVICE_ROLE_KEY. The ghostwriter owns the tab (its founder-app spec, section 6.2): the radar never creates
it and never edits rows; it appends, placing values by header name. In Supabase a row whose id is already there is
left alone. Errors are logged and swallowed, so the radar never fails because of the ghostwriter."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable, Mapping, Sequence

from radar import briefs
from radar.http import Http
from radar.models import Brief, Topic, TopicScore
from radar.timeutil import from_iso, ist, ist_date, to_iso

if TYPE_CHECKING:
    from radar.config import Config
    from radar.phrases import PhraseSpike
    from radar.store import Store

log = logging.getLogger(__name__)

RADAR_TAB = "Radar topics"
RADAR_COLUMNS = ("id", "found_at", "topic_id", "topic", "bucket", "stage", "heat", "kind", "headline",
                 "headline_url", "evidence", "angles", "market_move")
RISING_STAGES = ("Emerging", "Peaking")


def radar_row(brief: Brief, kind: str, now: datetime) -> dict[str, str]:
    """The radar's columns of one Radar topics row. `found_at` is IST wall-clock time; the id keeps UTC."""
    evidence = "\n".join(f"{text} | {url}" if url else text for text, url in brief.evidence)
    angles = "\n".join(f"{a['name']}: {a['hook']} | {a['linkedin']}" for a in brief.angles)
    return {
        "id": f"radar:{brief.topic.id}:{now.astimezone(timezone.utc).strftime('%Y%m%d%H%M')}",
        "found_at": ist(now).strftime("%Y-%m-%d %H:%M"),
        "topic_id": brief.topic.id,
        "topic": brief.topic.name,
        "bucket": brief.topic.bucket,
        "stage": brief.score.stage,
        "heat": f"{brief.score.heat:.1f}",
        "kind": kind,
        "headline": brief.headline,
        "headline_url": brief.headline_url or "",
        "evidence": evidence,
        "angles": angles,
        "market_move": "yes" if any(text.startswith("Market:") for text, _ in brief.evidence) else "no",
    }


def open_sheet(sheet_id: str, sa_json: str) -> Any:
    """The Radar topics worksheet, or None when the Sheet has no such tab. Never creates it."""
    import gspread

    book = gspread.service_account_from_dict(json.loads(sa_json)).open_by_key(sheet_id)
    try:
        return book.worksheet(RADAR_TAB)
    except gspread.exceptions.WorksheetNotFound:
        return None


def push_decision(brief: Brief, kind: str, now: datetime, env: Mapping[str, str],
                  opener: Callable[[str, str], Any] = open_sheet, http: Http | None = None) -> bool:
    """Hand one topic to every configured destination. True when at least one took it, so a topic the Sheet already
    has is not appended again on the next run just because Supabase failed (or the other way round)."""
    sheet = push_sheet(brief, kind, now, env, opener)
    return push_supabase(brief, kind, now, env, http) or sheet


def supabase_row(brief: Brief, kind: str, now: datetime) -> dict[str, Any]:
    """radar_row typed for the radar_topics table: found_at as ISO with offset, heat a number, market_move a bool."""
    row: dict[str, Any] = radar_row(brief, kind, now)
    row.update(found_at=to_iso(now), heat=round(brief.score.heat, 1), market_move=row["market_move"] == "yes")
    return row


def push_supabase(brief: Brief, kind: str, now: datetime, env: Mapping[str, str], http: Http | None = None) -> bool:
    """Insert one topic into radar_topics through PostgREST. True when the request succeeded (a duplicate id too)."""
    url, key = env.get("SUPABASE_URL", "").strip().rstrip("/"), env.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not (url and key):
        return False
    client = http or Http()
    try:
        # The sb_secret_ key is not a JWT: it goes in apikey only, never as Authorization: Bearer.
        client.request("POST", f"{url}/rest/v1/radar_topics", params={"on_conflict": "id"},
                       json=[supabase_row(brief, kind, now)],
                       headers={"apikey": key, "Prefer": "resolution=ignore-duplicates,return=minimal"})
        return True
    except Exception as exc:  # never let the ghostwriter break the radar
        status = getattr(getattr(exc, "response", None), "status_code", "")
        log.warning("supabase handoff failed for %s: %s %s", brief.topic.id, type(exc).__name__, status)
        return False
    finally:
        if http is None:
            client.close()


def push_sheet(brief: Brief, kind: str, now: datetime, env: Mapping[str, str],
               opener: Callable[[str, str], Any] = open_sheet) -> bool:
    """Append one topic to the Radar topics tab. Returns True when a row was written."""
    sheet_id, sa_json = env.get("GHOST_SHEET_ID", "").strip(), env.get("RADAR_SA_JSON", "").strip()
    if not (sheet_id and sa_json):
        return False
    try:
        ws = opener(sheet_id, sa_json)
        if ws is None:
            log.warning("handoff skipped for %s: the ghostwriter Sheet has no %r tab", brief.topic.id, RADAR_TAB)
            return False
        header = [str(h).strip() for h in ws.row_values(1)]
        if "id" not in header:
            log.warning("handoff skipped for %s: the %r header row has no id column", brief.topic.id, RADAR_TAB)
            return False
        values = radar_row(brief, kind, now)
        ws.append_rows([[values.get(h, "") for h in header]], value_input_option="RAW", table_range="A1")
        return True
    except Exception as exc:  # never let the ghostwriter break the radar
        log.warning("handoff failed for %s: %s", brief.topic.id, type(exc).__name__)
        return False


def push_rising(store: Store, cfg: Config, scores: Sequence[TopicScore], decided_ids: set[str],
                catalog: Mapping[str, Topic], now: datetime, env: Mapping[str, str],
                multipliers: dict[str, float], spikes: Sequence[PhraseSpike],
                push: Callable[..., bool] = push_decision) -> int:
    """Hand off rising topics, hottest first, as kind `rising`. Returns how many were written.

    Rising: Emerging or Peaking, heat at or above the watch threshold, and no alert decision this run. A topic that
    had a HOT or capped alert within `rising_repeat_hours` is skipped too, so it does not come back as rising while
    in cooldown. Each topic goes at most once per `rising_repeat_hours`, and at most `rising_daily_cap` per IST day.
    The store keys are written only after a successful push, so a failed push is retried on the next run."""
    limits, watch = cfg.settings["handoff"], cfg.settings["scoring"]["watch_threshold"]
    repeat = timedelta(hours=limits["rising_repeat_hours"])
    count_key = f"handoff_rising_count:{ist_date(now).isoformat()}"
    sent_today = int(store.get_kv(count_key) or 0)
    pushed = 0
    for score in sorted(scores, key=lambda sc: sc.heat, reverse=True):
        topic = catalog.get(score.topic_id)
        if topic is None or score.stage not in RISING_STAGES or score.heat < watch or topic.id in decided_ids:
            continue
        if sent_today >= limits["rising_daily_cap"]:
            break
        last = store.get_kv(f"handoff_rising:{topic.id}")
        if (last and now - from_iso(last) < repeat) or _alerted_since(store, topic.id, now - repeat):
            continue
        topic_phrases = sorted(sp.phrase for sp in spikes if sp.topic_id == topic.id)
        brief = briefs.build_brief(store.conn, cfg, topic, score, now, multipliers, topic_phrases)
        if push(brief, "rising", now, env):
            sent_today += 1
            pushed += 1
            store.set_kv(f"handoff_rising:{topic.id}", to_iso(now))
            store.set_kv(count_key, str(sent_today))
    return pushed


def _alerted_since(store: Store, topic_id: str, since: datetime) -> bool:
    return store.conn.execute("SELECT 1 FROM alerts WHERE topic_id = ? AND sent_at >= ? LIMIT 1",
                              (topic_id, to_iso(since))).fetchone() is not None
