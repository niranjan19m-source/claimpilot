"""Endpoints added for the investigation dashboard: honest system status, evidence
index, audit trail, analytics, policy library, human decisions and rerouting."""
from __future__ import annotations

import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from . import db, events
from .agent import runner
from .agent.graph import record_decision
from .config import ALLOW_NETWORK, DEMO_PACE, FAST_MODEL, MAX_TOOL_CALLS, PRIMARY_MODEL, UPLOAD_DIR, llm_enabled
from .tools import policy as policy_tool
from .tools.decision import QUEUES, create_ticket
from .tools.documents import extract_text

router = APIRouter(prefix="/api")

# ------------------------------------------------------------------ status
_probe_cache: dict[str, tuple[float, dict]] = {}


def _probe(name: str, url: str, params: dict) -> dict:
    """Cheap reachability probe, cached for 60s so the top bar can poll it."""
    hit = _probe_cache.get(name)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    if not ALLOW_NETWORK:
        res = {"state": "disabled", "detail": "Network access disabled (CLAIMPILOT_ALLOW_NETWORK=0); cache only"}
    else:
        try:
            r = httpx.get(url, params=params, timeout=4, headers={"User-Agent": "ClaimPilot-hackathon-demo/1.0"})
            res = {"state": "connected" if r.status_code < 500 else "degraded", "detail": f"HTTP {r.status_code}"}
        except httpx.HTTPError as exc:
            res = {"state": "unavailable", "detail": type(exc).__name__}
    _probe_cache[name] = (time.time(), res)
    return res


@router.get("/status")
def status() -> dict:
    try:
        n = db.one("SELECT COUNT(*) AS n FROM policies")["n"]
        dbs = {"state": "connected", "detail": f"{n} policies"}
    except Exception as exc:  # pragma: no cover
        dbs = {"state": "unavailable", "detail": str(exc)}
    return {
        "agent": {"state": "online", "mode": "llm" if llm_enabled() else "deterministic",
                  "model": PRIMARY_MODEL if llm_enabled() else None, "fast_model": FAST_MODEL if llm_enabled() else None},
        "services": {
            "policy_database": dbs,
            "llm_provider": {"state": "connected" if llm_enabled() else "not_configured",
                             "detail": "Anthropic API" if llm_enabled() else "ANTHROPIC_API_KEY not set — rules mode"},
            "weather_api": _probe("weather", "https://archive-api.open-meteo.com/v1/archive",
                                  {"latitude": 19, "longitude": 72.8, "start_date": "2026-01-01", "end_date": "2026-01-01",
                                   "daily": "precipitation_sum"}),
            "geocoder": _probe("geocoder", "https://nominatim.openstreetmap.org/status", {"format": "json"}),
            "vehicle_registry": {"state": "mock", "detail": "Simulated VAHAN registry (local data)"},
            "reverse_image_search": {"state": "not_configured", "detail": "No provider configured; local perceptual-hash matching only"},
        },
        "data": {"source": "synthetic", "detail": "All claims, policies and people are synthetic demo data"},
    }


@router.get("/settings")
def settings() -> dict:
    """Non-secret configuration. Keys are never returned, only whether they are set."""
    return {"llm_provider": "anthropic" if llm_enabled() else "none", "primary_model": PRIMARY_MODEL,
            "fast_model": FAST_MODEL, "anthropic_key_configured": llm_enabled(), "max_tool_calls": MAX_TOOL_CALLS,
            "demo_pace_seconds": DEMO_PACE, "network_enabled": ALLOW_NETWORK,
            "queues": {k: v["label"] for k, v in QUEUES.items()}}


# ------------------------------------------------------------------ evidence
CATEGORY = {"lookup_policy": "policy", "check_coverage": "policy", "search_policy_wording": "policy",
            "review_documents": "documents", "read_document": "documents", "check_weather": "weather",
            "geocode_location": "location", "photo_forensics": "image_forensics", "assess_damage_photos": "image_forensics",
            "claims_history": "claim_history", "network_analysis": "claim_history", "anomaly_model": "analytics",
            "vehicle_registry": "registry"}
