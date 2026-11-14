"""Coverage rules engine.

Coverage is decided by explicit rules, each tied to a clause in the policy wording,
never by an LLM guess. The output is a ledger: every clause checked, whether it
passed, and how each rupee of the payable estimate was computed."""
from __future__ import annotations

from typing import Any

from .base import ToolResult, inr, parse_date
from .policy import clause

MOTOR_PERILS = {
    "collision": "M-2.1", "accident": "M-2.1", "fire": "M-2.2", "theft": "M-2.3",
    "flood": "M-2.4", "storm": "M-2.4", "hailstorm": "M-2.4", "cyclone": "M-2.4",
    "natural_calamity": "M-2.4", "vandalism": "M-2.5", "riot": "M-2.5",
    "windshield": "M-2.6", "glass": "M-2.6",
}
METAL_DEPRECIATION = [(0.5, 0.0), (1, 0.05), (2, 0.10), (3, 0.15), (4, 0.25), (5, 0.35), (10, 0.40)]
MATERIAL_DEPRECIATION = {"plastic": 0.5, "rubber": 0.5, "battery": 0.5, "tyre": 0.5, "fibre": 0.3, "glass": 0.0}

SPECIFIED_DISEASES = {
    "cataract": "cataract", "prostat": "benign prostatic hypertrophy", "hernia": "hernia",
    "hydrocele": "hydrocele", "knee replacement": "joint replacement", "hip replacement": "joint replacement",
    "joint replacement": "joint replacement", "kidney stone": "kidney stones", "renal calcul": "kidney stones",
    "gallbladder": "gallbladder stones", "cholecyst": "gallbladder stones", "sinus": "sinusitis",
    "varicose": "varicose veins",
}
COSMETIC = ("cosmetic", "liposuction", "rhinoplasty", "bariatric", "obesity", "weight loss")
SUBSTANCE = ("alcohol", "intoxicat", "drug abuse", "de-addiction", "self-inflicted", "self inflicted")


class Ledger:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.fail: list[str] = []
        self.needs: list[str] = []

    def check(self, clause_id: str, passed: bool | None, note: str, effect: str = "") -> None:
        c = clause(clause_id) or {"title": clause_id, "text": ""}
        outcome = "pass" if passed else ("fail" if passed is False else "needs_info")
        self.rows.append({"clause_id": clause_id, "title": c["title"], "text": c["text"],
                          "outcome": outcome, "note": note, "effect": effect})
        if passed is False:
            self.fail.append(f"{clause_id} {c['title']}: {note}")
        elif passed is None:
            self.needs.append(f"{clause_id}: {note}")

    def apply(self, clause_id: str, note: str) -> None:
        c = clause(clause_id) or {"title": clause_id, "text": ""}
        self.rows.append({"clause_id": clause_id, "title": c["title"], "text": c["text"],
                          "outcome": "applied", "note": note, "effect": "adjusts payable"})


def _common(ledger: Ledger, policy: dict, period_clause: str, premium_clause: str) -> None:
    ledger.check(period_clause, policy.get("incident_in_period"),
                 f"Loss date within {policy.get('start_date')} – {policy.get('end_date')}"
                 if policy.get("incident_in_period") else
                 f"Loss date falls outside {policy.get('start_date')} – {policy.get('end_date')}")
    ledger.check(premium_clause, policy.get("premium_paid"),
                 "Premium realised" if policy.get("premium_paid") else "Premium not realised")


def _status(ledger: Ledger, partial: bool) -> str:
    if ledger.fail:
        return "not_covered"
    if ledger.needs:
        return "needs_info"
    return "partially_covered" if partial else "covered"


# ------------------------------------------------------------------- motor
def _metal_rate(age_years: float) -> float:
    for limit, rate in METAL_DEPRECIATION:
        if age_years <= limit:
            return rate
    return 0.5


