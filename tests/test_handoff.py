import copy
import dataclasses
import json
import sys
import types
from datetime import timedelta

import httpx
from helpers import NOW
from test_pipeline import CFG, fake_collectors, past_warmup

from radar import handoff, pipeline, scorer
from radar.http import Http
from radar.models import Brief, Signal, Topic, TopicScore
from radar.store import Store
from radar.timeutil import ist

ENV = {"GHOST_SHEET_ID": "sheet", "RADAR_SA_JSON": "{}"}
SHEET_HEADER = (*handoff.RADAR_COLUMNS, "status", "queue_id", "post_on", "image")
TOPIC_IDS = [t.id for t in CFG.topics]


def lead(genre):
    """The static topics whose first genre is `genre` (every genre has its own lead topics), in topics.yaml order."""
    return [t.id for t in CFG.topics if t.genres[0] == genre]


CRICKET, FOOD = lead("cricket"), lead("food")


def make_brief(evidence=None, genres=("economy", "personal_finance")):
    topic = Topic(id="gold_price", name="Gold & silver prices", bucket="markets", keywords=("gold",),
                  angles=("myth_bust",), genres=genres)
    score = TopicScore(topic_id="gold_price", heat=12.0, stage="Emerging", n_sources=3)
    if evidence is None:
        evidence = [("News: 14 articles in the last hour (normally about 2)", "https://n.test/1"),
                    ("Market: Gold futures up 2.3% today", "https://y.test/1")]
    return Brief(topic=topic, score=score, urgency="post within 3h", headline="Gold hits record high",
                 headline_url="https://n.test/1", evidence=evidence, phrases=[],
                 angles=[{"name": "Myth vs fact", "linkedin": "Text post: 3 myths", "x": "", "instagram": "",
                          "hook": "3 myths about gold"}], hooks_now=[])


class FakeWorksheet:
    def __init__(self, header=()):
        self.rows = [list(header)] if header else []

    def row_values(self, n):
        return self.rows[n - 1] if len(self.rows) >= n else []

    def append_rows(self, values, value_input_option=None, table_range=None):
        assert (value_input_option, table_range) == ("RAW", "A1")
        self.rows.extend(values)


class FakePush:
    """Stands in for a push function: records (topic id, kind), and the briefs, and returns `ok`."""

    def __init__(self, ok=True):
        self.ok, self.calls, self.briefs = ok, [], []

    def __call__(self, brief, kind, now, env):
        self.calls.append((brief.topic.id, kind))
        self.briefs.append(brief)
        return self.ok


class Lane(FakePush):
    """A FakePush that also writes (lane, topic id, kind) to a log shared by the lanes of one run, to show their order."""

    def __init__(self, lane, log):
        super().__init__()
        self.lane, self.log = lane, log

    def __call__(self, brief, kind, now, env):
        self.log.append((self.lane, brief.topic.id, kind))
        return super().__call__(brief, kind, now, env)


def push_rising(st, scores, now=NOW, decided=(), push=None):
    return handoff.push_rising(st, CFG, scores, set(decided), CFG.topic_map, now, {}, {}, [], push=push)


def push_feed(st, scores, now=NOW, decided=(), push=None, cfg=CFG):
    return handoff.push_feed(st, cfg, scores, set(decided), cfg.topic_map, now, {}, {}, [], push=push)


def push_quiet(st, scores=(), now=NOW, push=None):
    return handoff.push_quiet(st, CFG, scores, CFG.topic_map, now, {}, {}, push=push)


def add_news(st, topic_id, n, hours_ago=1.0, source_type="news", dated=True):
    """n items about the topic, published (or just first seen, when undated) `hours_ago` before NOW."""
    when = NOW - timedelta(hours=hours_ago)
    signals = [Signal(source="news_feeds", source_type=source_type, feed="f", title=f"{topic_id} story {i}",
                      url=f"https://n.test/{topic_id}/{i}", published_at=when if dated else None) for i in range(n)]
    for item_id, _ in st.add_items(signals, when):
        st.add_item_topics(item_id, [topic_id])


def run_radar(st, push, out, now=NOW, *, sheet=None, feed=None, collectors=None):
    """One run. `sheet` defaults to `push`, so one recorder sees the alerts and the rising topics in order; `feed` (the
    Supabase hand-off of every genre) defaults to a recorder of its own."""
    return pipeline.run(CFG, st, None, now, dry_run=True, out_dir=out, env={},
                        collectors=fake_collectors() if collectors is None else collectors,
                        push=push, sheet=push if sheet is None else sheet, feed=FakePush() if feed is None else feed)


