"""Severity scoring, routing policy, and the actions that close the loop
(ticket, assignment, notifications). Deliberately rule-based: a regulator or a
claims manager can read this file and know exactly why a claim went where it went."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import db
from .base import ToolResult, inr

QUEUES = {
    "fast_track": {"label": "Fast Track — Auto-approve", "role": "fast_track"},
    "standard": {"label": "Standard Adjuster", "role": "adjuster"},
    "senior": {"label": "Senior Adjuster", "role": "senior_adjuster"},
    "medical": {"label": "Medical Review", "role": "medical_reviewer"},
    "siu": {"label": "Special Investigations Unit", "role": "siu"},
    "coverage_review": {"label": "Coverage Review (denial)", "role": "adjuster"},
}
CITY_REGION = {"chennai": "South", "bengaluru": "South", "hyderabad": "South", "kochi": "South",
               "pune": "West", "mumbai": "West", "ahmedabad": "West", "nashik": "West",
               "delhi": "North", "gurugram": "North", "noida": "North", "jaipur": "North", "lucknow": "North",
               "kolkata": "East"}
# Mandatory SIU referral indicators: hard, independently verifiable evidence that warrants
# investigation on its own, whatever the aggregate score (standard practice in SIU referral rules).
MANDATORY_SIU = {"WEATHER_MISMATCH": "claimed peril contradicted by weather records",
                 "DUPLICATE_IMAGE": "photo re-used from another claim",
                 "EXIF_PREDATES_POLICY": "photo taken before the policy existed",
                 "PRIOR_FRAUD": "claimant has a prior fraud repudiation",
                 "FRAUD_RING_LINK": "linked to a confirmed fraud cluster"}
SLA_HOURS = {"critical": 4, "high": 24, "medium": 48, "low": 72}


def severity(claim: dict, facts: dict, coverage: dict | None, loss: dict | None) -> dict[str, Any]:
    pts, reasons = 0, []
    amt = float((coverage or {}).get("payable", {}).get("gross") or claim.get("amount_claimed") or 0)
    if amt >= 500000:
        pts += 3; reasons.append(f"High value loss ({inr(amt)})")
    elif amt >= 100000:
        pts += 2; reasons.append(f"Significant value ({inr(amt)})")
    elif amt >= 25000:
        pts += 1; reasons.append(f"Moderate value ({inr(amt)})")
    else:
        reasons.append(f"Low value ({inr(amt)})")
    injury = facts.get("injury") or "none"
    critical = False
    if injury == "fatal":
        critical = True; reasons.append("Fatality reported")
    elif injury == "serious":
        pts += 3; reasons.append("Serious bodily injury")
    elif injury == "minor":
        pts += 1; reasons.append("Minor injury")
    if facts.get("third_party_injury"):
        critical = True; reasons.append("Third-party bodily injury (MACT exposure)")
    if (coverage or {}).get("total_loss") or claim.get("claim_type") == "theft":
        pts += 2; reasons.append("Total loss / vehicle theft")
    if (loss or {}).get("icu"):
        pts += 2; reasons.append("ICU admission")
    if int((loss or {}).get("days") or 0) > 5:
        pts += 1; reasons.append(f"Extended stay ({loss['days']} days)")
    if facts.get("vulnerable_customer"):
        pts += 1; reasons.append("Vulnerable customer — expedite")
    level = "critical" if critical or pts >= 6 else "high" if pts >= 4 else "medium" if pts >= 2 else "low"
    return {"level": level, "points": pts, "reasons": reasons}


def route(claim: dict, sev: dict, fraud: dict, coverage: dict | None, docs: dict | None,
          confidence: float) -> dict[str, Any]:
    cov_status = (coverage or {}).get("status", "needs_info")
    amt = float(claim.get("amount_claimed") or 0)
    rationale: list[str] = []
    human = False
    hard = [MANDATORY_SIU[s["code"]] for s in fraud["signals"] if s["code"] in MANDATORY_SIU]
    if fraud["score"] >= 60 or hard:
        q = "siu"; human = True
        if fraud["score"] >= 60:
            rationale.append(f"Fraud score {fraud['score']} ≥ 60 — refer to SIU before any payment.")
        if hard:
            rationale.append("Mandatory SIU referral: " + "; ".join(hard) + ".")
    elif cov_status == "not_covered":
        q = "coverage_review"; human = True
        rationale.append("Rules engine indicates the loss is not covered — a human must confirm any denial.")
    elif sev["level"] == "critical" or amt >= 500000:
        q = "senior"
        rationale.append(f"Severity {sev['level']} / value {inr(amt)} exceeds standard authority.")
    elif claim.get("line") == "health" and (amt >= 100000 or sev["level"] in ("high", "critical")):
        q = "medical"
        rationale.append("High-value or complex hospitalisation — clinical review required.")
    elif (fraud["score"] < 30 and cov_status in ("covered", "partially_covered") and amt <= 50000
          and sev["level"] in ("low", "medium") and not (docs or {}).get("missing")):
        q = "fast_track"
        rationale.append(f"Low risk ({fraud['score']}), covered, {inr(amt)} ≤ ₹50,000, documents complete — straight-through.")
    else:
        q = "standard"
        why = []
        if fraud["score"] >= 30: why.append(f"moderate fraud score {fraud['score']}")
        if (docs or {}).get("missing"): why.append("documents outstanding")
        if amt > 50000: why.append(f"value {inr(amt)} above fast-track limit")
        if cov_status in ("needs_info", "partially_covered"): why.append(f"coverage {cov_status.replace('_', ' ')}")
        rationale.append("Standard handling — " + (", ".join(why) or "default route") + ".")
    if fraud["band"] == "medium" and q not in ("siu",):
        rationale.append("Medium fraud indicators — handler to review flagged items before settlement.")
    if confidence < 0.6 and not human:
        human = True
        rationale.append(f"Agent confidence {confidence:.0%} below 60% — human confirmation required.")
    priority = {"critical": "P1", "high": "P2", "medium": "P3", "low": "P4"}[sev["level"]]
    if q == "siu":
        priority = "P2" if priority in ("P3", "P4") else priority
    return {"queue": q, "queue_label": QUEUES[q]["label"], "requires_human": human, "priority": priority,
            "rationale": rationale, "auto_approve": q == "fast_track" and not human}


def pick_handler(queue: str, line: str, amount: float, city: str | None) -> dict | None:
    role = QUEUES[queue]["role"]
    rows = db.query("SELECT * FROM handlers WHERE role = ?", (role,))
    rows = [r for r in rows if line in (db.loads(r["lines"], []) or [line])] or rows
    eligible = [r for r in rows if (r["authority_limit"] or 0) >= amount] or rows
    if not eligible:
        return None
    region = CITY_REGION.get((city or "").lower())
    # Prefer the claim's region, then the lightest caseload.
    eligible.sort(key=lambda r: (0 if r["region"] in (region, "All") else 1, r["open_cases"]))
    return eligible[0]


def create_ticket(claim: dict, routing: dict, sev: dict, summary: str) -> ToolResult:
    amt = float(claim.get("amount_claimed") or 0)
    h = pick_handler(routing["queue"], claim.get("line", "motor"), amt, claim.get("city"))
    hours = 2 if routing["queue"] == "fast_track" else SLA_HOURS[sev["level"]]
    due = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(timespec="minutes")
    tid = "TKT-" + uuid.uuid4().hex[:6].upper()
    status = "auto_approved" if routing.get("auto_approve") else "open"
    db.insert("tickets", {"id": tid, "claim_id": claim["id"], "queue": routing["queue"],
                          "handler_id": h["id"] if h else None, "priority": routing["priority"], "sla_due": due,
                          "status": status, "summary": summary, "created_at": db.now_iso()})
    if h:
        db.execute("UPDATE handlers SET open_cases = open_cases + 1 WHERE id = ?", (h["id"],))
    return ToolResult(True, f"Ticket {tid} in {routing['queue_label']} ({routing['priority']}, SLA {hours}h)"
                      + (f", assigned to {h['name']}." if h else ", unassigned."),
                      {"ticket_id": tid, "queue": routing["queue"], "handler": h, "sla_due": due,
                       "sla_hours": hours, "status": status})


def notify(claim_id: str, channel: str, recipient: str, subject: str, body: str) -> ToolResult:
    db.insert("notifications", {"claim_id": claim_id, "channel": channel, "recipient": recipient,
                                "subject": subject, "body": body, "created_at": db.now_iso()})
    return ToolResult(True, f"{channel} sent to {recipient}: {subject}", {"channel": channel, "recipient": recipient,
                                                                         "subject": subject})