def motor(claim: dict, policy: dict, loss: dict, facts: dict) -> ToolResult:
    led = Ledger()
    _common(led, policy, "M-1.1", "M-1.2")
    if policy.get("vehicle_match") is not None:
        led.check("M-1.3", policy["vehicle_match"],
                  "Claim vehicle matches the Schedule" if policy["vehicle_match"] else
                  "Claim vehicle is not the vehicle in the Schedule")
    peril = (claim.get("claim_type") or "").lower()
    peril_clause = MOTOR_PERILS.get(peril)
    led.check(peril_clause or "M-2.1", bool(peril_clause),
              f"Peril '{peril}' is an insured peril" if peril_clause else f"Peril '{peril}' is not an insured peril")
    if peril == "theft":
        led.check("M-6.3", True if facts.get("fir_present") else None,
                  "FIR on file" if facts.get("fir_present") else "FIR not yet provided")

    exclusions = [
        ("intoxication", "M-4.2", "Driver reported under the influence"),
        ("licence_invalid", "M-4.3", "Driver did not hold a valid licence"),
        ("commercial_use", "M-4.4", "Vehicle used for hire or reward"),
        ("mechanical_breakdown", "M-4.1", "Loss is mechanical/electrical breakdown"),
    ]
    for key, cid, note in exclusions:
        if facts.get(key) is True:
            led.check(cid, False, note)

    vehicle = policy.get("vehicle") or {}
    idv = float(policy.get("idv") or 0)
    addons = set(policy.get("addons") or [])
    age = max(0.0, (parse_date(claim.get("incident_date")) - parse_date(f"{vehicle.get('year', 2020)}-04-01")).days / 365.25) \
        if claim.get("incident_date") else 3.0
    parts = loss.get("parts") or []
    labour = float(loss.get("labour") or 0)
    lines: list[dict[str, Any]] = []
    partial = False

    gross = sum(float(p["cost"]) for p in parts) + labour
    if not parts and not labour:
        gross = float(loss.get("total") or claim.get("amount_claimed") or 0)
        lines.append({"label": "Claimed amount (no itemised estimate)", "amount": gross})
    else:
        lines.append({"label": f"Parts ({len(parts)} items)", "amount": sum(float(p['cost']) for p in parts)})
        lines.append({"label": "Labour & paint", "amount": labour})

    # Engine water ingress without Engine Protect
    if facts.get("engine_water_damage") and "engine_protect" not in addons:
        eng = [p for p in parts if "engine" in p["name"].lower()]
        eng_cost = sum(float(p["cost"]) for p in eng)
        if eng_cost:
            parts = [p for p in parts if p not in eng]
            lines.append({"label": "Less: engine damage from water ingress (excluded)", "amount": -eng_cost})
            note = f"Engine components {inr(eng_cost)} excluded — Engine Protect not opted"
            if parts or labour:
                led.apply("M-4.5", note)
                partial = True
            else:
                led.check("M-4.5", False, note)
    elif facts.get("engine_water_damage"):
        led.apply("M-5.2", "Engine Protect opted — water-ingress engine damage payable")

    dep_total = 0.0
    if parts and "zero_dep" not in addons:
        mrate = _metal_rate(age)
        for p in parts:
            mat = (p.get("material") or "metal").lower()
            rate = MATERIAL_DEPRECIATION.get(mat, mrate)
            dep_total += float(p["cost"]) * rate
        if dep_total:
            lines.append({"label": f"Less: depreciation (vehicle age {age:.1f} yrs, metal {int(mrate*100)}%)",
                          "amount": -round(dep_total)})
            led.apply("M-3.2", f"Depreciation of {inr(dep_total)} on replaced parts")
    elif parts:
        led.apply("M-5.1", "Zero Depreciation add-on — no depreciation deducted")

    cc = int(vehicle.get("cc") or 1200)
    deductible = (2000 if cc > 1500 else 1000) + float(policy.get("deductible") or 0)
    led.apply("M-3.1", f"Deductible {inr(deductible)} ({cc}cc, incl. voluntary {inr(policy.get('deductible') or 0)})")

    eligible = sum(l["amount"] for l in lines)
    ctl = idv and gross > 0.75 * idv
    if ctl:
        salvage = round(idv * 0.2)
        led.apply("M-3.4", f"Repair cost {inr(gross)} exceeds 75% of IDV {inr(idv)} — total-loss basis")
        lines = [{"label": "Insured Declared Value", "amount": idv},
                 {"label": "Less: estimated salvage (20%)", "amount": -salvage}]
        eligible = idv - salvage
    lines.append({"label": "Less: deductible", "amount": -deductible})
    net = max(0.0, eligible - deductible)
    if idv and net > idv:
        led.apply("M-3.3", f"Capped at IDV {inr(idv)}")
        net = idv
    reported = parse_date(claim.get("reported_date"))
    incident = parse_date(claim.get("incident_date"))
    conditions = []
    if reported and incident and (reported - incident).days > 2:
        conditions.append(f"Notice given {(reported - incident).days} days after loss (M-6.1 requires 48h) — delay must be explained.")
    status = _status(led, partial)
    return ToolResult(True, _summary(status, net, led), {
        "status": status, "basis": led.rows, "failed": led.fail, "needs_info": led.needs,
        "payable": {"lines": lines, "net": round(net) if status != "not_covered" else 0, "gross": round(gross)},
        "total_loss": bool(ctl), "conditions": conditions,
    })