def genre_collectors():
    """The finance fakes plus a cricket spike (14 headlines from 14 outlets and a Google trend, so a HOT alert's score)
    and one food story (too small to spike, so the quiet floor's)."""
    cricket, food = CFG.topic_map[CRICKET[0]].keywords[0], CFG.topic_map[FOOD[0]].keywords[0]

    def other_genres(ctx):
        news = [Signal(source="google_news", source_type="news", feed=f"gn:outlet{i}",
                       title=f"{cricket} franchise talks, day {i}", url=f"https://c.test/{i}",
                       published_at=ctx.now - timedelta(minutes=5), genres=("cricket",)) for i in range(14)]
        trend = Signal(source="google_trends", source_type="search_trend", feed="google_trends_in",
                       title=f"{cricket} auction", url="https://g.test/ipl", published_at=ctx.now - timedelta(minutes=30),
                       metrics={"approx_traffic": 50000.0})
        story = Signal(source="google_news", source_type="news", feed="gn:slurrp", title=f"{food} chain opens",
                       url="https://f.test/1", published_at=ctx.now - timedelta(minutes=20), genres=("food",))
        return [*news, trend, story]

    return {**fake_collectors(), "other_genres": other_genres}


# --- C1: rows for the Radar topics tab ---------------------------------------------------------------------------

def test_radar_row_values():
    row = handoff.radar_row(make_brief(), "hot", NOW)
    assert tuple(row) == handoff.RADAR_COLUMNS
    assert row["id"] == "radar:gold_price:202609260800"
    assert row["found_at"] == "2026-09-26 13:30"
    assert (row["topic_id"], row["topic"], row["bucket"]) == ("gold_price", "Gold & silver prices", "markets")
    assert (row["headline"], row["headline_url"]) == ("Gold hits record high", "https://n.test/1")
    assert row["evidence"] == ("News: 14 articles in the last hour (normally about 2) | https://n.test/1\n"
                               "Market: Gold futures up 2.3% today | https://y.test/1")
    assert row["angles"] == "Myth vs fact: 3 myths about gold | Text post: 3 myths"
    assert (row["heat"], row["stage"], row["kind"], row["market_move"]) == ("12.0", "Emerging", "hot", "yes")
    no_market = handoff.radar_row(make_brief([("News: 3", None)]), "capped", NOW)
    assert no_market["market_move"] == "no" and no_market["evidence"] == "News: 3" and no_market["kind"] == "capped"


def test_found_at_is_ist_while_the_id_stays_utc():
    late = NOW.replace(hour=19, minute=45)  # 01:15 IST on 27 September
    row = handoff.radar_row(make_brief(), "rising", late)
    assert (row["found_at"], row["id"]) == ("2026-09-27 01:15", "radar:gold_price:202609261945")
    assert handoff.radar_row(make_brief(), "hot", ist(NOW))["id"] == "radar:gold_price:202609260800"


def test_push_places_values_by_header_name():
    header = [c for c in reversed(SHEET_HEADER) if c != "market_move"]  # other order, one radar column missing
    header[header.index("topic")] = " topic "  # stray spaces in a header cell
    header.insert(3, "notes")  # a column the radar does not know
    ws = FakeWorksheet(header)
    assert handoff.push_decision(make_brief(), "hot", NOW, ENV, opener=lambda sid, sa: ws) is True
    assert len(ws.rows) == 2 and ws.rows[0] == header
    written = dict(zip(header, ws.rows[1]))
    expected = handoff.radar_row(make_brief(), "hot", NOW)
    assert written.pop(" topic ") == expected.pop("topic")
    del expected["market_move"]
    assert written == {**expected, "status": "", "queue_id": "", "post_on": "", "image": "", "notes": ""}
    assert handoff.push_decision(make_brief(), "rising", NOW, ENV, opener=lambda sid, sa: ws) is True
    assert len(ws.rows) == 3 and ws.rows[0] == header


def test_push_needs_both_secrets_before_opening_the_sheet():
    opened = []

    def opener(sid, sa):
        opened.append(sid)
        return FakeWorksheet(SHEET_HEADER)

    for env in ({}, {"GHOST_SHEET_ID": "sheet"}, {"RADAR_SA_JSON": "{}"}, {"GHOST_SHEET_ID": " ", "RADAR_SA_JSON": "{}"},
                {"INBOX_SHEET_ID": "sheet", "INBOX_SA_JSON": "{}"}):
        assert handoff.push_decision(make_brief(), "hot", NOW, env, opener=opener) is False
    assert opened == []


def test_missing_tab_gives_false_and_a_warning(caplog):
    assert handoff.push_decision(make_brief(), "hot", NOW, ENV, opener=lambda sid, sa: None) is False
    assert "Radar topics" in caplog.text


def test_tab_without_a_header_row_is_left_alone():
    ws = FakeWorksheet()
    assert handoff.push_decision(make_brief(), "hot", NOW, ENV, opener=lambda sid, sa: ws) is False
    assert ws.rows == []


def test_open_sheet_never_creates_the_tab(monkeypatch):
    class WorksheetNotFound(Exception):
        pass

    class Book:
        def __init__(self, titles):
            self.titles = titles

        def worksheet(self, title):
            if title not in self.titles:
                raise WorksheetNotFound(title)
            return f"ws:{title}"

        def add_worksheet(self, **kwargs):
            raise AssertionError("the radar must never create tabs")

    books = {"with": Book({"Queue", "Radar topics"}), "without": Book({"Queue"})}
    client = types.SimpleNamespace(open_by_key=books.__getitem__)
    fake = types.SimpleNamespace(service_account_from_dict=lambda info: client,
                                 exceptions=types.SimpleNamespace(WorksheetNotFound=WorksheetNotFound))
    monkeypatch.setitem(sys.modules, "gspread", fake)
    assert handoff.open_sheet("with", "{}") == "ws:Radar topics"
    assert handoff.open_sheet("without", "{}") is None


