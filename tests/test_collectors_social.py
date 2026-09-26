from datetime import datetime, timedelta, timezone

import httpx
import pytest
from helpers import fixture_bytes, fixture_text, make_ctx

from radar.collectors import markets, reddit, x_trends

NOW_M = datetime(2026, 9, 26, 8, 40, tzinfo=timezone.utc)  # 10 minutes after the fixture's market time
NIFTY = {"symbol": "^NSEI", "name": "Nifty 50", "threshold": 1.5, "topic": "market_moves"}


def test_trends24_uses_latest_hour_only():
    assert x_trends.parse_trends24(fixture_text("trends24_india.html")) == [
        (1, "#PlusGSTLaunched"), (2, "Sensex Crash"), (3, "#JioHotstar")]


def test_getdaytrends_uses_first_table():
    assert x_trends.parse_getdaytrends(fixture_text("getdaytrends_india.html")) == [(1, "#PlusGSTLaunched"), (2, "Nifty")]


def test_x_trends_falls_back_to_getdaytrends():
    def handler(request):
        if "trends24" in str(request.url):
            return httpx.Response(503)
        return httpx.Response(200, text=fixture_text("getdaytrends_india.html"))

    sigs = x_trends.collect(make_ctx(handler))
    assert [(s.title, s.metrics["rank"], s.feed) for s in sigs] == [
        ("#PlusGSTLaunched", 1.0, "getdaytrends"), ("Nifty", 2.0, "getdaytrends")]
    assert sigs[0].url == "https://x.com/search?q=%23PlusGSTLaunched"


def test_x_trends_raises_when_both_mirrors_are_empty():
    with pytest.raises(RuntimeError):
        x_trends.collect(make_ctx(lambda request: httpx.Response(200, text="<html></html>")))


def test_market_move_over_threshold_emits_signal():
    s = markets.parse(fixture_bytes("yahoo_chart.json"), NIFTY, NOW_M, freshness_minutes=30)
    assert s.title == "Nifty 50 down 2.0% today"
    assert s.metrics == {"pct_move": -2.01, "threshold": 1.5}
    assert s.key == "^NSEI:down:2026-09-26"
    assert s.topic_hint == "market_moves"


def test_market_stale_small_and_wrong_direction_are_ignored():
    raw = fixture_bytes("yahoo_chart.json")
    assert markets.parse(raw, NIFTY, NOW_M + timedelta(hours=2), freshness_minutes=30) is None
    assert markets.parse(raw, dict(NIFTY, threshold=2.5), NOW_M, freshness_minutes=30) is None
    assert markets.parse(raw, dict(NIFTY, up_only=True), NOW_M, freshness_minutes=30) is None


def test_reddit_parse_keeps_rising_rank():
    sigs = reddit.parse(fixture_bytes("reddit_rising.xml"), "IndiaInvestments")
    assert [(s.title, s.metrics["rising_rank"]) for s in sigs] == [
        ("UPI MDR charges from October 15 - how will it affect SIPs?", 1.0), ("Portfolio review please", 2.0)]
    assert (sigs[0].feed, sigs[0].key) == ("r/IndiaInvestments", "t3_1abcde")


def test_reddit_stops_after_429(monkeypatch):
    monkeypatch.setattr(reddit.time, "sleep", lambda seconds: None)
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(429)

    with pytest.raises(RuntimeError):
        reddit.collect(make_ctx(handler))
    assert len(calls) == 1


def test_reddit_keeps_partial_results(monkeypatch):
    monkeypatch.setattr(reddit.time, "sleep", lambda seconds: None)

    def handler(request):
        if "IndiaTax" in str(request.url):
            return httpx.Response(403)
        return httpx.Response(200, content=fixture_bytes("reddit_rising.xml"))

    assert len(reddit.collect(make_ctx(handler))) == 2 * 7  # 8 subreddits, one forbidden
