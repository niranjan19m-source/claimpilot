"""ClaimPilot evaluation harness.

Generates a labelled set of synthetic claims from 16 archetypes (labels encode the
*intended* real-world outcome, written before looking at the engine's output), runs
every one through the full agent graph, and scores routing, coverage and fraud.

    python -m evals.run_eval            # deterministic mode (free, reproducible)
    python -m evals.run_eval --llm      # full LLM agent (needs ANTHROPIC_API_KEY)

Writes evals/results.json, which the dashboard's Evaluation page renders."""
from __future__ import annotations

import json
import os
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("CLAIMPILOT_DB", str(HERE / "eval.db"))
os.environ.setdefault("CLAIMPILOT_CHECKPOINT_DB", str(HERE / "eval_checkpoints.db"))
if "--llm" not in sys.argv:
    os.environ["CLAIMPILOT_OFFLINE"] = "1"

from app import db, seed  # noqa: E402
from app.agent import runner  # noqa: E402
from app.assets import photo, recompress  # noqa: E402
from app.config import ASSET_DIR, CHECKPOINT_DB, DB_PATH, llm_enabled  # noqa: E402

R = random.Random(7)
OUT = ASSET_DIR / "evals"
CITY = {"Pune": (18.5204, 73.8567), "Mumbai": (19.0760, 72.8777), "Bengaluru": (12.9716, 77.5946),
        "Hyderabad": (17.3850, 78.4867), "Delhi": (28.6139, 77.2090),
        "Chennai": (12.9815, 80.2180)}
n_case = 0


def new_ids():
    global n_case
    n_case += 1
    return f"EV-{n_case:03d}", f"C-EV{n_case:03d}", f"POL-EV{n_case:03d}"


def motor_case(arch: str, label: dict, *, ctype="collision", amount=None, city=None, pol_days=200, first_days=900,
               paid=True, desc=None, inc_days=4, report_delay=0, parts=None, labour=8000, form=None, photos=1,
               photo_kw=None, garage=None, phone_=None, bank=None, car=None, year=None, addons=None,
               incident_date=None, docs=("claim_form", "rc", "driving_licence", "repair_estimate")) -> dict:
    cid, cust, pno = new_ids()
    city = city or R.choice([c for c in CITY if c != "Chennai"])
    seed.customer(cust, f"{R.choice(seed.FIRST)} {R.choice(seed.LAST)}", city, ph=phone_, bank=bank)
    start = seed.d(pol_days)
    pol = seed.motor_policy(pno, cust, city, start, first=seed.d(first_days) if first_days else None,
                            car=car or R.choice(seed.CARS), year=year or R.randint(2019, 2024),
                            addons=addons if addons is not None else ["zero_dep"], paid=paid)
    inc = incident_date or seed.d(inc_days)
    parts = parts or [("Front bumper", "plastic", 14000), ("Bonnet", "metal", 18000)]
    amt = amount if amount is not None else sum(p[2] for p in parts) + labour
    c = {"policy_no": pno, "incident_date": inc, "location": city, "city": city, "claim_type": ctype,
         "amount_claimed": amt, "description": desc or f"{ctype.title()} damage while driving in {city}."}
    from datetime import date, timedelta
    seed._claim(cid, f"eval:{arch}", {"injury": "none", **(form or {}), "vehicle_reg": pol["details"]["vehicle"]["reg"]},
                customer_id=cust, line="motor", incident_time=f"{R.randint(7, 21):02d}:{R.randint(0, 59):02d}",
                reported_date=str(date.fromisoformat(inc) + timedelta(days=report_delay)), lat=None, lon=None,
                garage_id=garage or R.choice([g[0] for g in seed.GARAGES if g[2] == city] or ["G-MUM1"]),
                hospital_id=None, contact_phone=phone_ or seed.phone(), bank_account=bank or str(R.randint(10**11, 10**12)),
                insured_member=None, **c)
    dp = OUT / cid
    if "claim_form" in docs:
        seed._doc(cid, "claim_form", seed.claim_form(dp, cid, c))
    if "rc" in docs:
        seed._doc(cid, "rc", seed.rc(dp, pol))
    if "driving_licence" in docs:
        seed._doc(cid, "driving_licence", seed.dl(dp, "Insured Driver", "2035-01-01"))
    if "repair_estimate" in docs:
        seed._doc(cid, "repair_estimate", seed.estimate(dp, cid, "Partner Garage", inc, "front",
                                                        [tuple(p) for p in parts], labour))
    if "fir" in docs:
        seed._doc(cid, "fir", seed.pdf(dp / "fir.pdf", "First Information Report", "Police", [
            "FIR No.: 1/2026", f"Date of Occurrence: {inc}", f"Date of Report: {inc}"]))
    if "keys_declaration" in docs:
        seed._doc(cid, "keys_declaration", seed.pdf(dp / "keys.pdf", "Keys Declaration", "Insured", ["Keys declaration"]))
    kw = {"seed": R.randint(1, 10**6), "body": R.choice(["white", "red", "blue", "grey", "silver"]),
          "damage": "front", "taken_at": f"{inc.replace('-', ':')} 18:00:00", "lat": CITY[city][0], "lon": CITY[city][1]}
    kw.update(photo_kw or {})
    src = kw.pop("recycle", None)
    for i in range(photos):
        p = dp / f"photo_{i}.jpg"
        if src:
            recompress(src, p, kw["taken_at"], kw["lat"], kw["lon"])
        else:
            photo(p, **{**kw, "seed": kw["seed"] + i})
        seed._doc(cid, "photo", p, "image/jpeg")
    return {"id": cid, "archetype": arch, **label}