STAGE = {"policy": "Policy verification", "documents": "Data extraction", "weather": "External investigation",
         "location": "External investigation", "registry": "External investigation", "image_forensics": "Fraud analysis",
         "claim_history": "Fraud analysis", "analytics": "Fraud analysis"}


def _status_of(e: dict) -> str:
    if not e.get("ok"):
        return "unverified"
    if e.get("signals"):
        return "contradictory"
    return "verified"


@router.get("/evidence")
def evidence(claim_id: str | None = None, category: str | None = None, status: str | None = None,
             q: str | None = None) -> list[dict]:
    rows = db.query("SELECT id, triage, claim_type, amount_claimed FROM claims WHERE historical = 0 AND triage IS NOT NULL"
                    + (" AND id = ?" if claim_id else ""), (claim_id,) if claim_id else ())
    out = []
    for c in rows:
        t = db.loads(c["triage"], {}) or {}
        for e in t.get("ledger") or []:
            cat = CATEGORY.get(e["tool"], "other")
            item = {"evidence_id": e["id"], "key": f"{c['id']}:{e['id']}", "claim_id": c["id"], "tool": e["tool"],
                    "label": e["label"], "category": cat, "stage": STAGE.get(cat, "Investigation"),
                    "summary": e["summary"], "status": _status_of(e), "signals": e.get("signals", []),
                    "ms": e.get("ms"), "data": e.get("data"), "input": e.get("input"), "auto": e.get("auto", False)}
            out.append(item)
        for f in t.get("findings") or []:
            out.append({"evidence_id": ",".join(f.get("evidence", [])), "key": f"{c['id']}:{f['code']}",
                        "claim_id": c["id"], "tool": "agent_finding", "label": f["label"], "category": "agent_finding",
                        "stage": "Evidence verification", "summary": f["detail"], "status": "interpretation",
                        "signals": [f], "ms": None, "data": f, "input": {}, "auto": False})
    if category:
        out = [o for o in out if o["category"] == category]
    if status:
        out = [o for o in out if o["status"] == status]
    if q:
        ql = q.lower()
        out = [o for o in out if ql in (o["summary"] + o["label"] + o["claim_id"]).lower()]
    return out


# ------------------------------------------------------------------ audit trail
AUDIT_TYPES = {"run_started": "agent", "plan": "agent", "tool_result": "tool", "finding": "evidence", "fact": "evidence",
               "verify": "verification", "routing": "routing", "interrupt": "human", "resume": "human",
               "action": "action", "document_received": "document", "run_completed": "agent", "error": "error",
               "warning": "error"}


def _audit_text(e: dict) -> str:
    p = e["payload"]
    t = e["type"]
    if t == "tool_result":
        return f"{p.get('label')} [{p.get('evidence_id')}]: {p.get('summary')}"
    if t == "plan":
        return f"Plan: {p.get('depth')} investigation, {len(p.get('steps', []))} steps"
    if t == "verify":
        return f"Verifier: confidence {round(p.get('confidence', 0) * 100)}%, {len(p.get('gaps', []))} gap(s)"
    if t == "routing":
        return f"Recommended {p.get('queue_label')} ({p.get('priority')})"
    if t == "interrupt":
        return "Paused for documents: " + ", ".join(p.get("missing", [])) if p.get("kind") == "documents" else "Paused for human review"
    if t == "resume":
        return f"Human decision: {p.get('decision', 'documents received')}" + (f" → {p['queue']}" if p.get("queue") else "")
    if t in ("finding", "fact"):
        return f"{p.get('label') or p.get('key')}: {p.get('detail') or p.get('value')}"
    if t == "run_started":
        return f"Agent run started ({p.get('mode')})"
    if t == "run_completed":
        return f"Investigation completed: {p.get('status')}"
    if t == "document_received":
        return f"Document received: {p.get('label')}"
    return p.get("summary") or p.get("message") or t


