"""Document intake: text extraction, field parsing, and the required-documents checklist."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .. import db
from .base import ToolResult, inr, parse_date, signal

REQUIRED_DOCS: dict[str, dict[str, list[str]]] = {
    "motor": {
        "_default": ["claim_form", "photo", "driving_licence", "rc", "repair_estimate"],
        "theft": ["claim_form", "fir", "rc", "keys_declaration"],
        "windshield": ["claim_form", "photo", "rc"],
        "fire": ["claim_form", "photo", "rc", "fire_report"],
    },
    "health": {"_default": ["claim_form", "discharge_summary", "hospital_bill"]},
}
# Missing these blocks triage entirely; others are requested but don't block.
BLOCKING = {"fir", "discharge_summary", "hospital_bill"}

DOC_LABELS = {
    "claim_form": "Claim form", "photo": "Damage photographs", "driving_licence": "Driving licence",
    "rc": "Registration certificate", "repair_estimate": "Repair estimate", "fir": "Police FIR",
    "keys_declaration": "Keys declaration", "fire_report": "Fire brigade report",
    "discharge_summary": "Discharge summary", "hospital_bill": "Itemised hospital bill",
    "prescription": "Prescriptions", "other": "Other document",
}


def extract_text(path: str | Path) -> str:
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        try:
            return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
        except Exception as exc:  # corrupt/encrypted PDFs must not crash triage
            return f"[unreadable PDF: {exc}]"
    if p.suffix.lower() in {".txt", ".md"}:
        return p.read_text(errors="ignore")
    return ""


def classify(filename: str, text: str) -> str:
    f = f"{filename} {text[:400]}".lower()
    rules = [
        ("fir", ("first information report", "fir no", "fir_")), ("repair_estimate", ("estimate", "quotation")),
        ("discharge_summary", ("discharge summary",)), ("hospital_bill", ("final bill", "hospital bill", "bill_")),
        ("driving_licence", ("driving licence", "license", "licence")), ("rc", ("registration certificate", "rc_")),
        ("claim_form", ("claim form",)), ("fire_report", ("fire brigade", "fire station")),
        ("keys_declaration", ("keys declaration", "key declaration")), ("prescription", ("prescription", "rx")),
    ]
    for kind, keys in rules:
        if any(k in f for k in keys):
            return kind
    if Path(filename).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".heic"}:
        return "photo"
    return "other"


def _money(pattern: str, text: str) -> float | None:
    m = re.search(r"(?:" + pattern + r")[^\d\n]{0,20}([\d,]+(?:\.\d+)?)", text, re.I)
    return float(m.group(1).replace(",", "")) if m else None


def parse_fields(kind: str, text: str) -> dict[str, Any]:
    """Field extraction for the structured documents our partners send.
    In LLM mode the agent additionally reads the raw text, so this is the floor, not the ceiling."""
    out: dict[str, Any] = {}
    if kind == "repair_estimate":
        parts = []
        for m in re.finditer(r"^\s*-\s*(.+?)\s*\|\s*(metal|plastic|glass|rubber|fibre|battery|tyre)\s*\|\s*([\d,]+)", text, re.M | re.I):
            parts.append({"name": m.group(1).strip(), "material": m.group(2).lower(),
                          "cost": float(m.group(3).replace(",", ""))})
        out["parts"] = parts
        out["labour"] = _money(r"Labour(?: & Paint)?", text) or 0
        out["total"] = _money(r"Grand Total", text)
        g = re.search(r"Garage:\s*(.+)", text)
        out["garage"] = g.group(1).strip() if g else None
        d = re.search(r"Inspection Date:\s*([\d-]+)", text)
        out["inspection_date"] = d.group(1) if d else None
        out["impact_side"] = (re.search(r"Impact:\s*(\w+)", text, re.I) or [None, None])[1]
    elif kind == "hospital_bill":
        out["total"] = _money(r"Grand Total|Net Payable|Total Bill", text)
        out["room_rent_per_day"] = _money(r"Room Rent per Day", text)
        out["days"] = int(_money(r"Length of Stay", text) or 0)
        out["associated_charges"] = _money(r"Associated Charges", text) or 0
        out["icu"] = bool(re.search(r"Room Category:\s*ICU", text, re.I))
        h = re.search(r"Hospital:\s*(.+)", text)
        out["hospital"] = h.group(1).strip() if h else None
    elif kind == "discharge_summary":
        d = re.search(r"Diagnosis:\s*(.+)", text)
        out["diagnosis"] = d.group(1).strip() if d else None
        a = re.search(r"Date of Admission:\s*([\d-]+)", text)
        out["admission_date"] = a.group(1) if a else None
        h = re.search(r"History:\s*(.+)", text)
        out["history"] = h.group(1).strip() if h else None
        out["cause"] = "accident" if re.search(r"road traffic accident|RTA|fall|injury", text, re.I) else "illness"
    elif kind == "fir":
        n = re.search(r"FIR No\.?:\s*(\S+)", text)
        out["fir_no"] = n.group(1) if n else None
        d = re.search(r"Date of Occurrence:\s*([\d-]+)", text)
        out["occurrence_date"] = d.group(1) if d else None
        r = re.search(r"Date of Report:\s*([\d-]+)", text)
        out["report_date"] = r.group(1) if r else None
    elif kind == "driving_licence":
        v = re.search(r"Valid Till:\s*([\d-]+)", text)
        out["valid_till"] = v.group(1) if v else None
    return out


def review_documents(claim: dict) -> ToolResult:
    docs = db.query("SELECT id, kind, filename, extracted_text, meta FROM documents WHERE claim_id = ?", (claim["id"],))
    line = claim.get("line", "motor")
    req_map = REQUIRED_DOCS.get(line, {})
    required = req_map.get(claim.get("claim_type", ""), req_map.get("_default", []))
    present = {d["kind"] for d in docs}
    missing = [k for k in required if k not in present]
    blocking = [k for k in missing if k in BLOCKING]
    signals: list[dict] = []
    extracted: dict[str, Any] = {}
    for d in docs:
        if d["kind"] == "photo":
            continue
        fields = parse_fields(d["kind"], d["extracted_text"] or "")
        extracted[d["kind"]] = fields
        db.update("documents", "id", d["id"], {"meta": {**db.loads(d["meta"], {}), "fields": fields}})

    inc = parse_date(claim.get("incident_date"))
    amt = float(claim.get("amount_claimed") or 0)
    est = extracted.get("repair_estimate") or extracted.get("hospital_bill") or {}
    if est.get("total") and amt and abs(est["total"] - amt) / amt > 0.10:
        signals.append(signal("AMOUNT_MISMATCH", "Claimed amount differs from supporting bill", 12,
                              f"Claimed {inr(amt)} but document total is {inr(est['total'])}."))
    fir = extracted.get("fir") or {}
    if fir.get("occurrence_date") and inc and parse_date(fir["occurrence_date"]) != inc:
        signals.append(signal("FIR_DATE_MISMATCH", "FIR date of occurrence differs from claim", 18,
                              f"FIR says {fir['occurrence_date']}, claim says {inc}."))
    if fir.get("report_date") and inc:
        gap = (parse_date(fir["report_date"]) - inc).days
        if gap > 3:
            signals.append(signal("LATE_FIR", "FIR lodged late", 10, f"FIR lodged {gap} days after the loss."))
    dl = extracted.get("driving_licence") or {}
    if dl.get("valid_till") and inc and parse_date(dl["valid_till"]) < inc:
        signals.append(signal("LICENCE_EXPIRED", "Driving licence expired on loss date", 0,
                              f"Licence valid till {dl['valid_till']}.", "coverage"))
    ds = extracted.get("discharge_summary") or {}
    if ds.get("admission_date") and inc and parse_date(ds["admission_date"]) != inc:
        signals.append(signal("ADMISSION_DATE_MISMATCH", "Admission date differs from claim", 10,
                              f"Discharge summary admission {ds['admission_date']} vs claim {inc}."))

    summary = f"{len(docs)} documents on file."
    if missing:
        summary += " Missing: " + ", ".join(DOC_LABELS.get(m, m) for m in missing) + "."
        if blocking:
            summary += " Blocking: " + ", ".join(DOC_LABELS.get(m, m) for m in blocking) + "."
    else:
        summary += " Checklist complete."
    return ToolResult(True, summary, {
        "documents": [{"id": d["id"], "kind": d["kind"], "label": DOC_LABELS.get(d["kind"], d["kind"]),
                       "filename": d["filename"]} for d in docs],
        "required": required, "missing": missing, "blocking_missing": blocking,
        "missing_labels": [DOC_LABELS.get(m, m) for m in missing], "extracted": extracted,
    }, signals)


def read_document(claim_id: str, document_id: int) -> ToolResult:
    d = db.one("SELECT * FROM documents WHERE id = ? AND claim_id = ?", (document_id, claim_id))
    if not d:
        return ToolResult(False, f"Document {document_id} not found on this claim.")
    text = (d["extracted_text"] or "")[:6000]
    return ToolResult(True, f"{DOC_LABELS.get(d['kind'], d['kind'])} ({d['filename']}), {len(text)} chars.",
                      {"kind": d["kind"], "filename": d["filename"], "text": text})
