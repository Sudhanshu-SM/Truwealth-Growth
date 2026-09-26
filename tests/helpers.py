"""Shared test helpers. pytest puts tests/ on sys.path, so test modules can `from helpers import ...`."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc)  # 13:30 IST


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")
