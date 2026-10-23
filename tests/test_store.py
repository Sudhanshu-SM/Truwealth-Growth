import sqlite3
from datetime import timedelta

from helpers import NOW

from radar.models import Signal
from radar.store import Store, item_id

# The items and emerging_topics tables as a database restored from the Actions cache has them, before genres.
OLD_ITEMS_AND_EMERGING_SCHEMA = """
CREATE TABLE items (
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
CREATE TABLE emerging_topics (
    topic_id TEXT PRIMARY KEY,
    phrase TEXT NOT NULL,
    name TEXT NOT NULL,
    bucket TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
"""


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


def test_old_database_gains_genre_columns(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    with old:      # the items and emerging_topics tables as they were before genres
        old.executescript(OLD_ITEMS_AND_EMERGING_SCHEMA)
        old.execute("INSERT INTO items (id, source, source_type, feed, title, first_seen_at, last_seen_at) "
                    "VALUES ('i1', 's', 'news', 'f', 'Old', 'x', 'x')")
    old.close()
    st = Store(path)
    cols = {r["name"] for r in st.conn.execute("PRAGMA table_info(items)")}
    assert "genres" in cols and "genres" in {r["name"] for r in st.conn.execute("PRAGMA table_info(emerging_topics)")}
    assert tuple(st.conn.execute("SELECT title, genres FROM items").fetchone()) == ("Old", "")


def test_old_emerging_topics_get_a_finance_genre_from_their_bucket(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    with old:
        old.executescript(OLD_ITEMS_AND_EMERGING_SCHEMA)
        old.executemany("INSERT INTO emerging_topics (topic_id, phrase, name, bucket, created_at, last_seen_at) "
                        "VALUES (?, ?, ?, ?, 'x', 'x')",
                        [(f"emerging:{b}", b, b, b)
                         for b in ("personal_finance", "markets", "wealth", "trading", "odd")])
    old.close()

    def genres_by_phrase(store):
        return {r["phrase"]: r["genres"] for r in store.conn.execute("SELECT phrase, genres FROM emerging_topics")}

    st = Store(path)
    assert genres_by_phrase(st) == {"personal_finance": "personal_finance", "markets": "economy", "wealth": "wealth",
                                    "trading": "stock_market", "odd": "economy"}
    # a later run writes genres of its own, which opening the file again must not overwrite
    st.conn.execute("UPDATE emerging_topics SET genres = 'cricket' WHERE phrase = 'markets'")
    st.close()
    again = genres_by_phrase(Store(path))
    assert again["markets"] == "cricket" and again["wealth"] == "wealth"


def test_items_keep_their_genres(tmp_path):
    st = Store(tmp_path / "r.db")
    st.add_items([Signal(source="google_news", source_type="news", feed="gn:x", title="IPL auction",
                         url=None, published_at=NOW, genres=("cricket", "sports"))], NOW)
    assert st.conn.execute("SELECT genres FROM items").fetchone()[0] == "cricket,sports"


def test_same_headline_from_two_searches_keeps_both_genres(tmp_path):
    st = Store(tmp_path / "r.db")
    ((_, merged),) = st.add_items([sig(genres=("business",)), sig(genres=("stock_market",), feed="gn:et")], NOW)
    assert merged.genres == ("business", "stock_market")
    assert st.conn.execute("SELECT genres FROM items").fetchone()[0] == "business,stock_market"
    # a row already stored is left as it is, whatever a later search says
    assert st.add_items([sig(genres=("crypto",))], NOW + timedelta(minutes=15)) == []
    assert st.conn.execute("SELECT genres FROM items").fetchone()[0] == "business,stock_market"


def test_merged_genres_keep_first_seen_order_without_repeats(tmp_path):
    st = Store(tmp_path / "r.db")
    (_, merged), (_, other) = st.add_items([sig("Gold rallies", genres=("economy", "wealth")),
                                            sig("Gold rallies", genres=("wealth", "crypto")),
                                            sig("Oscar race", genres=("movies",))], NOW)
    assert merged.genres == ("economy", "wealth", "crypto") and other.genres == ("movies",)
    stored = st.conn.execute("SELECT genres FROM items WHERE title = 'Gold rallies'").fetchone()[0]
    assert stored == "economy,wealth,crypto"
