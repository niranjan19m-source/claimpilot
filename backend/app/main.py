"""ClaimPilot HTTP API."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from . import db, events, seed
from .api_extra import router as extra_router
from .agent import runner
from .agent.prompts import COPILOT_SYSTEM
from .config import BASE_DIR, FAST_MODEL, PRIMARY_MODEL, UPLOAD_DIR, llm_enabled
from .llm import create, text_of
from .pii import Masker
from .tools.decision import QUEUES
from .tools.documents import DOC_LABELS, classify, extract_text

def _startup() -> None:
    db.init_db()
    if not db.one("SELECT 1 FROM claims LIMIT 1"):
        seed.run()
    # Runs interrupted by a server restart resume from their LangGraph checkpoint on the next action;
    # anything stuck mid-node is marked so the UI can offer a re-run.
    db.execute("UPDATE claims SET status = 'interrupted' WHERE status = 'triaging'")


@asynccontextmanager
async def lifespan(_: FastAPI):
    _startup()
    yield


app = FastAPI(title="ClaimPilot", version="1.1", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(extra_router)

SUMMARY_COLS = ("id, policy_no, line, claim_type, incident_date, city, amount_claimed, status, severity, fraud_score, "
                "coverage_status, route, assigned_handler, created_at, scenario, triage_ms")


# ---------------------------------------------------------------- meta
@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "mode": "llm" if llm_enabled() else "deterministic",
            "model": PRIMARY_MODEL if llm_enabled() else None, "fast_model": FAST_MODEL if llm_enabled() else None,
            "queues": {k: v["label"] for k, v in QUEUES.items()}}


@app.get("/api/stats")
def stats() -> dict:
    live = db.query(f"SELECT {SUMMARY_COLS} FROM claims WHERE historical = 0")
    done = [c for c in live if c["route"]]
    by_route: dict[str, int] = {}
    for c in done:
        by_route[c["route"]] = by_route.get(c["route"], 0) + 1
    times = [c["triage_ms"] for c in done if c["triage_ms"]]
    payable = 0
    for c in done:
        t = db.loads((db.one("SELECT triage FROM claims WHERE id = ?", (c["id"],)) or {}).get("triage"), {}) or {}
        payable += ((t.get("assessment") or {}).get("coverage") or {}).get("payable", {}).get("net", 0) or 0
    return {
        "total": len(live), "triaged": len(done),
        "straight_through": by_route.get("fast_track", 0),
        "siu": by_route.get("siu", 0),
        "awaiting_human": sum(1 for c in live if c["status"] in ("awaiting_review", "awaiting_documents")),
        "avg_triage_s": round(sum(times) / len(times) / 1000, 1) if times else None,
        "by_route": by_route, "payable_total": payable,
        "history": db.one("SELECT COUNT(*) AS n FROM claims WHERE historical = 1")["n"],
    }


@app.get("/api/scenarios")
def scenarios() -> list[dict]:
    idx = seed.scenario_index()
    for s in idx:
        c = db.one("SELECT status, route, fraud_score, severity FROM claims WHERE id = ?", (s["id"],)) or {}
        s.update(c)
        s.pop("upload_hint", None)
        s["has_upload"] = s["id"] == "CLM-2611-1005"
    return idx


@app.get("/api/scenarios/{claim_id}/upload-sample")
def scenario_upload(claim_id: str):
    hint = next((s.get("upload_hint") for s in seed.scenario_index() if s["id"] == claim_id), None)
    if not hint or not Path(hint).exists():
        raise HTTPException(404, "No sample upload for this scenario")
    return FileResponse(hint, filename="FIR_0871_2026.pdf", media_type="application/pdf")


# ---------------------------------------------------------------- claims
def mask_name(name: str | None) -> str:
    """'Nilesh Shinde' -> 'N. S*****'. Cards and lists never need full names."""
    if not name:
        return "Unknown claimant"
    parts = name.split()
    return f"{parts[0][0]}. {parts[-1][0]}{'*' * max(2, len(parts[-1]) - 1)}" if len(parts) > 1 else parts[0][0] + "***"


@app.get("/api/claims")
def list_claims(history: bool = False, limit: int = 100) -> list[dict]:
    where = "" if history else "WHERE historical = 0"
    rows = db.query(f"SELECT {SUMMARY_COLS}, customer_id, triage FROM claims {where} ORDER BY created_at DESC LIMIT ?", (limit,))
    hmap = {h["id"]: h["name"] for h in db.query("SELECT id, name FROM handlers")}
    names = {c["id"]: c["name"] for c in db.query("SELECT id, name FROM customers")}
    for r in rows:
        t = db.loads(r.pop("triage"), {}) or {}
        a = t.get("assessment") or {}
        rt = t.get("routing") or {}
        r["handler_name"] = hmap.get(r["assigned_handler"])
        r["queue_label"] = QUEUES.get(r["route"] or "", {}).get("label")
        r["claimant"] = mask_name(names.get(r.pop("customer_id")))
        r["confidence"] = a.get("confidence")
        r["summary"] = (t.get("report") or {}).get("summary") or (rt.get("rationale") or [None])[0]
        r["flags"] = [s["label"] for s in (a.get("fraud") or {}).get("signals", [])][:3]
        r["coverage_flags"] = (a.get("coverage") or {}).get("failed", [])[:1]
        r["missing_documents"] = (a.get("documents") or {}).get("missing", [])
        r["requires_human"] = r["status"] == "awaiting_review"
        r["priority"] = rt.get("priority")
    return rows


@app.get("/api/claims/{claim_id}")
def get_claim(claim_id: str) -> dict:
    c = db.one("SELECT * FROM claims WHERE id = ?", (claim_id,))
    if not c:
        raise HTTPException(404, "Claim not found")
    c["triage"] = db.loads(c["triage"], {})
    pol = db.one("SELECT * FROM policies WHERE policy_no = ?", (c["policy_no"],))
    if pol:
        pol["details"] = db.loads(pol["details"], {})
    cust = db.one("SELECT id, name, city, created_at FROM customers WHERE id = ?", (c["customer_id"],))
    docs = db.query("SELECT id, kind, filename, mime, meta, created_at FROM documents WHERE claim_id = ?", (claim_id,))
    for d in docs:
        d["meta"] = db.loads(d["meta"], {})
        d["label"] = DOC_LABELS.get(d["kind"], d["kind"])
    tickets = db.query("SELECT * FROM tickets WHERE claim_id = ?", (claim_id,))
    for t in tickets:
        t["handler"] = db.one("SELECT id, name, role FROM handlers WHERE id = ?", (t["handler_id"],))
    notes = db.query("SELECT * FROM notifications WHERE claim_id = ? ORDER BY id", (claim_id,))
    garage = db.one("SELECT * FROM garages WHERE id = ?", (c["garage_id"],)) if c.get("garage_id") else None
    hospital = db.one("SELECT * FROM hospitals WHERE id = ?", (c["hospital_id"],)) if c.get("hospital_id") else None
    return {"claim": c, "policy": pol, "customer": cust, "documents": docs, "tickets": tickets,
            "notifications": notes, "garage": garage, "hospital": hospital, "running": runner.is_running(claim_id)}


@app.post("/api/claims")
async def create_claim(
    policy_no: str = Form(...), claim_type: str = Form(...), incident_date: str = Form(...),
    location: str = Form(...), city: str = Form(...), description: str = Form(...), amount_claimed: float = Form(...),
    incident_time: str = Form("12:00"), contact_phone: str = Form(""), insured_member: str = Form(""),
    injury: str = Form("none"), third_party_injury: bool = Form(False), vehicle_reg: str = Form(""),
    files: list[UploadFile] = File(default=[]),
) -> dict:
    pol = db.one("SELECT * FROM policies WHERE policy_no = ?", (policy_no.strip().upper(),))
    cid = f"CLM-{db.now_iso()[2:4]}{db.now_iso()[5:7]}-{uuid.uuid4().hex[:4].upper()}"
    db.insert("claims", {
        "id": cid, "policy_no": policy_no.strip().upper(), "customer_id": pol["customer_id"] if pol else None,
        "line": pol["line"] if pol else ("health" if claim_type == "hospitalization" else "motor"),
        "claim_type": claim_type, "incident_date": incident_date, "incident_time": incident_time,
        "reported_date": db.now_iso()[:10], "location": location, "city": city, "description": description,
        "amount_claimed": amount_claimed, "contact_phone": contact_phone, "insured_member": insured_member or None,
        "status": "submitted", "historical": 0, "created_at": db.now_iso(),
        "triage": {"form": {"injury": injury, "third_party_injury": third_party_injury,
                            "vehicle_reg": vehicle_reg or None}, "run": 1}})
    await _save_files(cid, files)
    runner.start(cid)
    return {"id": cid}


async def _save_files(claim_id: str, files: list[UploadFile]) -> list[dict]:
    out = []
    folder = UPLOAD_DIR / claim_id
    folder.mkdir(parents=True, exist_ok=True)
    for f in files:
        if not f.filename:
            continue
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(f.filename).name)[:120]
        dest = folder / safe
        dest.write_bytes(await f.read())
        text = extract_text(dest)
        kind = classify(safe, text)
        mime = f.content_type or ("application/pdf" if safe.lower().endswith(".pdf") else "image/jpeg")
        did = db.insert("documents", {"claim_id": claim_id, "kind": kind, "filename": safe, "path": str(dest),
                                      "mime": mime, "extracted_text": text, "meta": {}, "created_at": db.now_iso()})
        out.append({"id": did, "kind": kind, "filename": safe})
    return out


@app.post("/api/claims/{claim_id}/documents")
async def add_documents(claim_id: str, files: list[UploadFile] = File(...)) -> dict:
    c = db.one("SELECT status FROM claims WHERE id = ?", (claim_id,))
    if not c:
        raise HTTPException(404, "Claim not found")
    saved = await _save_files(claim_id, files)
    for s in saved:
        events.emit(claim_id, "document_received", "portal", **s, label=DOC_LABELS.get(s["kind"], s["kind"]))
    resumed = False
    if c["status"] == "awaiting_documents":
        resumed = runner.resume(claim_id, {"uploaded": [s["filename"] for s in saved]})
    return {"saved": saved, "resumed": resumed}


@app.post("/api/claims/{claim_id}/run")
def run_claim(claim_id: str) -> dict:
    c = db.one("SELECT status FROM claims WHERE id = ?", (claim_id,))
    if not c:
        raise HTTPException(404, "Claim not found")
    fresh = c["status"] == "submitted"
    if not runner.start(claim_id, rerun=not fresh):
        raise HTTPException(409, "Triage already running")
    return {"started": True}


class Review(BaseModel):
    decision: str  # approve | override
    queue: str | None = None
    note: str = ""
    reviewer: str = "Claims Manager"


@app.post("/api/claims/{claim_id}/review")
def review(claim_id: str, body: Review) -> dict:
    c = db.one("SELECT status FROM claims WHERE id = ?", (claim_id,))
    if not c or c["status"] != "awaiting_review":
        raise HTTPException(409, "Claim is not awaiting review")
    if body.decision == "override" and body.queue not in QUEUES:
        raise HTTPException(400, "Override needs a valid queue")
    runner.resume(claim_id, body.model_dump())
    return {"resumed": True}


@app.get("/api/claims/{claim_id}/events")
def get_events(claim_id: str, after: int = 0) -> list[dict]:
    return events.since(claim_id, after)


@app.get("/api/claims/{claim_id}/stream")
async def stream(claim_id: str, after: int = 0):
    async def gen():
        last, idle = after, 0
        while True:
            rows = events.since(claim_id, last)
            for r in rows:
                last = r["id"]
                yield f"id: {r['id']}\ndata: {json.dumps(r, default=str)}\n\n"
            idle = 0 if rows else idle + 1
            if idle and idle % 40 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.25)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class Ask(BaseModel):
    question: str


@app.post("/api/claims/{claim_id}/ask")
def ask(claim_id: str, body: Ask) -> dict:
    c = db.one("SELECT * FROM claims WHERE id = ?", (claim_id,))
    if not c:
        raise HTTPException(404, "Claim not found")
    t = db.loads(c["triage"], {}) or {}
    ledger = t.get("ledger") or []
    if not llm_enabled():
        words = {w for w in re.findall(r"[a-z]{4,}", body.question.lower())}
        ranked = sorted(ledger, key=lambda e: -len(words & set(re.findall(r"[a-z]{4,}", e["summary"].lower()))))
        top = [e for e in ranked[:3]]
        return {"answer": "LLM is disabled (deterministic mode). The most relevant evidence:\n" +
                "\n".join(f"[{e['id']}] {e['label']}: {e['summary']}" for e in top), "source": "retrieval"}
    cust = db.one("SELECT name FROM customers WHERE id = ?", (c["customer_id"],)) or {}
    m = Masker(names=[n for n in (cust.get("name"), c.get("insured_member")) if n])
    record = m.mask(json.dumps({
        "claim": {k: c.get(k) for k in ("id", "line", "claim_type", "incident_date", "city", "amount_claimed", "description")},
        "evidence": [{"id": e["id"], "tool": e["label"], "summary": e["summary"], "signals": e["signals"],
                      "data": e["data"] if e["tool"] in ("check_coverage", "check_weather", "lookup_policy") else None}
                     for e in ledger],
        "findings": t.get("findings"), "assessment": t.get("assessment"), "routing": t.get("routing"),
        "verification": t.get("verification")}, default=str)[:60000])
    msg = create(model=PRIMARY_MODEL, effort="low", max_tokens=4000, system=COPILOT_SYSTEM,
                 messages=[{"role": "user", "content": f"TRIAGE RECORD\n{record}\n\nQUESTION: {m.mask(body.question)}"}])
    return {"answer": text_of(msg), "source": "llm"}


@app.get("/api/documents/{doc_id}/file")
def doc_file(doc_id: int):
    d = db.one("SELECT path, filename, mime FROM documents WHERE id = ?", (doc_id,))
    if not d or not Path(d["path"]).exists():
        raise HTTPException(404, "File not found")
    p = Path(d["path"]).resolve()
    if BASE_DIR.resolve() not in p.parents:
        raise HTTPException(403, "Forbidden")
    return FileResponse(p, media_type=d["mime"], filename=d["filename"],
                        content_disposition_type="inline")


@app.get("/api/handlers")
def handlers() -> list[dict]:
    rows = db.query("SELECT * FROM handlers ORDER BY role, name")
    for r in rows:
        r["lines"] = db.loads(r["lines"], [])
        r["assigned_live"] = db.query("SELECT t.claim_id, t.priority, t.sla_due, t.queue, t.status FROM tickets t "
                                      "WHERE t.handler_id = ? ORDER BY t.created_at DESC", (r["id"],))
    return rows


@app.get("/api/evals")
def evals() -> dict:
    p = BASE_DIR / "evals" / "results.json"
    if not p.exists():
        return {"available": False}
    return {"available": True, **json.loads(p.read_text())}


@app.get("/api/policies/{policy_no}")
def policy(policy_no: str) -> dict[str, Any]:
    p = db.one("SELECT policy_no, product, line, start_date, end_date, status, sum_insured, details FROM policies "
               "WHERE policy_no = ?", (policy_no.strip().upper(),))
    if not p:
        raise HTTPException(404, "Policy not found")
    d = db.loads(p.pop("details"), {})
    p["vehicle"] = (d.get("vehicle") or {}).get("reg")
    p["members"] = [m["name"] for m in d.get("members", [])]
    return p
