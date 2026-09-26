from datetime import timedelta

from helpers import NOW

from radar import hooks
from radar.store import Store
from radar.timeutil import to_iso


def test_classify_examples():
    assert hooks.classify("5 mistakes to avoid with credit cards") == "mistakes_list"
    assert hooks.classify("FD vs Debt Fund: which is better?") == "data_compare"
    assert hooks.classify("₹10,000 SIP for 20 years = ?") == "what_if_calculator"
    assert hooks.classify("New tax rules from April 1") == "before_after_rule"
    assert hooks.classify("Is this a SCAM? Red flags in stock tips") == "red_flags"
    assert hooks.classify("Market update") == "other"


def insert_video(st, vid, is_short, outlier, hook):
    st.conn.execute(
        "INSERT INTO videos (video_id, channel_id, channel_name, title, url, published_at, is_short, views, "
        "first_seen_at, last_seen_at, outlier, hook_type) VALUES (?, 'UC1', 'Chan', ?, ?, ?, ?, 1000, ?, ?, ?, ?)",
        (vid, f"title {vid}", f"https://yt.test/{vid}", to_iso(NOW - timedelta(days=1)), is_short,
         to_iso(NOW), to_iso(NOW), outlier, hook))


def test_scoreboard_and_multipliers(tmp_path):
    st = Store(tmp_path / "r.db")
    for vid, is_short, outlier, hook in [("a", 1, 3.0, "mistakes_list"), ("b", 1, 5.0, "mistakes_list"),
                                         ("c", 1, 4.0, "mistakes_list"), ("d", 0, 1.0, "explainer"),
                                         ("e", 0, 1.2, "explainer"), ("f", 0, 0.8, "explainer"),
                                         ("g", 0, 9.0, "myth_bust")]:
        insert_video(st, vid, is_short, outlier, hook)
    board = hooks.scoreboard(st.conn, NOW)
    assert [(b["angle"], b["format"], b["median"], b["count"], b["example"]) for b in board] == [
        ("mistakes_list", "Short", 4.0, 3, "title b"), ("explainer", "Long", 1.0, 3, "title e")]
    assert hooks.angle_multipliers(st.conn, NOW) == {"mistakes_list": 4.0, "explainer": 1.0}