def test_push_swallows_errors_and_logs_only_their_type(caplog):
    def broken_open(sid, sa):
        raise RuntimeError("sheets down")

    class BrokenAppend(FakeWorksheet):
        def append_rows(self, *args, **kwargs):
            raise ConnectionError("quota for secret-token")

    assert handoff.push_decision(make_brief(), "hot", NOW, ENV, opener=broken_open) is False
    assert handoff.push_decision(make_brief(), "hot", NOW, ENV,
                                 opener=lambda sid, sa: BrokenAppend(SHEET_HEADER)) is False
    assert "RuntimeError" in caplog.text and "ConnectionError" in caplog.text
    assert "secret-token" not in caplog.text


# --- Supabase radar_topics -------------------------------------------------------------------------------------

SUPA_ENV = {"SUPABASE_URL": "https://proj.supabase.test/", "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_fake"}


def fake_http(status=201, error=None):
    """An Http whose requests go to a fake transport; returns (http, list of requests sent)."""
    sent = []

    def handle(request):
        sent.append(request)
        if error:
            raise error
        return httpx.Response(status)

    return Http(retry_wait=0, client=httpx.Client(transport=httpx.MockTransport(handle))), sent


def test_supabase_insert_request():
    http, sent = fake_http()
    assert handoff.push_supabase(make_brief(), "hot", NOW, SUPA_ENV, http=http) is True
    (req,) = sent
    assert (req.method, req.url.path, dict(req.url.params)) == ("POST", "/rest/v1/radar_topics", {"on_conflict": "id"})
    assert req.url.host == "proj.supabase.test"
    assert req.headers["apikey"] == "sb_secret_fake" and "authorization" not in req.headers
    assert req.headers["prefer"] == "resolution=ignore-duplicates,return=minimal"
    (row,) = json.loads(req.content)
    assert tuple(row) == (*handoff.RADAR_COLUMNS, "genres")
    expected = handoff.radar_row(make_brief(), "hot", NOW)
    assert row == {**expected, "found_at": "2026-09-26T08:00:00+00:00", "heat": 12.0, "market_move": True,
                   "genres": ["economy", "personal_finance"]}
    no_market = handoff.supabase_row(make_brief([("News: 3", None)]), "rising", NOW)
    assert no_market["market_move"] is False


def test_supabase_row_carries_genres_in_order():
    assert handoff.supabase_row(make_brief(genres=("economy", "personal_finance")), "hot", NOW)["genres"] == [
        "economy", "personal_finance"]
    assert handoff.supabase_row(make_brief(genres=("personal_finance", "economy")), "hot", NOW)["genres"] == [
        "personal_finance", "economy"]
    assert "genres" not in handoff.radar_row(make_brief(), "hot", NOW)  # the Sheet's columns are unchanged


def test_supabase_needs_both_settings():
    http, sent = fake_http()
    for env in ({}, ENV, {"SUPABASE_URL": "https://p.test"}, {"SUPABASE_SERVICE_ROLE_KEY": "k"},
                {"SUPABASE_URL": " ", "SUPABASE_SERVICE_ROLE_KEY": "k"}):
        assert handoff.push_supabase(make_brief(), "hot", NOW, env, http=http) is False
    assert sent == []


def test_supabase_swallows_errors_and_never_logs_the_key(caplog):
    tries = []
    for status, error in ((401, None), (500, None), (201, httpx.ConnectError("down"))):
        http, sent = fake_http(status, error)
        assert handoff.push_supabase(make_brief(), "hot", NOW, SUPA_ENV, http=http) is False
        tries.append(len(sent))
    assert tries == [1, 2, 2]  # 5xx and connection errors are retried once (safe: duplicates are ignored)
    assert "HTTPStatusError 401" in caplog.text and "HTTPStatusError 500" in caplog.text
    assert "ConnectError" in caplog.text
    assert "sb_secret_fake" not in caplog.text


def test_push_decision_writes_to_both_side_by_side():
    ws, (http, sent) = FakeWorksheet(SHEET_HEADER), fake_http()
    both = {**ENV, **SUPA_ENV}
    assert handoff.push_decision(make_brief(), "hot", NOW, both, opener=lambda sid, sa: ws, http=http) is True
    assert len(ws.rows) == 2 and len(sent) == 1
    # one destination failing still counts as handed off, so the other does not get a duplicate on retry
    broken, _ = fake_http(401)
    assert handoff.push_decision(make_brief(), "hot", NOW, both, opener=lambda sid, sa: ws, http=broken) is True
    assert handoff.push_decision(make_brief(), "hot", NOW, both, opener=lambda sid, sa: None, http=http) is True
    assert handoff.push_decision(make_brief(), "hot", NOW, SUPA_ENV, opener=lambda sid, sa: None, http=http) is True
    assert handoff.push_decision(make_brief(), "hot", NOW, SUPA_ENV, http=broken) is False


