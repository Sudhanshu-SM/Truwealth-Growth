"""Shared test helpers. pytest puts tests/ on sys.path, so test modules can `from helpers import ...`."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx

from radar.collectors import Context
from radar.config import load_config
from radar.http import Http

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc)  # 13:30 IST


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_ctx(handler, now: datetime = NOW, run_index: int = 0, config=None) -> Context:
    """Collector context whose HTTP calls go to `handler(request) -> httpx.Response`."""
    http = Http(retry_wait=0, client=httpx.Client(transport=httpx.MockTransport(handler)))
    return Context(http=http, config=config or load_config(), now=now, run_index=run_index)
