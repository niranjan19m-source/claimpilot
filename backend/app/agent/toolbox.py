"""The agent's tool catalogue: JSON-schema definitions for Claude plus the dispatcher
that runs each tool against the live claim state and writes it to the evidence ledger."""
from __future__ import annotations

import json
import time
from typing import Any, Callable

from .. import db, events
from ..config import DEMO_PACE
from ..pii import Masker
from ..tools import coverage, documents, external, forensics, fraud, policy, vision
from ..tools.base import ToolResult

FACT_KEYS = ["intoxication", "licence_invalid", "commercial_use", "mechanical_breakdown", "engine_water_damage",
             "fir_present", "injury", "third_party_injury", "ped_related", "diagnostic_only", "cause",
             "diagnosis", "vulnerable_customer"]


def _obj(props: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props or {}, "required": required or []}


CATALOGUE: list[dict[str, Any]] = [
    {"name": "lookup_policy", "label": "Policy admin lookup",
     "description": "Fetch the policy from the policy administration system: status, period, premium, insured "
                    "vehicle or members, add-ons, IDV/sum insured, and days between inception and the loss.",
     "input_schema": _obj()},
    {"name": "review_documents", "label": "Document review",
     "description": "Classify every submitted document, extract key fields (estimate line items, bill totals, "
                    "FIR dates, diagnosis), compare against the claim, and list missing mandatory documents.",
     "input_schema": _obj()},
    {"name": "read_document", "label": "Read document",
     "description": "Return the full extracted text of one document by id, to read details the structured "
                    "extraction may have missed (e.g. remarks in an FIR or history in a discharge summary).",
     "input_schema": _obj({"document_id": {"type": "integer"}}, ["document_id"])},
    {"name": "search_policy_wording", "label": "Policy wording search",
     "description": "Semantic search over the policy wording. Returns the most relevant clauses with ids.",
     "input_schema": _obj({"query": {"type": "string"}}, ["query"])},
    {"name": "check_coverage", "label": "Coverage rules engine",
     "description": "Run the coverage rules engine: checks every applicable clause (period, premium, peril, "
                    "exclusions, waiting periods) and computes the payable estimate line by line. Requires "
                    "lookup_policy and review_documents first. Re-run after record_fact.",
     "input_schema": _obj()},
    {"name": "geocode_location", "label": "Geocode loss location",
     "description": "Resolve the loss location to coordinates (offline gazetteer, then OpenStreetMap).",
     "input_schema": _obj()},
    {"name": "check_weather", "label": "Historical weather (Open-Meteo)",
     "description": "Retrieve recorded rainfall, wind and weather codes at the loss location for the days "
                    "around the loss, and test them against the claimed peril. Requires geocode_location.",
     "input_schema": _obj()},
    {"name": "vehicle_registry", "label": "Vehicle registry (VAHAN)",
     "description": "Look up the vehicle registration: make/model, year, fuel, permits, hypothecation.",
     "input_schema": _obj()},
    {"name": "photo_forensics", "label": "Image forensics",
     "description": "Read photo EXIF capture time and GPS, compare with loss date, location and policy start, "
                    "detect editing software, and match perceptual hashes against all past claim photos.",
     "input_schema": _obj()},
    {"name": "assess_damage_photos", "label": "Damage assessment (vision)",
     "description": "Look at the damage photos: damaged parts, impact direction, severity, and consistency "
                    "with the claimant's account.",
     "input_schema": _obj()},
    {"name": "claims_history", "label": "Claims history",
     "description": "Prior claims by this customer, frequency in the last 12 months, prior fraud outcomes.",
     "input_schema": _obj()},
    {"name": "network_analysis", "label": "Entity link analysis",
     "description": "Graph analysis linking claims through shared phones, bank accounts, people, garages and "
                    "hospitals; finds clusters connected to confirmed fraud and garage/hospital hotspots.",
     "input_schema": _obj()},
    {"name": "anomaly_model", "label": "Anomaly model",
     "description": "Isolation Forest trained on historical genuine claims; returns how unusual this claim's "
                    "profile is (amount vs cover, time since inception, reporting delay, time of day).",
     "input_schema": _obj()},
    {"name": "record_fact", "label": "Record fact",
     "description": "Record a fact established from evidence that affects coverage or severity.",
     "input_schema": _obj({
         "key": {"type": "string", "enum": FACT_KEYS},
         "value": {"description": "true/false, or for injury: none|minor|serious|fatal, cause: accident|illness, "
                                  "diagnosis: text"},
         "evidence_ids": {"type": "array", "items": {"type": "string"}},
         "rationale": {"type": "string"}}, ["key", "value", "evidence_ids", "rationale"])},
    {"name": "record_finding", "label": "Record finding",
     "description": "Record a red flag or concern found by reading the evidence that no tool raised itself.",
     "input_schema": _obj({
         "kind": {"type": "string", "enum": ["fraud", "coverage", "severity"]},
         "label": {"type": "string", "description": "Short title"},
         "detail": {"type": "string"},
         "weight": {"type": "integer", "minimum": 0, "maximum": 30},
         "evidence_ids": {"type": "array", "items": {"type": "string"}}},
         ["kind", "label", "detail", "weight", "evidence_ids"])},
    {"name": "finish_investigation", "label": "Finish investigation",
     "description": "Call once the evidence is sufficient for a triage decision.",
     "input_schema": _obj({"summary": {"type": "string"},
                           "open_questions": {"type": "array", "items": {"type": "string"}}},
                          ["summary", "open_questions"])},
]
LABELS = {t["name"]: t["label"] for t in CATALOGUE}
INVESTIGATION_TOOLS = [t["name"] for t in CATALOGUE if t["name"] not in ("record_fact", "record_finding",
                                                                        "finish_investigation", "read_document",
                                                                        "search_policy_wording")]


