"""Builds the synthetic book of business: customers, policies, garages, hospitals,
handlers, ~420 historical claims (with a planted fraud ring), and demo scenarios.

Run:  python -m app.seed          (idempotent; --reset wipes and rebuilds)"""
from __future__ import annotations

import random
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

from . import db
from .assets import pdf, photo, recompress
from .config import AS_OF_DATE, ASSET_DIR, CHECKPOINT_DB, DB_PATH
from .tools import forensics

TODAY = date.fromisoformat(AS_OF_DATE)
R = random.Random(42)

FIRST = ["Aarav", "Vivaan", "Aditya", "Arjun", "Sai", "Reyansh", "Ishaan", "Kabir", "Rohan", "Karan", "Ananya",
         "Diya", "Saanvi", "Aadhya", "Kavya", "Meera", "Priya", "Neha", "Pooja", "Sneha", "Rahul", "Vikram",
         "Suresh", "Ramesh", "Lakshmi", "Deepa", "Farhan", "Imran", "Zoya", "Sana", "Gurpreet", "Harleen",
         "Joseph", "Mary", "Thomas", "Anil", "Sunita", "Manoj", "Rekha", "Nikhil"]
LAST = ["Sharma", "Verma", "Iyer", "Nair", "Reddy", "Patil", "Kulkarni", "Deshmukh", "Gupta", "Mehta", "Shah",
        "Joshi", "Khan", "Siddiqui", "Singh", "Gill", "Das", "Banerjee", "Mukherjee", "Menon", "Pillai", "Rao",
        "Naidu", "Chauhan", "Agarwal", "D'Souza", "Fernandes", "Kapoor", "Malhotra", "Bhat"]
CITIES = {"Pune": (18.5204, 73.8567), "Mumbai": (19.0760, 72.8777), "Bengaluru": (12.9716, 77.5946),
          "Chennai": (13.0827, 80.2707), "Hyderabad": (17.3850, 78.4867), "Delhi": (28.6139, 77.2090),
          "Kolkata": (22.5726, 88.3639), "Ahmedabad": (23.0225, 72.5714)}
CARS = [("Maruti Suzuki Swift VXi", 1197, "Petrol", 620000), ("Hyundai Creta SX", 1497, "Petrol", 1350000),
        ("Tata Nexon XZ+", 1199, "Petrol", 980000), ("Mahindra XUV700 AX7", 2198, "Diesel", 2150000),
        ("Honda City ZX", 1498, "Petrol", 1280000), ("Kia Seltos HTX", 1497, "Diesel", 1420000),
        ("Toyota Innova Crysta", 2393, "Diesel", 2050000), ("Maruti Baleno Alpha", 1197, "Petrol", 760000),
        ("Tata Punch Creative", 1199, "Petrol", 720000), ("Hyundai i20 Asta", 1197, "Petrol", 830000)]
STATE_CODE = {"Pune": "MH12", "Mumbai": "MH02", "Bengaluru": "KA03", "Chennai": "TN09", "Hyderabad": "TS09",
              "Delhi": "DL8C", "Kolkata": "WB02", "Ahmedabad": "GJ01"}


def d(days_ago: int) -> str:
    return str(TODAY - timedelta(days=days_ago))


def phone() -> str:
    return f"{R.choice('6789')}{R.randint(100000000, 999999999)}"


def reg(city: str) -> str:
    return f"{STATE_CODE[city]} {''.join(R.choice('ABCDEFGHJKLMNPRSTUVWXYZ') for _ in range(2))} {R.randint(1000, 9999)}"


# ====================================================================== reference data
GARAGES = [
    ("G-SPEED", "Speedline Auto Works", "Pune", 0), ("G-PUN1", "Kothrud Motors (Authorised)", "Pune", 1),
    ("G-MUM1", "Andheri Car Care", "Mumbai", 1), ("G-MUM2", "Western Express Autos", "Mumbai", 1),
    ("G-BLR1", "Koramangala Auto Hub", "Bengaluru", 1), ("G-BLR2", "Whitefield Motors", "Bengaluru", 1),
    ("G-CHE1", "Velachery Service Point", "Chennai", 1), ("G-HYD1", "Gachibowli Cars", "Hyderabad", 1),
    ("G-DEL1", "Okhla Auto Clinic", "Delhi", 1), ("G-KOL1", "Salt Lake Motors", "Kolkata", 1),
    ("G-AMD1", "SG Highway Autos", "Ahmedabad", 1),
]
HOSPITALS = [
    ("H-PUN1", "Sahyadri Multispeciality (Network)", "Pune", 1, 0), ("H-PUN2", "Lifeline Nursing Home", "Pune", 0, 1),
    ("H-MUM1", "Andheri City Hospital", "Mumbai", 1, 0), ("H-BLR1", "Manipal-style General (Network)", "Bengaluru", 1, 0),
    ("H-CHE1", "Adyar Care Hospital", "Chennai", 1, 0), ("H-HYD1", "Banjara Hills Medical Centre", "Hyderabad", 1, 0),
    ("H-DEL1", "Saket Heart & Ortho", "Delhi", 1, 0), ("H-KOL1", "Park Street Clinic", "Kolkata", 0, 0),
]
HANDLERS = [
    ("U-AUTO", "ClaimPilot Auto-Settle", "fast_track", ["motor", "health"], 50000, "All"),
    ("U-ADJ1", "Priya Raman", "adjuster", ["motor"], 300000, "South"),
    ("U-ADJ2", "Kunal Bhosale", "adjuster", ["motor", "health"], 300000, "West"),
    ("U-ADJ3", "Farah Qureshi", "adjuster", ["motor"], 300000, "North"),
    ("U-SR1", "R. Venkatesh", "senior_adjuster", ["motor", "health"], 5000000, "South"),
    ("U-SR2", "Anjali Deshpande", "senior_adjuster", ["motor"], 5000000, "West"),
    ("U-MED1", "Dr. Shalini Rao", "medical_reviewer", ["health"], 2000000, "All"),
    ("U-MED2", "Dr. Arvind Menon", "medical_reviewer", ["health"], 2000000, "All"),
    ("U-SIU1", "Inspector-grade: Harish Malik", "siu", ["motor", "health"], 10000000, "All"),
    ("U-SIU2", "Meenal Kaur (SIU)", "siu", ["motor", "health"], 10000000, "All"),
]

