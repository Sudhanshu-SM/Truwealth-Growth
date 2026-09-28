import sys
import types
from datetime import timedelta

from helpers import NOW
from test_pipeline import CFG, fake_collectors, past_warmup

from radar import handoff, pipeline, scorer
from radar.models import Brief, Topic, TopicScore
from radar.store import Store
from radar.timeutil import ist

ENV = {"GHOST_SHEET_ID": "sheet", "RADAR_SA_JSON": "{}"}
SHEET_HEADER = (*handoff.RADAR_COLUMNS, "status", "queue_id", "post_on", "image")
TOPIC_IDS = [t.id for t in CFG.topics]


def make_brief(evidence=None):
    topic = Topic(id="gold_price", name="Gold & silver prices", bucket="markets", keywords=("gold",),
                  angles=("myth_bust",))
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
    """Stands in for push_decision: records (topic id, kind) and returns `ok`."""

    def __init__(self, ok=True):
        self.ok, self.calls = ok, []

    def __call__(self, brief, kind, now, env):
        self.calls.append((brief.topic.id, kind))
        return self.ok


def push_rising(st, scores, now=NOW, decided=(), push=None):
    return handoff.push_rising(st, CFG, scores, set(decided), CFG.topic_map, now, {}, {}, [], push=push)


def run_radar(st, push, out, now=NOW):
    return pipeline.run(CFG, st, None, now, dry_run=True, out_dir=out, env={}, collectors=fake_collectors(),
                        push=push)


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
    push, st = FakePush(), Store(tmp_path / "r.db")
    run_radar(st, push, tmp_path / "out")
    heat = {r["topic_id"]: (r["heat"], r["stage"]) for r in st.conn.execute("SELECT * FROM topic_heat")}
    assert heat["market_moves"] == (6.0, "Emerging")  # would qualify after warm-up
    assert push.calls == []
    assert st.get_kv("handoff_rising_count:2026-09-26") is None
