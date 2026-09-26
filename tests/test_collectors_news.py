from datetime import datetime, timezone

import httpx
from helpers import NOW, fixture_bytes, make_ctx

from radar.collectors import google_news, google_trends, news_feeds, regulators


def test_google_trends_parse():
    sigs = google_trends.parse(fixture_bytes("google_trends_in.xml"))
    assert [s.title for s in sigs] == ["gold rate today", "lottery sambad"]
    gold = sigs[0]
    assert gold.source_type == "search_trend"
    assert gold.metrics["approx_traffic"] == 50_000
    assert gold.url == "https://example.test/gold-record"
    assert "Gold hits record high" in gold.text
    assert gold.published_at == datetime(2026, 9, 26, 8, 40, tzinfo=timezone.utc)
    assert sigs[1].metrics["approx_traffic"] == 10_000
    assert sigs[1].url is None


def test_parse_traffic():
    assert google_trends.parse_traffic("2M+") == 2_000_000
    assert google_trends.parse_traffic("500+") == 500
    assert google_trends.parse_traffic(None) == 0


def test_google_news_keeps_indian_outlets_and_strips_suffix():
    sigs = google_news.parse(fixture_bytes("google_news.xml"), lang="en", allowed_domains=frozenset({"bhaskar.com"}))
    assert [s.title for s in sigs] == ["Sensex falls 800 points as FPIs sell", "नए UPI MDR नियम 15 अक्टूबर से लागू होंगे"]
    assert [s.feed for s in sigs] == ["gn:the-economic-times", "gn:dainik-bhaskar"]
    assert sigs[0].source_type == "news"
    assert sigs[0].published_at == datetime(2026, 9, 26, 7, 51, 13, tzinfo=timezone.utc)


def test_indian_source_rules():
    allowed = frozenset({"livemint.com"})
    assert google_news.indian_source("https://www.livemint.com", allowed)
    assert google_news.indian_source("https://economictimes.indiatimes.com", allowed)
    assert google_news.indian_source("https://www.aajtak.in", allowed)
    assert not google_news.indian_source("https://www.fool.com", allowed)


def test_google_news_collect_runs_every_query_for_the_last_hour():
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(200, content=fixture_bytes("google_news.xml"))

    sigs = google_news.collect(make_ctx(handler))
    assert len(seen) == 11
    assert all(u.params["q"].endswith(" when:1h") for u in seen)
    assert len([u for u in seen if u.params["hl"] == "hi"]) == 2
    assert len(sigs) == 22


def test_news_feeds_parse():
    sigs = news_feeds.parse(fixture_bytes("news_feed.xml"), "et_markets")
    assert [s.feed for s in sigs] == ["et_markets", "et_markets"]
    assert sigs[0].text.startswith("J Infratech Ltd")
    assert sigs[1].published_at == datetime(2026, 9, 26, 12, 27, 36, tzinfo=timezone.utc)


def test_news_feeds_collect_survives_failing_feeds():
    def handler(request):
        if "livemint" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, content=fixture_bytes("news_feed.xml"))

    assert len(news_feeds.collect(make_ctx(handler))) == 2 * 10  # 12 feeds, the two Mint feeds fail


def test_regulators_keep_today_and_yesterday_only():
    sigs = regulators.parse(fixture_bytes("sebi.xml"), "sebi", NOW)
    assert [s.title for s in sigs] == ["Key decisions taken in the SEBI Board Meeting dated 24th September, 2026"]
    assert (sigs[0].source_type, sigs[0].feed) == ("regulator", "sebi")
