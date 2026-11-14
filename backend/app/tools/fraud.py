"""Fraud analytics: claims history, entity-link network, unsupervised anomaly model,
and the explainable score aggregation."""
from __future__ import annotations

import math
import threading
from datetime import timedelta
from typing import Any

import networkx as nx
import numpy as np
from sklearn.ensemble import IsolationForest

from .. import db
from ..config import AS_OF_DATE
from .base import ToolResult, inr, parse_date, signal

_model_lock = threading.Lock()
_models: dict[str, tuple[IsolationForest, np.ndarray]] = {}


# ------------------------------------------------------------------ history
def claims_history(claim: dict) -> ToolResult:
    inc = parse_date(claim.get("incident_date")) or parse_date(AS_OF_DATE)
    rows = db.query(
        "SELECT id, policy_no, claim_type, incident_date, amount_claimed, outcome, status FROM claims "
        "WHERE customer_id = ? AND id != ? ORDER BY incident_date DESC",
        (claim.get("customer_id"), claim["id"]))
    recent = [r for r in rows if parse_date(r["incident_date"]) and (inc - parse_date(r["incident_date"])).days <= 365]
    signals = []
    if len(recent) >= 2:
        signals.append(signal("FREQUENT_CLAIMANT", "Frequent claimant", 8 + 4 * min(len(recent) - 2, 3),
                              f"{len(recent)} other claims in the 12 months before this loss."))
    bad = [r for r in rows if r["outcome"] in ("fraud_confirmed", "repudiated_fraud")]
    if bad:
        signals.append(signal("PRIOR_FRAUD", "Claimant has a prior claim repudiated for fraud", 30,
                              f"Claim {bad[0]['id']} ({bad[0]['incident_date']}) was repudiated for fraud."))
    total = sum(r["amount_claimed"] or 0 for r in recent)
    return ToolResult(True, f"{len(rows)} prior claims ({len(recent)} in last 12 months, {inr(total)}).",
                      {"prior_claims": rows[:10], "count_12m": len(recent), "amount_12m": total}, signals)


# ------------------------------------------------------------------ network
def _entities(c: dict) -> list[tuple[str, str]]:
    out = [("person", c["customer_id"])] if c.get("customer_id") else []
    if c.get("contact_phone"):
        out.append(("phone", c["contact_phone"].replace(" ", "")[-10:]))
    if c.get("bank_account"):
        out.append(("bank", c["bank_account"]))
    if c.get("garage_id"):
        out.append(("garage", c["garage_id"]))
    if c.get("hospital_id"):
        out.append(("hospital", c["hospital_id"]))
    return out


