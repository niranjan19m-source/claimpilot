#!/usr/bin/env bash
# Rebuild the hosted read-only demo (GitHub Pages, served from docs/).
# 1. Records a fresh real run of every demo scenario through the agent.
# 2. Builds the dashboard as a static site that replays that recording.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/backend"
CLAIMPILOT_DB="$PWD/data/snapshot.db" CLAIMPILOT_CHECKPOINT_DB="$PWD/data/snapshot_ckpt.db" \
  .venv/bin/python -m scripts.export_snapshot ../frontend/public/snapshot
cd "$ROOT/frontend"
rm -rf .next out
NEXT_PUBLIC_SNAPSHOT=1 NEXT_PUBLIC_BASE_PATH=/claimpilot npx next build
cp -R out/. "$ROOT/docs/"
touch "$ROOT/docs/.nojekyll"
rm -rf .next   # so the next local `./start.sh` rebuilds the live (non-snapshot) app
echo "Hosted demo rebuilt in docs/. Commit and push to publish."
