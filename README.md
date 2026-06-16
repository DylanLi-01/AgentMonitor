# Codex tmux Monitor

A local web dashboard for monitoring Codex agents running in tmux sessions.

It is designed for people who keep several agents open at the same time and
need a dense, glanceable view of what is working, done, idle, blocked, or asking
for input.

## Features

- Live tmux session discovery.
- Status detection for `error`, `needs_input`, `blocked`, `partial`, `done`,
  `working`, `idle`, and `unknown`.
- Compact dashboard for quick all-session monitoring.
- Detailed session list with live tail previews.
- Per-session archive, collapse, group, and display-name notes.
- Web input controls for sending text, Enter, and Ctrl-C to a selected session.
- Managed Mode with a dedicated Codex steward session for coordinating
  unarchived Codex agents conservatively.
- Local JSON metadata storage.
- Single-port production build served by FastAPI.
- Docker Compose and local script based startup.

## Quick Start

Recommended local install:

```bash
git clone <repo-url>
cd codex-tmux-monitor
./scripts/start.sh
```

Open:

```text
http://127.0.0.1:8765
```

The script installs backend dependencies into `backend/.venv`, installs frontend
dependencies with `npm ci`, builds the frontend, and starts FastAPI.

Requirements:

- Linux or macOS with tmux installed.
- Python 3.11+.
- Node.js 20+.
- npm.

## Docker Compose

Linux hosts can run:

```bash
./scripts/docker-up.sh
```

Open:

```text
http://127.0.0.1:8765
```

Docker access to host tmux is Linux-specific. The compose file runs the
container as your host UID/GID and mounts `/tmp/tmux-$UID` so the containerized
tmux client can connect to your host tmux server. If your tmux socket lives
elsewhere, use the local script or adjust `docker-compose.yml`.

## Development

```bash
./scripts/dev.sh
```

This starts:

- FastAPI backend at `http://127.0.0.1:8765`
- Vite frontend at `http://127.0.0.1:5173`

The Vite dev server proxies `/api` to the backend.

## Checks

Run all local checks:

```bash
./scripts/check.sh
```

Or use Make:

```bash
make check
```

Checks include backend unit tests, backend compile checks, frontend build, and a
high-severity npm audit.

## Configuration

Environment variables:

| Variable | Default | Description |
| --- | --- | --- |
| `HOST` | `127.0.0.1` | Host used by `scripts/start.sh`. |
| `PORT` | `8765` | Backend and production web port. |
| `PYTHON_BIN` | `python3` | Python executable for scripts. |
| `CODEX_MONITOR_DATA_DIR` | `backend/data` | Directory for runtime metadata. |
| `CODEX_MONITOR_METADATA_PATH` | unset | Exact metadata JSON path. Overrides `CODEX_MONITOR_DATA_DIR`. |
| `CODEX_MONITOR_MANAGED_MODE_PATH` | unset | Exact Managed Mode JSON state path. Overrides `CODEX_MONITOR_DATA_DIR` for this file. |
| `VITE_DEV_API_TARGET` | `http://localhost:8766` | Vite dev proxy target. `scripts/dev.sh` sets this automatically. |

Runtime metadata is stored in `session_metadata.json` and contains only UI
annotations:

- `archived`
- `collapsed`
- `group`
- `note`

Do not commit this file.

Managed Mode state is stored in `managed_mode.json`. When enabled, the backend
creates or reuses the `agentmonitor-steward` tmux session and sends it a
periodic brief of monitored targets. Monitored targets are unarchived tmux
sessions whose current pane command looks like the Codex TUI (`codex` or
`node`), excluding AgentMonitor-owned sessions. Archived sessions are never
included in the steward brief. Working and done sessions are included as
observe-only targets so the steward can report on them without interrupting
them. The dispatch interval can be adjusted from the web UI and is persisted in
the same state file. The API validates the interval as 30 to 3600 seconds; the
UI exposes whole-minute values from 1 to 60 minutes.

The steward prompt is intentionally conservative. It tells the steward to prefer
reviewing existing code, running focused tests, inspecting logs, reproducing
errors, debugging current results, and summarizing status. It explicitly avoids
broad implementations, rewrites, refactors, migrations, dependency upgrades,
pushes, and deployments unless the requested work is small, localized, already
requested by the user, and testable with existing checks.

When Managed Mode is ended from the web UI, the backend stops future dispatches
and asks the steward to write a final Chinese stewardship report. The steward
session is left running so the report remains visible in the dashboard.

## Codex Status Footer

The analyzer reads final machine-parseable status from an agent reply. It does
not infer `error`, `done`, `needs_input`, or similar states from arbitrary
output keywords.

```yaml
CODEX_STATUS:
  status: done
  summary: "Short outcome summary."
  needs_user: false
  next_action: "none"
```

JSON is also supported:

```json
{
  "CODEX_STATUS": {
    "status": "done",
    "summary": "Short outcome summary.",
    "needs_user": false,
    "next_action": "none"
  }
}
```

Supported status values:

- `done`
- `needs_input`
- `blocked`
- `error`
- `working`
- `partial`

If no structured status is present, the backend only uses tmux activity state:
changed output is `working`, no output change after the idle threshold is
`idle`, and otherwise the status is `unknown`.

## API

```text
GET   /api/health
GET   /api/sessions
GET   /api/sessions/{name}
PATCH /api/sessions/{name}/metadata
POST  /api/sessions/{name}/input
GET   /api/managed-mode
POST  /api/managed-mode
```

The input and Managed Mode endpoints can send keys to tmux sessions. Managed
Mode can also start and stop the `agentmonitor-steward` tmux session.

## Security

The dashboard displays tmux pane output. Pane output may contain secrets,
private prompts, local paths, or project context. The dashboard can also send
input to tmux sessions and, when Managed Mode is enabled, start a Codex steward
agent that can coordinate other unarchived Codex agents.

For local use, bind to `127.0.0.1`. If you expose the app over a network, put
authentication in front of it.

## Project Layout

```text
backend/
  app/
    main.py
    analyzer.py
    tmux_client.py
    metadata_store.py
    state_store.py
  tests/
frontend/
  src/
scripts/
Dockerfile
docker-compose.yml
Makefile
```

## License

MIT
