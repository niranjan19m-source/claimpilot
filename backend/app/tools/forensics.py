"""Image forensics: EXIF capture time & GPS vs. the stated loss, and perceptual-hash
matching against every photo previously submitted on any claim."""
from __future__ import annotations

import hashlib
import math
import os
from typing import Any

import imagehash
from PIL import Image

from .. import db
from .base import ToolResult, parse_date, signal

EXIF_IFD, GPS_IFD = 0x8769, 0x8825
DATETIME_ORIGINAL, SOFTWARE = 36867, 305
EDITORS = ("photoshop", "gimp", "snapseed", "picsart", "lightroom", "canva")


def _dms(v: Any) -> float:
    d, m, s = (float(x) for x in v)
    return d + m / 60 + s / 3600


def read_exif(path: str) -> dict[str, Any]:
    try:
        img = Image.open(path)
        ex = img.getexif()
    except Exception:
        return {}
    out: dict[str, Any] = {"software": ex.get(SOFTWARE), "format": img.format, "dimensions": f"{img.width}×{img.height}",
                           "camera": " ".join(str(v) for v in (ex.get(271), ex.get(272)) if v) or None}
    dt = ex.get_ifd(EXIF_IFD).get(DATETIME_ORIGINAL) or ex.get(306)
    if dt:
        out["taken_at"] = str(dt)
    gps = ex.get_ifd(GPS_IFD)
    try:
        if gps and 2 in gps and 4 in gps:
            lat, lon = _dms(gps[2]), _dms(gps[4])
            out["lat"] = -lat if gps.get(1) == "S" else lat
            out["lon"] = -lon if gps.get(3) == "W" else lon
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    return out


def phash(path: str) -> str | None:
    try:
        return str(imagehash.phash(Image.open(path)))
    except Exception:
        return None


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def analyse_photos(claim: dict, policy_start: str | None = None) -> ToolResult:
    photos = db.query("SELECT id, filename, path FROM documents WHERE claim_id = ? AND kind = 'photo'", (claim["id"],))
    if not photos:
        return ToolResult(True, "No photographs on file to analyse.", {"photos": []})
    inc = parse_date(claim.get("incident_date"))
    start = parse_date(policy_start)
    loc = (claim.get("lat"), claim.get("lon"))
    others = db.query("SELECT claim_id, filename, phash FROM image_hashes WHERE claim_id != ?", (claim["id"],))
    results, signals = [], []
    for p in photos:
        meta = read_exif(p["path"])
        h = phash(p["path"])
        try:
            raw = open(p["path"], "rb").read()
            meta["bytes"] = os.path.getsize(p["path"])
            meta["sha256"] = hashlib.sha256(raw).hexdigest()
        except OSError:
            pass
        meta["exif_status"] = "present" if meta.get("taken_at") else "missing"
        row: dict[str, Any] = {"filename": p["filename"], "document_id": p["id"], **meta, "phash": h, "flags": []}
        taken = parse_date(meta.get("taken_at"))
        if taken and inc:
            row["days_from_incident"] = (taken - inc).days
            if taken < inc:
                row["flags"].append("taken_before_incident")
                signals.append(signal("EXIF_PREDATES_LOSS", "Photo captured before the stated loss date", 28,
                                      f"{p['filename']} EXIF date {taken} precedes loss date {inc}."))
            if start and taken < start:
                row["flags"].append("taken_before_policy")
                signals.append(signal("EXIF_PREDATES_POLICY", "Photo captured before the policy existed", 30,
                                      f"{p['filename']} EXIF date {taken} precedes policy start {start} — "
                                      "pre-existing damage indicator."))
        if meta.get("lat") is not None and loc[0] is not None:
            km = haversine_km((meta["lat"], meta["lon"]), (float(loc[0]), float(loc[1])))
            row["km_from_incident"] = round(km, 1)
            if km > 25:
                row["flags"].append("gps_far_from_incident")
                signals.append(signal("EXIF_GPS_MISMATCH", "Photo location far from the stated loss location", 16,
                                      f"{p['filename']} was taken {km:.0f} km from the reported loss location."))
        sw = (meta.get("software") or "").lower()
        if any(e in sw for e in EDITORS):
            row["flags"].append("edited")
            signals.append(signal("IMAGE_EDITED", "Photo processed in editing software", 12,
                                  f"{p['filename']} EXIF software tag: {meta['software']}."))
        if h:
            hv = imagehash.hex_to_hash(h)
            for o in others:
                if o["phash"] and hv - imagehash.hex_to_hash(o["phash"]) <= 6:
                    row["flags"].append(f"duplicate_of:{o['claim_id']}")
                    signals.append(signal("DUPLICATE_IMAGE", "Same photo was submitted on a previous claim", 35,
                                          f"{p['filename']} matches {o['filename']} on claim {o['claim_id']} "
                                          f"(perceptual-hash distance {hv - imagehash.hex_to_hash(o['phash'])})."))
                    break
        results.append(row)
    flagged = sum(1 for r in results if r["flags"])
    summary = f"Analysed {len(results)} photos; {flagged} with forensic flags." if flagged else \
        f"Analysed {len(results)} photos; capture metadata consistent with the stated loss."
    # dedupe identical signals
    seen, uniq = set(), []
    for s in signals:
        if (s["code"], s["detail"]) not in seen:
            seen.add((s["code"], s["detail"]))
            uniq.append(s)
    return ToolResult(True, summary, {"photos": results}, uniq)


def register_hashes(claim_id: str) -> None:
    """Called once a claim is triaged, so future claims can be matched against it."""
    for p in db.query("SELECT filename, path FROM documents WHERE claim_id = ? AND kind = 'photo'", (claim_id,)):
        h = phash(p["path"])
        if h and not db.one("SELECT 1 FROM image_hashes WHERE claim_id = ? AND filename = ?", (claim_id, p["filename"])):
            db.insert("image_hashes", {"claim_id": claim_id, "filename": p["filename"], "phash": h})