RING_PHONE, RING_BANK = "9822041177", "50100248813377"


def reference() -> None:
    for g in GARAGES:
        db.insert("garages", {"id": g[0], "name": g[1], "city": g[2], "network": g[3], "phone": phone()})
    for h in HOSPITALS:
        db.insert("hospitals", {"id": h[0], "name": h[1], "city": h[2], "network": h[3], "flagged": h[4]})
    for h in HANDLERS:
        db.insert("handlers", {"id": h[0], "name": h[1], "role": h[2], "lines": h[3], "authority_limit": h[4],
                               "open_cases": R.randint(3, 14) if h[0] != "U-AUTO" else 0, "region": h[5],
                               "email": f"{h[0].lower()}@claims.example"})


# ====================================================================== customers & policies
def customer(cid: str, name: str, city: str, ph: str | None = None, bank: str | None = None, since: str | None = None) -> dict:
    row = {"id": cid, "name": name, "phone": ph or phone(), "email": f"{name.split()[0].lower()}{R.randint(10, 99)}@mail.example",
           "address": f"{R.randint(1, 400)}, {R.choice(['MG Road', 'Station Road', 'Link Road', 'Ring Road', 'Main Street'])}, {city}",
           "city": city, "dob": f"{R.randint(1958, 2000)}-{R.randint(1, 12):02d}-{R.randint(1, 28):02d}",
           "pan": "".join(R.choice("ABCDEFGHJKLMNPRSTUVWXYZ") for _ in range(5)) + f"{R.randint(1000, 9999)}" + R.choice("ABCDEFGH"),
           "bank_account": bank or str(R.randint(10 ** 11, 10 ** 13)), "created_at": since or d(R.randint(400, 2500))}
    db.insert("customers", row)
    return row


def motor_policy(pno: str, cid: str, city: str, start: str, *, first: str | None = None, car: tuple | None = None,
                 year: int | None = None, addons: list[str] | None = None, regno: str | None = None,
                 paid: bool = True, vol_ded: float = 0, permit: bool = False) -> dict:
    car = car or R.choice(CARS)
    year = year or R.randint(2017, 2025)
    idv = round(car[3] * max(0.5, 1 - 0.1 * (TODAY.year - year)), -3)
    s = date.fromisoformat(start)
    details = {"vehicle": {"reg": regno or reg(city), "make_model": car[0], "year": year, "cc": car[1], "fuel": car[2],
                           "chassis_no": f"MA3{R.randint(10 ** 13, 10 ** 14)}", "engine_no": f"K12N{R.randint(10 ** 6, 10 ** 7)}",
                           "hypothecation": R.choice([None, "HDFC Bank", "ICICI Bank", None]), "commercial_permit": permit},
               "idv": idv, "addons": addons if addons is not None else R.choice([[], ["zero_dep"], ["zero_dep", "engine_protect"], []]),
               "first_inception_date": first or start, "ncb": R.choice([0, 20, 25, 35])}
    row = {"policy_no": pno, "customer_id": cid, "product": "MOTOR-PKG", "line": "motor", "start_date": start,
           "end_date": str(s + timedelta(days=364)), "status": "active" if paid else "lapsed",
           "premium": round(idv * 0.028), "premium_paid": int(paid), "sum_insured": idv, "deductible": vol_ded,
           "details": details}
    db.insert("policies", row)
    return {**row, "details": details}


def health_policy(pno: str, cid: str, start: str, members: list[dict], si: float, *, first: str | None = None) -> dict:
    s = date.fromisoformat(start)
    details = {"members": members, "first_inception_date": first or start, "room_category": "single private"}
    row = {"policy_no": pno, "customer_id": cid, "product": "HEALTH-FLT", "line": "health", "start_date": start,
           "end_date": str(s + timedelta(days=364)), "status": "active", "premium": round(si * 0.035), "premium_paid": 1,
           "sum_insured": si, "deductible": 0, "details": details}
    db.insert("policies", row)
    return row


