"""Shared HTTP client: 10 s timeout (5 s to connect), one retry on timeouts, connection errors and 5xx."""
from __future__ import annotations

import time

import httpx

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")


class Http:
    def __init__(self, timeout: float = 10.0, retry_wait: float = 2.0, client: httpx.Client | None = None):
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(timeout, connect=5.0), follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-IN,en;q=0.9"})
        self.retry_wait = retry_wait

    def get(self, url: str, params: dict | None = None) -> httpx.Response:
        for attempt in (1, 2):
            try:
                resp = self.client.get(url, params=params)
            except httpx.TransportError:
                if attempt == 2:
                    raise
                time.sleep(self.retry_wait)
                continue
            if resp.status_code >= 500 and attempt == 1:
                time.sleep(self.retry_wait)
                continue
            resp.raise_for_status()
            return resp
        raise AssertionError("unreachable")

    def close(self) -> None:
        self.client.close()