# --- C2: rising topics -----------------------------------------------------------------------------------------

def test_rising_topic_is_sent_once_per_24_hours(tmp_path):
    st, push = Store(tmp_path / "r.db"), FakePush()
    scores = [TopicScore("gold_price", 5.0, "Emerging", 2)]
    assert push_rising(st, scores, push=push) == 1
    assert push.calls == [("gold_price", "rising")]
    assert st.get_kv("handoff_rising:gold_price") == "2026-09-26T08:00:00+00:00"
    assert st.get_kv("handoff_rising_count:2026-09-26") == "1"
    assert push_rising(st, scores, NOW + timedelta(minutes=15), push=push) == 0
    assert push_rising(st, scores, NOW + timedelta(hours=23, minutes=59), push=push) == 0
    assert push_rising(st, scores, NOW + timedelta(hours=24), push=push) == 1
    assert push.calls == [("gold_price", "rising")] * 2


def test_rising_respects_the_daily_cap(tmp_path):
    st, push = Store(tmp_path / "r.db"), FakePush()
    cap = CFG.settings["handoff"]["rising_daily_cap"]
    ids = TOPIC_IDS[:cap + 2]
    scores = [TopicScore(tid, 30.0 - i, "Peaking", 2) for i, tid in enumerate(ids)]
    assert push_rising(st, scores[::-1], push=push) == cap
    assert [tid for tid, _ in push.calls] == ids[:cap]  # hottest first
    assert st.get_kv("handoff_rising_count:2026-09-26") == str(cap)
    assert push_rising(st, scores, NOW + timedelta(minutes=15), push=push) == 0
    next_day = NOW + timedelta(hours=20)  # 09:30 IST on 27 September; the first ones went 20 h ago
    assert push_rising(st, scores, next_day, push=push) == 2
    assert [tid for tid, _ in push.calls[cap:]] == ids[cap:]
    assert st.get_kv("handoff_rising_count:2026-09-27") == "2"


def test_rising_takes_emerging_or_peaking_topics_at_watch_without_an_alert_decision(tmp_path):
    st, push = Store(tmp_path / "r.db"), FakePush()
    watch = CFG.settings["scoring"]["watch_threshold"]
    t = TOPIC_IDS
    scores = [TopicScore(t[0], 9.0, "Emerging", 3),  # got an alert decision this run
              TopicScore(t[1], 8.0, "Fading", 2),
              TopicScore(t[2], 7.0, "Quiet", 0),
              TopicScore(t[3], watch - 0.1, "Emerging", 1),
              TopicScore(t[4], watch, "Peaking", 1),
              TopicScore(t[5], 6.0, "Emerging", 1)]
    assert push_rising(st, scores, decided={t[0]}, push=push) == 2
    assert push.calls == [(t[5], "rising"), (t[4], "rising")]


def test_topic_alerted_in_the_last_24_hours_is_not_resent_as_rising(tmp_path):
    st, push = Store(tmp_path / "r.db"), FakePush()
    a, b, c = TOPIC_IDS[:3]
    scorer.record_alert(st.conn, a, "hot", NOW - timedelta(hours=2), 9.0, "subject")
    scorer.record_alert(st.conn, b, "capped", NOW - timedelta(hours=5), 9.0, "subject")
    scorer.record_alert(st.conn, c, "hot", NOW - timedelta(hours=25), 9.0, "subject")
    assert push_rising(st, [TopicScore(x, 5.0, "Peaking", 2) for x in (a, b, c)], push=push) == 1
    assert push.calls == [(c, "rising")]


def test_failed_push_records_nothing(tmp_path):
    st, failing = Store(tmp_path / "r.db"), FakePush(ok=False)
    scores = [TopicScore("gold_price", 5.0, "Emerging", 2)]
    assert push_rising(st, scores, push=failing) == 0
    assert failing.calls == [("gold_price", "rising")]
    assert st.get_kv("handoff_rising:gold_price") is None
    assert st.get_kv("handoff_rising_count:2026-09-26") is None
    assert push_rising(st, scores, NOW + timedelta(minutes=15), push=FakePush()) == 1  # retried on the next run


# --- the Sheet is finance-only ---------------------------------------------------------------------------------

def test_rising_sends_only_finance_topics_to_the_sheet(tmp_path):
    st, push = Store(tmp_path / "r.db"), FakePush()
    scores = [TopicScore(CRICKET[0], 9.0, "Peaking", 3), TopicScore("gold_price", 5.0, "Emerging", 2)]
    assert push_rising(st, scores, push=push) == 1
    assert push.calls == [("gold_price", "rising")]
    assert st.get_kv(f"handoff_rising:{CRICKET[0]}") is None
    assert st.get_kv("handoff_rising_count:2026-09-26") == "1"


def test_mixed_genre_topic_still_reaches_the_sheet(tmp_path):
    st, push = Store(tmp_path / "r.db"), FakePush()
    assert CFG.topic_map["home_buying"].genres == ("personal_finance", "real_estate")
    assert CFG.topic_map["housing_market_launches"].genres == ("real_estate",)
    scores = [TopicScore("housing_market_launches", 8.0, "Peaking", 3), TopicScore("home_buying", 5.0, "Emerging", 2)]
    assert push_rising(st, scores, push=push) == 1
    assert push.calls == [("home_buying", "rising")]


