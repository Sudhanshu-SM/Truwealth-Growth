from datetime import datetime, timezone

import httpx
import pytest
from helpers import NOW

from radar.collectors import Context, gather, run_all
from radar.http import Http
from radar.models import Signal
from radar.rss import parse_feed
from radar.timeutil import IST


def make_http(handler):
    return Http(retry_wait=0, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_http_retries_once_on_5xx_then_succeeds():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, text="ok")

    assert make_http(handler).get("https://example.test/").text == "ok"
    assert len(calls) == 2


def test_http_raises_after_second_5xx():
    with pytest.raises(httpx.HTTPStatusError):
        make_http(lambda request: httpx.Response(500)).get("https://example.test/")


def test_http_does_not_retry_429():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429)

    with pytest.raises(httpx.HTTPStatusError):
        make_http(handler).get("https://example.test/")
    assert len(calls) == 1


def test_http_retries_transport_errors_once():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(httpx.ConnectError):
        make_http(handler).get("https://example.test/")
    assert len(calls) == 2


RSS = b"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>
<item><title>Nifty &amp; Sensex slip</title><link>https://ex.test/a</link>
<description>&lt;p&gt;Markets fell&lt;/p&gt;</description><pubDate>Sat, 26 Sep 2026 17:05:56 +0530</pubDate>
<guid>https://ex.test/a</guid><source url="https://et.test">The Economic Times</source></item>
<item><title>RBI release</title><link>https://ex.test/b</link><pubDate>Fri, 25 Sep 2026 21:50:00</pubDate></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Should I stop my SIP?</title><link href="https://www.reddit.com/r/IndiaInvestments/comments/abc/"/>
<id>t3_abc</id><updated>2026-09-26T07:30:00+00:00</updated><content type="html">&lt;p&gt;Question&lt;/p&gt;</content></entry>
</feed>"""


def test_rss_items():
    a, b = parse_feed(RSS, default_tz=IST)
    assert (a.title, a.summary, a.source) == ("Nifty & Sensex slip", "Markets fell", "The Economic Times")
    assert a.source_url == "https://et.test"
    assert a.published == datetime(2026, 9, 26, 11, 35, 56, tzinfo=timezone.utc)
    assert b.published == datetime(2026, 9, 25, 16, 20, tzinfo=timezone.utc)
    assert b.guid == "https://ex.test/b"


def test_atom_entries():
    (e,) = parse_feed(ATOM)
    assert e.link == "https://www.reddit.com/r/IndiaInvestments/comments/abc/"
    assert (e.guid, e.summary) == ("t3_abc", "Question")
    assert e.published == datetime(2026, 9, 26, 7, 30, tzinfo=timezone.utc)


def s(title):
    return Signal(source="t", source_type="news", feed="f", title=title, url=None, published_at=NOW)


def test_run_all_isolates_failures():
    def broken(ctx):
        raise ValueError("broken feed")

    signals, results = run_all({"ok": lambda ctx: [s("a")], "bad": broken},
                               Context(http=None, config=None, now=NOW, run_index=0), workers=2)
    assert [x.title for x in signals] == ["a"]
    assert results["ok"] is None
    assert results["bad"].startswith("ValueError")


def test_gather_tolerates_partial_failure():
    def boom():
        raise RuntimeError("x")

    assert [x.title for x in gather([("a", lambda: [s("a")]), ("b", boom)])] == ["a"]


def test_gather_raises_when_everything_fails():
    def boom():
        raise RuntimeError("all down")

    with pytest.raises(RuntimeError, match="all down"):
        gather([("a", boom), ("b", boom)])
    assert gather([]) == []
