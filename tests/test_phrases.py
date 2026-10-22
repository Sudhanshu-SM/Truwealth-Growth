from collections import Counter
from datetime import timedelta

from helpers import NOW

from radar.config import load_config
from radar.matcher import Matcher
from radar.models import Signal
from radar.phrases import active_emerging, common_genres, detect, extract, link_emerging
from radar.store import Store
from radar.timeutil import ist_hour_bucket, to_iso

CFG = load_config()
P = CFG.settings["phrases"]
STOP = frozenset(P["stopwords"].split())
BLOCK = frozenset(P["blocklist"])

# One story about a cricketer no static topic knows: none of these titles matches a keyword in topics.yaml.
MARSH = ["Jaden Marsh debut shocks selectors", "Jaden Marsh: the debutant everyone is talking about",
         "How Jaden Marsh cracked the nets in Perth", "Jaden Marsh signs on for a county stint"]
ZETA = ["Zeta Bank collapse shocks depositors", "Zeta Bank collapse: what depositors must know",
        "RBI steps in after Zeta Bank collapse", "Zeta Bank collapse explained"]


def news(title, feed, minutes_ago=10, source_type="news", genres=()):
    return Signal(source="t", source_type=source_type, feed=feed, title=title, url=None,
                  published_at=NOW - timedelta(minutes=minutes_ago), genres=genres)


def story(titles, genres=()):
    """One news item per title, each from its own feed."""
    return [news(t, f"feed{i}", genres=genres) for i, t in enumerate(titles)]


def live_zeta_topic(st, genres):
    """The Zeta Bank emerging topic as the radar stores it, with the given comma-joined genres."""
    st.conn.execute("INSERT INTO emerging_topics (topic_id, phrase, name, bucket, genres, created_at, last_seen_at) "
                    "VALUES ('emerging:zeta-bank-collapse', 'zeta bank collapse', 'Zeta Bank collapse', 'markets', "
                    "?, ?, ?)", (genres, to_iso(NOW), to_iso(NOW)))
    return active_emerging(st.conn, NOW, 48)


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


def test_common_genres_keeps_shared_genres_most_common_first():
    assert common_genres(Counter({"cricket": 5, "sports": 4, "politics": 1}), 6, 0.3) == ("cricket", "sports")
    assert common_genres(Counter({"food": 1, "travel": 1}), 10, 0.3) == ("food",)   # none reach the share: the top one
    assert len(common_genres(Counter({g: 9 for g in "abcd"}), 9, 0.3)) == 3


def test_unknown_spike_becomes_emerging_topic(tmp_path):
    st = Store(tmp_path / "r.db")
    new = st.add_items(story(ZETA, ("economy",)), NOW)
    spikes = detect(st.conn, CFG, new, NOW)
    assert [(s.phrase, s.emerging, s.topic_id, s.feeds, len(s.item_ids)) for s in spikes] == [
        ("zeta bank collapse", True, "emerging:zeta-bank-collapse", 4, 4)]
    (topic,) = active_emerging(st.conn, NOW, 48)
    assert (topic.id, topic.name, topic.genres) == ("emerging:zeta-bank-collapse", "Zeta Bank collapse", ("economy",))
    assert topic.bucket == "economy"      # no static topic matched: the bucket is the first genre, not "markets"


def test_cricket_phrase_becomes_an_emerging_cricket_topic(tmp_path):
    st = Store(tmp_path / "r.db")
    assert not any(Matcher(CFG.topics).match(t) for t in MARSH)     # else the spike would map to a static topic
    new = st.add_items(story(MARSH, ("cricket",)), NOW)
    assert [(s.phrase, s.emerging) for s in detect(st.conn, CFG, new, NOW)] == [("jaden marsh", True)]
    (topic,) = [t for t in active_emerging(st.conn, NOW, 48) if "jaden marsh" in t.keywords[0]]
    assert topic.genres == ("cricket",) and topic.bucket == "cricket"


def test_items_without_source_genres_count_through_the_static_topics_they_matched(tmp_path):
    # Items restored from an old cache have no genres of their own. Two of these four matched banking_news, which
    # is half of them (enough for the gate) but under map_share (so the spike stays an emerging topic).
    st = Store(tmp_path / "r.db")
    new = st.add_items(story(ZETA), NOW)
    for iid, _ in new[:2]:
        st.add_item_topics(iid, ["banking_news"])
    detect(st.conn, CFG, new, NOW)
    (topic,) = active_emerging(st.conn, NOW, 48)
    assert topic.genres == ("economy", "personal_finance") and topic.bucket == "markets"   # banking_news's own


def test_emerging_topic_from_an_old_database_has_no_genres(tmp_path):
    st = Store(tmp_path / "r.db")
    assert [t.genres for t in live_zeta_topic(st, "")] == [()]


def test_spike_attaches_to_matching_topic(tmp_path):
    st = Store(tmp_path / "r.db")      # no source genres: upi_payments' genres are what let the phrase through the gate
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
    new = st.add_items([news("UPI MDR charges from October 15", "et", genres=("personal_finance",)),
                        news("UPI MDR charges: banks explain", "mint", genres=("personal_finance",)),
                        news("What UPI MDR charges mean for you", "bs", genres=("personal_finance",))], NOW)
    assert "upi mdr charges" not in {s.phrase for s in detect(st.conn, CFG, new, NOW)}


def test_phrase_seen_only_in_trends_is_not_a_topic(tmp_path):
    # the Marsh spike again, but from trend items: no genres of their own and no static topic to take them from
    st = Store(tmp_path / "r.db")
    new = st.add_items([news(MARSH[0], "trends24", source_type="x_trend"),
                        news(MARSH[1], "google_trends", source_type="search_trend"),
                        news(MARSH[2], "getdaytrends", source_type="x_trend")], NOW)
    assert detect(st.conn, CFG, new, NOW) == []


def test_link_emerging_tags_new_items_and_expiry(tmp_path):
    st = Store(tmp_path / "r.db")
    topics = live_zeta_topic(st, "economy")
    new = st.add_items([news("Depositors queue after Zeta Bank collapse", "et")], NOW)
    link_emerging(st.conn, CFG, new, topics, NOW)
    assert st.conn.execute("SELECT topic_id FROM item_topics").fetchone()[0] == "emerging:zeta-bank-collapse"
    assert active_emerging(st.conn, NOW + timedelta(hours=49), 48) == []


def test_link_emerging_respects_genres(tmp_path):
    st = Store(tmp_path / "r.db")
    topics = live_zeta_topic(st, "stock_market")
    new = st.add_items([news("Zeta Bank collapse becomes an election issue", "toi", genres=("politics",)),
                        news("Zeta Bank collapse: what depositors must know", "mint", genres=("stock_market",))], NOW)
    link_emerging(st.conn, CFG, new, topics, NOW)
    assert [r["item_id"] for r in st.conn.execute("SELECT item_id FROM item_topics")] == [new[1][0]]
