from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .analyzer import analyze_session
from .managed_mode import ManagedModeController, ManagedModeError, ManagedModeStore
from .metadata_store import MetadataStore
from .models import (
    STATUS_PRIORITY,
    HealthResponse,
    ManagedModePatch,
    ManagedModeStatus,
    SessionInputRequest,
    SessionInputResponse,
    SessionMetadata,
    SessionMetadataPatch,
    SessionDetail,
    SessionSummary,
    SessionsResponse,
)
from .state_store import StateStore
from .tmux_client import TmuxClient, TmuxError


app = FastAPI(title="Codex tmux Monitor", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "PATCH", "POST"],
    allow_headers=["*"],
)


def _metadata_path() -> Path:
    explicit_path = os.getenv("CODEX_MONITOR_METADATA_PATH")
    if explicit_path:
        return Path(explicit_path).expanduser()

    data_dir = os.getenv("CODEX_MONITOR_DATA_DIR")
    if data_dir:
        return Path(data_dir).expanduser() / "session_metadata.json"

    return Path(__file__).resolve().parents[1] / "data" / "session_metadata.json"


def _managed_mode_path() -> Path:
    explicit_path = os.getenv("CODEX_MONITOR_MANAGED_MODE_PATH")
    if explicit_path:
        return Path(explicit_path).expanduser()

    data_dir = os.getenv("CODEX_MONITOR_DATA_DIR")
    if data_dir:
        return Path(data_dir).expanduser() / "managed_mode.json"

    return Path(__file__).resolve().parents[1] / "data" / "managed_mode.json"


tmux_client = TmuxClient()
state_store = StateStore()
metadata_store = MetadataStore(_metadata_path())
managed_mode_controller: ManagedModeController | None = None
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.on_event("shutdown")
def shutdown_managed_mode() -> None:
    if managed_mode_controller is not None:
        managed_mode_controller.shutdown()


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    sessions = _safe_list_sessions()
    return HealthResponse(
        ok=True,
        tmux_available=tmux_client.tmux_available(),
        session_count=len(sessions),
    )


@app.get("/api/sessions", response_model=SessionsResponse)
def sessions() -> SessionsResponse:
    names = _safe_list_sessions()
    summaries = [_build_summary(name) for name in names]
    summaries.sort(key=lambda item: (STATUS_PRIORITY[item.status], item.name.lower()))
    return SessionsResponse(sessions=summaries)


@app.get("/api/managed-mode", response_model=ManagedModeStatus)
def managed_mode_status() -> ManagedModeStatus:
    try:
        return _managed_controller().status()
    except (ManagedModeError, TmuxError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/managed-mode", response_model=ManagedModeStatus)
def update_managed_mode(patch: ManagedModePatch) -> ManagedModeStatus:
    if patch.enabled is None and patch.interval_seconds is None:
        raise HTTPException(status_code=400, detail="Managed mode patch is empty")

    try:
        controller = _managed_controller()
        status = controller.status()
        if patch.interval_seconds is not None:
            status = controller.set_interval(patch.interval_seconds)
        if patch.enabled is not None:
            status = controller.set_enabled(patch.enabled)
    except (ManagedModeError, TmuxError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if status.enabled:
        metadata_store.update(
            status.steward_session,
            SessionMetadataPatch(group="AgentMonitor", note="Managed Mode Steward"),
        )
    return status


@app.get("/api/sessions/{name}", response_model=SessionDetail)
def session_detail(name: str) -> SessionDetail:
    names = set(_safe_list_sessions())
    if name not in names:
        raise HTTPException(status_code=404, detail=f"Session '{name}' not found")

    summary = _build_summary(name)
    tail_text = tmux_client.capture_session(name)
    return SessionDetail(
        **summary.model_dump(),
        tail=tail_text.splitlines(),
    )


@app.patch("/api/sessions/{name}/metadata", response_model=SessionMetadata)
def update_session_metadata(name: str, patch: SessionMetadataPatch) -> SessionMetadata:
    try:
        return metadata_store.update(name, patch)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sessions/{name}/input", response_model=SessionInputResponse)
def send_session_input(name: str, payload: SessionInputRequest) -> SessionInputResponse:
    names = set(_safe_list_sessions())
    if name not in names:
        raise HTTPException(status_code=404, detail=f"Session '{name}' not found")

    text = payload.text
    if not text and not payload.key and not payload.enter:
        raise HTTPException(status_code=400, detail="Input payload is empty")

    try:
        if text:
            tmux_client.send_text(name, text, enter=False)
        if payload.enter:
            tmux_client.send_key(name, "Enter")
        if payload.key:
            tmux_client.send_key(name, payload.key)
    except TmuxError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return SessionInputResponse()


@app.get("/", include_in_schema=False)
def frontend_index() -> FileResponse:
    return _frontend_index()


@app.get("/{full_path:path}", include_in_schema=False)
def frontend_app(full_path: str) -> FileResponse:
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")

    candidate = (FRONTEND_DIST / full_path).resolve()
    dist_root = FRONTEND_DIST.resolve()
    if candidate.is_file() and (candidate == dist_root or dist_root in candidate.parents):
        return FileResponse(candidate)

    return _frontend_index()


def _safe_list_sessions() -> list[str]:
    try:
        names = tmux_client.list_sessions()
    except TmuxError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    state_store.prune(set(names))
    return names


def _list_session_summaries() -> list[SessionSummary]:
    names = tmux_client.list_sessions()
    state_store.prune(set(names))
    return [_build_summary(name) for name in names]


def _managed_controller() -> ManagedModeController:
    global managed_mode_controller
    if managed_mode_controller is None:
        managed_mode_controller = ManagedModeController(
            store=ManagedModeStore(_managed_mode_path()),
            tmux_client=tmux_client,
            project_root=Path(__file__).resolve().parents[2],
            summary_provider=_list_session_summaries,
            tail_provider=tmux_client.capture_session,
        )
    return managed_mode_controller


def _frontend_index() -> FileResponse:
    index_path = FRONTEND_DIST / "index.html"
    if not index_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Frontend build not found. Run `npm run build` in frontend/.",
        )
    return FileResponse(index_path)


def _build_summary(name: str) -> SessionSummary:
    tail_text = tmux_client.capture_session(name)
    current_command = tmux_client.get_current_command(name)
    activity_time = tmux_client.get_activity_time(name)
    changed, idle_seconds, last_activity = state_store.observe(
        name,
        tail_text,
        external_activity=activity_time,
    )
    analysis = analyze_session(
        tail_text=tail_text,
        idle_seconds=idle_seconds,
        changed=changed,
        current_command=current_command,
    )
    metadata = metadata_store.get(name)

    return SessionSummary(
        name=name,
        status=analysis.status,
        idle_seconds=idle_seconds,
        last_activity=last_activity,
        preview=analysis.preview,
        attention_reason=analysis.attention_reason,
        current_command=current_command,
        archived=metadata.archived,
        collapsed=metadata.collapsed,
        group=metadata.group,
        note=metadata.note,
    )
