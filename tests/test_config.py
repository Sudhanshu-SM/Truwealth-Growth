from pathlib import Path

import pytest

from radar.config import BUCKETS, ConfigError, load_config

GENRE_IDS = ["personal_finance", "stock_market", "economy", "wealth", "crypto", "real_estate", "business", "careers",
             "marketing", "technology", "ai", "science", "cricket", "football", "sports", "movies", "ott_tv", "music",
             "gaming", "health", "food", "travel", "fashion", "auto", "spirituality", "politics", "education",
             "environment"]
FINANCE = {"personal_finance", "stock_market", "economy", "wealth", "crypto"}


def _load_edited(tmp_path, filename, old, new):
    """Load a copy of the real config in which the first `old` in `filename` is replaced by `new`."""
    src = Path(__file__).resolve().parent.parent / "config"
    for f in src.glob("*.yaml"):
        (tmp_path / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    text = (tmp_path / filename).read_text(encoding="utf-8")
    assert old in text
    (tmp_path / filename).write_text(text.replace(old, new, 1), encoding="utf-8")
    return load_config(tmp_path)


def test_real_config_loads():
    cfg = load_config()
    assert {t.bucket for t in cfg.topics if t.bucket in BUCKETS} == set(BUCKETS)
    assert len(cfg.angles) == 15
    assert len(cfg.channels) == 91
    assert all(c["id"].startswith("UC") and len(c["id"]) == 24 for c in cfg.channels)
    assert len({c["id"] for c in cfg.channels}) == len(cfg.channels)
    assert len(cfg.sources["google_news"]["queries"]) >= 11 + 23
    assert len(cfg.sources["news_feeds"]) == 12
    assert "sensex" in cfg.finance_vocab
    assert "on" in cfg.settings["phrases"]["stopwords"].split()


def test_every_topic_has_keywords_and_three_angles():
    for t in load_config().topics:
        assert t.keywords, t.id
        assert len(t.angles) >= 3, t.id


def test_unknown_angle_reference_raises(tmp_path):
    with pytest.raises(ConfigError, match="unknown angles"):
        _load_edited(tmp_path, "topics.yaml", "angles: [myth_bust", "angles: [no_such_angle")


def test_genre_list_is_the_contract():
    cfg = load_config()
    assert list(cfg.genres) == GENRE_IDS
    assert cfg.genres["ott_tv"] == "OTT & TV" and cfg.finance_genres == FINANCE


def test_finance_topics_keep_a_finance_genre():
    cfg = load_config()
    finance = [t for t in cfg.topics if t.bucket in BUCKETS]
    assert len(finance) == 47 and all(cfg.is_finance(t) for t in finance)


def test_is_finance_is_false_for_none_and_for_non_finance_topics():
    cfg = load_config()
    assert not cfg.is_finance(None)
    assert cfg.is_finance(cfg.topic_map["home_buying"])    # personal_finance + real_estate: still a finance topic
    assert not cfg.is_finance(next(t for t in cfg.topics if t.genres[0] == "cricket"))


def test_every_other_genre_has_topics_and_a_news_search():
    cfg = load_config()
    for g in set(GENRE_IDS) - FINANCE:
        assert len([t for t in cfg.topics if g in t.genres]) >= 3, g
        assert any(g in q["genres"] for q in cfg.sources["google_news"]["queries"]), g


def test_each_other_genre_leads_three_topics_that_never_reach_the_sheet():
    """The per-genre cap counts a topic's first genre, and a finance genre anywhere would send it to the Sheet."""
    cfg = load_config()
    for g in set(GENRE_IDS) - FINANCE:
        own = [t for t in cfg.topics if t.genres[0] == g]
        assert len(own) >= 3, g
        assert all(len(t.keywords) >= 8 and t.bucket == g and not cfg.is_finance(t) for t in own), g


def test_searches_for_other_genres_look_back_a_day():
    queries = load_config().sources["google_news"]["queries"]
    assert all(q["window"] == "when:1d" for q in queries if not FINANCE & set(q["genres"]))


def test_unknown_genre_raises(tmp_path):
    with pytest.raises(ConfigError, match="unknown genres"):
        _load_edited(tmp_path, "topics.yaml", "genres: [personal_finance", "genres: [no_such_genre")


@pytest.mark.parametrize("filename, new, message", [
    ("topics.yaml", "genres: []", "topic sip_mutual_funds: no genres"),
    ("topics.yaml", "genres: [cricket]", "topic sip_mutual_funds: finance bucket without a finance genre"),
    ("sources.yaml", "genres: [no_such_genre]", r"source mf: unknown genres \['no_such_genre'\]"),
    ("sources.yaml", "genres: []", "source mf: no genres"),
])
def test_genres_are_validated_on_topics_and_sources(tmp_path, filename, new, message):
    with pytest.raises(ConfigError, match=message):
        _load_edited(tmp_path, filename, "genres: [personal_finance]", new)
