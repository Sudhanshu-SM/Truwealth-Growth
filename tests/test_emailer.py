import re
import smtplib

import pytest
from helpers import NOW

from radar.config import load_config
from radar.digest import DigestData
from radar.emailer import EmailError, hot_subject, render_digest, render_hot, send, write_preview
from radar.models import Brief, Topic, TopicScore

EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿]")
ENV = {"SMTP_USER": "radar@example.test", "SMTP_APP_PASSWORD": "app-pass",
       "ALERT_TO": "founder@example.test, team@example.test"}
SETTINGS = load_config().settings


def brief():
    topic = Topic("gold_price", "Gold & silver prices", "markets", ("gold",), ("explainer",))
    return Brief(topic=topic, score=TopicScore("gold_price", 12.0, "Emerging", 3), urgency="post within 3h",
                 headline="Gold hits record high as rupee weakens and investors rush to safety in a big way",
                 headline_url="https://n.test/1",
                 evidence=[("News: 14 articles in the last hour (normally about 2)", "https://n.test/1")],
                 phrases=["gold record high"],
                 angles=[{"name": "Plain-language explainer", "linkedin": "Carousel", "x": "Thread",
                          "instagram": "Reel", "hook": "Gold & silver prices, explained in 60 seconds."}],
                 hooks_now=[{"title": "Gold at record?", "creator": "Asset Yogi", "format": "Short", "score": "4.1x",
                             "url": "https://yt.test/1"}])


def test_hot_subject_format_and_truncation():
    subject = hot_subject(brief())
    assert subject == ("HOT [Markets & macro] Gold & silver prices: "
                       "Gold hits record high as rupee weakens and investors rush... — post within 3h")


def test_render_hot_has_every_section_and_no_emoji():
    subject, text, html = render_hot(brief())
    for part in ("Why now", "Angles", "Hooks working right now", "LinkedIn", "Instagram", "Gold &amp; silver prices"):
        assert part in html
    assert 'Hook: "Gold & silver prices, explained in 60 seconds."' in text
    assert not EMOJI.search(subject + text + html)


def test_render_digest_sections():
    d = DigestData(date_label="02 Oct", top=[{"name": "Gold & silver prices", "bucket": "Markets & macro", "peak": 12.0,
                                              "stage": "Peaking", "status": "sent", "evidence": "Gold hits record",
                                              "url": "https://n.test/1"}], health=["All sources OK"])
    subject, text, html = render_digest(d, {"mistakes_list": "Common mistakes"})
    assert subject == "Radar digest 02 Oct — 1 trends"
    for part in ("Top trends", "Near misses", "Format scoreboard", "Coming up", "Source health", "All sources OK"):
        assert part in html and part in text


class FakeSMTP:
    sent: list = []

    def __init__(self, host, port, timeout):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def test_send_builds_multipart_message():
    FakeSMTP.sent.clear()
    send("HOT subject", "text body", "<p>html</p>", settings=SETTINGS, env=ENV, smtp_factory=FakeSMTP)
    msg = FakeSMTP.sent[0]
    assert msg["To"] == "founder@example.test, team@example.test"
    assert msg["From"] == "Truwealth Radar <radar@example.test>"
    assert msg.get_body(("plain",)).get_content().strip() == "text body"


def test_send_retries_once_then_raises():
    class Broken(FakeSMTP):
        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    with pytest.raises(EmailError):
        send("s", "t", "<p>h</p>", settings=SETTINGS, env=ENV, smtp_factory=Broken)


def test_missing_credentials_raise():
    with pytest.raises(EmailError, match="SMTP_USER"):
        send("s", "t", "h", settings=SETTINGS, env={}, smtp_factory=FakeSMTP)


def test_write_preview(tmp_path):
    path = write_preview("HOT x", "<p>x</p>", out_dir=tmp_path, kind="hot", slug="gold_price", now=NOW)
    assert path.name == "20260926T080000Z-hot-gold-price.html"
    assert path.read_text(encoding="utf-8") == "<p>x</p>"
