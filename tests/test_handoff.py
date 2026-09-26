from helpers import NOW
from test_pipeline import CFG, fake_collectors, past_warmup

from radar import handoff, pipeline
from radar.models import Brief, Topic, TopicScore
from radar.store import Store


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
    def __init__(self, header=None):
        self.rows = [list(header)] if header else []

    def row_values(self, n):
        return self.rows[n - 1] if len(self.rows) >= n else []

    def update(self, values, range_name=None):
        self.rows[0:1] = values

    def append_rows(self, values, value_input_option=None, table_range=None):
        assert value_input_option == "RAW"
        self.rows.extend(values)


ENV = {"INBOX_SHEET_ID": "sheet", "INBOX_SA_JSON": "{}"}


def test_inbox_row_format():
    row = dict(zip(handoff.INBOX_COLUMNS, handoff.inbox_row(make_brief(), "hot", NOW)))
    assert row["id"] == "radar:gold_price:202609260800"
    assert row["created_at_utc"] == "2026-09-26T08:00:00+00:00"
    assert row["evidence"] == ("News: 14 articles in the last hour (normally about 2) | https://n.test/1\n"
                               "Market: Gold futures up 2.3% today | https://y.test/1")
    assert row["angles"] == "Myth vs fact: 3 myths about gold | Text post: 3 myths"
    assert (row["heat"], row["stage"], row["market_move"]) == ("12.0", "Emerging", "yes")
    no_market = dict(zip(handoff.INBOX_COLUMNS, handoff.inbox_row(make_brief([("News: 3", None)]), "capped", NOW)))
    assert no_market["market_move"] == "no" and no_market["evidence"] == "News: 3" and no_market["kind"] == "capped"


def test_push_decision_needs_both_secrets():
    assert handoff.push_decision(make_brief(), "hot", NOW, {}) is False
    assert handoff.push_decision(make_brief(), "hot", NOW, {"INBOX_SHEET_ID": "x"}) is False


def test_push_decision_writes_header_then_rows():
    ws = FakeWorksheet()
    assert handoff.push_decision(make_brief(), "hot", NOW, ENV, opener=lambda sid, sa: ws) is True
    assert ws.rows[0] == list(handoff.INBOX_COLUMNS) and ws.rows[1][0] == "radar:gold_price:202609260800"
    handoff.push_decision(make_brief(), "capped", NOW, ENV, opener=lambda sid, sa: ws)
    assert len(ws.rows) == 3 and ws.rows[0] == list(handoff.INBOX_COLUMNS)


def test_push_decision_never_raises():
    def broken(sid, sa):
        raise RuntimeError("sheets down")

    assert handoff.push_decision(make_brief(), "hot", NOW, ENV, opener=broken) is False


def test_radar_run_pushes_each_hot_decision(tmp_path):
    pushed = []
    st = past_warmup(Store(tmp_path / "r.db"))
    pipeline.run(CFG, st, None, NOW, dry_run=True, out_dir=tmp_path / "out", env={}, collectors=fake_collectors(),
                 push=lambda brief, kind, now, env: pushed.append((brief.topic.id, kind)))
    assert pushed == [("gold_price", "hot")]
