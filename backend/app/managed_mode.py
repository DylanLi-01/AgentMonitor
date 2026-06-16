from __future__ import annotations

import json
import shlex
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from pydantic import ValidationError

from .models import ManagedModeState, ManagedModeStatus, STATUS_PRIORITY, SessionStatus, SessionSummary
from .tmux_client import TmuxClient, TmuxError


DEFAULT_STEWARD_SESSION = "agentmonitor-steward"
MANAGED_TARGET_LIMIT = 24
TARGET_TAIL_LINES = 60
TARGET_TAIL_CHAR_LIMIT = 1600
MONITOR_OWNED_PREFIXES = ("agentmonitor-", "codex-tmux-monitor")
CODEX_PANE_COMMANDS = {"codex", "node"}
TARGET_STATUSES = {
    SessionStatus.ERROR,
    SessionStatus.NEEDS_INPUT,
    SessionStatus.BLOCKED,
    SessionStatus.PARTIAL,
    SessionStatus.IDLE,
    SessionStatus.UNKNOWN,
}


class ManagedModeError(RuntimeError):
    pass


class ManagedModeStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._state = ManagedModeState()
        self._load()

    def get(self) -> ManagedModeState:
        with self._lock:
            return self._state.model_copy(deep=True)

    def update(self, **updates: object) -> ManagedModeState:
        with self._lock:
            payload = self._state.model_dump()
            payload.update(updates)
            payload["updated_at"] = _utc_now()
            self._state = ManagedModeState.model_validate(payload)
            self._save_locked()
            return self._state.model_copy(deep=True)

    def _load(self) -> None:
        if not self._path.exists():
            return

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid managed mode state file: {self._path}") from exc

        if not isinstance(raw, dict):
            raise ValueError(f"Invalid managed mode state file: {self._path}")

        try:
            self._state = ManagedModeState.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"Invalid managed mode state file: {self._path}") from exc

    def _save_locked(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._state.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )


class ManagedModeController:
    def __init__(
        self,
        *,
        store: ManagedModeStore,
        tmux_client: TmuxClient,
        project_root: Path,
        summary_provider: Callable[[], list[SessionSummary]],
        tail_provider: Callable[[str, int], str],
        codex_binary: str = "codex",
    ) -> None:
        self._store = store
        self._tmux_client = tmux_client
        self._project_root = project_root
        self._summary_provider = summary_provider
        self._tail_provider = tail_provider
        self._codex_binary = codex_binary
        self._worker_lock = threading.Lock()
        self._dispatch_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None

    def status(self) -> ManagedModeStatus:
        state = self._store.get()
        if state.enabled:
            self._ensure_worker()
        return ManagedModeStatus(
            **state.model_dump(),
            steward_running=self._session_exists(state.steward_session),
        )

    def set_enabled(self, enabled: bool) -> ManagedModeStatus:
        if enabled:
            self._ensure_tmux_available()
            self._ensure_codex_available()
            self._store.update(enabled=True, last_error=None)
            self._ensure_worker()
            try:
                self.dispatch_if_due(force=True)
            except Exception as exc:
                self._store.update(enabled=False, last_error=str(exc))
                self._stop_event.set()
                raise
            return self.status()

        self._store.update(enabled=False)
        self._stop_event.set()
        state = self._store.get()
        self._tmux_client.kill_session(state.steward_session)
        return self.status()

    def shutdown(self) -> None:
        self._stop_event.set()

    def dispatch_if_due(self, *, force: bool = False) -> None:
        with self._dispatch_lock:
            state = self._store.get()
            if not state.enabled:
                return

            now = _utc_now()
            if not force and state.last_dispatch_at is not None:
                elapsed = (now - state.last_dispatch_at).total_seconds()
                if elapsed < state.interval_seconds:
                    return

            self._dispatch_once(state, now)

    def _run_worker(self) -> None:
        while not self._stop_event.wait(5):
            state = self._store.get()
            if not state.enabled:
                return

            try:
                self.dispatch_if_due()
            except Exception as exc:
                self._store.update(last_error=str(exc))

    def _ensure_worker(self) -> None:
        with self._worker_lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._stop_event.clear()
            self._worker = threading.Thread(
                target=self._run_worker,
                name="agentmonitor-managed-mode",
                daemon=True,
            )
            self._worker.start()

    def _dispatch_once(self, state: ManagedModeState, now: datetime) -> None:
        self._ensure_tmux_available()
        self._ensure_codex_available()
        self._ensure_steward_session(state.steward_session)

        targets = select_managed_targets(self._summary_provider(), state.steward_session)
        if not targets:
            self._store.update(
                last_dispatch_at=now,
                last_error=None,
                last_summary="No eligible unarchived Codex sessions.",
                last_targets=[],
            )
            return

        prompt = build_steward_prompt(targets, self._tail_provider, now)
        self._tmux_client.send_text(state.steward_session, prompt, enter=True)
        self._store.update(
            last_dispatch_at=now,
            last_error=None,
            last_summary=f"Sent stewardship brief for {len(targets)} session(s).",
            last_targets=[target.name for target in targets],
        )

    def _ensure_steward_session(self, name: str) -> None:
        if self._session_exists(name):
            return

        codex_path = self._ensure_codex_available()
        command = " ".join(
            [
                shlex.quote(codex_path),
                "--dangerously-bypass-approvals-and-sandbox",
                "--ask-for-approval",
                "never",
                "--no-alt-screen",
                "--cd",
                shlex.quote(str(self._project_root)),
            ]
        )
        self._tmux_client.new_session(name, command, start_directory=str(self._project_root))
        time.sleep(1)

    def _ensure_codex_available(self) -> str:
        codex_path = shutil.which(self._codex_binary)
        if not codex_path:
            raise ManagedModeError(f"Codex binary not found: {self._codex_binary}")
        return codex_path

    def _ensure_tmux_available(self) -> None:
        if not self._tmux_client.tmux_available():
            raise ManagedModeError("tmux binary not found")

    def _session_exists(self, name: str) -> bool:
        return name in set(self._tmux_client.list_sessions())


