"""Tests: coverage rules, fraud aggregation, PII masking, the full graph in deterministic
mode, and the LLM tool-use loop driven by a scripted fake model (no API key needed)."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from app import db  # noqa: E402
from app.pii import Masker  # noqa: E402
from app.tools import coverage, fraud  # noqa: E402


def run(cid: str):
    from app.agent import runner
    runner.run_sync(cid)
    return db.one("SELECT * FROM claims WHERE id = ?", (cid,))


# ---------------------------------------------------------------- units
def test_noisy_or_saturates_and_is_traceable():
    agg = fraud.aggregate([{"code": "A", "weight": 30, "kind": "fraud"}, {"code": "B", "weight": 30, "kind": "fraud"},
                           {"code": "A", "weight": 10, "kind": "fraud"}, {"code": "C", "weight": 50, "kind": "coverage"}])
    assert agg["score"] == 51  # 1 - 0.7*0.7, duplicate code counted once, coverage ignored
    assert [s["code"] for s in agg["signals"]] == ["A", "B"]


def test_pii_masking_is_stable_and_complete():
    m = Masker(names=["Nilesh Shinde"])
    out = m.mask("Nilesh Shinde, 9822041177, nilesh@mail.example, PAN ABCDE1234F")
    assert "9822041177" not in out and "@" not in out and "ABCDE1234F" not in out and "Nilesh" not in out
    assert m.mask("call 9822041177") .split()[-1] == out.split(",")[1].strip()


def test_health_room_rent_proportionate_deduction():
    pol = {"found": True, "line": "health", "incident_in_period": True, "premium_paid": True, "sum_insured": 500000,
           "days_since_first_inception": 1000, "member": {"name": "X", "age": 34, "ped": []}}
    loss = {"total": 186000, "room_rent_per_day": 9000, "days": 3, "associated_charges": 102000}
    r = coverage.health({"description": "appendicitis", "insured_member": "X"}, pol, loss, {"diagnosis": "appendicitis"})
    assert r.data["status"] == "partially_covered"
    assert r.data["payable"]["net"] == 128667


def test_motor_drunk_driving_excluded():
    pol = {"found": True, "line": "motor", "incident_in_period": True, "premium_paid": True, "vehicle_match": True,
           "idv": 600000, "addons": ["zero_dep"], "vehicle": {"cc": 1200, "year": 2022}, "deductible": 0}
    r = coverage.motor({"claim_type": "collision", "incident_date": "2026-11-01"}, pol, {"total": 50000},
                       {"intoxication": True})
    assert r.data["status"] == "not_covered"
    assert any(b["clause_id"] == "M-4.2" and b["outcome"] == "fail" for b in r.data["basis"])


# ---------------------------------------------------------------- graph (deterministic)
@pytest.mark.parametrize("cid,route,status", [
    ("CLM-2611-1001", "fast_track", "approved"),
    ("CLM-2611-1002", "siu", "awaiting_review"),
    ("CLM-2611-1004", "coverage_review", "awaiting_review"),
    ("CLM-2611-1005", "senior", "awaiting_documents"),
    ("CLM-2611-1006", "senior", "assigned"),
    ("CLM-2611-1008", "medical", "assigned"),
])
def test_scenarios_route_as_designed(cid, route, status):
    c = run(cid)
    assert (c["route"], c["status"]) == (route, status)


def test_every_event_is_ordered_and_audit_complete():
    from app import events
    ev = events.since("CLM-2611-1001")
    types = [e["type"] for e in ev]
    for t in ("run_started", "plan", "tool_call", "tool_result", "verify", "assessment", "routing", "report",
              "action", "run_completed"):
        assert t in types, t
    assert types.index("plan") < types.index("tool_call") < types.index("verify") < types.index("routing")


# ---------------------------------------------------------------- LLM loop with a scripted model
def _msg(blocks, stop="end_turn"):
    return NS(content=blocks, stop_reason=stop, usage=NS(input_tokens=100, output_tokens=50, cache_read_input_tokens=0))


def _text(t):
    return NS(type="text", text=t)


def _tool(i, name, inp=None):
    return NS(type="tool_use", id=f"tu_{i}", name=name, input=inp or {})


def test_llm_investigation_loop(monkeypatch):
    from app.agent import graph as g
    monkeypatch.setattr(g, "llm_enabled", lambda: True)
    script = iter([
        _msg([_text("Checking policy and documents first."), _tool(1, "lookup_policy"), _tool(2, "review_documents")],
             "tool_use"),
        _msg([_tool(3, "photo_forensics"), _tool(4, "record_finding", {
            "kind": "fraud", "label": "Implausible chip location", "detail": "Stone chip at driver eye-line",
            "weight": 6, "evidence_ids": ["E2"]}), _tool(5, "record_finding", {
            "kind": "fraud", "label": "Uncited", "detail": "x", "weight": 30, "evidence_ids": ["E99"]})], "tool_use"),
        _msg([_tool(6, "check_coverage")], "tool_use"),
        _msg([_tool(7, "finish_investigation", {"summary": "Routine glass claim.", "open_questions": []})], "tool_use"),
    ])
    calls = []

    def fake_create(**kw):
        calls.append(kw)
        if kw.get("schema") is g.PLAN_SCHEMA:
            return _msg([_text(json.dumps({"depth": "light", "rationale": "Small glass claim.",
                                           "hypotheses": ["Covered"], "steps": [
                                               {"tool": "lookup_policy", "reason": "r"},
                                               {"tool": "photo_forensics", "reason": "r"}]}))])
        if kw.get("schema") is g.REPORT_SCHEMA:
            return _msg([_text(json.dumps({"headline": "Low risk glass claim", "summary": "s", "key_findings": [],
                                           "recommended_actions": [], "handler_brief": "b",
                                           "claimant_message": {"subject": "s", "body": "b"}}))])
        return next(script)

    monkeypatch.setattr(g, "create", fake_create)
    monkeypatch.setattr(g, "json_call", lambda *a, **k: {
        "injury": "none", "third_party_injury": False, "third_party_property": False, "intoxication_mentioned": False,
        "commercial_use_mentioned": False, "engine_water_damage": False, "vulnerable_customer": False, "cause": "na",
        "diagnosis": "", "narrative_red_flags": [], "one_line": "Windshield chip."})
    from app.agent import runner
    db.update("claims", "id", "CLM-2611-1001", {"triage": {"form": {"injury": "none"}, "run": 9}})
    runner.run_sync("CLM-2611-1001")
    t = db.loads(db.one("SELECT triage FROM claims WHERE id = 'CLM-2611-1001'")["triage"], {})
    tools = [e["tool"] for e in t["ledger"]]
    assert tools[:2] == ["lookup_policy", "review_documents"]
    assert "check_coverage" in tools
    assert t["plan"]["steps"][-1]["tool"] == "check_coverage"          # guardrail appended coverage last
    assert "review_documents" in [s["tool"] for s in t["plan"]["steps"]]  # guardrail added mandatory step
    assert [f["label"] for f in t["findings"]] == ["Implausible chip location"]  # uncited finding rejected
    assert t["report"]["headline"] == "Low risk glass claim"
    # Parallel tool results go back in ONE user message, matching tool_use ids.
    inv = [c for c in calls if c.get("tools")]
    last = inv[-1]["messages"]
    tool_msgs = [m for m in last if m["role"] == "user" and isinstance(m["content"], list)]
    assert [r["tool_use_id"] for r in tool_msgs[0]["content"]] == ["tu_1", "tu_2"]
    assert any(r.get("is_error") for r in tool_msgs[1]["content"])  # rejected finding surfaced as error
    # PII never reaches the model.
    blob = json.dumps([c.get("messages") for c in calls], default=str)
    assert "Kavya" not in blob