# ------------------------------------------------------------------- health
def health(claim: dict, policy: dict, loss: dict, facts: dict) -> ToolResult:
    led = Ledger()
    _common(led, policy, "H-1.1", "H-1.1")
    member = policy.get("member")
    led.check("H-1.2", bool(member),
              f"{claim.get('insured_member')} is a named insured" if member else
              f"{claim.get('insured_member') or 'Patient'} is not named in the Schedule")
    diagnosis = (facts.get("diagnosis") or claim.get("description") or "").lower()
    accident = facts.get("cause") == "accident" or "accident" in diagnosis
    days = policy.get("days_since_first_inception")
    if days is not None:
        if not accident:
            led.check("H-4.1", days > 30, f"{days} days since first inception (30-day initial wait)")
        else:
            led.check("H-4.1", True, "Accident — initial waiting period does not apply")
        disease = next((v for k, v in SPECIFIED_DISEASES.items() if k in diagnosis), None)
        if disease:
            led.check("H-4.3", days > 730, f"'{disease}' has a 24-month wait; {days} days of cover")
        peds = [p.lower() for p in (member or {}).get("ped", [])]
        ped_hit = facts.get("ped_related") is True or any(p and p in diagnosis for p in peds)
        if ped_hit:
            led.check("H-4.2", days > 1095,
                      f"Treatment relates to declared pre-existing condition ({', '.join(peds) or 'per records'}); "
                      f"{days} of 1,095 days served")
    if any(w in diagnosis for w in COSMETIC):
        led.check("H-5.1", False, "Cosmetic / obesity treatment")
    if any(w in diagnosis for w in SUBSTANCE) or facts.get("intoxication"):
        led.check("H-5.2", False, "Self-inflicted or substance-related")
    if facts.get("diagnostic_only"):
        led.check("H-5.3", False, "Admission for investigation only")

    si = float(policy.get("sum_insured") or 0)
    total = float(loss.get("total") or claim.get("amount_claimed") or 0)
    room_day = float(loss.get("room_rent_per_day") or 0)
    nights = int(loss.get("days") or 0)
    icu = bool(loss.get("icu"))
    assoc = float(loss.get("associated_charges") or 0)  # doctor, OT, nursing — proportionate
    lines = [{"label": "Final hospital bill", "amount": total}]
    partial = False
    if room_day and nights:
        cap = si * (0.02 if icu else 0.01)
        if room_day > cap:
            ratio = cap / room_day
            room_cut = (room_day - cap) * nights
            assoc_cut = assoc * (1 - ratio)
            lines.append({"label": f"Less: room rent above {inr(cap)}/day × {nights} days", "amount": -round(room_cut)})
            if assoc_cut:
                lines.append({"label": f"Less: proportionate deduction ({ratio:.0%}) on associated charges",
                              "amount": -round(assoc_cut)})
            led.apply("H-3.1", f"Room {inr(room_day)}/day vs eligible {inr(cap)}/day — proportionate deduction")
            partial = True
    eligible = sum(l["amount"] for l in lines)
    if "cataract" in diagnosis and eligible > 40000:
        lines.append({"label": "Less: cataract sub-limit (₹40,000/eye)", "amount": -(eligible - 40000)})
        led.apply("H-3.3", "Cataract sub-limit applied")
        eligible, partial = 40000, True
    age = (member or {}).get("age", 0)
    if age >= 61:
        cop = eligible * 0.10
        lines.append({"label": f"Less: 10% co-payment (member aged {age})", "amount": -round(cop)})
        led.apply("H-3.2", f"Co-payment for insured aged {age}")
        eligible -= cop
        partial = True
    net = min(eligible, si) if si else eligible
    conditions = []
    if facts.get("hospital_network") is False:
        conditions.append("Non-network hospital — settle by reimbursement (H-6.3).")
    status = _status(led, partial)
    return ToolResult(True, _summary(status, net, led), {
        "status": status, "basis": led.rows, "failed": led.fail, "needs_info": led.needs,
        "payable": {"lines": lines, "net": round(net) if status != "not_covered" else 0, "gross": round(total)},
        "total_loss": False, "conditions": conditions,
    })


def _summary(status: str, net: float, led: Ledger) -> str:
    if status == "not_covered":
        return "NOT COVERED — " + "; ".join(led.fail[:2])
    if status == "needs_info":
        return "Coverage pending information — " + "; ".join(led.needs[:2])
    label = "Covered" if status == "covered" else "Partially covered"
    return f"{label}. Estimated payable {inr(net)} after policy adjustments."


def check_coverage(claim: dict, policy: dict | None, loss: dict | None, facts: dict | None) -> ToolResult:
    if not policy or not policy.get("found"):
        return ToolResult(False, "Cannot assess coverage: policy not found.",
                          {"status": "needs_info", "basis": [], "failed": [], "needs_info": ["Policy record"],
                           "payable": {"lines": [], "net": 0, "gross": 0}, "conditions": []})
    fn = motor if policy.get("line") == "motor" else health
    return fn(claim, policy, loss or {}, facts or {})
