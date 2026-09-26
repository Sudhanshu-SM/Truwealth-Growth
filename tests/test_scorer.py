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
