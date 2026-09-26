"""Upcoming dated events for the digest's "Coming up" section."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable


def upcoming(events: Iterable[dict[str, Any]], today: date, days: int) -> list[dict[str, Any]]:
    horizon = today + timedelta(days=days)
    return sorted((e for e in events if e.get("date_end", e["date"]) >= today and e["date"] <= horizon),
                  key=lambda e: e["date"])