def health_case(arch: str, label: dict, *, amount, diagnosis, history="No significant past history.", age=40,
                ped=None, first_days=900, inc_days=5, room=4000, days=3, assoc=40000, si=500000,
                hospital="H-MUM1") -> dict:
    cid, cust, pno = new_ids()
    name = f"{R.choice(seed.FIRST)} {R.choice(seed.LAST)}"
    seed.customer(cust, name, "Mumbai")
    seed.health_policy(pno, cust, seed.d(min(first_days, 200)), [{"name": name, "relation": "self", "age": age,
                                                               "ped": ped or []}], si, first=seed.d(first_days))
    inc = seed.d(inc_days)
    c = {"policy_no": pno, "incident_date": inc, "location": "Hospital", "city": "Mumbai",
         "claim_type": "hospitalization", "amount_claimed": amount, "description": f"Hospitalised for {diagnosis}."}
    seed._claim(cid, f"eval:{arch}", {"injury": "none"}, customer_id=cust, line="health", incident_time="10:00",
                reported_date=inc, lat=None, lon=None, garage_id=None, hospital_id=hospital, contact_phone=seed.phone(),
                bank_account=str(R.randint(10**11, 10**12)), insured_member=name, **c)
    dp = OUT / cid
    seed._doc(cid, "claim_form", seed.claim_form(dp, cid, c))
    seed._doc(cid, "discharge_summary", seed.pdf(dp / "ds.pdf", "Discharge Summary", "Hospital", [
        f"Date of Admission: {inc}", f"Diagnosis: {diagnosis}", f"History: {history}"]))
    seed._doc(cid, "hospital_bill", seed.pdf(dp / "bill.pdf", "Final Hospital Bill", "Hospital", [
        "Room Category: Single", f"Room Rent per Day: {room:,}", f"Length of Stay: {days}",
        f"Associated Charges: {assoc:,}", f"Grand Total: {amount:,}"]))
    return {"id": cid, "archetype": arch, **label}