def network_analysis(claim: dict) -> ToolResult:
    rows = db.query("SELECT id, customer_id, contact_phone, bank_account, garage_id, hospital_id, incident_date, "
                    "amount_claimed, outcome, claim_type FROM claims WHERE status != 'draft'")
    rows = [r for r in rows if r["id"] != claim["id"]] + [claim]
    g = nx.Graph()
    for r in rows:
        g.add_node(f"claim:{r['id']}", kind="claim", outcome=r.get("outcome"), amount=r.get("amount_claimed"),
                   date=r.get("incident_date"))
        for kind, val in _entities(r):
            g.add_node(f"{kind}:{val}", kind=kind)
            g.add_edge(f"claim:{r['id']}", f"{kind}:{val}")
    me = f"claim:{claim['id']}"
    # Hubs (a network garage serving hundreds of honest claims) would connect everything;
    # traverse only through "personal" identifiers, then report hub stats separately.
    personal = [n for n in g.nodes if g.nodes[n]["kind"] in ("person", "phone", "bank")]
    sub = g.subgraph([n for n in g.nodes if g.nodes[n]["kind"] == "claim"] + personal)
    ring = nx.node_connected_component(sub, me)
    ring_claims = [n for n in ring if n.startswith("claim:") and n != me]
    persons = {n for n in ring if n.startswith("person:")}
    signals: list[dict] = []
    shared = []
    for kind, val in _entities(claim):
        node = f"{kind}:{val}"
        if kind in ("phone", "bank"):
            owners = {p for c in g.neighbors(node) for p in g.neighbors(c) if p.startswith("person:")}
            owners.discard(f"person:{claim.get('customer_id')}")
            if owners:
                shared.append({"kind": kind, "value": val, "other_claimants": len(owners)})
    if shared:
        s = shared[0]
        signals.append(signal("SHARED_IDENTIFIER", f"{s['kind'].title()} shared with other claimants", 22,
                              f"This claim's {s['kind']} appears on claims by {s['other_claimants']} other "
                              f"claimant(s)."))
    confirmed = [n for n in ring_claims if g.nodes[n].get("outcome") in ("fraud_confirmed", "repudiated_fraud")]
    if confirmed:
        signals.append(signal("FRAUD_RING_LINK", "Linked to a cluster with confirmed fraud", 25,
                              f"Connected through shared identifiers to {len(ring_claims)} claims across "
                              f"{len(persons)} people; {len(confirmed)} were repudiated for fraud."))
    hubs = []
    inc = parse_date(claim.get("incident_date")) or parse_date(AS_OF_DATE)
    for kind in ("garage", "hospital"):
        ent = claim.get(f"{kind}_id")
        if not ent:
            continue
        node = f"{kind}:{ent}"
        linked = [n for n in g.neighbors(node) if n != me]
        recent = [n for n in linked if parse_date(g.nodes[n].get("date"))
                  and timedelta(0) <= inc - parse_date(g.nodes[n]["date"]) <= timedelta(days=90)]
        flagged = [n for n in linked if g.nodes[n].get("outcome") in ("fraud_confirmed", "repudiated_fraud")]
        meta = db.one(f"SELECT * FROM {kind}s WHERE id = ?", (ent,)) or {}
        hubs.append({"kind": kind, "id": ent, "name": meta.get("name"), "claims_total": len(linked),
                     "claims_90d": len(recent), "fraud_linked": len(flagged),
                     "network": bool(meta.get("network")), "flagged": bool(meta.get("flagged"))})
        if len(flagged) >= 2:
            signals.append(signal(f"{kind.upper()}_HOTSPOT", f"{kind.title()} linked to repeated fraud", 18,
                                  f"{meta.get('name', ent)} appears on {len(flagged)} fraud-repudiated claims "
                                  f"and {len(recent)} claims in the last 90 days."))
        if meta.get("flagged"):
            signals.append(signal(f"{kind.upper()}_WATCHLIST", f"{kind.title()} on the insurer's watch-list", 15,
                                  f"{meta.get('name', ent)} is on the exclusion/watch-list."))

    # Visual subgraph: ring + hub neighbours (capped) for the UI.
    keep = set(ring)
    for h in hubs:
        node = f"{h['kind']}:{h['id']}"
        keep.add(node)
        flagged_first = sorted(g.neighbors(node), key=lambda n: g.nodes[n].get("outcome") is None)
        keep.update(flagged_first[:12])
    nodes = [{"id": n, "kind": g.nodes[n]["kind"], "label": n.split(":", 1)[1], "self": n == me,
              "outcome": g.nodes[n].get("outcome")} for n in list(keep)[:80]]
    ids = {n["id"] for n in nodes}
    edges = [{"source": a, "target": b} for a, b in g.edges(ids) if a in ids and b in ids]
    summary = (f"Linked cluster: {len(ring_claims)} other claims, {len(persons)} people"
               + (f", {len(confirmed)} fraud-repudiated" if confirmed else "") + ". "
               + " ".join(f"{h['name']}: {h['claims_90d']} claims in 90d"
                          + (f", {h['fraud_linked']} fraud-linked" if h['fraud_linked'] else "") + "."
                          for h in hubs))
    return ToolResult(True, summary, {"cluster_claims": len(ring_claims), "cluster_people": len(persons),
                                      "confirmed_fraud": len(confirmed), "shared": shared, "hubs": hubs,
                                      "graph": {"nodes": nodes, "edges": edges}}, signals)


