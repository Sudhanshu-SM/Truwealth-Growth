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