# ====================================================================== history
def history() -> None:
    hist_dir = ASSET_DIR / "history"
    n = 0
    # --- genuine book
    for i in range(330):
        city = R.choice(list(CITIES))
        name = f"{R.choice(FIRST)} {R.choice(LAST)}"
        cid = f"C-{1000 + i}"
        cust = customer(cid, name, city)
        line = "motor" if i < 230 else "health"
        start = d(R.randint(60, 700))
        if line == "motor":
            pol = motor_policy(f"MOT-{25000 + i}", cid, city, start, first=d(R.randint(700, 2500)) if R.random() < 0.7 else start)
            gar = R.choice([g for g in GARAGES if g[2] == city and g[0] != "G-SPEED"] or [GARAGES[2]])[0]
            ctype = R.choices(["collision", "windshield", "theft", "flood", "fire", "vandalism"], [70, 14, 4, 6, 2, 4])[0]
            amt = {"collision": R.randint(12000, 180000), "windshield": R.randint(6000, 22000),
                   "theft": int(pol["details"]["idv"]), "flood": R.randint(40000, 250000),
                   "fire": R.randint(50000, 400000), "vandalism": R.randint(8000, 45000)}[ctype]
        else:
            age = R.randint(28, 70)
            pol = health_policy(f"HLT-{40000 + i}", cid, start, [{"name": name, "relation": "self", "age": age, "ped": []}],
                                R.choice([300000, 500000, 1000000]), first=d(R.randint(400, 2500)))
            gar = None
            ctype = "hospitalization"
            amt = R.randint(25000, 350000)
        ps = date.fromisoformat(pol["start_date"])
        inc = ps + timedelta(days=R.randint(20, max(21, (TODAY - ps).days - 5)))
        if inc >= TODAY:
            inc = TODAY - timedelta(days=R.randint(5, 30))
        outcome = R.choices(["settled", "settled_partial", "repudiated_coverage", "withdrawn"], [78, 12, 7, 3])[0]
        n += 1
        db.insert("claims", {
            "id": f"CLM-H{n:04d}", "policy_no": pol["policy_no"], "customer_id": cid, "line": line, "claim_type": ctype,
            "incident_date": str(inc), "incident_time": f"{R.randint(6, 22):02d}:{R.randint(0, 59):02d}",
            "reported_date": str(inc + timedelta(days=R.choices([0, 1, 2, 3, 6], [50, 30, 12, 5, 3])[0])),
            "location": city, "city": city, "lat": CITIES[city][0], "lon": CITIES[city][1],
            "description": f"Historical {ctype} claim", "amount_claimed": amt, "garage_id": gar,
            "hospital_id": R.choice([h for h in HOSPITALS if h[2] == city] or [HOSPITALS[0]])[0] if line == "health" else None,
            "contact_phone": cust["phone"], "bank_account": cust["bank_account"],
            "insured_member": name if line == "health" else None, "status": "closed", "historical": 1,
            "outcome": outcome, "created_at": str(inc), "scenario": None})
        if n == 42:  # a past Mumbai collision whose photo will be "recycled" by a demo claim
            db.update("claims", "id", f"CLM-H{n:04d}", {"city": "Mumbai", "location": "Andheri East", "claim_type": "collision",
                                                        "amount_claimed": 58000, "garage_id": "G-MUM1"})
            p = photo(hist_dir / "CLM-H0042_front.jpg", seed=4242, body="silver", damage="front",
                      taken_at=f"{inc:%Y:%m:%d} 18:22:10", lat=19.1136, lon=72.8697)
            db.insert("documents", {"claim_id": "CLM-H0042", "kind": "photo", "filename": p.name, "path": str(p),
                                    "mime": "image/jpeg", "extracted_text": "", "meta": {}, "created_at": str(inc)})
            forensics.register_hashes("CLM-H0042")

    # --- the fraud ring: 4 people, one phone, one bank account, one garage, staged losses
    ring = [("C-R1", "Sachin Gaikwad"), ("C-R2", "Amol Jadhav"), ("C-R3", "Swapnil More"), ("C-R4", "Tejas Pawar")]
    for j, (cid, name) in enumerate(ring):
        customer(cid, name, "Pune", ph=RING_PHONE if j % 2 == 0 else phone(), bank=RING_BANK if j != 3 else None,
                 since=d(R.randint(90, 200)))
        for k in range(2 if j < 3 else 3):
            pno = f"MOT-R{j}{k}"
            start = d(R.randint(70, 150))
            pol = motor_policy(pno, cid, "Pune", start, car=R.choice(CARS[1:6]), year=R.randint(2018, 2022), addons=["zero_dep"])
            inc = date.fromisoformat(start) + timedelta(days=R.randint(4, 14))
            n += 1
            fraud = (j, k) in {(0, 0), (1, 1), (2, 0)}
            db.insert("claims", {
                "id": f"CLM-H{n:04d}", "policy_no": pno, "customer_id": cid, "line": "motor",
                "claim_type": R.choice(["flood", "collision", "flood"]), "incident_date": str(inc),
                "incident_time": f"{R.choice([0, 1, 2, 23, 22]):02d}:{R.randint(10, 59)}",
                "reported_date": str(inc + timedelta(days=R.randint(3, 9))), "location": "Koregaon Park", "city": "Pune",
                "lat": 18.5362, "lon": 73.8940, "description": "Historical ring claim",
                "amount_claimed": round(pol["details"]["idv"] * R.uniform(0.55, 0.8), -3), "garage_id": "G-SPEED",
                "hospital_id": None, "contact_phone": RING_PHONE if (j + k) % 2 == 0 else phone(),
                "bank_account": RING_BANK, "insured_member": None, "status": "closed", "historical": 1,
                "outcome": "fraud_confirmed" if fraud else "under_investigation", "created_at": str(inc), "scenario": None})


