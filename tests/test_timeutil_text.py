from datetime import datetime, timezone

from radar.text import clean, normalize_title, sha1, slugify
from radar.timeutil import IST, from_iso, ist_date, ist_day_start_utc, ist_hour_bucket, parse_date, to_iso


def test_parse_rfc822_with_offset():
    assert parse_date("Sat, 26 Sep 2026 06:50:00 -0700") == datetime(2026, 9, 26, 13, 50, tzinfo=timezone.utc)


def test_parse_mint_sept_month():
    assert parse_date("Sat, 26 Sept 2026 17:57:36 +0530") == datetime(2026, 9, 26, 12, 27, 36, tzinfo=timezone.utc)


def test_parse_missing_timezone_uses_default():
    assert parse_date("Fri, 25 Sep 2026 21:50:00", IST) == datetime(2026, 9, 25, 16, 20, tzinfo=timezone.utc)


def test_parse_sebi_date_only():
    assert parse_date("24 Sep, 2026 +0530") == datetime(2026, 9, 23, 18, 30, tzinfo=timezone.utc)


def test_parse_iso():
    assert parse_date("2026-09-26T12:43:44+00:00") == datetime(2026, 9, 26, 12, 43, 44, tzinfo=timezone.utc)


def test_parse_garbage_returns_none():
    assert parse_date("not a date") is None
    assert parse_date(None) is None


def test_iso_roundtrip():
    dt = datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc)
    assert to_iso(dt) == "2026-09-26T08:00:00+00:00"
    assert from_iso(to_iso(dt)) == dt


def test_ist_helpers():
    dt = datetime(2026, 9, 26, 20, 0, tzinfo=timezone.utc)  # 01:30 IST on 27 Sep
    assert ist_hour_bucket(dt) == "2026-09-27T01"
    assert ist_date(dt).isoformat() == "2026-09-27"
    assert ist_day_start_utc(dt) == datetime(2026, 9, 26, 18, 30, tzinfo=timezone.utc)


def test_clean_strips_tags_emoji_and_entities():
    assert clean("<p>Gold &amp; silver</p> \U0001F6A6 rally\n now") == "Gold & silver rally now"


def test_normalize_hash_slug():
    assert normalize_title("  Nifty  Hits RECORD ") == "nifty hits record"
    assert sha1("a", "b") != sha1("ab")
    assert slugify("UPI Charges!") == "upi-charges"
