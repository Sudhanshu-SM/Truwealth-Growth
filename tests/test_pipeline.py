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