@router.get("/audit")
def audit(claim_id: str | None = None, category: str | None = None, q: str | None = None, limit: int = 500) -> list[dict]:
    rows = db.query("SELECT id, claim_id, ts, type, node, payload FROM claim_events "
                    + ("WHERE claim_id = ? " if claim_id else "") + "ORDER BY id DESC LIMIT ?",
                    (claim_id, limit) if claim_id else (limit,))
    out = []
    for r in rows:
        if r["type"] not in AUDIT_TYPES:
            continue
        r["payload"] = db.loads(r["payload"], {})
        out.append({"id": f"ev-{r['id']}", "claim_id": r["claim_id"], "ts": r["ts"], "category": AUDIT_TYPES[r["type"]],
                    "actor": "Adjuster" if r["type"] == "resume" and r["payload"].get("kind") == "human_review"
                    else "Claimant" if r["type"] == "document_received" else "ClaimPilot",
                    "type": r["type"], "text": _audit_text(r)})
    for d in db.query("SELECT * FROM decisions " + ("WHERE claim_id = ? " if claim_id else "") + "ORDER BY id DESC",
                      (claim_id,) if claim_id else ()):
        out.append({"id": f"dec-{d['id']}", "claim_id": d["claim_id"], "ts": d["created_at"], "category": "human",
                    "actor": d["reviewer"], "type": "decision",
                    "text": f"{d['decision'].replace('_', ' ').title()}: recommendation {d['original_queue']} → "
                            f"{d['new_queue']}" + (f" · reason: {d['reason']}" if d["reason"] else "")})
    out.sort(key=lambda x: x["ts"], reverse=True)
    if category:
        out = [o for o in out if o["category"] == category]
    if q:
        ql = q.lower()
        out = [o for o in out if ql in (o["text"] + o["claim_id"] + o["actor"]).lower()]
    return out[:limit]


@router.get("/decisions")
def decisions(claim_id: str | None = None) -> list[dict]:
    return db.query("SELECT * FROM decisions " + ("WHERE claim_id = ? " if claim_id else "") + "ORDER BY id DESC",
                    (claim_id,) if claim_id else ())


# ------------------------------------------------------------------ analytics
@router.get("/analytics")
def analytics() -> dict:
    live = db.query("SELECT id, route, status, fraud_score, severity, triage_ms, triage, line FROM claims WHERE historical = 0")
    triaged = [c for c in live if c["route"]]
    routes = Counter(c["route"] for c in triaged)
    bands = Counter("high" if c["fraud_score"] >= 60 else "medium" if c["fraud_score"] >= 30 else "low"
                    for c in triaged if c["fraud_score"] is not None)
    sev = Counter(c["severity"] for c in triaged if c["severity"])
    missing: Counter = Counter()
    signals: Counter = Counter()
    times = []
    for c in triaged:
        t = db.loads(c["triage"], {}) or {}
        a = t.get("assessment") or {}
        for m in (a.get("documents") or {}).get("missing", []):
            missing[m] += 1
        for s in (a.get("fraud") or {}).get("signals", []):
            signals[s["label"]] += 1
        if c["triage_ms"]:
            times.append({"claim_id": c["id"], "seconds": round(c["triage_ms"] / 1000, 2),
                          "tools": len(t.get("ledger") or [])})
    decs = db.query("SELECT decision FROM decisions")
    hist = db.query("SELECT outcome, COUNT(*) AS n FROM claims WHERE historical = 1 GROUP BY outcome")
    return {
        "scope": {"live_claims": len(live), "triaged": len(triaged),
                  "note": "Computed from the synthetic demo book in the database."},
        "routes": [{"queue": k, "label": QUEUES[k]["label"], "count": v} for k, v in routes.most_common()],
        "risk_bands": [{"band": b, "count": bands.get(b, 0)} for b in ("low", "medium", "high")],
        "severity": [{"level": s, "count": sev.get(s, 0)} for s in ("low", "medium", "high", "critical")],
        "triage_times": sorted(times, key=lambda x: x["claim_id"]),
        "missing_documents": [{"document": k, "count": v} for k, v in missing.most_common()],
        "discrepancies": [{"signal": k, "count": v} for k, v in signals.most_common(10)],
        "human_decisions": {"total": len(decs), **Counter(d["decision"] for d in decs)},
        "history_outcomes": [{"outcome": h["outcome"], "count": h["n"]} for h in hist],
    }


