"""ClaimPilot agent graph (LangGraph).

    intake → plan → investigate ⇄ verify → assess → report → docs_gate → human_gate → act
                                                            ↺ await_documents   ↳ await_review

* plan        — risk-proportionate plan with explicit hypotheses (LLM; rule baseline offline)
* investigate — Claude tool-use loop over the toolbox, adapting to what it finds
* verify      — deterministic critic: required evidence present, citations valid, coverage
                re-run after new facts. Sends the agent back with a gap list if not.
* assess      — explainable scoring (noisy-OR fraud score, points-based severity) + routing policy
* docs_gate   — interrupt: blocking documents missing → ask claimant, pause, re-plan on upload
* human_gate  — interrupt: SIU / denial / low confidence → wait for an adjuster's decision
* act         — ticket, assignment, notifications, audit
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Literal, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .. import db, events
from ..config import CHECKPOINT_DB, FAST_MODEL, MAX_TOOL_CALLS, MAX_VERIFY_LOOPS, PRIMARY_MODEL, llm_enabled
from ..llm import create, json_call, strict_schema, text_of, usage_of
from ..pii import Masker
from ..tools import decision, forensics
from ..tools.base import inr
from ..tools.documents import DOC_LABELS
from ..tools.external import WEATHER_PERILS
from ..tools.fraud import aggregate
from . import prompts
from .facts import derive
from .toolbox import CATALOGUE, INVESTIGATION_TOOLS, LABELS, Toolbox, claude_tools


class State(TypedDict, total=False):
    claim_id: str
    mode: str
    started: float
    claim: dict
    intake_facts: dict
    facts: dict
    agent_facts: dict
    plan: dict
    ledger: list
    results: dict
    findings: list
    tool_calls: int
    verify_loops: int
    gaps: list
    verification: dict
    finished: dict
    assessment: dict
    routing: dict
    report: dict
    human: dict
    actions: list
    usage: dict
    pii_masked: int
    decision_ms: int
    requested_docs: list


# ============================================================ helpers
def load_claim(claim_id: str) -> dict:
    c = db.one("SELECT * FROM claims WHERE id = ?", (claim_id,)) or {}
    c["form"] = (db.loads(c.get("triage"), {}) or {}).get("form", {})
    cust = db.one("SELECT name FROM customers WHERE id = ?", (c.get("customer_id"),)) or {}
    c["claimant_name"] = cust.get("name")
    pol = db.one("SELECT details FROM policies WHERE policy_no = ?", (c.get("policy_no"),))
    veh = (db.loads(pol["details"], {}) if pol else {}).get("vehicle", {})
    c["vehicle_reg"] = c["form"].get("vehicle_reg") or veh.get("reg")
    return c


def masker_for(state: State) -> Masker:
    c = state["claim"]
    m = Masker(names=[n for n in (c.get("claimant_name"), c.get("insured_member")) if n])
    return m


def node_event(state: State, node: str, status: str, **kw: Any) -> None:
    events.emit(state["claim_id"], "node", node, status=status, **kw)


def add_usage(state: State, msg) -> None:
    u = state.setdefault("usage", {"input": 0, "output": 0, "cache_read": 0, "calls": 0})
    for k, v in usage_of(msg).items():
        u[k] = u.get(k, 0) + v
    u["calls"] = u.get("calls", 0) + 1


def persist(state: State, status: str | None = None) -> None:
    c = state["claim"]
    prev = db.loads((db.one("SELECT triage FROM claims WHERE id = ?", (c["id"],)) or {}).get("triage"), {}) or {}
    triage = {
        "form": prev.get("form", c.get("form", {})), "mode": state.get("mode"), "plan": state.get("plan"),
        "facts": state.get("facts"), "ledger": state.get("ledger"), "findings": state.get("findings"),
        "verification": state.get("verification"), "assessment": state.get("assessment"),
        "routing": state.get("routing"), "report": state.get("report"), "human": state.get("human"),
        "actions": state.get("actions"), "usage": state.get("usage"), "pii_masked": state.get("pii_masked", 0),
        "finished": state.get("finished"), "decision_ms": state.get("decision_ms"),
    }
    a = state.get("assessment") or {}
    fields: dict[str, Any] = {"triage": triage}
    if a:
        fields.update(severity=a["severity"]["level"], fraud_score=a["fraud"]["score"],
                      coverage_status=a["coverage"].get("status"))
    if state.get("routing"):
        fields["route"] = state["routing"]["queue"]
    if state.get("decision_ms"):
        fields["triage_ms"] = state["decision_ms"]
    if status:
        fields["status"] = status
    db.update("claims", "id", c["id"], fields)


# ============================================================ intake
INTAKE_SCHEMA = strict_schema({
    "injury": {"type": "string", "enum": ["none", "minor", "serious", "fatal"]},
    "third_party_injury": {"type": "boolean"},
    "third_party_property": {"type": "boolean"},
    "intoxication_mentioned": {"type": "boolean"},
    "commercial_use_mentioned": {"type": "boolean"},
    "engine_water_damage": {"type": "boolean"},
    "vulnerable_customer": {"type": "boolean"},
    "cause": {"type": "string", "enum": ["accident", "illness", "na"]},
    "diagnosis": {"type": "string"},
    "narrative_red_flags": {"type": "array", "items": {"type": "string"}},
    "one_line": {"type": "string", "description": "One-sentence neutral summary of the loss"},
})


def intake(state: State) -> dict:
    cid = state["claim_id"]
    node_event(state, "intake", "start")
    claim = load_claim(cid)
    st: State = {**state, "claim": claim, "results": {}, "ledger": [], "findings": [], "agent_facts": {},
                 "tool_calls": 0, "verify_loops": 0, "gaps": [], "finished": {}, "actions": [],
                 "mode": "llm" if llm_enabled() else "deterministic"}
    masker = masker_for(st)
    intake_facts: dict = {}
    if st["mode"] == "llm":
        text = masker.mask(
            f"Line: {claim.get('line')}\nClaim type: {claim.get('claim_type')}\nLoss date: {claim.get('incident_date')} "
            f"{claim.get('incident_time') or ''}\nLocation: {claim.get('location')}, {claim.get('city')}\n"
            f"Amount claimed: {inr(claim.get('amount_claimed'))}\nDeclared injury: {claim['form'].get('injury', 'not stated')}\n"
            f"Account: {claim.get('description')}")
        try:
            msg_facts = json_call(text, INTAKE_SCHEMA, system=prompts.INTAKE_SYSTEM, model=FAST_MODEL)
            intake_facts = msg_facts
        except Exception as exc:
            events.emit(cid, "warning", "intake", message=f"Intake extraction failed, using form data: {exc}")
    st["intake_facts"] = intake_facts
    st["facts"] = derive(st)
    st["pii_masked"] = masker.count
    events.emit(cid, "intake", "intake", claim={k: claim.get(k) for k in (
        "id", "line", "claim_type", "incident_date", "location", "city", "amount_claimed", "policy_no")},
        extracted=intake_facts, facts=st["facts"], pii_masked=masker.count)
    node_event(st, "intake", "end")
    return {k: st[k] for k in ("claim", "results", "ledger", "findings", "agent_facts", "tool_calls",
                               "verify_loops", "gaps", "finished", "actions", "mode", "intake_facts", "facts",
                               "pii_masked")}


# ============================================================ plan
def baseline_plan(claim: dict, facts: dict) -> dict:
    amt = float(claim.get("amount_claimed") or 0)
    line, peril = claim.get("line"), (claim.get("claim_type") or "").lower()
    has_photos = bool(db.one("SELECT 1 FROM documents WHERE claim_id = ? AND kind = 'photo'", (claim["id"],)))
    pol = db.one("SELECT start_date, details FROM policies WHERE policy_no = ?", (claim.get("policy_no"),))
    early = False
    if pol:
        from ..tools.base import parse_date
        s, i = parse_date(pol["start_date"]), parse_date(claim.get("incident_date"))
        early = bool(s and i and 0 <= (i - s).days <= 45)
    deep = amt >= 200000 or early or peril in WEATHER_PERILS or peril == "theft" or facts.get("injury") in ("serious", "fatal")
    light = amt < 25000 and not deep
    depth = "deep" if deep else "light" if light else "standard"
    steps: list[tuple[str, str]] = [
        ("review_documents", "Establish what has been submitted and what is missing"),
        ("lookup_policy", "Confirm the policy was in force and paid on the loss date"),
    ]
    if line == "motor" and depth != "light":
        steps.append(("vehicle_registry", "Confirm the vehicle matches the policy and check permits"))
    if has_photos:
        steps.append(("photo_forensics", "Check photo capture date/location and reuse across claims"))
        if line == "motor" and depth != "light":
            steps.append(("assess_damage_photos", "Check visible damage against the claimant's account"))
    if peril in WEATHER_PERILS:
        steps.append(("geocode_location", "Resolve the loss location for weather verification"))
        steps.append(("check_weather", f"Verify that {peril} conditions occurred on the loss date"))
    steps.append(("claims_history", "Check claim frequency and prior outcomes"))
    if depth != "light":
        steps.append(("network_analysis", "Look for links to known fraud clusters and hotspots"))
        steps.append(("anomaly_model", "Compare the claim profile with genuine historical claims"))
    steps.append(("check_coverage", "Apply policy clauses and compute the payable estimate"))
    hyp = ["The loss is covered under the policy"]
    if early:
        hyp.append("The damage pre-dates the policy (loss soon after inception)")
    if peril in WEATHER_PERILS:
        hyp.append(f"The {peril} event actually occurred at the stated place and date")
    if depth == "deep":
        hyp.append("The claim is connected to organised or repeat fraud")
    reason = {"deep": "High value, new policy, weather peril, theft or serious injury: full investigation.",
              "standard": "Routine profile: standard checks.",
              "light": f"Low value ({inr(amt)}), no risk triggers: light-touch checks for straight-through processing."}[depth]
    return {"depth": depth, "rationale": reason, "hypotheses": hyp,
            "steps": [{"tool": t, "reason": r} for t, r in steps], "source": "rules"}


PLAN_SCHEMA = strict_schema({
    "depth": {"type": "string", "enum": ["light", "standard", "deep"]},
    "rationale": {"type": "string"},
    "hypotheses": {"type": "array", "items": {"type": "string"}},
    "steps": {"type": "array", "items": strict_schema({
        "tool": {"type": "string", "enum": INVESTIGATION_TOOLS}, "reason": {"type": "string"}})},
})
MANDATORY = ["review_documents", "lookup_policy", "check_coverage"]


def plan(state: State) -> dict:
    node_event(state, "plan", "start")
    claim, facts = state["claim"], state["facts"]
    base = baseline_plan(claim, facts)
    p = base
    if state["mode"] == "llm":
        masker = masker_for(state)
        catalogue = "\n".join(f"- {t['name']}: {t['description']}" for t in CATALOGUE if t["name"] in INVESTIGATION_TOOLS)
        docs = db.query("SELECT id, kind, filename FROM documents WHERE claim_id = ?", (claim["id"],))
        prompt = masker.mask(
            f"CLAIM\n{json.dumps({k: claim.get(k) for k in ('line', 'claim_type', 'incident_date', 'incident_time', 'reported_date', 'location', 'city', 'amount_claimed', 'description')}, default=str)}\n"
            f"Extracted facts: {json.dumps(state.get('intake_facts') or {})}\n"
            f"Documents submitted: {json.dumps([{'id': d['id'], 'kind': d['kind'], 'file': d['filename']} for d in docs])}\n\n"
            f"TOOL CATALOGUE\n{catalogue}\n\nA rules-based baseline plan, for reference (improve on it):\n"
            f"{json.dumps(base)}\n\nProduce the investigation plan.")
        try:
            msg = create(model=PRIMARY_MODEL, effort="medium", schema=PLAN_SCHEMA, system=prompts.PLANNER_SYSTEM,
                         messages=[{"role": "user", "content": prompt}])
            add_usage(state, msg)
            p = {**json.loads(text_of(msg)), "source": "llm"}
        except Exception as exc:
            events.emit(state["claim_id"], "warning", "plan", message=f"Planner failed, using rules baseline: {exc}")
    # Guardrail: mandatory steps are always in the plan, coverage always last.
    tools = [s["tool"] for s in p["steps"]]
    for t in MANDATORY:
        if t not in tools:
            p["steps"].insert(0 if t != "check_coverage" else len(p["steps"]),
                              {"tool": t, "reason": "Mandatory step (guardrail)"})
    p["steps"] = [s for s in p["steps"] if s["tool"] != "check_coverage"] + \
                 [next(s for s in p["steps"] if s["tool"] == "check_coverage")]
    for s in p["steps"]:
        s["label"] = LABELS.get(s["tool"], s["tool"])
    events.emit(state["claim_id"], "plan", "plan", **p)
    node_event(state, "plan", "end")
    return {"plan": p, "usage": state.get("usage", {})}


# ============================================================ investigate
def investigate(state: State) -> dict:
    node_event(state, "investigate", "start", loop=state.get("verify_loops", 0))
    st: State = {**state}
    st["results"] = dict(st["results"]); st["ledger"] = list(st["ledger"]); st["findings"] = list(st["findings"])
    st["agent_facts"] = dict(st.get("agent_facts") or {})
    masker = masker_for(st)
    box = Toolbox(st, masker)
    gaps = st.get("gaps") or []
    if st["mode"] == "llm":
        _investigate_llm(st, box, gaps)
    else:
        todo = gaps if gaps else [s["tool"] for s in st["plan"]["steps"]]
        for t in todo:
            if t == "check_coverage" or t not in st["results"]:
                box.call(t, {})
            events.emit(st["claim_id"], "thought", "investigate", text=_auto_thought(t, st))
    st["facts"] = derive(st)
    st["pii_masked"] = st.get("pii_masked", 0) + masker.count
    node_event(st, "investigate", "end", tool_calls=st["tool_calls"])
    return {k: st[k] for k in ("results", "ledger", "findings", "agent_facts", "facts", "tool_calls", "finished",
                               "usage", "pii_masked", "claim") if k in st}


def _auto_thought(tool: str, st: State) -> str:
    e = next((e for e in reversed(st["ledger"]) if e["tool"] == tool), None)
    if not e:
        return f"{LABELS.get(tool, tool)} already available."
    if e["signals"]:
        return f"{LABELS[tool]} raised {len(e['signals'])} flag(s): {e['signals'][0]['label']}."
    return f"{LABELS[tool]}: nothing adverse."


def _investigate_llm(st: State, box: Toolbox, gaps: list[str]) -> None:
    claim = st["claim"]
    budget = MAX_TOOL_CALLS - st["tool_calls"]
    system = prompts.INVESTIGATOR_SYSTEM.format(budget=budget)
    plan_txt = "\n".join(f"{i + 1}. {s['tool']} — {s['reason']}" for i, s in enumerate(st["plan"]["steps"]))
    docs = db.query("SELECT id, kind, filename FROM documents WHERE claim_id = ?", (claim["id"],))
    if gaps:
        ledger_txt = "\n".join(f"[{e['id']}] {e['label']}: {e['summary']}" for e in st["ledger"])
        user = (f"The verifier sent the investigation back. Evidence so far:\n{ledger_txt}\n\n"
                f"Gaps to close: {', '.join(gaps)}. Close them, then call finish_investigation.")
    else:
        user = (f"Claim {claim['id']} ({claim.get('line')}, {claim.get('claim_type')}), loss {claim.get('incident_date')} "
                f"at {claim.get('location')}, {claim.get('city')}. Claimed {inr(claim.get('amount_claimed'))}.\n"
                f"Account: {claim.get('description')}\nDocuments: {json.dumps([dict(d) for d in docs])}\n\n"
                f"Plan ({st['plan']['depth']}):\n{plan_txt}\nHypotheses: {'; '.join(st['plan']['hypotheses'])}\n\n"
                "Execute the plan. Independent steps can be called in parallel.")
    messages: list[dict] = [{"role": "user", "content": box.masker.mask(user)}]
    tools = claude_tools()
    st["finished"] = {}
    for _ in range(12):  # model turns
        try:
            msg = create(model=PRIMARY_MODEL, effort="medium", system=system, tools=tools, messages=messages,
                         thinking={"type": "adaptive", "display": "omitted"})
        except Exception as exc:
            events.emit(st["claim_id"], "warning", "investigate",
                        message=f"LLM investigation interrupted ({exc}); completing plan deterministically.")
            for s in st["plan"]["steps"]:
                if s["tool"] not in st["results"]:
                    box.call(s["tool"], {})
            return
        add_usage(st, msg)
        for b in msg.content:
            # Only the model's public text between tool calls is shown (an action summary);
            # thinking blocks are never surfaced.
            if b.type == "text" and b.text.strip():
                events.emit(st["claim_id"], "thought", "investigate", text=b.text.strip()[:800])
        messages.append({"role": "assistant", "content": msg.content})
        uses = [b for b in msg.content if b.type == "tool_use"]
        if msg.stop_reason == "pause_turn":
            continue
        if not uses:
            break
        results = []
        for u in uses:
            if st["tool_calls"] >= MAX_TOOL_CALLS and u.name != "finish_investigation":
                payload, err = {"error": "Tool budget exhausted. Call finish_investigation now."}, True
            else:
                payload = box.call(u.name, dict(u.input or {}))
                err = not payload.get("ok", True)
            results.append({"type": "tool_result", "tool_use_id": u.id, "content": box.llm_payload(payload),
                            **({"is_error": True} if err else {})})
        messages.append({"role": "user", "content": results})
        if st.get("finished"):
            break
    # The plan is a contract: anything the model skipped that is mandatory is run now.
    for t in MANDATORY:
        if t not in st["results"]:
            box.call(t, {}, auto=True)


# ============================================================ verify
def verify(state: State) -> dict:
    node_event(state, "verify", "start")
    claim, r, ledger = state["claim"], state["results"], state["ledger"]
    checks, gaps = [], []
    conf = 0.95

    def check(name: str, ok: bool, detail: str, gap: str | None = None, penalty: float = 0.0) -> None:
        nonlocal conf
        checks.append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            if gap:
                gaps.append(gap)
            conf -= penalty

    for t in MANDATORY:
        check(f"{LABELS[t]} completed", t in r, "present" if t in r else "missing", t, 0.2)
    peril = (claim.get("claim_type") or "").lower()
    if peril in WEATHER_PERILS:
        w = r.get("check_weather")
        if w is None:
            check("Weather peril independently verified", False, "not run", "check_weather", 0.15)
        else:
            check("Weather peril independently verified", bool(w.get("verified")),
                  "verified" if w.get("verified") else "weather service unavailable", None, 0.15)
    has_photos = bool(db.one("SELECT 1 FROM documents WHERE claim_id = ? AND kind = 'photo'", (claim["id"],)))
    if has_photos:
        check("Photo forensics run", "photo_forensics" in r, "", "photo_forensics", 0.1)
    if claim.get("line") == "motor" and float(claim.get("amount_claimed") or 0) >= 25000:
        check("Vehicle identity confirmed", "vehicle_registry" in r, "", "vehicle_registry", 0.05)
    # Evidence-weight rule: if early risk signals exist, network + history must have been checked.
    sigs = [s for e in ledger for s in e.get("signals", [])]
    if sum(s["weight"] for s in sigs) >= 20:
        check("Escalated checks after red flags", "network_analysis" in r and "claims_history" in r,
              "red flags present → link analysis required",
              "network_analysis" if "network_analysis" not in r else "claims_history", 0.1)
    # Coverage must reflect the latest facts.
    last_cov = max((i for i, e in enumerate(ledger) if e["tool"] == "check_coverage"), default=-1)
    stale = state.get("agent_facts") and last_cov >= 0 and any(
        e["tool"] == "record_fact" for e in ledger[last_cov:])
    check("Coverage reflects latest facts", not stale, "", "check_coverage" if stale else None)
    # Citation integrity of agent findings.
    known = {e["id"] for e in ledger}
    bad = [f for f in state["findings"] if not set(f.get("evidence", [])) <= known]
    check("All findings cite valid evidence", not bad, f"{len(bad)} finding(s) with invalid citations dropped" if bad else "")
    findings = [f for f in state["findings"] if f not in bad]
    failed_tools = [e["label"] for e in ledger if not e["ok"] and e["tool"] not in ("read_document",)]
    if failed_tools:
        conf -= 0.05 * len(failed_tools)
    vis = r.get("assess_damage_photos") or {}
    if vis.get("assessed") and vis.get("confidence", 1) < 0.5:
        conf -= 0.1
    cov = r.get("check_coverage") or {}
    if cov.get("status") == "needs_info":
        conf -= 0.1
    conf = round(max(0.3, min(0.99, conf)), 2)
    loops = state.get("verify_loops", 0) + (1 if gaps else 0)
    can_retry = gaps and loops <= MAX_VERIFY_LOOPS
    v = {"checks": checks, "gaps": gaps, "confidence": conf, "loop": loops, "failed_tools": failed_tools,
         "decision": "reinvestigate" if can_retry else "proceed"}
    events.emit(state["claim_id"], "verify", "verify", **v)
    node_event(state, "verify", "end")
    return {"verification": v, "gaps": gaps if can_retry else [], "verify_loops": loops, "findings": findings}


def after_verify(state: State) -> Literal["investigate", "assess"]:
    return "investigate" if state.get("gaps") else "assess"


# ============================================================ assess
def assess(state: State) -> dict:
    node_event(state, "assess", "start")
    claim, r = state["claim"], state["results"]
    sigs = [dict(s, evidence=[e["id"]], source="tool") for e in state["ledger"] for s in e.get("signals", [])]
    sigs += [f for f in state["findings"]]
    fraud = aggregate(sigs)
    facts = derive(state)
    cov = r.get("check_coverage") or {"status": "needs_info", "payable": {"net": 0, "gross": 0, "lines": []}}
    docs = r.get("review_documents") or {}
    ext = docs.get("extracted", {})
    loss = ext.get("repair_estimate") or ext.get("hospital_bill") or {}
    sev = decision.severity(claim, facts, cov, loss)
    conf = state["verification"]["confidence"]
    routing = decision.route(claim, sev, fraud, cov, docs, conf)
    coverage_flags = [s for s in sigs if s.get("kind") == "coverage"]
    a = {"fraud": fraud, "severity": sev, "coverage": {
        "status": cov.get("status"), "payable": cov.get("payable"), "basis": cov.get("basis", []),
        "failed": cov.get("failed", []), "needs_info": cov.get("needs_info", []),
        "conditions": cov.get("conditions", []), "flags": coverage_flags},
        "confidence": conf, "documents": {"missing": docs.get("missing_labels", []),
                                          "blocking": [DOC_LABELS.get(b, b) for b in docs.get("blocking_missing", [])]}}
    ms = int((time.time() - state["started"]) * 1000)
    events.emit(state["claim_id"], "assessment", "assess", **a)
    events.emit(state["claim_id"], "routing", "assess", **routing)
    st = {**state, "assessment": a, "routing": routing, "facts": facts, "decision_ms": ms}
    persist(st, "triaged")
    node_event(state, "assess", "end")
    return {"assessment": a, "routing": routing, "facts": facts, "decision_ms": ms}


# ============================================================ report
REPORT_SCHEMA = strict_schema({
    "headline": {"type": "string"},
    "summary": {"type": "string"},
    "key_findings": {"type": "array", "items": strict_schema({
        "text": {"type": "string"}, "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "tone": {"type": "string", "enum": ["positive", "neutral", "concern"]}})},
    "recommended_actions": {"type": "array", "items": {"type": "string"}},
    "handler_brief": {"type": "string"},
    "claimant_message": strict_schema({"subject": {"type": "string"}, "body": {"type": "string"}}),
})


def report(state: State) -> dict:
    node_event(state, "report", "start")
    a, rt = state["assessment"], state["routing"]
    rep = _template_report(state)
    if state["mode"] == "llm":
        masker = masker_for(state)
        record = masker.mask(json.dumps({
            "claim": {k: state["claim"].get(k) for k in ("id", "line", "claim_type", "incident_date", "city",
                                                          "amount_claimed", "description")},
            "evidence": [{"id": e["id"], "tool": e["label"], "summary": e["summary"],
                          "signals": [s["label"] + ": " + s["detail"] for s in e["signals"]]} for e in state["ledger"]],
            "agent_findings": state["findings"], "assessment": {
                "fraud": {"score": a["fraud"]["score"], "band": a["fraud"]["band"]},
                "severity": a["severity"], "coverage": {k: a["coverage"][k] for k in ("status", "payable", "failed",
                                                                                       "needs_info", "conditions")},
                "missing_documents": a["documents"]["missing"]},
            "routing": rt}, default=str))
        try:
            msg = create(model=PRIMARY_MODEL, effort="low", schema=REPORT_SCHEMA, system=prompts.REPORT_SYSTEM,
                         messages=[{"role": "user", "content": "Write the triage report.\n" + record}])
            add_usage(state, msg)
            rep = {**json.loads(text_of(msg)), "source": "llm"}
        except Exception as exc:
            events.emit(state["claim_id"], "warning", "report", message=f"Report drafting fell back to template: {exc}")
    events.emit(state["claim_id"], "report", "report", **rep)
    persist({**state, "report": rep})
    node_event(state, "report", "end")
    return {"report": rep, "usage": state.get("usage", {})}


def _template_report(state: State) -> dict:
    a, rt, c = state["assessment"], state["routing"], state["claim"]
    cov, fr, sev = a["coverage"], a["fraud"], a["severity"]
    kf = []
    for s in fr["signals"][:5]:
        kf.append({"text": f"{s['label']}: {s['detail']}", "evidence_ids": s.get("evidence", []), "tone": "concern"})
    for f in cov.get("failed", [])[:2]:
        kf.append({"text": f"Coverage: {f}", "evidence_ids": [], "tone": "concern"})
    if not kf:
        kf.append({"text": "No adverse indicators found across policy, documents, forensics and history.",
                   "evidence_ids": [], "tone": "positive"})
    pay = cov.get("payable") or {}
    status_txt = cov.get("status", "needs_info").replace("_", " ")
    headline = f"{sev['level'].title()} severity · {status_txt} · fraud risk {fr['band']} ({fr['score']}) → {rt['queue_label']}"
    missing = a["documents"]["missing"]
    body = (f"Dear Customer,\n\nWe have received your claim {c['id']}. ")
    if missing:
        body += f"To proceed, please upload: {', '.join(missing)}. "
    if rt["queue"] == "fast_track":
        body += f"Your claim has been approved for an estimated {inr(pay.get('net'))}, subject to final bill verification. "
    elif cov.get("status") == "not_covered":
        body += "Our claims team is reviewing your policy terms against this loss and will write to you shortly. "
    else:
        body += "A claims specialist has been assigned and will contact you within the service timeline. "
    body += "\n\nRegards,\nClaims Team"
    actions = list(rt["rationale"])
    if missing:
        actions.append("Obtain: " + ", ".join(missing))
    return {"headline": headline,
            "summary": f"{c.get('claim_type', '').title()} claim for {inr(c.get('amount_claimed'))}. "
                       f"Coverage {status_txt}; estimated payable {inr(pay.get('net'))}. "
                       f"{len(fr['signals'])} fraud indicator(s), score {fr['score']}.",
            "key_findings": kf, "recommended_actions": actions,
            "handler_brief": " ".join(rt["rationale"]),
            "claimant_message": {"subject": f"Update on your claim {c['id']}", "body": body}, "source": "template"}


# ============================================================ gates
def docs_gate(state: State) -> Command:
    blocking = state["assessment"]["documents"]["blocking"]
    if not blocking:
        return Command(goto="human_gate")
    c = state["claim"]
    msg = (f"To continue processing claim {c['id']}, please upload: {', '.join(blocking)}. "
           "You can reply to this message or use the claim portal.")
    decision.notify(c["id"], "sms", c.get("contact_phone") or "claimant", "Documents required", msg)
    events.emit(state["claim_id"], "action", "docs_gate", kind="document_request",
                summary=f"Requested from claimant: {', '.join(blocking)}")
    events.emit(state["claim_id"], "interrupt", "docs_gate", kind="documents", missing=blocking)
    persist(state, "awaiting_documents")
    return Command(goto="await_documents")


def await_documents(state: State) -> Command:
    # Interrupt-only node: LangGraph re-executes a node from the top on resume, so side
    # effects live in docs_gate and this node does nothing but wait.
    missing = state.get("requested_docs") or state["assessment"]["documents"]["blocking"]
    value = interrupt({"kind": "documents", "missing": missing})
    events.emit(state["claim_id"], "resume", "await_documents", kind="documents", value=value)
    return Command(goto="intake", update={"started": time.time(), "requested_docs": []})


def human_gate(state: State) -> Command:
    rt = state["routing"]
    if not rt["requires_human"]:
        return Command(goto="act")
    events.emit(state["claim_id"], "interrupt", "human_gate", kind="human_review", queue=rt["queue"],
                reason=rt["rationale"])
    persist(state, "awaiting_review")
    return Command(goto="await_review")


def await_review(state: State) -> Command:
    """Waits for an adjuster. Decisions: approve | override | escalate_senior |
    further_investigation | request_documents. Every decision is persisted with the
    original recommendation for the audit trail."""
    rt = state["routing"]
    d = interrupt({"kind": "human_review", "queue": rt["queue"]})
    d = d if isinstance(d, dict) else {"decision": "approve"}
    kind = d.get("decision", "approve")
    target = {"escalate_senior": "senior", "further_investigation": "siu"}.get(kind, d.get("queue"))
    record_decision(state["claim_id"], rt["queue"], kind, target if kind != "approve" else rt["queue"], d)
    events.emit(state["claim_id"], "resume", "await_review", kind="human_review", **d)
    who = d.get("reviewer") or "reviewer"
    why = d.get("reason") or d.get("note") or ""
    if kind == "request_documents":
        docs = d.get("documents") or ["Additional supporting documents"]
        c = state["claim"]
        decision.notify(c["id"], "sms", c.get("contact_phone") or "claimant", "Documents required",
                        f"To continue processing claim {c['id']}, please upload: {', '.join(docs)}.")
        events.emit(state["claim_id"], "action", "await_review", kind="document_request",
                    summary=f"Adjuster requested: {', '.join(docs)}")
        events.emit(state["claim_id"], "interrupt", "await_review", kind="documents", missing=docs)
        persist({**state, "human": d}, "awaiting_documents")
        return Command(goto="await_documents", update={"requested_docs": docs, "human": d})
    new_rt = dict(rt)
    if kind in ("override", "escalate_senior", "further_investigation") and target in decision.QUEUES:
        new_rt.update(queue=target, queue_label=decision.QUEUES[target]["label"], auto_approve=target == "fast_track")
        label = {"override": "Overridden", "escalate_senior": "Escalated to senior adjuster",
                 "further_investigation": "Sent for further investigation"}[kind]
        new_rt["rationale"] = rt["rationale"] + [f"{label} by {who}" + (f": {why}" if why else "")]
    else:
        new_rt["rationale"] = rt["rationale"] + [f"Confirmed by {who}" + (f": {why}" if why else "")]
    new_rt["human_decision"] = d
    return Command(goto="act", update={"routing": new_rt, "human": d})


def record_decision(claim_id: str, original: str, kind: str, new_queue: str | None, d: dict) -> None:
    db.insert("decisions", {"claim_id": claim_id, "original_queue": original, "decision": kind,
                            "new_queue": new_queue, "reason": d.get("reason") or "", "note": d.get("note") or "",
                            "reviewer": d.get("reviewer") or "Claims Manager", "created_at": db.now_iso()})


# ============================================================ act
def act(state: State) -> dict:
    node_event(state, "act", "start")
    c, rt, a, rep = state["claim"], state["routing"], state["assessment"], state["report"]
    actions = []
    sev = a["severity"]
    t = decision.create_ticket(c, rt, sev, rep.get("headline", ""))
    actions.append({"kind": "ticket", "summary": t.summary, **t.data})
    events.emit(c["id"], "action", "act", kind="ticket", summary=t.summary, data=t.data)
    h = t.data.get("handler")
    if h:
        n = decision.notify(c["id"], "in_app", h["name"], f"[{rt['priority']}] New {rt['queue_label']} case {c['id']}",
                            rep.get("handler_brief", ""))
        actions.append({"kind": "notify_handler", "summary": n.summary})
        events.emit(c["id"], "action", "act", kind="notify_handler", summary=n.summary)
        db.update("claims", "id", c["id"], {"assigned_handler": h["id"]})
    cm = rep.get("claimant_message") or {}
    n2 = decision.notify(c["id"], "email", "claimant", cm.get("subject", "Claim update"), cm.get("body", ""))
    actions.append({"kind": "notify_claimant", "summary": n2.summary})
    events.emit(c["id"], "action", "act", kind="notify_claimant", summary=n2.summary)
    if rt.get("auto_approve"):
        pay = a["coverage"]["payable"]["net"]
        actions.append({"kind": "settlement", "summary": f"Payment of {inr(pay)} queued for disbursement."})
        events.emit(c["id"], "action", "act", kind="settlement", summary=f"Payment of {inr(pay)} queued for disbursement.")
    forensics.register_hashes(c["id"])
    status = "approved" if rt.get("auto_approve") else "assigned"
    persist({**state, "actions": actions}, status)
    events.emit(c["id"], "run_completed", "act", status=status, decision_ms=state.get("decision_ms"),
                usage=state.get("usage"))
    node_event(state, "act", "end")
    return {"actions": actions}


# ============================================================ build
def build(checkpointer=None):
    g = StateGraph(State)
    g.add_node("intake", intake)
    g.add_node("plan", plan)
    g.add_node("investigate", investigate)
    g.add_node("verify", verify)
    g.add_node("assess", assess)
    g.add_node("report", report)
    g.add_node("docs_gate", docs_gate, destinations=("human_gate", "await_documents"))
    g.add_node("await_documents", await_documents, destinations=("intake",))
    g.add_node("human_gate", human_gate, destinations=("act", "await_review"))
    g.add_node("await_review", await_review, destinations=("act", "await_documents"))
    g.add_node("act", act)
    g.add_edge(START, "intake")
    g.add_edge("intake", "plan")
    g.add_edge("plan", "investigate")
    g.add_edge("investigate", "verify")
    g.add_conditional_edges("verify", after_verify, {"investigate": "investigate", "assess": "assess"})
    g.add_edge("assess", "report")
    g.add_edge("report", "docs_gate")
    g.add_edge("act", END)
    return g.compile(checkpointer=checkpointer)


_graph = None


def graph():
    global _graph
    if _graph is None:
        conn = sqlite3.connect(CHECKPOINT_DB, check_same_thread=False)
        _graph = build(SqliteSaver(conn))
    return _graph
