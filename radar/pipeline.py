"""One radar run and the daily digest, wiring all modules together."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping

from radar import briefs, emailer, handoff, hooks, phrases, scorer
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
        env: Mapping[str, str], collectors: Mapping[str, Collector] | None = None,
        push: Callable[..., bool] = handoff.push_decision) -> int:
    """One radar cycle. Returns the process exit code.

    `push` hands each HOT, capped and rising topic to the ghostwriter's Radar topics tab."""
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
    warm = warming_up(store, now, s)
    if warm:
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
            push(brief, "capped", now, env)
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
        push(brief, "hot", now, env)
    rising = 0 if warm else handoff.push_rising(
        store, cfg, scores, {sc.topic_id for sc, _ in decisions}, catalog, now, env, multipliers, spikes, push=push)

    phrases.prune_singletons(store.conn, now)
    store.prune(now, s["retention"])
    store.set_kv("run_index", str(run_index + 1))
    log.info("run done: %d signals, %d new items, %d spikes, %d scored topics, %d alert decisions, %d rising sent",
             len(signals), len(new_items), len(spikes), len(scores), len(decisions), rising)
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
