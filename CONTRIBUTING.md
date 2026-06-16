# Contributing

Thanks for working on Codex tmux Monitor.

## Development

```bash
./scripts/dev.sh
```

The frontend runs through Vite and proxies `/api` to the local FastAPI backend.

## Checks

Run the same checks used by CI:

```bash
./scripts/check.sh
```

This runs backend unit tests, compiles backend modules, builds the frontend, and
runs a high-severity npm audit.

## Pull Requests

- Keep UI changes compact and operational rather than marketing-oriented.
- Do not commit local runtime state from `backend/data/`.
- Add focused tests for analyzer and state-store behavior changes.
- Document new environment variables or deployment assumptions in `README.md`.
