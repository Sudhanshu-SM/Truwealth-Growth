"""Time helpers. Everything is stored in UTC; IST is used for display and for day/hour buckets."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

IST = timezone(timedelta(hours=5, minutes=30), "IST")  # India has no DST

_MONTH_FIXES = (("Sept", "Sep"), ("June", "Jun"), ("July", "Jul"))
_DATE_ONLY = re.compile(r"^(\d{1,2}) ([A-Za-z]{3}),? (\d{4})(?: ([+-]\d{4}))?$")  # SEBI: "24 Sep, 2026 +0530"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def from_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def ist(dt: datetime) -> datetime:
    return dt.astimezone(IST)


def ist_date(dt: datetime) -> date:
    return ist(dt).date()


def ist_hour_bucket(dt: datetime) -> str:
    """'YYYY-MM-DDTHH' in IST; used for hourly phrase counts."""
    return ist(dt).strftime("%Y-%m-%dT%H")


def ist_day_start_utc(dt: datetime) -> datetime:
    """Midnight IST of dt's IST date, as a UTC datetime."""
    return ist(dt).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def parse_date(s: str | None, default_tz: timezone = timezone.utc) -> datetime | None:
    """Parse the RSS/Atom dates our feeds emit. Returns an aware UTC datetime, or None."""
    if not s:
        return None
    s = s.strip()
    for bad, good in _MONTH_FIXES:
        s = re.sub(rf"\b{bad}\b", good, s)
    m = _DATE_ONLY.match(s)
    if m:
        day, month, year, offset = m.groups()
        s = f"{day} {month} {year} 00:00:00 {offset or ''}".strip()
    try:
        dt = parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_tz)
    return dt.astimezone(timezone.utc)
