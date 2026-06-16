# Security

Codex tmux Monitor reads local tmux pane output and exposes it through an HTTP
dashboard. That pane output may contain secrets, paths, prompts, or private
project context.

## Recommendations

- Bind to `127.0.0.1` for local use.
- Put authentication in front of the service before exposing it on a network.
- Do not publish screenshots or logs without reviewing pane output.
- Treat `backend/data/session_metadata.json` as local runtime state.

## Reporting

If this repository is published on GitHub, use private vulnerability reporting
if enabled. Otherwise, contact the repository owner directly.