def build_cases() -> list[dict]:
    L = lambda route, cov, fraud, status=None: {"expected_route": route, "expected_coverage": cov,  # noqa: E731
                                                 "expected_fraud": fraud, "expected_status": status}
    cases = []
    ring_phone, ring_bank = seed.RING_PHONE, seed.RING_BANK
    for _ in range(4):
        amt = R.randint(4, 18) * 1000
        cases.append(motor_case("glass_small", L("fast_track", "covered", "low"), ctype="windshield",
                                parts=[("Windshield", "glass", amt - 1500)], labour=1500, docs=("claim_form", "rc"),
                                photo_kw={"damage": "windshield"}))
        cases.append(motor_case("collision_small_clean", L("fast_track", "covered", "low"),
                                parts=[("Rear bumper", "plastic", R.randint(9, 20) * 1000)], labour=R.randint(3, 8) * 1000,
                                photo_kw={"damage": "rear"}))
        cases.append(motor_case("collision_mid_clean", L("standard", "covered", "low"),
                                parts=[("Bonnet", "metal", R.randint(40, 90) * 1000), ("Headlamp", "plastic", 22000)],
                                labour=R.randint(15, 30) * 1000))
        cases.append(motor_case("collision_high_value", L("senior", "covered", "low"), car=seed.CARS[3], year=2025,
                                parts=[("Front structure", "metal", R.randint(420, 650) * 1000), ("Airbags", "metal", 90000)],
                                labour=60000))
        cases.append(motor_case("tp_injury", L("senior", "covered", "low"), form={"third_party_injury": True},
                                desc="Hit a pedestrian who stepped onto the road; pedestrian hospitalised.",
                                parts=[("Bonnet", "metal", 30000)], labour=12000))
        cases.append(motor_case("lapsed_premium", L("coverage_review", "not_covered", "low"), paid=False,
                                first_days=900))
        cases.append(motor_case("drunk_driving", L("coverage_review", "not_covered", "low"),
                                desc="Car hit the divider at night. Police breath analyser test showed the driver was drunk."))
        cases.append(motor_case("theft_no_fir", L("senior", "needs_info", "low", "awaiting_documents"), ctype="theft",
                                amount=650000, car=seed.CARS[1], year=2024, photos=0, docs=("claim_form", "rc", "keys_declaration")))
        cases.append(motor_case("fraud_weather_new_policy", L("siu", "any", "high"), ctype="flood", city="Pune",
                                incident_date=R.choice(["2026-11-05", "2026-11-06", "2026-11-07"]), pol_days=12, first_days=12,
                                report_delay=4, parts=[("Engine assembly", "metal", 260000), ("ECU", "metal", 90000)],
                                labour=50000, photo_kw={"damage": "none", "flood": True, "lat": 18.5362, "lon": 73.8940}))
        cases.append(motor_case("fraud_predated_photos", L("siu", "any", "high"), pol_days=9, first_days=9,
                                photo_kw={"taken_at": seed.d(40).replace("-", ":") + " 12:00:00", "software": "Snapseed"},
                                parts=[("Door", "metal", 60000), ("Quarter panel", "metal", 45000)], labour=20000))
        cases.append(motor_case("fraud_ring_link", L("siu", "any", "high"), city="Pune", garage="G-SPEED",
                                phone_=ring_phone, bank=ring_bank, pol_days=20, first_days=20, report_delay=5,
                                parts=[("Front structure", "metal", 180000)], labour=30000))
        cases.append(motor_case("recycled_photo_only", L("siu", "any", "high"), city="Mumbai",
                                photo_kw={"recycle": ASSET_DIR / "history" / "CLM-H0042_front.jpg"}))
        cases.append(motor_case("noisy_genuine", L("standard", "covered", "low"), report_delay=4,
                                desc="Minor collision at a junction; reported late as I was travelling.",
                                parts=[("Fender", "metal", 38000), ("Bumper", "plastic", 22000)], labour=14000))
        # Held-out archetype, written after the SIU rules were calibrated: a genuine flood
        # (rain confirmed) on a brand-new policy must NOT be referred to SIU.
        cases.append(motor_case("heldout_genuine_flood_new_policy", L("standard", "covered", "low"), ctype="flood",
                                city="Chennai", incident_date="2026-10-18", pol_days=30, first_days=30,
                                parts=[("Carpet and seats", "fibre", 30000), ("Starter motor", "metal", 18000)],
                                labour=12000, photo_kw={"damage": "none", "flood": True}))
        cases.append(health_case("health_small_clean", L("fast_track", "covered", "low"), amount=R.randint(28, 48) * 1000,
                                 diagnosis="Dengue fever with thrombocytopenia", assoc=15000))
        cases.append(health_case("health_large", L("medical", "covered", "low"), amount=R.randint(180, 320) * 1000,
                                 diagnosis="Acute myocardial infarction - angioplasty", assoc=90000, room=4500))
        cases.append(health_case("health_ped", L("coverage_review", "not_covered", "low"), amount=R.randint(80, 200) * 1000,
                                 diagnosis="Diabetic foot ulcer - debridement", ped=["diabetic"], first_days=500, age=58))
    return cases


def coverage_bucket(s: str | None) -> str:
    return {"covered": "covered", "partially_covered": "covered"}.get(s or "", s or "none")