# ====================================================================== scenarios
def _doc(claim_id: str, kind: str, p: Path, mime: str = "application/pdf") -> None:
    from .tools.documents import extract_text
    db.insert("documents", {"claim_id": claim_id, "kind": kind, "filename": p.name, "path": str(p), "mime": mime,
                            "extracted_text": extract_text(p) if mime == "application/pdf" else "", "meta": {},
                            "created_at": db.now_iso()})


def _claim(cid: str, scenario: str, form: dict, **row) -> None:
    db.execute("DELETE FROM documents WHERE claim_id = ?", (cid,))
    db.execute("DELETE FROM claim_events WHERE claim_id = ?", (cid,))
    db.execute("DELETE FROM tickets WHERE claim_id = ?", (cid,))
    db.execute("DELETE FROM notifications WHERE claim_id = ?", (cid,))
    db.execute("DELETE FROM image_hashes WHERE claim_id = ?", (cid,))
    db.insert("claims", {"id": cid, "status": "submitted", "historical": 0, "created_at": db.now_iso(),
                         "scenario": scenario, "triage": {"form": form, "run": 1}, "outcome": None, "severity": None,
                         "fraud_score": None, "coverage_status": None, "route": None, "assigned_handler": None, **row})


def claim_form(dirp: Path, cid: str, c: dict, extra: list[str] | None = None) -> Path:
    return pdf(dirp / f"claim_form_{cid}.pdf", "Claim Form", "ClaimPilot General Insurance (Demo)", [
        f"Claim Reference: {cid}", f"Policy No.: {c['policy_no']}", f"Date of Loss: {c['incident_date']}",
        f"Place of Loss: {c['location']}, {c['city']}", f"Nature of Loss: {c['claim_type']}",
        f"Amount Claimed: INR {c['amount_claimed']:,}", "## Claimant's description", *_wrap(c["description"]),
        *(extra or []), "## Declaration", "I declare the above is true to the best of my knowledge."])


def _wrap(t: str, n: int = 95) -> list[str]:
    out, line = [], ""
    for w in t.split():
        if len(line) + len(w) > n:
            out.append(line)
            line = ""
        line += w + " "
    return out + [line] if line else out


def estimate(dirp: Path, cid: str, garage: str, insp: str, impact: str, parts: list[tuple[str, str, int]], labour: int) -> Path:
    total = sum(p[2] for p in parts) + labour
    return pdf(dirp / f"repair_estimate_{cid}.pdf", "Repair Estimate", garage, [
        f"Garage: {garage}", f"Inspection Date: {insp}", f"Impact: {impact}", "## Parts (name | material | INR)",
        *[f"- {p[0]} | {p[1]} | {p[2]:,}" for p in parts], "## Labour", f"Labour & Paint: {labour:,}",
        f"Grand Total: {total:,}"])


def rc(dirp: Path, pol: dict) -> Path:
    v = pol["details"]["vehicle"]
    return pdf(dirp / f"rc_{v['reg'].replace(' ', '')}.pdf", "Registration Certificate", "Regional Transport Office", [
        f"Registration No.: {v['reg']}", f"Maker / Model: {v['make_model']}", f"Year of Manufacture: {v['year']}",
        f"Fuel: {v['fuel']}", f"Chassis No.: {v['chassis_no']}", f"Engine No.: {v['engine_no']}"])


def dl(dirp: Path, name: str, valid: str) -> Path:
    return pdf(dirp / f"driving_licence_{name.split()[0].lower()}.pdf", "Driving Licence", "Transport Department", [
        f"Name: {name}", f"Licence No.: MH12 2015{R.randint(1000000, 9999999)}", "Class: LMV", f"Valid Till: {valid}"])