def test_rising_writes_the_sheet_and_not_supabase_by_default(tmp_path, monkeypatch):
    ws = FakeWorksheet(SHEET_HEADER)
    client = types.SimpleNamespace(open_by_key=lambda sheet_id: types.SimpleNamespace(worksheet=lambda title: ws))
    monkeypatch.setitem(sys.modules, "gspread", types.SimpleNamespace(
        service_account_from_dict=lambda info: client, exceptions=types.SimpleNamespace(WorksheetNotFound=KeyError)))
    http, sent = fake_http()
    monkeypatch.setattr(handoff, "Http", lambda: http)
    scores = [TopicScore("gold_price", 5.0, "Emerging", 2)]
    assert handoff.push_rising(Store(tmp_path / "r.db"), CFG, scores, set(), CFG.topic_map, NOW,
                               {**ENV, **SUPA_ENV}, {}, []) == 1
    assert [row[SHEET_HEADER.index("topic_id")] for row in ws.rows[1:]] == ["gold_price"]
    assert sent == []


# --- Supabase gets every genre ---------------------------------------------------------------------------------

def supabase_only(monkeypatch):
    """Both destinations configured. The Sheet fails the test if touched; Supabase requests are recorded.
    Returns (env, requests sent)."""
    def forbidden(*args, **kwargs):
        raise AssertionError("this hand-off must stay off the Sheet")

    monkeypatch.setattr(handoff, "open_sheet", forbidden)
    monkeypatch.setattr(handoff, "push_sheet", forbidden)
    http, sent = fake_http()
    http.close = lambda: None  # push_supabase closes a client it opened itself; one fake serves every push here
    monkeypatch.setattr(handoff, "Http", lambda: http)
    return {**ENV, **SUPA_ENV}, sent


def test_feed_sends_every_genre_hot_above_the_hot_threshold(tmp_path):
    st, push = Store(tmp_path / "r.db"), FakePush()
    hot = CFG.settings["scoring"]["hot_threshold"]
    scores = [TopicScore("gold_price", 5.0, "Emerging", 2),
              TopicScore(CRICKET[0], hot, "Emerging", 2),  # at the threshold with two sources: a HOT alert's score
              TopicScore(FOOD[0], hot + 2, "Peaking", 1)]  # hotter, but one source and no bonus: not an alert's score
    assert push_feed(st, scores, push=push) == 3
    assert push.calls == [(FOOD[0], "rising"), (CRICKET[0], "hot"), ("gold_price", "rising")]  # hottest first
    stamp = "2026-09-26T08:00:00+00:00"
    assert st.get_kv(f"feed_sent:{CRICKET[0]}") == st.get_kv("feed_sent:gold_price") == stamp
    # the daily cap counts a topic's first genre only; every one of its genres counts as fed
    genres = ("cricket", "economy", "personal_finance")
    assert [st.get_kv(f"feed_count:{g}:2026-09-26") for g in genres] == ["1", "1", None]
    assert [st.get_kv(f"feed_last:{g}") for g in genres] == [stamp] * 3
    assert st.get_kv("handoff_rising:gold_price") is None  # the Sheet's own bookkeeping is separate


def test_feed_takes_emerging_or_peaking_topics_at_watch(tmp_path):
    st, push = Store(tmp_path / "r.db"), FakePush()
    watch = CFG.settings["scoring"]["watch_threshold"]
    a, b, c, d, e = CRICKET[:5]
    scores = [TopicScore(a, 8.0, "Fading", 2),
              TopicScore(b, 7.0, "Quiet", 0),
              TopicScore(c, watch - 0.1, "Emerging", 1),
              TopicScore(d, watch, "Peaking", 1),
              TopicScore(e, 5.0, "Emerging", 1)]
    assert push_feed(st, scores, push=push) == 2
    assert push.calls == [(e, "rising"), (d, "rising")]


def test_feed_caps_each_genre_per_day(tmp_path):
    cap = 2  # each genre has only a few lead topics, so the test lowers the cap in its own copy of the settings
    settings = copy.deepcopy(CFG.settings)
    settings["handoff"]["feed_daily_cap_per_genre"] = cap
    cfg = dataclasses.replace(CFG, settings=settings)
    st, push = Store(tmp_path / "r.db"), FakePush()
    cricket = CRICKET[:cap + 2]
    assert len(cricket) == cap + 2
    scores = [TopicScore(t, 9.0 - i, "Peaking", 2) for i, t in enumerate(cricket)]
    scores.append(TopicScore(FOOD[0], 5.0, "Peaking", 2))
    assert push_feed(st, scores[::-1], push=push, cfg=cfg) == cap + 1
    assert push.calls == [(cricket[0], "hot"), (cricket[1], "hot"), (FOOD[0], "rising")]  # the hottest cricket topics
    assert st.get_kv("feed_count:cricket:2026-09-26") == str(cap)
    assert st.get_kv("feed_count:food:2026-09-26") == "1"
    assert push_feed(st, scores, NOW + timedelta(minutes=15), push=push, cfg=cfg) == 0  # cricket is full for today
    next_day = NOW + timedelta(hours=20)  # 09:30 IST on 27 September; the first ones went 20 h ago
    assert push_feed(st, scores, next_day, push=push, cfg=cfg) == cap
    assert [t for t, _ in push.calls[cap + 1:]] == cricket[cap:]
    assert st.get_kv("feed_count:cricket:2026-09-27") == str(cap)