def main() -> None:
    for p in (DB_PATH, Path(str(DB_PATH) + "-wal"), Path(str(DB_PATH) + "-shm"), CHECKPOINT_DB):
        if p.exists():
            p.unlink()
    db.init_db()
    seed.reference()
    seed.history()
    cases = build_cases()
    print(f"Built {len(cases)} eval cases. Mode: {'llm' if llm_enabled() else 'deterministic'}")
    rows = []
    for i, case in enumerate(cases):
        t0 = time.perf_counter()
        runner.run_sync(case["id"])
        ms = int((time.perf_counter() - t0) * 1000)
        c = db.one("SELECT status, route, fraud_score, coverage_status, severity FROM claims WHERE id = ?", (case["id"],))
        t = db.loads(db.one("SELECT triage FROM claims WHERE id = ?", (case["id"],))["triage"], {}) or {}
        band = ((t.get("assessment") or {}).get("fraud") or {}).get("band")
        exp_fraud = case["expected_fraud"] == "high"
        got_fraud = c["route"] == "siu"
        r = {**case, "route": c["route"], "status": c["status"], "coverage": c["coverage_status"],
             "fraud_score": c["fraud_score"], "fraud_band": band, "severity": c["severity"], "ms": ms,
             "tools": len(t.get("ledger") or []),
             "route_ok": c["route"] == case["expected_route"],
             "coverage_ok": case["expected_coverage"] == "any" or coverage_bucket(c["coverage_status"]) == case["expected_coverage"],
             "fraud_tp": exp_fraud and got_fraud, "fraud_fp": got_fraud and not exp_fraud,
             "fraud_fn": exp_fraud and not got_fraud,
             "status_ok": case["expected_status"] is None or c["status"] == case["expected_status"]}
        rows.append(r)
        mark = "✓" if r["route_ok"] and r["coverage_ok"] else "✗"
        print(f"  {mark} {case['id']} {case['archetype']:<26} route={c['route']:<16} exp={case['expected_route']:<16} "
              f"cov={c['coverage_status']:<18} fraud={c['fraud_score']:>4} {ms}ms")
    tp, fp, fn = (sum(r[k] for r in rows) for k in ("fraud_tp", "fraud_fp", "fraud_fn"))
    per_arch = defaultdict(lambda: Counter())
    for r in rows:
        a = per_arch[r["archetype"]]
        a["n"] += 1
        a["route_ok"] += r["route_ok"]
        a["coverage_ok"] += r["coverage_ok"]
    confusion = Counter((r["expected_route"], r["route"]) for r in rows)
    res = {
        "mode": "llm" if llm_enabled() else "deterministic", "generated_at": db.now_iso(), "n": len(rows),
        "metrics": {
            "routing_accuracy": round(sum(r["route_ok"] for r in rows) / len(rows), 3),
            "coverage_accuracy": round(sum(r["coverage_ok"] for r in rows) / len(rows), 3),
            "fraud_precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "fraud_recall": round(tp / (tp + fn), 3) if tp + fn else None,
            "false_positive_rate_genuine": round(fp / max(1, sum(1 for r in rows if r["expected_fraud"] == "low")), 3),
            "heldout_accuracy": round(sum(r["route_ok"] for r in rows if r["archetype"].startswith("heldout")) / max(1, sum(1 for r in rows if r["archetype"].startswith("heldout"))), 3),
            "documents_gate_accuracy": round(sum(r["status_ok"] for r in rows) / len(rows), 3),
            "avg_ms": int(sum(r["ms"] for r in rows) / len(rows)),
            "avg_tools": round(sum(r["tools"] for r in rows) / len(rows), 1),
        },
        "per_archetype": {k: dict(v) for k, v in sorted(per_arch.items())},
        "confusion": [{"expected": e, "got": g, "n": n} for (e, g), n in sorted(confusion.items())],
        "cases": rows,
    }
    (HERE / "results.json").write_text(json.dumps(res, indent=2, default=str))
    m = res["metrics"]
    print(f"\nRouting {m['routing_accuracy']:.1%} | Coverage {m['coverage_accuracy']:.1%} | Fraud P {m['fraud_precision']} "
          f"R {m['fraud_recall']} | FPR genuine {m['false_positive_rate_genuine']:.1%} | avg {m['avg_ms']} ms")


if __name__ == "__main__":
    main()
