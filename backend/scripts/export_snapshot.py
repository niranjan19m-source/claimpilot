"""Record a real backend run as a static snapshot for the hosted read-only demo.

Runs every demo scenario through the actual agent graph (deterministic mode),
then saves each GET response the dashboard uses, plus every claim's event log and
documents, as static files the frontend can read without a server.

    python -m scripts.export_snapshot <output_dir>
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("CLAIMPILOT_OFFLINE", "1")
os.environ.setdefault("CLAIMPILOT_PACE", "0.35")  # realistic gaps between recorded events

from fastapi.testclient import TestClient  # noqa: E402

from app import db, seed  # noqa: E402
from app.agent import runner  # noqa: E402
from app.main import app  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "snapshot").resolve()
DEMO_IDS = [f"CLM-2611-100{i}" for i in range(1, 9)]


def name(path: str) -> str:
    return path.removeprefix("/api/").replace("/", "__") + ".json"


def main() -> None:
    seed.run(reset=True)
    for cid in DEMO_IDS:
        runner.run_sync(cid)
        print(f"  ran {cid}: {db.one('SELECT status, route FROM claims WHERE id = ?', (cid,))}")

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "files").mkdir(parents=True)
    client = TestClient(app)

    def save(path: str, transform=None) -> dict | list:
        r = client.get(path)
        r.raise_for_status()
        data = r.json()
        if transform:
            data = transform(data)
        (OUT / name(path)).write_text(json.dumps(data, default=str))
        return data

    for p in ("/api/health", "/api/settings", "/api/stats", "/api/scenarios", "/api/claims", "/api/decisions",
              "/api/evidence", "/api/audit", "/api/analytics", "/api/policy-library", "/api/handlers", "/api/evals"):
        save(p)

    def status_note(s: dict) -> dict:
        s["data"]["detail"] = ("Read-only snapshot of a real backend run (deterministic mode) on synthetic demo data. "
                               "Actions are disabled in the hosted demo")
        s["snapshot"] = True
        return s
    save("/api/status", status_note)

    for c in client.get("/api/claims").json():
        cid = c["id"]
        save(f"/api/claims/{cid}")
        save(f"/api/claims/{cid}/events")
        save(f"/api/claims/{cid}/forensics")
        save(f"/api/policies/{c['policy_no']}")
        for d in db.query("SELECT id, filename, path FROM documents WHERE claim_id = ?", (cid,)):
            src = Path(d["path"])
            if src.exists():
                shutil.copy(src, OUT / "files" / f"{d['id']}{src.suffix.lower()}")
    # Documents on historical claims referenced by forensics (e.g. the recycled photo's original).
    print(f"Snapshot written to {OUT} ({sum(1 for _ in OUT.rglob('*'))} files)")


if __name__ == "__main__":
    main()