# ------------------------------------------------------------------ anomaly model
def _features(c: dict) -> list[float]:
    pol = db.one("SELECT start_date, sum_insured, details FROM policies WHERE policy_no = ?", (c["policy_no"],)) or {}
    d = db.loads(pol.get("details"), {})
    cap = float(d.get("idv") or pol.get("sum_insured") or 1)
    inc, start = parse_date(c.get("incident_date")), parse_date(pol.get("start_date"))
    rep = parse_date(c.get("reported_date")) or inc
    hour = int((c.get("incident_time") or "12:00").split(":")[0] or 12)
    return [math.log1p(float(c.get("amount_claimed") or 0)), float(c.get("amount_claimed") or 0) / cap,
            math.log1p(max(0, (inc - start).days if inc and start else 365)),
            float(max(0, (rep - inc).days if rep and inc else 0)), 1.0 if hour < 5 or hour >= 23 else 0.0]


def _model(line: str) -> tuple[IsolationForest, np.ndarray] | None:
    with _model_lock:
        if line in _models:
            return _models[line]
        rows = db.query("SELECT * FROM claims WHERE historical = 1 AND line = ? AND "
                        "(outcome IS NULL OR outcome NOT IN ('fraud_confirmed','repudiated_fraud'))", (line,))
        if len(rows) < 30:
            return None
        x = np.array([_features(r) for r in rows])
        m = IsolationForest(n_estimators=200, contamination="auto", random_state=7).fit(x)
        _models[line] = (m, np.sort(m.score_samples(x)))
        return _models[line]


def anomaly_score(claim: dict) -> ToolResult:
    pack = _model(claim.get("line", "motor"))
    if not pack:
        return ToolResult(False, "Anomaly model unavailable (insufficient history).")
    m, ref = pack
    f = _features(claim)
    s = float(m.score_samples(np.array([f]))[0])
    pct = round(float(100 * (1 - np.searchsorted(ref, s) / len(ref))), 1)  # % of normal claims less anomalous
    names = ["log_amount", "amount_to_cover_ratio", "log_days_since_inception", "report_delay_days", "night_incident"]
    signals = []
    if pct >= 97:
        signals.append(signal("ANOMALY", "Statistical outlier vs. historical genuine claims", 14,
                              f"More anomalous than {pct}% of genuine {claim.get('line')} claims (Isolation Forest)."))
    elif pct >= 90:
        signals.append(signal("ANOMALY", "Unusual claim profile", 7,
                              f"More anomalous than {pct}% of genuine {claim.get('line')} claims (Isolation Forest)."))
    return ToolResult(True, f"Anomaly percentile {pct} (higher = more unusual).",
                      {"percentile": pct, "features": dict(zip(names, [round(v, 3) for v in f]))}, signals)


# ------------------------------------------------------------------ aggregation
def aggregate(signals: list[dict[str, Any]]) -> dict[str, Any]:
    """Noisy-OR: independent red flags compound, but the score saturates below 100
    and no single weak flag can dominate. Every point is traceable to a flag."""
    best: dict[str, dict] = {}
    for s in signals:
        if s.get("kind", "fraud") != "fraud" or s.get("weight", 0) <= 0:
            continue
        if s["code"] not in best or s["weight"] > best[s["code"]]["weight"]:
            best[s["code"]] = s
    p = 1.0
    for s in best.values():
        p *= 1 - min(s["weight"], 95) / 100
    score = round(100 * (1 - p))
    band = "high" if score >= 60 else "medium" if score >= 30 else "low"
    contrib = sorted(best.values(), key=lambda s: -s["weight"])
    return {"score": score, "band": band, "signals": contrib}