def scenarios() -> list[dict]:
    """Eight demo scenarios that between them exercise every branch of the graph."""
    out = []
    base = ASSET_DIR / "scenarios"

    # 1 ─ windshield, fast track
    cid = "CLM-2611-1001"; dp = base / "s1"
    customer("C-S1", "Kavya Iyer", "Bengaluru", since="2021-06-14")
    pol = motor_policy("MOT-77001", "C-S1", "Bengaluru", "2026-03-02", first="2021-06-14", car=CARS[7], year=2022,
                       addons=["zero_dep"], regno="KA03 MK 4471")
    c = {"policy_no": "MOT-77001", "incident_date": "2026-11-10", "location": "Koramangala 5th Block", "city": "Bengaluru",
         "claim_type": "windshield", "amount_claimed": 8400,
         "description": "A stone thrown up by a truck on Hosur Road cracked the front windshield while I was driving to "
                        "work. No other damage, nobody hurt. Car is drivable but the crack is spreading."}
    _claim(cid, "windshield_fast_track", {"injury": "none", "vehicle_reg": "KA03 MK 4471"}, customer_id="C-S1",
           line="motor", incident_time="09:12", reported_date="2026-11-10", lat=None, lon=None, garage_id="G-BLR1",
           hospital_id=None, contact_phone=phone(), bank_account=str(R.randint(10 ** 11, 10 ** 12)), insured_member=None,
           **c)
    _doc(cid, "claim_form", claim_form(dp, cid, c))
    _doc(cid, "photo", photo(dp / "windshield_1.jpg", seed=11, body="blue", damage="windshield",
                             taken_at="2026:11:10 09:31:02", lat=12.9352, lon=77.6245), "image/jpeg")
    _doc(cid, "rc", rc(dp, pol))
    _doc(cid, "repair_estimate", estimate(dp, cid, "Koramangala Auto Hub", "2026-11-11", "front",
                                          [("Windshield glass (laminated)", "glass", 6900)], 1500))
    out.append({"id": cid, "title": "Cracked windshield", "tag": "Fast track",
                "blurb": "₹8,400 glass claim, long-standing customer, clean documents."})

    # 2 ─ Pune "flood", policy 6 days old, photo pre-dates policy, ring phone → SIU
    cid = "CLM-2611-1002"; dp = base / "s2"
    customer("C-S2", "Nilesh Shinde", "Pune", ph=RING_PHONE, bank=RING_BANK, since="2026-10-30")
    pol = motor_policy("MOT-77002", "C-S2", "Pune", "2026-11-01", car=CARS[1], year=2021, addons=["zero_dep"],
                       regno="MH12 RT 8812")
    c = {"policy_no": "MOT-77002", "incident_date": "2026-11-07", "location": "Koregaon Park Lane 6", "city": "Pune",
         "claim_type": "flood", "amount_claimed": 685000,
         "description": "Heavy rain flooded the basement parking overnight and my Creta was submerged up to the dashboard. "
                        "Engine will not start, interiors and electricals destroyed. Car towed to Speedline Auto Works."}
    _claim(cid, "flood_fraud_ring", {"injury": "none", "vehicle_reg": "MH12 RT 8812"}, customer_id="C-S2", line="motor",
           incident_time="02:30", reported_date="2026-11-11", lat=None, lon=None, garage_id="G-SPEED", hospital_id=None,
           contact_phone=RING_PHONE, bank_account=RING_BANK, insured_member=None, **c)
    _doc(cid, "claim_form", claim_form(dp, cid, c))
    _doc(cid, "photo", photo(dp / "flood_1.jpg", seed=21, body="white", damage="none", flood=True,
                             taken_at="2026:10:12 17:05:44", lat=18.5362, lon=73.8940), "image/jpeg")
    _doc(cid, "photo", photo(dp / "flood_2.jpg", seed=22, body="white", damage="front", flood=True,
                             taken_at="2026:10:12 17:06:30", lat=18.5362, lon=73.8940, software="Snapseed 2.21"), "image/jpeg")
    _doc(cid, "rc", rc(dp, pol))
    _doc(cid, "driving_licence", dl(dp, "Nilesh Shinde", "2031-05-30"))
    _doc(cid, "repair_estimate", estimate(dp, cid, "Speedline Auto Works", "2026-11-11", "underbody", [
        ("Engine assembly (hydrostatic lock)", "metal", 285000), ("ECU and wiring harness", "metal", 118000),
        ("Seats and interior trim", "fibre", 96000), ("Infotainment unit", "plastic", 64000),
        ("Carpet and insulation", "rubber", 38000)], 84000))
    out.append({"id": cid, "title": "Basement flood, new policy", "tag": "Fraud ring",
                "blurb": "₹6.85L flood claim 6 days after inception. Weather, EXIF and the claims graph disagree."})

    # 3 ─ genuine Chennai flood, engine exclusion → partial, standard adjuster
    cid = "CLM-2611-1003"; dp = base / "s3"
    customer("C-S3", "Lakshmi Narayanan", "Chennai", since="2019-02-11")
    pol = motor_policy("MOT-77003", "C-S3", "Chennai", "2026-01-20", first="2019-02-11", car=CARS[4], year=2020,
                       addons=["zero_dep"], regno="TN09 BX 2204")
    c = {"policy_no": "MOT-77003", "incident_date": "2026-10-18", "location": "Velachery Main Road", "city": "Chennai",
         "claim_type": "flood", "amount_claimed": 146500,
         "description": "During the heavy northeast monsoon rain the street outside our apartment flooded to knee height. "
                        "The car was parked on the street; water entered the cabin and the engine stalled when I tried to "
                        "move it to higher ground."}
    _claim(cid, "flood_genuine_partial", {"injury": "none", "vehicle_reg": "TN09 BX 2204"}, customer_id="C-S3",
           line="motor", incident_time="21:40", reported_date="2026-10-19", lat=None, lon=None, garage_id="G-CHE1",
           hospital_id=None, contact_phone=phone(), bank_account=str(R.randint(10 ** 11, 10 ** 12)), insured_member=None,
           **c)
    _doc(cid, "claim_form", claim_form(dp, cid, c))
    _doc(cid, "photo", photo(dp / "street_flood.jpg", seed=31, body="grey", damage="none", flood=True,
                             taken_at="2026:10:18 22:14:51", lat=12.9815, lon=80.2180), "image/jpeg")
    _doc(cid, "rc", rc(dp, pol))
    _doc(cid, "driving_licence", dl(dp, "Lakshmi Narayanan", "2034-01-01"))
    _doc(cid, "repair_estimate", estimate(dp, cid, "Velachery Service Point", "2026-10-21", "underbody", [
        ("Engine overhaul (water ingress)", "metal", 72000), ("Carpet and seat cleaning", "fibre", 14500),
        ("Starter motor", "metal", 18500), ("Interior electricals", "plastic", 21500)], 20000))
    out.append({"id": cid, "title": "Monsoon street flood", "tag": "Partial cover",
                "blurb": "Genuine flood confirmed by weather data; engine damage excluded without Engine Protect."})

    # 4 ─ health: knee replacement inside 24-month specified-disease wait → coverage review
    cid = "CLM-2611-1004"; dp = base / "s4"
    customer("C-S4", "Ramesh Kulkarni", "Pune", since="2025-08-01")
    health_policy("HLT-88004", "C-S4", "2026-08-01", [
        {"name": "Ramesh Kulkarni", "relation": "self", "age": 64, "ped": ["hypertension"]},
        {"name": "Sunita Kulkarni", "relation": "spouse", "age": 60, "ped": []}], 500000, first="2025-08-01")
    c = {"policy_no": "HLT-88004", "incident_date": "2026-11-03", "location": "Sahyadri Hospital, Deccan", "city": "Pune",
         "claim_type": "hospitalization", "amount_claimed": 342000,
         "description": "Planned total knee replacement (right knee) for osteoarthritis. Admitted 3 Nov, discharged 7 Nov."}
    _claim(cid, "health_waiting_period", {"injury": "none"}, customer_id="C-S4", line="health", incident_time="08:00",
           reported_date="2026-11-01", lat=None, lon=None, garage_id=None, hospital_id="H-PUN1", contact_phone=phone(),
           bank_account=str(R.randint(10 ** 11, 10 ** 12)), insured_member="Ramesh Kulkarni", **c)
    _doc(cid, "claim_form", claim_form(dp, cid, c))
    _doc(cid, "discharge_summary", pdf(dp / "discharge_summary.pdf", "Discharge Summary", "Sahyadri Multispeciality Hospital", [
        "Patient: Ramesh Kulkarni, 64 M", "Date of Admission: 2026-11-03", "Date of Discharge: 2026-11-07",
        "Diagnosis: Primary osteoarthritis right knee - total knee replacement (TKR) performed",
        "History: Knee pain for 3 years, on analgesics. Known hypertensive.", "Procedure: Right TKR under spinal anaesthesia",
        "Condition at discharge: Stable, mobilising with walker"]))
    _doc(cid, "hospital_bill", pdf(dp / "final_bill.pdf", "Final Hospital Bill", "Sahyadri Multispeciality Hospital", [
        "Hospital: Sahyadri Multispeciality (Network)", "Room Category: Single Private", "Room Rent per Day: 6,500",
        "Length of Stay: 4", "Associated Charges: 98,000", "Implant (knee prosthesis): 1,45,000",
        "Medicines & consumables: 73,000", "Grand Total: 3,42,000"]))
    out.append({"id": cid, "title": "Knee replacement, year 2", "tag": "Not covered",
                "blurb": "₹3.42L TKR 15 months into cover: 24-month specified-disease wait. Denial needs a human."})

    # 5 ─ theft without FIR → docs gate; upload FIR to resume → senior
    cid = "CLM-2611-1005"; dp = base / "s5"
    customer("C-S5", "Farhan Siddiqui", "Delhi", since="2020-09-09")
    pol = motor_policy("MOT-77005", "C-S5", "Delhi", "2026-05-15", first="2020-09-09", car=CARS[5], year=2023,
                       addons=["zero_dep"], regno="DL8C AF 3390")
    idv = int(pol["details"]["idv"])
    c = {"policy_no": "MOT-77005", "incident_date": "2026-11-09", "location": "Saket, near Select City Walk", "city": "Delhi",
         "claim_type": "theft", "amount_claimed": idv,
         "description": "Parked the car outside my building at 11 pm. In the morning it was gone. Building CCTV shows two "
                        "men leaving with it at 3:40 am. Police complaint registered, FIR copy awaited."}
    _claim(cid, "theft_missing_fir", {"injury": "none", "vehicle_reg": "DL8C AF 3390"}, customer_id="C-S5", line="motor",
           incident_time="03:40", reported_date="2026-11-10", lat=None, lon=None, garage_id=None, hospital_id=None,
           contact_phone=phone(), bank_account=str(R.randint(10 ** 11, 10 ** 12)), insured_member=None, **c)
    _doc(cid, "claim_form", claim_form(dp, cid, c))
    _doc(cid, "rc", rc(dp, pol))
    _doc(cid, "keys_declaration", pdf(dp / "keys_declaration.pdf", "Keys Declaration", "Insured", [
        "I confirm both original keys are in my possession and will be surrendered.", "Keys declaration signed: 2026-11-10"]))
    pdf(dp / "upload_later_FIR.pdf", "First Information Report", "Delhi Police - PS Saket", [
        "FIR No.: 0871/2026", "Police Station: Saket", "Date of Occurrence: 2026-11-09", "Date of Report: 2026-11-10",
        "Offence: Sec 303(2) BNS - Theft of motor vehicle", f"Vehicle: DL8C AF 3390 ({CARS[5][0]})",
        "Complainant: as per records", "Status: Under investigation"])
    out.append({"id": cid, "title": "Overnight vehicle theft", "tag": "Pauses for FIR",
                "blurb": "Agent pauses for the FIR, then re-plans when it is uploaded.",
                "upload_hint": str(dp / "upload_later_FIR.pdf")})

    # 6 ─ collision with third-party injury → critical → senior adjuster
    cid = "CLM-2611-1006"; dp = base / "s6"
    customer("C-S6", "Sneha Reddy", "Hyderabad", since="2018-04-22")
    pol = motor_policy("MOT-77006", "C-S6", "Hyderabad", "2026-04-22", first="2018-04-22", car=CARS[3], year=2023,
                       addons=["zero_dep", "engine_protect"], regno="TS09 EZ 7015")
    c = {"policy_no": "MOT-77006", "incident_date": "2026-11-11", "location": "Gachibowli flyover", "city": "Hyderabad",
         "claim_type": "collision", "amount_claimed": 212000,
         "description": "A two-wheeler cut across my lane on the Gachibowli flyover; I braked but hit it. The rider was "
                        "thrown off and taken to hospital with a fractured leg. Front of my car badly damaged, airbags "
                        "deployed. Traffic police attended."}
    _claim(cid, "collision_tp_injury", {"injury": "none", "third_party_injury": True, "vehicle_reg": "TS09 EZ 7015"},
           customer_id="C-S6", line="motor", incident_time="19:05", reported_date="2026-11-11", lat=None, lon=None,
           garage_id="G-HYD1", hospital_id=None, contact_phone=phone(), bank_account=str(R.randint(10 ** 11, 10 ** 12)),
           insured_member=None, **c)
    _doc(cid, "claim_form", claim_form(dp, cid, c))
    _doc(cid, "photo", photo(dp / "front_damage.jpg", seed=61, body="black", damage="front",
                             taken_at="2026:11:11 19:31:08", lat=17.4401, lon=78.3489), "image/jpeg")
    _doc(cid, "rc", rc(dp, pol))
    _doc(cid, "driving_licence", dl(dp, "Sneha Reddy", "2035-08-19"))
    _doc(cid, "repair_estimate", estimate(dp, cid, "Gachibowli Cars", "2026-11-12", "front", [
        ("Front bumper assembly", "plastic", 38000), ("Bonnet", "metal", 42000), ("Radiator & condenser", "metal", 36000),
        ("Airbag modules (2)", "metal", 54000), ("Headlamp LH", "plastic", 18000)], 24000))
    out.append({"id": cid, "title": "Flyover collision, rider injured", "tag": "Critical",
                "blurb": "Third-party bodily injury means MACT exposure, so it goes to a senior adjuster."})

    # 7 ─ recycled photo from an old claim → medium/high fraud
    cid = "CLM-2611-1007"; dp = base / "s7"
    customer("C-S7", "Vikram Malhotra", "Mumbai", since="2023-01-05")
    pol = motor_policy("MOT-77007", "C-S7", "Mumbai", "2026-02-10", first="2023-01-05", car=CARS[9], year=2021,
                       addons=[], regno="MH02 FK 6630")
    c = {"policy_no": "MOT-77007", "incident_date": "2026-11-08", "location": "Andheri East, near metro station",
         "city": "Mumbai", "claim_type": "collision", "amount_claimed": 61500,
         "description": "While reversing out of a parking spot a reversing tempo hit the front of my car. Front bumper and "
                        "grille broken, bonnet dented."}
    _claim(cid, "recycled_photo", {"injury": "none", "vehicle_reg": "MH02 FK 6630"}, customer_id="C-S7", line="motor",
           incident_time="20:15", reported_date="2026-11-09", lat=None, lon=None, garage_id="G-MUM1", hospital_id=None,
           contact_phone=phone(), bank_account=str(R.randint(10 ** 11, 10 ** 12)), insured_member=None, **c)
    _doc(cid, "claim_form", claim_form(dp, cid, c))
    dp.mkdir(parents=True, exist_ok=True)
    _doc(cid, "photo", recompress(ASSET_DIR / "history" / "CLM-H0042_front.jpg", dp / "IMG_20261108_2031.jpg",
                                  "2026:11:08 20:31:12", 19.1136, 72.8697), "image/jpeg")
    _doc(cid, "rc", rc(dp, pol))
    _doc(cid, "driving_licence", dl(dp, "Vikram Malhotra", "2033-03-03"))
    _doc(cid, "repair_estimate", estimate(dp, cid, "Andheri Car Care", "2026-11-09", "front", [
        ("Front bumper", "plastic", 16500), ("Radiator grille", "plastic", 7800), ("Bonnet", "metal", 21000)], 16200))
    out.append({"id": cid, "title": "Parking-lot fender bender", "tag": "Recycled photo",
                "blurb": "The photo matches one from a 2025 claim (perceptual hash), even with fresh EXIF."})

    # 8 ─ health appendicitis, room-rent overage → partial, medical review
    cid = "CLM-2611-1008"; dp = base / "s8"
    customer("C-S8", "Meera Joshi", "Mumbai", since="2022-03-01")
    health_policy("HLT-88008", "C-S8", "2026-03-01", [
        {"name": "Meera Joshi", "relation": "self", "age": 34, "ped": []},
        {"name": "Aditya Joshi", "relation": "spouse", "age": 36, "ped": []}], 500000, first="2022-03-01")
    c = {"policy_no": "HLT-88008", "incident_date": "2026-11-05", "location": "Andheri City Hospital", "city": "Mumbai",
         "claim_type": "hospitalization", "amount_claimed": 186000,
         "description": "Severe abdominal pain at night, diagnosed with acute appendicitis. Emergency laparoscopic "
                        "appendectomy. Took a deluxe room as the standard rooms were full."}
    _claim(cid, "health_room_rent", {"injury": "none"}, customer_id="C-S8", line="health", incident_time="01:20",
           reported_date="2026-11-05", lat=None, lon=None, garage_id=None, hospital_id="H-MUM1", contact_phone=phone(),
           bank_account=str(R.randint(10 ** 11, 10 ** 12)), insured_member="Meera Joshi", **c)
    _doc(cid, "claim_form", claim_form(dp, cid, c))
    _doc(cid, "discharge_summary", pdf(dp / "discharge_summary.pdf", "Discharge Summary", "Andheri City Hospital", [
        "Patient: Meera Joshi, 34 F", "Date of Admission: 2026-11-05", "Date of Discharge: 2026-11-08",
        "Diagnosis: Acute appendicitis - laparoscopic appendectomy", "History: No significant past history.",
        "Condition at discharge: Stable"]))
    _doc(cid, "hospital_bill", pdf(dp / "final_bill.pdf", "Final Hospital Bill", "Andheri City Hospital", [
        "Hospital: Andheri City Hospital", "Room Category: Deluxe", "Room Rent per Day: 9,000", "Length of Stay: 3",
        "Associated Charges: 1,02,000", "Medicines & consumables: 57,000", "Grand Total: 1,86,000"]))
    out.append({"id": cid, "title": "Emergency appendectomy", "tag": "Medical review",
                "blurb": "Deluxe room over the 1% room-rent cap triggers a proportionate deduction."})
    return out


SCENARIOS: list[dict] = []


def scenario_index() -> list[dict]:
    import json
    p = ASSET_DIR / "scenarios" / "index.json"
    return json.loads(p.read_text()) if p.exists() else []


def run(reset: bool = False) -> None:
    import json
    if reset:
        for p in (DB_PATH, Path(str(DB_PATH) + "-wal"), Path(str(DB_PATH) + "-shm"), CHECKPOINT_DB):
            if p.exists():
                p.unlink()
        if ASSET_DIR.exists():
            shutil.rmtree(ASSET_DIR)
    db.init_db()
    if not db.one("SELECT 1 FROM handlers LIMIT 1"):
        reference()
        history()
    idx = scenarios()
    (ASSET_DIR / "scenarios").mkdir(parents=True, exist_ok=True)
    (ASSET_DIR / "scenarios" / "index.json").write_text(json.dumps(idx, indent=2))
    n = db.one("SELECT COUNT(*) AS n FROM claims")["n"]
    print(f"Seeded {n} claims ({len(idx)} demo scenarios) into {DB_PATH}")


if __name__ == "__main__":
    run(reset="--reset" in sys.argv)
