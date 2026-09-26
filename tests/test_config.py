from pathlib import Path

import pytest

from radar.config import BUCKETS, ConfigError, load_config


def test_real_config_loads():
    cfg = load_config()
    assert len(cfg.topics) == 47
    assert {t.bucket for t in cfg.topics} == set(BUCKETS)
    assert len(cfg.angles) == 15
    assert len(cfg.channels) == 91
    assert all(c["id"].startswith("UC") and len(c["id"]) == 24 for c in cfg.channels)
    assert len({c["id"] for c in cfg.channels}) == len(cfg.channels)
    assert len(cfg.sources["google_news"]["queries"]) == 11
    assert len(cfg.sources["news_feeds"]) == 12
    assert "sensex" in cfg.finance_vocab
    assert "on" in cfg.settings["phrases"]["stopwords"].split()


def test_every_topic_has_keywords_and_three_angles():
    for t in load_config().topics:
        assert t.keywords, t.id
        assert len(t.angles) >= 3, t.id


def test_unknown_angle_reference_raises(tmp_path):
    src = Path(__file__).resolve().parent.parent / "config"
    for f in src.glob("*.yaml"):
        (tmp_path / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    topics = (tmp_path / "topics.yaml").read_text(encoding="utf-8")
    (tmp_path / "topics.yaml").write_text(topics.replace("angles: [myth_bust", "angles: [no_such_angle", 1),
                                          encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown angles"):
        load_config(tmp_path)
