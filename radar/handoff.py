"""Hand radar decisions to the LinkedIn ghostwriter through the "Topics inbox" Google Sheet.

Optional: without INBOX_SHEET_ID and INBOX_SA_JSON nothing happens. Errors are logged and swallowed, so the radar
never fails because of the ghostwriter. The ghostwriter imports these rows (its spec, section 13)."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Callable, Mapping

from radar.models import Brief
from radar.timeutil import to_iso

log = logging.getLogger(__name__)

INBOX_TAB = "inbox"
INBOX_COLUMNS = ("id", "created_at_utc", "topic_id", "topic", "bucket", "stage", "heat", "kind", "headline",
                 "headline_url", "evidence", "angles", "market_move")


def inbox_row(brief: Brief, kind: str, now: datetime) -> list[str]:
    evidence = "\n".join(f"{text} | {url}" if url else text for text, url in brief.evidence)
    angles = "\n".join(f"{a['name']}: {a['hook']} | {a['linkedin']}" for a in brief.angles)
    values = {
        "id": f"radar:{brief.topic.id}:{now.strftime('%Y%m%d%H%M')}",
        "created_at_utc": to_iso(now),
        "topic_id": brief.topic.id,
        "topic": brief.topic.name,
        "bucket": brief.topic.bucket,
        "stage": brief.score.stage,
        "heat": f"{brief.score.heat:.1f}",
        "kind": kind,
        "headline": brief.headline,
        "headline_url": brief.headline_url or "",
        "evidence": evidence,
        "angles": angles,
        "market_move": "yes" if any(text.startswith("Market:") for text, _ in brief.evidence) else "no",
    }
    return [values[c] for c in INBOX_COLUMNS]


def open_inbox(sheet_id: str, sa_json: str) -> Any:
    import gspread

    sheet = gspread.service_account_from_dict(json.loads(sa_json)).open_by_key(sheet_id)
    try:
        return sheet.worksheet(INBOX_TAB)
    except gspread.exceptions.WorksheetNotFound:
        return sheet.add_worksheet(title=INBOX_TAB, rows=1000, cols=len(INBOX_COLUMNS))


def push_decision(brief: Brief, kind: str, now: datetime, env: Mapping[str, str],
                  opener: Callable[[str, str], Any] = open_inbox) -> bool:
    """Append one decision to the inbox. Returns True when a row was written."""
    sheet_id, sa_json = env.get("INBOX_SHEET_ID", "").strip(), env.get("INBOX_SA_JSON", "").strip()
    if not (sheet_id and sa_json):
        return False
    try:
        ws = opener(sheet_id, sa_json)
        if not ws.row_values(1):
            ws.update([list(INBOX_COLUMNS)], range_name="A1")
        ws.append_rows([inbox_row(brief, kind, now)], value_input_option="RAW", table_range="A1")
        return True
    except Exception as exc:  # never let the ghostwriter break the radar
        log.warning("inbox handoff failed for %s: %s", brief.topic.id, type(exc).__name__)
        return False