def test_feed_sends_a_topic_once_per_24_hours_and_skips_decided_or_alerted(tmp_path):
    st, push = Store(tmp_path / "r.db"), FakePush()
    once, alerted, old_alert, decided = CRICKET[:4]
    scorer.record_alert(st.conn, alerted, "hot", NOW - timedelta(hours=2), 9.0, "subject")
    scorer.record_alert(st.conn, old_alert, "capped", NOW - timedelta(hours=25), 9.0, "subject")
    scores = [TopicScore(t, 7.0, "Peaking", 2) for t in (once, alerted, old_alert, decided)]
    assert push_feed(st, scores, decided={decided}, push=push) == 2
    assert [t for t, _ in push.calls] == [once, old_alert]  # alerted 2 h ago, and decided in this very run: skipped
    assert push_feed(st, scores[:1], NOW + timedelta(minutes=15), push=push) == 0
    assert push_feed(st, scores[:1], NOW + timedelta(hours=23, minutes=59), push=push) == 0
    assert push_feed(st, scores[:1], NOW + timedelta(hours=24), push=push) == 1


def test_feed_and_quiet_never_send_a_topic_without_genres(tmp_path):
    st, push = Store(tmp_path / "r.db"), FakePush()
    nameless = Topic(id="emerging:nameless", name="Nameless", bucket="markets", keywords=("nameless",),
                     angles=("faq",), emerging=True)
    catalog, scores = {nameless.id: nameless}, [TopicScore(nameless.id, 9.0, "Peaking", 3)]
    add_news(st, nameless.id, 3)
    assert handoff.push_feed(st, CFG, scores, set(), catalog, NOW, {}, {}, [], push=push) == 0
    assert handoff.push_quiet(st, CFG, scores, catalog, NOW, {}, {}, push=push) == 0
    assert push.calls == []


def test_failed_feed_and_quiet_pushes_record_nothing(tmp_path):
    st, failing = Store(tmp_path / "r.db"), FakePush(ok=False)
    add_news(st, CRICKET[0], 2)
    scores = [TopicScore(CRICKET[0], 7.0, "Peaking", 2)]
    assert push_feed(st, scores, push=failing) == 0
    assert push_quiet(st, scores, push=failing) == 0
    assert failing.calls == [(CRICKET[0], "hot"), (CRICKET[0], "latest")]
    assert st.conn.execute("SELECT key FROM kv WHERE key LIKE 'feed_%'").fetchall() == []
    assert push_quiet(st, scores, NOW + timedelta(minutes=15), push=FakePush()) == 1  # retried on the next run


def test_feed_goes_to_supabase_and_never_the_sheet_by_default(tmp_path, monkeypatch):
    env, sent = supabase_only(monkeypatch)
    scores = [TopicScore(CRICKET[0], 9.0, "Peaking", 3)]
    assert handoff.push_feed(Store(tmp_path / "r.db"), CFG, scores, set(), CFG.topic_map, NOW, env, {}, []) == 1
    (req,) = sent
    (row,) = json.loads(req.content)
    assert (row["topic_id"], row["kind"], row["genres"]) == (CRICKET[0], "hot", ["cricket"])


# --- the quiet-genre floor ---------------------------------------------------------------------------------------

def test_quiet_genre_gets_its_biggest_recent_story_as_latest(tmp_path):
    st, push = Store(tmp_path / "r.db"), FakePush()
    big, small = CRICKET[:2]
    add_news(st, big, 3)
    add_news(st, small, 1, dated=False)  # no publish date: counted from when it was first seen
    big_score = TopicScore(big, 5.5, "Peaking", 2)
    assert push_quiet(st, [big_score], push=push) == 1
    assert push.calls == [(big, "latest")]
    assert push.briefs[0].score is big_score  # this run's score for the topic
    stamp = "2026-09-26T08:00:00+00:00"
    assert (st.get_kv("feed_last:cricket"), st.get_kv(f"feed_sent:{big}")) == (stamp, stamp)
    assert st.get_kv("feed_count:cricket:2026-09-26") == "1"
    assert push_quiet(st, [], NOW + timedelta(hours=11), push=push) == 0  # fed 11 h ago: not quiet yet
    assert push_quiet(st, [], NOW + timedelta(hours=12), push=push) == 1  # quiet again; `big` was fed within 24 h
    assert push.calls == [(big, "latest"), (small, "latest")]
    assert push.briefs[1].score == TopicScore(small, 0.0, "Quiet", 0)  # no score this run
    assert st.get_kv("feed_last:cricket") == "2026-09-26T20:00:00+00:00"


