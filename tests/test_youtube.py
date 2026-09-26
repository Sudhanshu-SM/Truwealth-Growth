import httpx
from helpers import NOW, fixture_bytes, make_ctx

from radar.collectors import youtube
from radar.config import load_config
from radar.store import Store


def test_parse_detects_shorts_and_views():
    sigs = youtube.parse(fixture_bytes("youtube_channel.xml"), "UCtest")
    assert len(sigs) == 5
    assert (sigs[0].key, sigs[0].metrics["is_short"], sigs[0].metrics["views"]) == ("vidShort001", 1.0, 12000.0)
    assert sigs[1].metrics["is_short"] == 0.0
    assert sigs[0].feed == "yt:UCtest"
    assert sigs[0].text == "Insurance stocks fell sharply today."


def test_rotation_splits_channels_into_groups():
    chans = [{"id": str(i)} for i in range(7)]
    assert [c["id"] for c in youtube.rotation(chans, 0, 3)] == ["0", "3", "6"]
    assert [c["id"] for c in youtube.rotation(chans, 4, 3)] == ["1", "4"]


def test_maturity_curve():
    assert youtube.maturity(72) == 1.0
    assert youtube.maturity(200) == 1.0
    assert youtube.maturity(0) == 0.15
    assert round(youtube.maturity(18), 3) == 0.5


def test_update_videos_scores_recent_uploads_against_channel_baseline(tmp_path):
    st = Store(tmp_path / "r.db")
    sigs = youtube.parse(fixture_bytes("youtube_channel.xml"), "UCtest")
    tracked = youtube.update_videos(st.conn, sigs, {"UCtest": "Test Creator"}, NOW, load_config().settings)
    # baseline = median of the three old videos (20k); the Short is 2 h old, the long video 5 h old
    assert [(s.key, s.metrics["outlier"]) for s in tracked] == [("vidShort001", 3.6), ("vidLong0001", 0.57)]
    row = st.conn.execute("SELECT channel_name, hook_type, outlier FROM videos WHERE video_id = 'vidLong0001'").fetchone()
    assert (row["channel_name"], row["hook_type"], row["outlier"]) == ("Test Creator", "mistakes_list", 0.57)
    assert st.conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 5


def test_collect_fetches_one_rotation_group():
    urls = []

    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200, content=fixture_bytes("youtube_channel.xml"))

    cfg = load_config()
    youtube.collect(make_ctx(handler, run_index=1, config=cfg))
    assert len(urls) == len(youtube.rotation(cfg.channels, 1, 3)) == 30
