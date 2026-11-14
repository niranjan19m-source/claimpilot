"""Policy administration lookup and policy-wording retrieval."""
from __future__ import annotations

import re
from functools import lru_cache

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .. import db
from ..config import POLICY_DIR
from .base import ToolResult, parse_date, signal

WORDING_FILES = {"MOTOR-PKG": "motor_comprehensive.md", "HEALTH-FLT": "health_floater.md"}


# ---------------------------------------------------------------- wording index
@lru_cache(maxsize=1)
def _clauses() -> list[dict]:
    out = []
    for product, fname in WORDING_FILES.items():
        text = (POLICY_DIR / fname).read_text()
        for m in re.finditer(r"^### (\S+) (.+?)\n(.+?)(?=\n### |\Z)", text, re.S | re.M):
            out.append({"product": product, "id": m.group(1), "title": m.group(2).strip(),
                        "text": " ".join(m.group(3).split())})
    return out


@lru_cache(maxsize=1)
def _index():
    clauses = _clauses()
    vec = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", sublinear_tf=True)
    mat = vec.fit_transform([f"{c['title']} {c['title']} {c['text']}" for c in clauses])
    return vec, mat


def clause(clause_id: str) -> dict | None:
    return next((c for c in _clauses() if c["id"] == clause_id), None)


def search_wording(query: str, product: str | None = None, k: int = 3) -> ToolResult:
    vec, mat = _index()
    sims = cosine_similarity(vec.transform([query]), mat)[0]
    clauses = _clauses()
    ranked = sorted(range(len(clauses)), key=lambda i: -sims[i])
    hits = [
        {**clauses[i], "score": round(float(sims[i]), 3)}
        for i in ranked
        if (product is None or clauses[i]["product"] == product) and sims[i] > 0.02
    ][:k]
    if not hits:
        return ToolResult(True, f"No wording clause matched '{query}'.", {"clauses": []})
    return ToolResult(True, f"Top clause for '{query}': {hits[0]['id']} {hits[0]['title']}", {"clauses": hits})


# ---------------------------------------------------------------- policy lookup
def get_policy(policy_no: str) -> dict | None:
    p = db.one("SELECT * FROM policies WHERE policy_no = ?", (policy_no.strip().upper(),))
    if p:
        p["details"] = db.loads(p["details"], {})
    return p


def lookup_policy(claim: dict) -> ToolResult:
    policy_no = (claim.get("policy_no") or "").strip().upper()
    p = get_policy(policy_no)
    if not p:
        return ToolResult(False, f"Policy {policy_no or '(blank)'} not found in policy admin system.",
                          {"policy_no": policy_no, "found": False},
                          [signal("POLICY_NOT_FOUND", "Policy not found", 35,
                                  f"No policy record for '{policy_no}'.")])
    cust = db.one("SELECT id, name, city, created_at FROM customers WHERE id = ?", (p["customer_id"],)) or {}
    d = p["details"]
    inc = parse_date(claim.get("incident_date"))
    start, end = parse_date(p["start_date"]), parse_date(p["end_date"])
    first_inception = parse_date(d.get("first_inception_date")) or start
    in_period = bool(inc and start and end and start <= inc <= end)
    days_since_start = (inc - start).days if inc and start else None
    days_since_first = (inc - first_inception).days if inc and first_inception else None
    signals = []
    if p["line"] != claim.get("line"):
        signals.append(signal("LINE_MISMATCH", "Claim line differs from policy line", 0,
                              f"Policy is {p['line']}, claim filed as {claim.get('line')}.", "coverage"))
    # Fraud: new business with a loss shortly after inception (renewals don't count).
    is_new_business = first_inception == start
    if is_new_business and days_since_start is not None and 0 <= days_since_start <= 15:
        signals.append(signal("EARLY_CLAIM", "Loss within 15 days of policy inception", 22,
                              f"Policy incepted {start}; loss on {inc} ({days_since_start} days later)."))
    elif is_new_business and days_since_start is not None and 15 < days_since_start <= 45:
        signals.append(signal("EARLY_CLAIM", "Loss within 45 days of policy inception", 10,
                              f"Policy incepted {start}; loss on {inc} ({days_since_start} days later)."))
    vehicle_match = None
    member = None
    if p["line"] == "motor":
        reg = (claim.get("vehicle_reg") or "").replace(" ", "").upper()
        pol_reg = d.get("vehicle", {}).get("reg", "").replace(" ", "").upper()
        vehicle_match = (reg == pol_reg) if reg else None
        if vehicle_match is False:
            signals.append(signal("VEHICLE_MISMATCH", "Vehicle on claim is not the insured vehicle", 30,
                                  f"Claim vehicle {reg} vs insured vehicle {pol_reg}."))
    if p["line"] == "health":
        name = (claim.get("insured_member") or "").strip().lower()
        member = next((m for m in d.get("members", []) if m["name"].lower() == name), None)
    data = {
        "found": True, "policy_no": p["policy_no"], "product": p["product"], "line": p["line"],
        "holder": cust.get("name"), "customer_since": cust.get("created_at"),
        "start_date": p["start_date"], "end_date": p["end_date"], "status": p["status"],
        "premium_paid": bool(p["premium_paid"]), "sum_insured": p["sum_insured"],
        "deductible": p["deductible"], "first_inception_date": str(first_inception),
        "incident_in_period": in_period, "days_since_policy_start": days_since_start,
        "days_since_first_inception": days_since_first, "new_business": is_new_business,
        "vehicle": d.get("vehicle"), "idv": d.get("idv"), "addons": d.get("addons", []),
        "vehicle_match": vehicle_match, "member": member,
        "members": [m["name"] for m in d.get("members", [])] if p["line"] == "health" else None,
    }
    bits = [f"{p['policy_no']} ({p['product']})", f"status {p['status']}",
            "premium paid" if p["premium_paid"] else "PREMIUM UNPAID",
            "loss inside policy period" if in_period else "LOSS OUTSIDE POLICY PERIOD"]
    if days_since_start is not None:
        bits.append(f"{days_since_start} days after start")
    return ToolResult(True, "; ".join(bits) + ".", data, signals)