def test_latest_carries_the_headline_and_url_of_a_story_hours_old(tmp_path):
    st, push = Store(tmp_path / "r.db"), FakePush()
    add_news(st, CRICKET[0], 1, hours_ago=10)  # older than the 6 h a rising topic's brief looks back
    assert push_quiet(st, push=push) == 1
    assert push.calls == [(CRICKET[0], "latest")]
    brief = push.briefs[0]
    url = f"https://n.test/{CRICKET[0]}/0"
    assert (brief.headline, brief.headline_url) == (f"{CRICKET[0]} story 0", url)
    assert brief.evidence == [("News: 1 article in the last 24 hours", url)]


def test_quiet_skips_genres_without_news_and_never_opens_the_sheet(tmp_path, monkeypatch):
    env, sent = supabase_only(monkeypatch)
    st = Store(tmp_path / "r.db")
    add_news(st, CRICKET[0], 2)
    add_news(st, lead("football")[0], 4, hours_ago=25)  # over a day old
    add_news(st, lead("movies")[0], 4, source_type="forum")  # not news; every other genre has nothing at all
    assert handoff.push_quiet(st, CFG, [], CFG.topic_map, NOW, env, {}) == 1
    (req,) = sent
    (row,) = json.loads(req.content)
    assert (row["topic_id"], row["kind"], row["genres"], row["stage"], row["heat"]) == (
        CRICKET[0], "latest", ["cricket"], "Quiet", 0.0)
    assert [st.get_kv(f"feed_last:{g}") for g in ("football", "movies")] == [None, None]


def test_a_genre_just_fed_by_a_rising_topic_is_not_quiet(tmp_path):
    st, push = Store(tmp_path / "r.db"), FakePush()
    first, second = CRICKET[:2]
    add_news(st, first, 3)
    add_news(st, second, 2)
    assert push_feed(st, [TopicScore(first, 7.0, "Peaking", 3)], push=push) == 1
    assert push_quiet(st, [], NOW + timedelta(hours=11), push=push) == 0
    assert push_quiet(st, [], NOW + timedelta(hours=12), push=push) == 1
    assert push.calls == [(first, "hot"), (second, "latest")]


def test_quiet_topic_with_two_genres_is_one_push_that_feeds_both(tmp_path):
    st, push = Store(tmp_path / "r.db"), FakePush()
    assert CFG.topic_map["ai_chatbots_tools"].genres == ("ai", "technology")
    assert CFG.topic_map["ai_risks_regulation"].genres == ("ai",)
    add_news(st, "ai_chatbots_tools", 2)
    add_news(st, "ai_risks_regulation", 1)  # technology comes before ai: its push feeds ai, so this one waits
    assert push_quiet(st, push=push) == 1
    assert push.calls == [("ai_chatbots_tools", "latest")]
    stamp = "2026-09-26T08:00:00+00:00"
    assert [st.get_kv(f"feed_last:{g}") for g in ("ai", "technology")] == [stamp, stamp]
    assert [st.get_kv(f"feed_count:{g}:2026-09-26") for g in ("ai", "technology")] == ["1", None]


def test_quiet_does_not_resend_a_topic_alerted_in_the_last_24_hours(tmp_path):
    st, push = Store(tmp_path / "r.db"), FakePush()
    alerted, other = CRICKET[:2]
    add_news(st, alerted, 3)
    add_news(st, other, 1)
    scorer.record_alert(st.conn, alerted, "hot", NOW - timedelta(hours=2), 9.0, "subject")
    assert push_quiet(st, push=push) == 1
    assert push.calls == [(other, "latest")]


# --- pipeline wiring ---------------------------------------------------------------------------------------------

def test_radar_run_hands_off_hot_decisions_then_rising_topics(tmp_path):
    push, st = FakePush(), past_warmup(Store(tmp_path / "r.db"))
    run_radar(st, push, tmp_path / "out")
    # gold_price got the HOT decision, so it is not also sent as rising
    assert push.calls[0] == ("gold_price", "hot")
    assert sorted(push.calls[1:]) == [("market_moves", "rising"), ("rupee_forex", "rising")]
    run_radar(st, push, tmp_path / "out", NOW + timedelta(minutes=15))
    assert len(push.calls) == 3  # gold_price is in cooldown after its alert; the others went already


def test_no_rising_topics_during_warm_up(tmp_path):
    push, feed, st = FakePush(), FakePush(), Store(tmp_path / "r.db")
    run_radar(st, push, tmp_path / "out", feed=feed, collectors=genre_collectors())
    heat = {r["topic_id"]: (r["heat"], r["stage"]) for r in st.conn.execute("SELECT * FROM topic_heat")}
    assert heat["market_moves"] == (6.0, "Emerging")  # would qualify after warm-up
    assert heat[CRICKET[0]] == (9.0, "Emerging")  # the cricket topic would qualify too, and the food story be a latest
    assert push.calls == [] and feed.calls == []  # not the Sheet's steps, nor Supabase's rising and quiet-genre steps
    assert st.get_kv("handoff_rising_count:2026-09-26") is None
    assert st.conn.execute("SELECT key FROM kv WHERE key LIKE 'feed_%'").fetchall() == []


