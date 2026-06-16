#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
  {
    echo "HOST_UID=$(id -u)"
    echo "HOST_GID=$(id -g)"
    echo "PORT=8765"
  } > "$ENV_FILE"
  echo "Created $ENV_FILE for Docker Compose user and port settings."
fi

TMUX_SOCKET_DIR="/tmp/tmux-$(id -u)"
if [ ! -d "$TMUX_SOCKET_DIR" ]; then
  echo "Warning: $TMUX_SOCKET_DIR does not exist." >&2
  echo "Start a tmux session first if you want the container to see host sessions." >&2
fi

cd "$ROOT_DIR"
docker compose up --build
