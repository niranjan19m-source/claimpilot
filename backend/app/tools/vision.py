"""Damage-photo assessment with Claude vision: what is damaged, from which direction,
and whether the photos are consistent with the claimant's account."""
from __future__ import annotations

import base64
import io

from PIL import Image

from .. import db
from ..config import PRIMARY_MODEL, llm_enabled
from ..llm import json_call, strict_schema
from ..pii import Masker
from .base import ToolResult, signal

SCHEMA = strict_schema({
    "subject_visible": {"type": "boolean", "description": "Is the insured subject (vehicle) clearly visible?"},
    "damaged_areas": {"type": "array", "items": strict_schema({
        "area": {"type": "string"}, "severity": {"type": "string", "enum": ["minor", "moderate", "severe"]}})},
    "impact_direction": {"type": "string", "enum": ["front", "rear", "left", "right", "top", "underbody",
                                                     "multiple", "none_visible", "not_applicable"]},
    "overall_severity": {"type": "string", "enum": ["none", "minor", "moderate", "severe", "total_loss"]},
    "water_damage_visible": {"type": "boolean"},
    "consistent_with_account": {"type": "boolean"},
    "inconsistencies": {"type": "array", "items": {"type": "string"}},
    "old_damage_indicators": {"type": "array", "items": {"type": "string"},
                              "description": "Rust, dirt in cracks, faded paint at damage edges, etc."},
    "confidence": {"type": "number"},
    "observations": {"type": "string"},
})

SYSTEM = ("You are a motor claims damage assessor. Describe only what is visible in the photographs. "
          "Compare it to the claimant's account and point out specific inconsistencies (wrong side of impact, "
          "damage type that does not match the peril, signs the damage is older than the stated date). "
          "If the photos are illustrations, low quality or ambiguous, say so and lower your confidence. "
          "Never speculate about the claimant's intent.")


def _b64(path: str) -> tuple[str, str]:
    img = Image.open(path).convert("RGB")
    img.thumbnail((1280, 1280))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode(), "image/jpeg"


def assess_damage(claim: dict, masker: Masker) -> ToolResult:
    photos = db.query("SELECT filename, path FROM documents WHERE claim_id = ? AND kind = 'photo' LIMIT 4", (claim["id"],))
    if not photos:
        return ToolResult(True, "No photographs to assess.", {"assessed": False})
    if not llm_enabled():
        return ToolResult(False, "Vision assessment skipped (deterministic mode, no LLM).", {"assessed": False})
    content: list[dict] = []
    for p in photos:
        data, mt = _b64(p["path"])
        content.append({"type": "text", "text": f"Photo: {p['filename']}"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": mt, "data": data}})
    content.append({"type": "text", "text": masker.mask(
        f"Claim type: {claim.get('claim_type')}. Claimant's account: {claim.get('description')}")})
    try:
        out = json_call(content, SCHEMA, system=SYSTEM, model=PRIMARY_MODEL, effort="medium")
    except Exception as exc:
        return ToolResult(False, f"Vision assessment failed: {exc}", {"assessed": False})
    signals = []
    if not out["consistent_with_account"] and out["confidence"] >= 0.5:
        signals.append(signal("NARRATIVE_DAMAGE_MISMATCH", "Photos inconsistent with claimant's account", 18,
                              "; ".join(out["inconsistencies"][:3]) or out["observations"][:200]))
    if out["old_damage_indicators"] and out["confidence"] >= 0.5:
        signals.append(signal("OLD_DAMAGE", "Indicators of pre-existing damage", 12,
                              "; ".join(out["old_damage_indicators"][:3])))
    areas = ", ".join(f"{a['area']} ({a['severity']})" for a in out["damaged_areas"][:5]) or "none visible"
    return ToolResult(True, f"Vision: {out['overall_severity']} damage, impact {out['impact_direction']}: {areas}. "
                      f"{'Consistent' if out['consistent_with_account'] else 'INCONSISTENT'} with account "
                      f"(confidence {out['confidence']:.0%}).", {"assessed": True, **out}, signals)
