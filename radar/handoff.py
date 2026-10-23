"""Hand radar topics to the LinkedIn ghostwriter: one row each in the "Radar topics" tab of its Google Sheet, and
in the shared `radar_topics` table of its Supabase project. Both run side by side until the Sheet is retired.

They get different topics. The ghostwriter's live engine drafts (and in autopilot posts) whatever lands in the Sheet,
so the Sheet only ever gets finance topics (a topic with at least one finance genre). Supabase gets every genre, each
row carrying its genres: Studio's Trending shows a person the rows that share a genre with them. A genre with
nothing handed off for a while gets its biggest recent story as kind `latest`, Supabase only.

Each is optional: the Sheet needs GHOST_SHEET_ID and RADAR_SA_JSON, Supabase needs SUPABASE_URL and
SUPABASE_SERVICE_ROLE_KEY. The ghostwriter owns the tab (its founder-app spec, section 6.2): the radar never creates
it and never edits rows; it appends, placing values by header name. In Supabase a row whose id is already there is
left alone. Errors are logged and swallowed, so the radar never fails because of the ghostwriter."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable, Iterator, Mapping, Sequence

from radar import briefs, scorer
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
LATEST_HOURS = 24  # how far back a quiet genre's story is counted, and its brief looks


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
    """radar_row typed for the radar_topics table: found_at as ISO with offset, heat a number, market_move a bool,
    and the topic's genres (most relevant first). The Sheet has no genres column."""
    row: dict[str, Any] = radar_row(brief, kind, now)
    row.update(found_at=to_iso(now), heat=round(brief.score.heat, 1), market_move=row["market_move"] == "yes",
               genres=list(brief.topic.genres))
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
                push: Callable[..., bool] = push_sheet) -> int:
    """Hand off rising finance topics to the Sheet, hottest first, as kind `rising`. Returns how many were written.

    Rising: Emerging or Peaking, heat at or above the watch threshold, and no alert decision this run. A topic that
    had a HOT or capped alert within `rising_repeat_hours` is skipped too, so it does not come back as rising while
    in cooldown. Each topic goes at most once per `rising_repeat_hours`, and at most `rising_daily_cap` per IST day.
    The store keys are written only after a successful push, so a failed push is retried on the next run.

    The Sheet is finance-only: a topic with no finance genre is left to `push_feed`."""
    limits = cfg.settings["handoff"]
    repeat = timedelta(hours=limits["rising_repeat_hours"])
    count_key = f"handoff_rising_count:{ist_date(now).isoformat()}"
    sent_today = int(store.get_kv(count_key) or 0)
    pushed = 0
    for score, topic in _rising(cfg, scores, decided_ids, catalog):
        if not cfg.is_finance(topic):
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


def push_feed(store: Store, cfg: Config, scores: Sequence[TopicScore], decided_ids: set[str],
              catalog: Mapping[str, Topic], now: datetime, env: Mapping[str, str],
              multipliers: dict[str, float], spikes: Sequence[PhraseSpike],
              push: Callable[..., bool] = push_supabase) -> int:
    """Hand off rising topics of every genre to Supabase, hottest first. Returns how many were written.

    A topic qualifies as for `push_rising`. It goes as kind `hot` when its score would qualify for a HOT alert apart
    from cooldown and the daily cap (`scorer.is_hot`: the engine drafts `hot` rows at once, so a single-source spike
    must not be one), else `rising`. It is skipped when it had an alert, or was fed, within `feed_repeat_hours`. At
    most `feed_daily_cap_per_genre` go per IST day for each first genre, so one busy genre cannot crowd out the rest.
    A topic without genres is not sent: it cannot be placed. The store keys are written only after a successful push."""
    limits = cfg.settings["handoff"]
    repeat = timedelta(hours=limits["feed_repeat_hours"])
    pushed = 0
    for score, topic in _rising(cfg, scores, decided_ids, catalog):
        if not topic.genres or _fed_within(store, topic.id, now, repeat):
            continue  # no genre to place it in, or it went to Supabase recently
        if int(store.get_kv(_count_key(topic, now)) or 0) >= limits["feed_daily_cap_per_genre"]:
            continue  # its genre has had its share for today
        topic_phrases = sorted(sp.phrase for sp in spikes if sp.topic_id == topic.id)
        brief = briefs.build_brief(store.conn, cfg, topic, score, now, multipliers, topic_phrases)
        if push(brief, "hot" if scorer.is_hot(score, cfg.settings) else "rising", now, env):
            _record_feed(store, topic, now)
            pushed += 1
    return pushed


