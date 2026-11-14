"""Runtime configuration. Everything is overridable through environment variables."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
POLICY_DIR = DATA_DIR / "policies"
ASSET_DIR = DATA_DIR / "assets"
UPLOAD_DIR = Path(os.getenv("CLAIMPILOT_UPLOAD_DIR", DATA_DIR / "uploads"))
DB_PATH = Path(os.getenv("CLAIMPILOT_DB", DATA_DIR / "claimpilot.db"))
CHECKPOINT_DB = Path(os.getenv("CLAIMPILOT_CHECKPOINT_DB", DATA_DIR / "checkpoints.db"))
WEATHER_CACHE = DATA_DIR / "weather_cache.json"

# Models. The primary model plans, investigates and reasons; the fast model does
# extraction and drafting where depth matters less than latency.
PRIMARY_MODEL = os.getenv("CLAIMPILOT_MODEL", "claude-opus-5-5")
FAST_MODEL = os.getenv("CLAIMPILOT_FAST_MODEL", "claude-haiku-5-5")
EFFORT = os.getenv("CLAIMPILOT_EFFORT", "medium")

# Hard ceilings so a misbehaving loop can never run away during a live demo.
MAX_TOOL_CALLS = int(os.getenv("CLAIMPILOT_MAX_TOOL_CALLS", "18"))
MAX_VERIFY_LOOPS = int(os.getenv("CLAIMPILOT_MAX_VERIFY_LOOPS", "2"))

# Seconds to pause after each tool in deterministic mode so a live audience can follow
# the trace. 0 for tests/evals; the demo start script sets it.
DEMO_PACE = float(os.getenv("CLAIMPILOT_PACE", "0"))

# Allow external HTTP (Open-Meteo, Nominatim). Cached results are always used first.
ALLOW_NETWORK = os.getenv("CLAIMPILOT_ALLOW_NETWORK", "1") == "1"
HTTP_USER_AGENT = "ClaimPilot-hackathon-demo/1.0"

# "Today" for the synthetic book of business. Pinned so the demo is reproducible.
AS_OF_DATE = os.getenv("CLAIMPILOT_AS_OF", "2026-11-13")


def llm_enabled() -> bool:
    """LLM mode is on when credentials exist and offline mode isn't forced."""
    if os.getenv("CLAIMPILOT_OFFLINE") == "1":
        return False
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


for _d in (UPLOAD_DIR,):
    _d.mkdir(parents=True, exist_ok=True)
