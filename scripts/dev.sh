#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
BACKEND_PORT="${BACKEND_PORT:-8765}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
DATA_DIR="${CODEX_MONITOR_DATA_DIR:-$ROOT_DIR/backend/data}"

cleanup() {
  jobs -p | xargs -r kill
}
trap cleanup EXIT INT TERM

mkdir -p "$DATA_DIR"

cd "$ROOT_DIR/backend"
if [ ! -d .venv ]; then
  "$PYTHON_BIN" -m venv .venv
fi

# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install -r requirements.txt
CODEX_MONITOR_DATA_DIR="$DATA_DIR" uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" --reload &

cd "$ROOT_DIR/frontend"
npm ci
VITE_DEV_API_TARGET="http://127.0.0.1:$BACKEND_PORT" npm run dev -- --port "$FRONTEND_PORT" &

echo "Frontend: http://127.0.0.1:$FRONTEND_PORT"
echo "Backend:  http://127.0.0.1:$BACKEND_PORT"
wait
