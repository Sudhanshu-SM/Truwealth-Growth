"""Collector plumbing: the run context, isolated concurrent execution, partial-failure tolerance."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from radar.models import Signal

log = logging.getLogger(__name__)


@dataclass
class Context:
    http: Any       # radar.http.Http
    config: Any     # radar.config.Config
    now: datetime
    run_index: int


Collector = Callable[[Context], list[Signal]]


def run_all(collectors: dict[str, Collector], ctx: Context, workers: int = 8) -> tuple[list[Signal], dict[str, str | None]]:
    """Run collectors concurrently. One failing collector never stops the others."""
    signals: list[Signal] = []
    results: dict[str, str | None] = {}
    if not collectors:
        return signals, results
    with ThreadPoolExecutor(max_workers=min(workers, len(collectors))) as pool:
        futures = {name: pool.submit(fn, ctx) for name, fn in collectors.items()}
        for name, future in futures.items():
            try:
                got = future.result()
            except Exception as exc:  # noqa: BLE001 - isolating collectors is the point
                results[name] = f"{type(exc).__name__}: {str(exc)[:200]}"
                log.warning("collector %s failed: %s", name, type(exc).__name__)
                continue
            signals.extend(got)
            results[name] = None
            log.info("collector %s: %d signals", name, len(got))
    return signals, results


def gather(tasks: list[tuple[str, Callable[[], list[Signal]]]]) -> list[Signal]:
    """Run sub-fetches in order; tolerate partial failure, raise only if every one failed."""
    out: list[Signal] = []
    errors: list[Exception] = []
    for name, fn in tasks:
        try:
            out.extend(fn())
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
            log.warning("sub-fetch %s failed: %s", name, type(exc).__name__)
    if tasks and len(errors) == len(tasks):
        raise errors[-1]
    return out