# ------------------------------------------------------------------ policy library
@router.get("/policy-library")
def policy_library(q: str | None = None, product: str | None = None, kind: str | None = None) -> dict:
    clauses = [dict(c) for c in policy_tool._clauses()]
    for c in clauses:
        c["kind"] = ("exclusion" if "exclusion" in c["title"].lower() else
                     "condition" if "condition" in c["title"].lower() else
                     "waiting_period" if "waiting" in c["title"].lower() or "pre-existing" in c["title"].lower() else
                     "limit" if any(w in c["title"].lower() for w in ("deductible", "limit", "co-payment", "sub-limit",
                                                                       "depreciation", "idv", "total loss")) else "coverage")
        c["source"] = policy_tool.WORDING_FILES[c["product"]]
    if q:
        hits = policy_tool.search_wording(q, product, k=12).data.get("clauses", [])
        order = {h["id"]: h["score"] for h in hits}
        clauses = sorted([c for c in clauses if c["id"] in order], key=lambda c: -order[c["id"]])
        for c in clauses:
            c["score"] = order[c["id"]]
    if product:
        clauses = [c for c in clauses if c["product"] == product]
    if kind:
        clauses = [c for c in clauses if c["kind"] == kind]
    uploads = db.query("SELECT id, name, filename, product, status, created_at, clauses FROM policy_library ORDER BY id DESC")
    for u in uploads:
        u["clauses"] = db.loads(u["clauses"], [])
    return {"products": [{"code": k, "file": v} for k, v in policy_tool.WORDING_FILES.items()],
            "clauses": clauses, "uploads": uploads}


@router.post("/policy-library")
async def upload_policy(file: UploadFile = File(...)) -> dict:
    name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(file.filename or "policy").name)[:120]
    if Path(name).suffix.lower() not in (".pdf", ".md", ".txt"):
        raise HTTPException(400, "Upload a PDF, Markdown or text policy wording")
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "File larger than 10 MB")
    dest = UPLOAD_DIR / "policies"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / name).write_bytes(data)
    text = extract_text(dest / name)
    # Clause detection: lines like "### M-2.1 Title", "4.2 Exclusion — ...", "Clause 7: ...".
    found = []
    for m in re.finditer(r"(?m)^(?:#+\s*)?((?:[A-Z]{1,3}-)?\d+(?:\.\d+)+|Clause\s+\d+[a-z]?)[:.)]?\s+(.{3,100})$", text):
        found.append({"id": m.group(1), "title": m.group(2).strip()})
    status = f"{len(found)} clauses detected" if found else ("Text extracted; no numbered clauses detected"
                                                             if text.strip() else "No extractable text (scanned PDF?)")
    pid = db.insert("policy_library", {"name": Path(name).stem, "filename": name, "path": str(dest / name),
                                       "product": None, "clauses": found[:300], "status": status,
                                       "created_at": db.now_iso()})
    return {"id": pid, "status": status, "clauses": len(found)}


# ------------------------------------------------------------------ decisions
class Decision(BaseModel):
    decision: str = Field(pattern="^(approve|override|escalate_senior|further_investigation|request_documents)$")
    queue: str | None = None
    reason: str = ""
    note: str = ""
    reviewer: str = "Claims Manager"
    documents: list[str] = []