def push_quiet(store: Store, cfg: Config, scores: Sequence[TopicScore], catalog: Mapping[str, Topic], now: datetime,
               env: Mapping[str, str], multipliers: dict[str, float],
               push: Callable[..., bool] = push_supabase) -> int:
    """Give each quiet genre its biggest recent story, as kind `latest`. Returns how many were written.

    A genre is quiet when nothing was fed for it in the last `quiet_genre_hours`. Its story is the topic with the most
    news items published in the last 24 hours (at least one) that was not fed or alerted within `feed_repeat_hours`;
    the brief looks as far back, so the card carries that story's headline and link however old it is. A topic in
    several genres is one push that feeds all of them. Supabase only, never the Sheet."""
    limits = cfg.settings["handoff"]
    quiet, repeat = timedelta(hours=limits["quiet_genre_hours"]), timedelta(hours=limits["feed_repeat_hours"])
    rows = store.conn.execute(
        "SELECT it.topic_id FROM items i JOIN item_topics it ON it.item_id = i.id "
        "WHERE i.source_type = 'news' AND COALESCE(i.published_at, i.first_seen_at) >= ? "
        "GROUP BY it.topic_id ORDER BY COUNT(*) DESC, it.topic_id", (to_iso(now - timedelta(hours=LATEST_HOURS)),))
    by_news = [row["topic_id"] for row in rows if row["topic_id"] in catalog]  # most news items first
    score_of = {score.topic_id: score for score in scores}
    pushed = 0
    for genre in cfg.genres:
        last = store.get_kv(f"feed_last:{genre}")  # read here, not above: an earlier genre's push can feed this one
        if last and now - from_iso(last) < quiet:
            continue
        topic = next((catalog[t] for t in by_news
                      if genre in catalog[t].genres and not _fed_within(store, t, now, repeat)), None)
        if topic is None:
            continue
        score = score_of.get(topic.id) or TopicScore(topic.id, 0.0, "Quiet", 0)
        brief = briefs.build_brief(store.conn, cfg, topic, score, now, multipliers, [], lookback_hours=LATEST_HOURS)
        if push(brief, "latest", now, env):
            _record_feed(store, topic, now)
            pushed += 1
    return pushed


def _rising(cfg: Config, scores: Sequence[TopicScore], decided_ids: set[str],
            catalog: Mapping[str, Topic]) -> Iterator[tuple[TopicScore, Topic]]:
    """The topics that qualify as rising, hottest first: Emerging or Peaking, heat at or above the watch threshold,
    and no alert decision this run."""
    watch = cfg.settings["scoring"]["watch_threshold"]
    for score in sorted(scores, key=lambda sc: sc.heat, reverse=True):
        topic = catalog.get(score.topic_id)
        if topic is not None and score.stage in RISING_STAGES and score.heat >= watch and topic.id not in decided_ids:
            yield score, topic


def _count_key(topic: Topic, now: datetime) -> str:
    """Rows fed today are counted on the topic's first genre only, so a second genre never uses up another's cap."""
    return f"feed_count:{topic.genres[0]}:{ist_date(now).isoformat()}"


def _fed_within(store: Store, topic_id: str, now: datetime, window: timedelta) -> bool:
    """Did the topic go to Supabase less than `window` ago, as feed or as a HOT or capped alert?"""
    last = store.get_kv(f"feed_sent:{topic_id}")
    return bool(last and now - from_iso(last) < window) or _alerted_since(store, topic_id, now - window)


def _record_feed(store: Store, topic: Topic, now: datetime) -> None:
    """After a successful push to Supabase: remember the topic, count it on its first genre, mark all its genres fed."""
    count_key = _count_key(topic, now)
    store.set_kv(count_key, str(int(store.get_kv(count_key) or 0) + 1))
    store.set_kv(f"feed_sent:{topic.id}", to_iso(now))
    for genre in topic.genres:
        store.set_kv(f"feed_last:{genre}", to_iso(now))


def _alerted_since(store: Store, topic_id: str, since: datetime) -> bool:
    return store.conn.execute("SELECT 1 FROM alerts WHERE topic_id = ? AND sent_at >= ? LIMIT 1",
                              (topic_id, to_iso(since))).fetchone() is not None