def claude_tools() -> list[dict]:
    return [{k: v for k, v in t.items() if k != "label"} for t in CATALOGUE]


class Toolbox:
    """Executes tools against mutable investigation state and keeps the evidence ledger."""

    def __init__(self, state: dict, masker: Masker) -> None:
        self.s = state
        self.masker = masker

    # ---- helpers
    @property
    def claim(self) -> dict:
        return self.s["claim"]

    def _loss(self) -> dict:
        ext = (self.s["results"].get("review_documents") or {}).get("extracted", {})
        return ext.get("repair_estimate") or ext.get("hospital_bill") or {}

    def _impl(self, name: str, args: dict) -> ToolResult:
        c, r = self.claim, self.s["results"]
        if name == "lookup_policy":
            return policy.lookup_policy(c)
        if name == "review_documents":
            return documents.review_documents(c)
        if name == "read_document":
            return documents.read_document(c["id"], int(args.get("document_id", 0)))
        if name == "search_policy_wording":
            prod = (r.get("lookup_policy") or {}).get("product")
            return policy.search_wording(str(args.get("query", "")), prod)
        if name == "check_coverage":
            if "lookup_policy" not in r:
                self.call("lookup_policy", {}, auto=True)
            if "review_documents" not in r:
                self.call("review_documents", {}, auto=True)
            from .facts import derive
            self.s["facts"] = derive(self.s)
            return coverage.check_coverage(c, r.get("lookup_policy"), self._loss(), self.s["facts"])
        if name == "geocode_location":
            res = external.geocode(c.get("location", ""), c.get("city"))
            if res.ok:
                c["lat"], c["lon"] = res.data["lat"], res.data["lon"]
                db.update("claims", "id", c["id"], {"lat": c["lat"], "lon": c["lon"]})
            return res
        if name == "check_weather":
            if c.get("lat") is None:
                self.call("geocode_location", {}, auto=True)
            return external.weather_check(c)
        if name == "vehicle_registry":
            return external.vehicle_registry(c.get("vehicle_reg", ""))
        if name == "photo_forensics":
            start = (r.get("lookup_policy") or {}).get("start_date")
            return forensics.analyse_photos(c, start)
        if name == "assess_damage_photos":
            return vision.assess_damage(c, self.masker)
        if name == "claims_history":
            return fraud.claims_history(c)
        if name == "network_analysis":
            return fraud.network_analysis(c)
        if name == "anomaly_model":
            return fraud.anomaly_score(c)
        if name == "record_fact":
            return self._record_fact(args)
        if name == "record_finding":
            return self._record_finding(args)
        if name == "finish_investigation":
            self.s["finished"] = {"summary": args.get("summary", ""), "open_questions": args.get("open_questions", [])}
            return ToolResult(True, "Investigation closed.", {})
        return ToolResult(False, f"Unknown tool {name}.")

    def _valid_refs(self, ids: list[str]) -> list[str]:
        known = {e["id"] for e in self.s["ledger"]}
        return [i for i in ids if i in known]

    def _record_fact(self, a: dict) -> ToolResult:
        key, val = a.get("key"), a.get("value")
        if key not in FACT_KEYS:
            return ToolResult(False, f"Unknown fact key {key}.")
        if isinstance(val, str) and val.lower() in ("true", "false"):
            val = val.lower() == "true"
        refs = self._valid_refs(a.get("evidence_ids", []))
        if not refs:
            return ToolResult(False, "Rejected: a fact must cite at least one existing evidence id.")
        self.s["agent_facts"][key] = val
        events.emit(self.claim["id"], "fact", "investigate", key=key, value=val, evidence=refs,
                    rationale=a.get("rationale", ""))
        return ToolResult(True, f"Fact recorded: {key} = {val}.", {"key": key, "value": val})

    def _record_finding(self, a: dict) -> ToolResult:
        refs = self._valid_refs(a.get("evidence_ids", []))
        if not refs:
            return ToolResult(False, "Rejected: a finding must cite at least one existing evidence id.")
        f = {"code": "AGENT_" + "".join(ch for ch in a.get("label", "FINDING").upper() if ch.isalnum() or ch == " ")
             .strip().replace(" ", "_")[:40], "label": a.get("label", ""), "detail": a.get("detail", ""),
             "weight": max(0, min(30, int(a.get("weight", 0)))), "kind": a.get("kind", "fraud"),
             "evidence": refs, "source": "agent"}
        self.s["findings"].append(f)
        events.emit(self.claim["id"], "finding", "investigate", **f)
        return ToolResult(True, f"Finding recorded: {f['label']}.", {"code": f["code"]})

    # ---- public
    def call(self, name: str, args: dict, auto: bool = False) -> dict:
        """Run a tool, write it to the ledger and event log, and return the LLM-facing payload."""
        eid = f"E{len(self.s['ledger']) + 1}"
        silent = name in ("record_fact", "record_finding", "finish_investigation")
        if not silent:
            events.emit(self.claim["id"], "tool_call", "investigate", evidence_id=eid, tool=name,
                        label=LABELS.get(name, name), input=args, auto=auto)
        t0 = time.perf_counter()
        try:
            res = self._impl(name, args)
        except Exception as exc:  # a broken tool must degrade the triage, not crash it
            res = ToolResult(False, f"Tool error: {type(exc).__name__}: {exc}")
        ms = int((time.perf_counter() - t0) * 1000)
        if DEMO_PACE and self.s.get("mode") == "deterministic" and not silent:
            time.sleep(DEMO_PACE)
        # Normalise to JSON-native types (numpy floats etc.) so checkpoints and the UI never choke.
        res.data = json.loads(json.dumps(res.data, default=_native))
        res.signals = json.loads(json.dumps(res.signals, default=_native))
        self.s["tool_calls"] += 0 if auto else 1
        if silent:
            return {"ok": res.ok, "summary": res.summary}
        entry = {"id": eid, "tool": name, "label": LABELS.get(name, name), "input": args, "ok": res.ok,
                 "summary": res.summary, "data": res.data, "signals": res.signals, "ms": ms, "auto": auto}
        self.s["ledger"].append(entry)
        if res.ok or name not in self.s["results"]:
            self.s["results"][name] = res.data
        events.emit(self.claim["id"], "tool_result", "investigate", evidence_id=eid, tool=name,
                    label=LABELS.get(name, name), ok=res.ok, summary=res.summary, signals=res.signals,
                    ms=ms, data=_ui_data(name, res.data))
        return {"evidence_id": eid, **res.to_dict(), "data": _llm_data(name, res.data)}

    def llm_payload(self, payload: dict) -> str:
        return self.masker.mask(json.dumps(payload, default=str)[:12000])


def _native(o: Any) -> Any:
    try:
        return o.item()  # numpy scalar
    except AttributeError:
        return str(o)


def _llm_data(name: str, data: dict) -> dict:
    """Trim bulky fields before they go to the model."""
    if name == "network_analysis":
        return {k: v for k, v in data.items() if k != "graph"}
    if name == "check_coverage":
        return {**data, "basis": [{k: v for k, v in b.items() if k != "text"} for b in data.get("basis", [])]}
    return data


def _ui_data(name: str, data: dict) -> dict:
    if name == "read_document":
        return {**data, "text": (data.get("text") or "")[:1500]}
    return data
