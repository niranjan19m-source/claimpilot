"""Append-only event log per claim. The UI streams it live over SSE and it doubles
as the regulator-facing audit trail: every plan, tool call, finding and decision."""
from __future__ import annotations

import json
from typing import Any

from . import db


def emit(claim_id: str, type_: str, node: str = "", **payload: Any) -> int:
    return db.execute(
        "INSERT INTO claim_events (claim_id, ts, type, node, payload) VALUES (?, ?, ?, ?, ?)",
        (claim_id, db.now_iso(), type_, node, json.dumps(payload, default=str)),
    )


def since(claim_id: str, after_id: int = 0) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT id, ts, type, node, payload FROM claim_events WHERE claim_id = ? AND id > ? ORDER BY id",
        (claim_id, after_id),
    )
    for r in rows:
        r["payload"] = db.loads(r["payload"], {})
    return rows


def clear(claim_id: str) -> None:
    db.execute("DELETE FROM claim_events WHERE claim_id = ?", (claim_id,))
