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
