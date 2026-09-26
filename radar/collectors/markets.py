"""Big index, gold and currency moves from Yahoo Finance's chart endpoint."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from radar.collectors import Context, gather
from radar.models import Signal
from radar.timeutil import ist_date


def parse(raw: bytes, spec: dict, now: datetime, freshness_minutes: int) -> Signal | None:
    meta = json.loads(raw)["chart"]["result"][0]["meta"]
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    stamp = meta.get("regularMarketTime")
    if not price or not prev or not stamp:
        return None
    at = datetime.fromtimestamp(stamp, tz=timezone.utc)
    if now - at > timedelta(minutes=freshness_minutes):
        return None
    pct = (price - prev) / prev * 100
    threshold = spec["threshold"]
    if abs(pct) < threshold or (spec.get("up_only") and pct < 0):
        return None
    direction = "up" if pct > 0 else "down"
    return Signal(
        source="markets", source_type="market", feed=f"yahoo:{spec['symbol']}",
        title=f"{spec['name']} {direction} {abs(pct):.1f}% today",
        url=f"https://finance.yahoo.com/quote/{quote(spec['symbol'], safe='')}", published_at=at,
        metrics={"pct_move": round(pct, 2), "threshold": float(threshold)},
        key=f"{spec['symbol']}:{direction}:{ist_date(at).isoformat()}", topic_hint=spec["topic"])


def collect(ctx: Context) -> list[Signal]:
    cfg = ctx.config.sources["markets"]

    def one(spec: dict) -> list[Signal]:
        url = cfg["url_template"].format(symbol=quote(spec["symbol"], safe=""))
        sig = parse(ctx.http.get(url, params={"interval": "5m", "range": "1d"}).content, spec, ctx.now,
                    cfg["freshness_minutes"])
        return [sig] if sig else []

    return gather([(s["symbol"], lambda s=s: one(s)) for s in cfg["symbols"]])