def validate(body: Decision) -> None:
    if body.decision == "override":
        if body.queue not in QUEUES:
            raise HTTPException(400, "Override needs a valid routing destination")
        if len(body.reason.strip()) < 5:
            raise HTTPException(400, "Override needs a reason (at least 5 characters)")
    if body.decision in ("escalate_senior", "further_investigation") and len(body.reason.strip()) < 5:
        raise HTTPException(400, "Escalation needs a reason")
    if body.decision == "request_documents" and not body.documents:
        raise HTTPException(400, "List the documents to request")


@router.post("/claims/{claim_id}/decision")
def decide(claim_id: str, body: Decision) -> dict:
    """Human decision. If the agent is paused for review, this resumes the graph;
    if the claim is already assigned, it reroutes the existing ticket (post-hoc override)."""
    validate(body)
    c = db.one("SELECT * FROM claims WHERE id = ?", (claim_id,))
    if not c:
        raise HTTPException(404, "Claim not found")
    if c["status"] == "awaiting_review":
        runner.resume(claim_id, body.model_dump())
        return {"mode": "resumed_agent"}
    if c["status"] not in ("assigned", "approved"):
        raise HTTPException(409, f"Claim is '{c['status']}'; decisions apply to claims awaiting review or assigned")
    if body.decision == "approve":
        record_decision(claim_id, c["route"], "approve", c["route"], body.model_dump())
        events.emit(claim_id, "resume", "adjuster", kind="human_review", **body.model_dump())
        return {"mode": "recorded"}
    if body.decision == "request_documents":
        db.insert("notifications", {"claim_id": claim_id, "channel": "sms", "recipient": c["contact_phone"] or "claimant",
                                    "subject": "Documents required",
                                    "body": f"To continue processing claim {claim_id}, please upload: {', '.join(body.documents)}.",
                                    "created_at": db.now_iso()})
        record_decision(claim_id, c["route"], "request_documents", c["route"], body.model_dump())
        events.emit(claim_id, "action", "adjuster", kind="document_request",
                    summary=f"Adjuster requested: {', '.join(body.documents)}")
        return {"mode": "recorded"}
    target = {"escalate_senior": "senior", "further_investigation": "siu"}.get(body.decision, body.queue)
    if target == c["route"]:
        raise HTTPException(400, "Claim is already in that queue")
    t = db.loads(c["triage"], {}) or {}
    rt = dict(t.get("routing") or {})
    rt.update(queue=target, queue_label=QUEUES[target]["label"], auto_approve=False, requires_human=False)
    rt["rationale"] = (rt.get("rationale") or []) + [f"Rerouted by {body.reviewer}: {body.reason}"]
    db.execute("UPDATE tickets SET status = 'reassigned' WHERE claim_id = ? AND status IN ('open','auto_approved')", (claim_id,))
    sev = (t.get("assessment") or {}).get("severity") or {"level": "medium"}
    ticket = create_ticket({**c}, rt, sev, f"Rerouted: {body.reason}")
    t["routing"] = rt
    db.update("claims", "id", claim_id, {"route": target, "status": "assigned", "triage": t,
                                         "assigned_handler": (ticket.data.get("handler") or {}).get("id")})
    record_decision(claim_id, c["route"], body.decision, target, body.model_dump())
    events.emit(claim_id, "resume", "adjuster", kind="human_review", **body.model_dump(), queue_label=QUEUES[target]["label"])
    events.emit(claim_id, "action", "adjuster", kind="ticket", summary=ticket.summary, data=ticket.data)
    return {"mode": "rerouted", "ticket": ticket.data["ticket_id"]}


# ------------------------------------------------------------------ helpers for the UI
@router.get("/claims/{claim_id}/forensics")
def claim_forensics(claim_id: str) -> dict[str, Any]:
    t = db.loads((db.one("SELECT triage FROM claims WHERE id = ?", (claim_id,)) or {}).get("triage"), {}) or {}
    led = t.get("ledger") or []
    pick = lambda tool: next((e for e in reversed(led) if e["tool"] == tool), None)  # noqa: E731
    return {"photo_forensics": pick("photo_forensics"), "vision": pick("assess_damage_photos"),
            "network": pick("network_analysis"), "history": pick("claims_history")}