def test_hot_alerts_consider_finance_topics_only(tmp_path):
    push, sheet, feed = FakePush(), FakePush(), FakePush()
    st = past_warmup(Store(tmp_path / "r.db"))
    run_radar(st, push, tmp_path / "out", sheet=sheet, feed=feed, collectors=genre_collectors())
    cricket = CRICKET[0]
    heat = st.conn.execute("SELECT heat FROM topic_heat WHERE topic_id = ?", (cricket,)).fetchone()[0]
    assert heat > CFG.settings["scoring"]["hot_threshold"]  # with two sources: the score of a HOT alert
    # but it is a cricket topic: no alert row, no email, and none of it goes to an alert's push or to the Sheet
    assert [r["topic_id"] for r in st.conn.execute("SELECT topic_id FROM alerts")] == ["gold_price"]
    assert [p.name for p in (tmp_path / "out").iterdir()] == ["20260926T080000Z-hot-gold-price.html"]
    assert (cricket, "hot") in feed.calls  # Supabase gets it as hot, which needs no email
    for recorder in (push, sheet):  # the end-to-end guarantee: Tejas's live engine drafts whatever lands in the Sheet
        assert recorder.briefs and all(CFG.is_finance(brief.topic) for brief in recorder.briefs)


def test_run_hands_off_alerts_then_sheet_then_feed_then_quiet(tmp_path):
    log = []
    st = past_warmup(Store(tmp_path / "r.db"))
    run_radar(st, Lane("alert", log), tmp_path / "out", sheet=Lane("sheet", log), feed=Lane("feed", log),
              collectors=genre_collectors())

    def calls(lane):
        return [(topic, kind) for name, topic, kind in log if name == lane]

    steps = [("quiet" if kind == "latest" else lane) for lane, _, kind in log]
    rank = {"alert": 0, "sheet": 1, "feed": 2, "quiet": 3}
    assert set(steps) == set(rank) and steps == sorted(steps, key=rank.get)
    assert calls("alert") == [("gold_price", "hot")]  # `push` takes the HOT decisions only
    assert sorted(calls("sheet")) == [("market_moves", "rising"), ("rupee_forex", "rising")]  # finance, rising only
    assert (CRICKET[0], "hot") in calls("feed") and (FOOD[0], "latest") in calls("feed")  # every genre, and the floor
    # gold_price had the alert, and it was recorded before the feed steps ran: it is neither fed as rising nor the
    # latest story of its quiet genre (personal_finance, where it is the only topic with news)
    assert "gold_price" not in [topic for topic, _ in calls("feed")]


def test_a_hot_decision_whose_email_failed_is_not_also_handed_off_as_rising(tmp_path):
    push, sheet, feed = FakePush(), FakePush(), FakePush()
    st = past_warmup(Store(tmp_path / "r.db"))
    # a real send without SMTP settings fails: the alert stays unrecorded, so the next run tries it again
    code = pipeline.run(CFG, st, None, NOW, dry_run=False, out_dir=tmp_path / "out", env={},
                        collectors=fake_collectors(), push=push, sheet=sheet, feed=feed)
    assert code == 1 and push.calls == []
    assert st.conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 0
    # the decision was made this run, so neither the Sheet's rising step nor the feed's takes the topic as well (it can
    # still be a quiet genre's latest story, which is Supabase only)
    assert sheet.calls and "gold_price" not in [topic for topic, _ in sheet.calls]
    assert ("gold_price", "hot") not in feed.calls and ("gold_price", "rising") not in feed.calls


def test_default_destinations_keep_the_sheet_finance_only(tmp_path, monkeypatch):
    ws = FakeWorksheet(SHEET_HEADER)
    client = types.SimpleNamespace(open_by_key=lambda sheet_id: types.SimpleNamespace(worksheet=lambda title: ws))
    monkeypatch.setitem(sys.modules, "gspread", types.SimpleNamespace(
        service_account_from_dict=lambda info: client, exceptions=types.SimpleNamespace(WorksheetNotFound=KeyError)))
    http, sent = fake_http()
    http.close = lambda: None  # one fake serves every push
    monkeypatch.setattr(handoff, "Http", lambda: http)
    st = past_warmup(Store(tmp_path / "r.db"))
    # no push, sheet or feed: the functions `python -m radar run` uses, with both destinations configured
    pipeline.run(CFG, st, None, NOW, dry_run=True, out_dir=tmp_path / "out", env={**ENV, **SUPA_ENV},
                 collectors=genre_collectors())
    on_sheet = [row[SHEET_HEADER.index("topic_id")] for row in ws.rows[1:]]
    assert sorted(on_sheet) == ["gold_price", "market_moves", "rupee_forex"]
    assert all(CFG.is_finance(CFG.topic_map[topic]) for topic in on_sheet)
    rows = [json.loads(request.content)[0] for request in sent]
    assert {(row["topic_id"], row["kind"]) for row in rows} >= {
        ("gold_price", "hot"), (CRICKET[0], "hot"), ("market_moves", "rising"), (FOOD[0], "latest")}
    assert len({row["topic_id"] for row in rows}) == len(rows)  # each topic once
    assert all(row["genres"] for row in rows)
