#!/usr/bin/env bash
# ClaimPilot: one-command local start.
#   ./start.sh            start (keeps existing data)
#   ./start.sh --reset    rebuild the synthetic database and demo scenarios first
# Set ANTHROPIC_API_KEY for the full LLM agent; without it the agent runs in deterministic mode.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-$(command -v python3.13 || command -v python3.14 || command -v python3.12 || command -v python3)}"

cd "$ROOT/backend"
if [ ! -d .venv ]; then
  echo "→ Creating Python environment"
  "$PY" -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi
if [ "${1:-}" = "--reset" ] || [ ! -f data/claimpilot.db ]; then
  echo "→ Seeding synthetic book of business"
  rm -f data/checkpoints.db
  .venv/bin/python -m app.seed --reset
fi

cd "$ROOT/frontend"
[ -d node_modules ] || npm install
[ -d .next ] || npx next build

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then echo "→ Mode: LLM agent"; else echo "→ Mode: deterministic (no ANTHROPIC_API_KEY)"; fi
cd "$ROOT/backend"
CLAIMPILOT_PACE="${CLAIMPILOT_PACE:-0.45}" .venv/bin/uvicorn app.main:app --port 8000 &
API_PID=$!
cd "$ROOT/frontend"
npx next start -p 3000 &
WEB_PID=$!
trap 'kill $API_PID $WEB_PID 2>/dev/null' EXIT INT TERM
echo "→ ClaimPilot running at http://localhost:3000  (API http://localhost:8000/docs)"
wait
