"""Fact derivation: merges what the claimant declared, what the documents say, what
intake extraction found, and what the investigator recorded (highest precedence)."""
from __future__ import annotations

from typing import Any

from .. import db

DRINK_WORDS = ("drunk", "intoxicated", "under the influence", "alcohol", "breath analyser", "breathalyser")
HIRE_WORDS = ("ola", "uber", "cab service", "passenger fare", "taxi service", "for hire", "rented it out")


def derive(state: dict) -> dict[str, Any]:
    c = state["claim"]
    r = state["results"]
    facts: dict[str, Any] = {}
    form = c.get("form") or {}
    facts["injury"] = form.get("injury") or "none"
    facts["third_party_injury"] = bool(form.get("third_party_injury"))

    # intake extraction (LLM) — never overrides an explicit declaration
    intake = state.get("intake_facts") or {}
    if intake:
        if facts["injury"] == "none" and intake.get("injury") not in (None, "none"):
            facts["injury"] = intake["injury"]
        facts["third_party_injury"] = facts["third_party_injury"] or bool(intake.get("third_party_injury"))
        for k_src, k_dst in (("intoxication_mentioned", "intoxication"), ("commercial_use_mentioned", "commercial_use"),
                             ("engine_water_damage", "engine_water_damage"),
                             ("vulnerable_customer", "vulnerable_customer")):
            if intake.get(k_src):
                facts[k_dst] = True
        if intake.get("cause") in ("accident", "illness"):
            facts["cause"] = intake["cause"]
        if intake.get("diagnosis"):
            facts["diagnosis"] = intake["diagnosis"]

    desc = (c.get("description") or "").lower()
    if any(w in desc for w in DRINK_WORDS):
        facts["intoxication"] = True
    if any(w in desc for w in HIRE_WORDS):
        facts["commercial_use"] = True

    docs = r.get("review_documents") or {}
    present = {d["kind"] for d in docs.get("documents", [])}
    facts["fir_present"] = "fir" in present
    ext = docs.get("extracted", {})
    ds = ext.get("discharge_summary") or {}
    if ds.get("diagnosis"):
        facts["diagnosis"] = f"{ds['diagnosis']}. {ds.get('history') or ''}".strip()
        facts.setdefault("cause", ds.get("cause"))
    est = ext.get("repair_estimate") or {}
    if c.get("claim_type") in ("flood", "natural_calamity") and any(
            "engine" in p["name"].lower() for p in est.get("parts", [])):
        facts["engine_water_damage"] = True
    for e in state["ledger"]:
        for s in e.get("signals", []):
            if s["code"] == "LICENCE_EXPIRED":
                facts["licence_invalid"] = True
    if c.get("hospital_id"):
        h = db.one("SELECT network FROM hospitals WHERE id = ?", (c["hospital_id"],))
        facts["hospital_network"] = bool(h and h["network"])

    facts.update(state.get("agent_facts") or {})
    return facts
