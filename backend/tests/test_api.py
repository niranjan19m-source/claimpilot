"""API tests for the dashboard contract: status, evidence, audit, analytics, policy
library, and every human-decision path (resume, request documents, reroute)."""
import time

from fastapi.testclient import TestClient

from app import db
from app.agent import runner
from app.main import app

client = TestClient(app)


def wait(cid, statuses, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = db.one("SELECT status FROM claims WHERE id = ?", (cid,))["status"]
        if s in statuses and not runner.is_running(cid):
            return s
        time.sleep(0.1)
    raise AssertionError(f"{cid} stuck in {s}")


def test_status_is_honest_about_unconfigured_services():
    s = client.get("/api/status").json()
    assert s["agent"]["mode"] == "deterministic"
    assert s["services"]["llm_provider"]["state"] == "not_configured"
    assert s["services"]["reverse_image_search"]["state"] == "not_configured"
    assert s["services"]["vehicle_registry"]["state"] == "mock"
    assert s["data"]["source"] == "synthetic"


def test_settings_never_return_secrets():
    body = client.get("/api/settings").text
    assert "sk-ant" not in body and "anthropic_key_configured" in body


def test_human_decision_validation():
    r = client.post("/api/claims/CLM-2611-1002/decision", json={"decision": "override", "queue": "standard"})
    assert r.status_code == 400  # reason required
    r = client.post("/api/claims/CLM-2611-1002/decision", json={"decision": "delete_claim"})
    assert r.status_code == 422


def test_override_while_paused_is_persisted_with_original_recommendation():
    client.post("/api/claims/CLM-2611-1002/run")
    assert wait("CLM-2611-1002", {"awaiting_review"}) == "awaiting_review"
    r = client.post("/api/claims/CLM-2611-1002/decision", json={
        "decision": "override", "queue": "standard", "reason": "Rain gauge 2 km away logged 40 mm", "reviewer": "QA Lead"})
    assert r.json()["mode"] == "resumed_agent"
    assert wait("CLM-2611-1002", {"assigned"}) == "assigned"
    d = client.get("/api/decisions?claim_id=CLM-2611-1002").json()[0]
    assert (d["original_queue"], d["new_queue"], d["decision"], d["reviewer"]) == ("siu", "standard", "override", "QA Lead")
    audit = client.get("/api/audit?claim_id=CLM-2611-1002&category=human").json()
    assert any("override" in a["text"].lower() for a in audit)


def test_reviewer_can_request_documents_then_agent_replans():
    client.post("/api/claims/CLM-2611-1004/run")
    assert wait("CLM-2611-1004", {"awaiting_review"}) == "awaiting_review"
    client.post("/api/claims/CLM-2611-1004/decision", json={
        "decision": "request_documents", "documents": ["Orthopaedic consultation notes from 2025"]})
    assert wait("CLM-2611-1004", {"awaiting_documents"}) == "awaiting_documents"
    files = {"files": ("ortho_notes.txt", b"Orthopaedic notes: knee pain began 2026.", "text/plain")}
    assert client.post("/api/claims/CLM-2611-1004/documents", files=files).json()["resumed"] is True
    assert wait("CLM-2611-1004", {"awaiting_review"}) == "awaiting_review"  # re-planned, still a denial


def test_post_assignment_reroute_creates_new_ticket():
    client.post("/api/claims/CLM-2611-1006/run")
    assert wait("CLM-2611-1006", {"assigned"}) == "assigned"
    r = client.post("/api/claims/CLM-2611-1006/decision", json={
        "decision": "further_investigation", "reason": "Rider's hospital differs from police report"})
    assert r.json()["mode"] == "rerouted"
    c = client.get("/api/claims/CLM-2611-1006").json()
    assert c["claim"]["route"] == "siu"
    assert [t["status"] for t in c["tickets"]].count("open") == 1


def test_evidence_index_and_analytics():
    ev = client.get("/api/evidence?claim_id=CLM-2611-1002").json()
    assert ev and all({"evidence_id", "category", "status", "summary"} <= set(e) for e in ev)
    assert any(e["status"] == "contradictory" and e["category"] == "weather" for e in ev)
    an = client.get("/api/analytics").json()
    assert an["scope"]["triaged"] >= 2 and an["routes"]


def test_forensic_metadata_includes_hash_and_format():
    f = client.get("/api/claims/CLM-2611-1002/forensics").json()["photo_forensics"]
    p = f["data"]["photos"][0]
    assert len(p["sha256"]) == 64 and p["format"] == "JPEG" and p["exif_status"] == "present"


def test_policy_library_search_and_upload():
    lib = client.get("/api/policy-library?q=flood engine water").json()
    assert lib["clauses"][0]["id"] in ("M-4.5", "M-2.4", "M-5.2")
    exc = client.get("/api/policy-library?kind=exclusion").json()["clauses"]
    assert exc and all(c["kind"] == "exclusion" for c in exc)
    up = client.post("/api/policy-library", files={"file": ("p.md", b"### 1.1 Cover\ntext\n### 1.2 Exclusion - war\ntext", "text/markdown")})
    assert up.json()["clauses"] == 2
    bad = client.post("/api/policy-library", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert bad.status_code == 400
