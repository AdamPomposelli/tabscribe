#!/usr/bin/env bash
# Start Tabscribe locally: http://127.0.0.1:8765
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3.11 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi
if [ ! -d frontend/dist ] || [ "${REBUILD:-0}" = "1" ]; then
  (cd frontend && npm install --silent && npm run build)
fi
command -v ffmpeg >/dev/null || { echo "ffmpeg is required (brew install ffmpeg)"; exit 1; }
echo "Tabscribe → http://127.0.0.1:8765"
exec .venv/bin/python -m uvicorn tabscribe.server:app --app-dir backend --host 127.0.0.1 --port 8765
