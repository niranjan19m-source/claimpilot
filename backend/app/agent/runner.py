"""Runs the agent graph in background threads (one per claim) and resumes it after
human or claimant input. Thread id == claim id, so state survives server restarts."""
from __future__ import annotations

import threading
import time
import traceback
from typing import Any

from langgraph.types import Command

from .. import db, events
from ..config import FAST_MODEL, PRIMARY_MODEL, llm_enabled
from .graph import graph

_running: set[str] = set()
_lock = threading.Lock()


def _cfg(claim_id: str, run: int) -> dict:
    return {"configurable": {"thread_id": f"{claim_id}:{run}"}, "recursion_limit": 60}


def _run_no(claim_id: str) -> int:
    t = db.loads((db.one("SELECT triage FROM claims WHERE id = ?", (claim_id,)) or {}).get("triage"), {}) or {}
    return int(t.get("run", 1))


def _after(claim_id: str, out: Any) -> None:
    intr = (out or {}).get("__interrupt__") if isinstance(out, dict) else None
    if intr:
        kind = intr[0].value.get("kind") if hasattr(intr[0], "value") else "unknown"
        events.emit(claim_id, "paused", "runner", kind=kind)


def _work(claim_id: str, payload: Any, fresh: bool) -> None:
    try:
        run = _run_no(claim_id)
        if fresh:
            events.emit(claim_id, "run_started", "runner", mode="llm" if llm_enabled() else "deterministic",
                        model=PRIMARY_MODEL if llm_enabled() else None,
                        fast_model=FAST_MODEL if llm_enabled() else None)
            out = graph().invoke({"claim_id": claim_id, "started": time.time()}, _cfg(claim_id, run))
        else:
            out = graph().invoke(Command(resume=payload), _cfg(claim_id, run))
        _after(claim_id, out)
    except Exception as exc:
        traceback.print_exc()
        events.emit(claim_id, "error", "runner", message=f"{type(exc).__name__}: {exc}")
        db.update("claims", "id", claim_id, {"status": "error"})
    finally:
        with _lock:
            _running.discard(claim_id)


def start(claim_id: str, rerun: bool = False) -> bool:
    with _lock:
        if claim_id in _running:
            return False
        _running.add(claim_id)
    if rerun:
        t = db.loads((db.one("SELECT triage FROM claims WHERE id = ?", (claim_id,)) or {}).get("triage"), {}) or {}
        form = t.get("form", {})
        db.update("claims", "id", claim_id, {"triage": {"form": form, "run": int(t.get("run", 1)) + 1},
                                              "status": "triaging", "severity": None, "fraud_score": None,
                                              "coverage_status": None, "route": None, "assigned_handler": None})
        events.clear(claim_id)
        db.execute("DELETE FROM tickets WHERE claim_id = ?", (claim_id,))
        db.execute("DELETE FROM notifications WHERE claim_id = ?", (claim_id,))
    else:
        db.update("claims", "id", claim_id, {"status": "triaging"})
    threading.Thread(target=_work, args=(claim_id, None, True), daemon=True).start()
    return True


def resume(claim_id: str, payload: dict) -> bool:
    with _lock:
        if claim_id in _running:
            return False
        _running.add(claim_id)
    db.update("claims", "id", claim_id, {"status": "triaging"})
    threading.Thread(target=_work, args=(claim_id, payload, False), daemon=True).start()
    return True


def run_sync(claim_id: str) -> None:
    """Blocking run used by the eval harness; auto-approves human gates."""
    run = _run_no(claim_id)
    events.emit(claim_id, "run_started", "runner", mode="llm" if llm_enabled() else "deterministic")
    out = graph().invoke({"claim_id": claim_id, "started": time.time()}, _cfg(claim_id, run))
    _after(claim_id, out)


def is_running(claim_id: str) -> bool:
    return claim_id in _running
