#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR/backend"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install -r requirements.txt
PYTHONPATH=. python -m unittest discover -s tests
python -m compileall app

cd "$ROOT_DIR/frontend"
npm ci
npm run build
npm audit --audit-level=high
