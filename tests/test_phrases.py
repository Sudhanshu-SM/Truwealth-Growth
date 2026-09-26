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