def select_managed_targets(
    sessions: list[SessionSummary],
    steward_session: str = DEFAULT_STEWARD_SESSION,
) -> list[SessionSummary]:
    targets = [
        session
        for session in sessions
        if _is_managed_target(session, steward_session)
    ]
    targets.sort(
        key=lambda session: (
            STATUS_PRIORITY[session.status],
            -session.idle_seconds,
            (session.group or "").lower(),
            (session.note or session.name).lower(),
        )
    )
    return targets[:MANAGED_TARGET_LIMIT]


def build_steward_prompt(
    targets: list[SessionSummary],
    tail_provider: Callable[[str, int], str],
    now: datetime,
) -> str:
    target_blocks = [
        _format_target_block(target, tail_provider(target.name, TARGET_TAIL_LINES))
        for target in targets
    ]
    return "\n\n".join(
        [
            "# AgentMonitor Managed Mode Tick",
            f"timestamp_utc: {now.astimezone(timezone.utc).isoformat()}",
            "You are the AgentMonitor steward Codex agent.",
            "Your job is to help only the listed, unarchived Codex tmux sessions make progress.",
            "Do not touch archived sessions, unlisted sessions, or AgentMonitor's own sessions.",
            "Do not edit project files directly from this steward session; direct the target agents instead.",
            "If a target can continue without a human decision, send it one concise instruction with tmux send-keys.",
            "If a target needs credentials, product judgment, or missing context, leave it alone and report that.",
            "Do not repeatedly send the same instruction if the tail already shows a recent steward nudge.",
            "When sending to a target, use literal tmux input and then Enter.",
            "Ask target agents to finish their replies with CODEX_STATUS so the monitor can classify them.",
            "Targets:",
            *target_blocks,
        ]
    )


def _is_managed_target(session: SessionSummary, steward_session: str) -> bool:
    if session.archived:
        return False
    if session.name == steward_session:
        return False
    if session.name.startswith(MONITOR_OWNED_PREFIXES):
        return False
    if (session.current_command or "").lower() not in CODEX_PANE_COMMANDS:
        return False
    return session.status in TARGET_STATUSES


def _format_target_block(session: SessionSummary, tail_text: str) -> str:
    display_name = session.note.strip() or session.name
    group = session.group.strip() or "Ungrouped"
    tail = _truncate_text(tail_text.strip() or "No recent output", TARGET_TAIL_CHAR_LIMIT)
    return "\n".join(
        [
            f"## {session.name}",
            f"display_name: {display_name}",
            f"group: {group}",
            f"status: {session.status.value}",
            f"idle_seconds: {session.idle_seconds}",
            f"current_command: {session.current_command or 'unknown'}",
            f"attention: {session.attention_reason or 'none'}",
            f"preview: {session.preview}",
            "tail:",
            "```text",
            tail,
            "```",
        ]
    )


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 40]}\n...[truncated {len(value) - limit + 40} chars]"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
