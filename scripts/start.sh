#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8765}"
DATA_DIR="${CODEX_MONITOR_DATA_DIR:-$ROOT_DIR/backend/data}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Missing Python interpreter: $PYTHON_BIN" >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "Missing npm. Install Node.js 20+ before running this script." >&2
  exit 1
fi

if ! command -v tmux >/dev/null 2>&1; then
  echo "Warning: tmux is not installed or not on PATH. The dashboard will start but show no sessions." >&2
fi

mkdir -p "$DATA_DIR"

cd "$ROOT_DIR/backend"
if [ ! -d .venv ]; then
  "$PYTHON_BIN" -m venv .venv
fi

# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

cd "$ROOT_DIR/frontend"
npm ci
npm run build

export CODEX_MONITOR_DATA_DIR="$DATA_DIR"

cd "$ROOT_DIR/backend"
echo "Codex tmux Monitor: http://$HOST:$PORT"
exec uvicorn app.main:app --host "$HOST" --port "$PORT"
