"""Shared test setup: isolated database, deterministic mode, seeded demo data."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TMP = ROOT / "tests" / ".tmp"
TMP.mkdir(exist_ok=True)
os.environ["CLAIMPILOT_DB"] = str(TMP / "test.db")
os.environ["CLAIMPILOT_CHECKPOINT_DB"] = str(TMP / "ckpt.db")
os.environ["CLAIMPILOT_OFFLINE"] = "1"
os.environ["CLAIMPILOT_ALLOW_NETWORK"] = os.environ.get("CLAIMPILOT_ALLOW_NETWORK", "1")
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session", autouse=True)
def seeded():
    from app import seed
    seed.run(reset=True)
    yield
