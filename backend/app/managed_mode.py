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

from .models import ManagedModeState, ManagedModeStatus, SessionStatus, SessionSummary
from .tmux_client import TmuxClient, TmuxError


DEFAULT_STEWARD_SESSION = "agentmonitor-steward"
MANAGED_TARGET_LIMIT = 24
TARGET_TAIL_LINES = 60
TARGET_TAIL_CHAR_LIMIT = 1600
STEWARD_STARTUP_TIMEOUT_SECONDS = 5.0
STEWARD_STARTUP_POLL_SECONDS = 0.2
STEWARD_STARTUP_SETTLE_SECONDS = 0.8
CODEX_UPDATE_PROMPT_LINES = 30
CODEX_UPDATE_PROMPT_MARKERS = ("Update available!", "Press enter to continue")
CODEX_UPDATE_SKIP_CHOICE = "2"
CODEX_UPDATE_SKIP_SETTLE_SECONDS = 0.5
MONITOR_OWNED_PREFIXES = ("agentmonitor-", "codex-tmux-monitor")
CODEX_PANE_COMMANDS = {"codex", "node"}
ACTIONABLE_STATUSES = {
    SessionStatus.ERROR,
    SessionStatus.NEEDS_INPUT,
    SessionStatus.BLOCKED,
    SessionStatus.PARTIAL,
    SessionStatus.IDLE,
    SessionStatus.UNKNOWN,
}
MANAGED_STATUS_PRIORITY = {
    SessionStatus.ERROR: 0,
    SessionStatus.NEEDS_INPUT: 1,
    SessionStatus.BLOCKED: 2,
    SessionStatus.PARTIAL: 3,
    SessionStatus.IDLE: 4,
    SessionStatus.UNKNOWN: 5,
    SessionStatus.WORKING: 6,
    SessionStatus.DONE: 7,
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
        steward_startup_timeout_seconds: float = STEWARD_STARTUP_TIMEOUT_SECONDS,
        steward_startup_settle_seconds: float = STEWARD_STARTUP_SETTLE_SECONDS,
    ) -> None:
        self._store = store
        self._tmux_client = tmux_client
        self._project_root = project_root
        self._summary_provider = summary_provider
        self._tail_provider = tail_provider
        self._codex_binary = codex_binary
        self._steward_startup_timeout_seconds = steward_startup_timeout_seconds
        self._steward_startup_settle_seconds = steward_startup_settle_seconds
        self._worker_lock = threading.Lock()
        self._dispatch_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None

    def status(self) -> ManagedModeStatus:
        state = self._store.get()
        if state.enabled:
            self._ensure_worker()
        steward_running = self._session_exists(state.steward_session)
        steward_tail = []
        if steward_running:
            steward_tail = self._tmux_client.capture_session(state.steward_session, lines=80).splitlines()
        return ManagedModeStatus(
            **state.model_dump(),
            steward_running=steward_running,
            steward_tail=steward_tail,
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

        with self._dispatch_lock:
            self._stop_event.set()
            now = _utc_now()
            state = self._store.update(
                enabled=False,
                last_error=None,
            )
            if self._session_exists(state.steward_session):
                self._tmux_client.send_text(
                    state.steward_session,
                    build_steward_report_prompt(state, now),
                    enter=True,
                )
                self._store.update(
                    report_requested_at=now,
                    last_summary="Managed mode ended; requested final stewardship report.",
                )
            else:
                self._store.update(
                    report_requested_at=None,
                    last_summary="Managed mode ended; steward session was not running.",
                )
        return self.status()

    def set_interval(self, interval_seconds: int) -> ManagedModeStatus:
        self._store.update(interval_seconds=interval_seconds, last_error=None)
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
                last_summary="No unarchived Codex sessions to monitor.",
                last_targets=[],
            )
            return

        prompt = build_steward_prompt(targets, self._tail_provider, now)
        try:
            self._tmux_client.send_text(state.steward_session, prompt, enter=True)
        except TmuxError as exc:
            if not self._session_exists(state.steward_session):
                raise ManagedModeError(
                    "Steward session exited before it could receive the stewardship brief."
                ) from exc
            raise
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
                "--no-alt-screen",
                "--cd",
                shlex.quote(str(self._project_root)),
            ]
        )
        self._tmux_client.new_session(name, command, start_directory=str(self._project_root))
        self._wait_for_steward_session(name)
        self._skip_codex_update_prompt_if_present(name)

    def _wait_for_steward_session(self, name: str) -> None:
        deadline = time.monotonic() + self._steward_startup_timeout_seconds
        while True:
            if self._session_exists(name):
                if self._steward_startup_settle_seconds > 0:
                    time.sleep(self._steward_startup_settle_seconds)
                if self._session_exists(name):
                    return
                raise ManagedModeError(
                    "Steward session exited immediately after startup; check Codex CLI startup options."
                )

            if time.monotonic() >= deadline:
                raise ManagedModeError(
                    "Steward session did not start; check Codex CLI startup options."
                )

            remaining = max(0.0, deadline - time.monotonic())
            time.sleep(min(STEWARD_STARTUP_POLL_SECONDS, remaining))

    def _skip_codex_update_prompt_if_present(self, name: str) -> None:
        tail = self._tmux_client.capture_session(name, lines=CODEX_UPDATE_PROMPT_LINES)
        if not _is_codex_update_prompt(tail):
            return

        try:
            self._tmux_client.send_text(name, CODEX_UPDATE_SKIP_CHOICE, enter=True)
        except TmuxError as exc:
            raise ManagedModeError(
                "Steward session did not accept the Codex update prompt response."
            ) from exc

        time.sleep(CODEX_UPDATE_SKIP_SETTLE_SECONDS)
        if not self._session_exists(name):
            raise ManagedModeError(
                "Steward session exited after skipping the Codex update prompt."
            )

        tail_after_skip = self._tmux_client.capture_session(name, lines=CODEX_UPDATE_PROMPT_LINES)
        if _is_codex_update_prompt(tail_after_skip):
            raise ManagedModeError(
                "Codex update prompt blocked steward startup; update Codex CLI or select Skip manually."
            )

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
            MANAGED_STATUS_PRIORITY[session.status],
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
            "Your job is to conservatively supervise only the listed, unarchived Codex tmux sessions.",
            "Default posture: observe, review existing code, run or ask for focused tests, diagnose failures, and summarize state.",
            "Avoid aggressive development. Do not start broad implementations, refactors, rewrites, migrations, dependency upgrades, pushes, or deployments.",
            "Only suggest implementation if it is small, localized, clearly requested by the user, and testable with existing checks.",
            "Do not touch archived sessions, unlisted sessions, or AgentMonitor's own sessions.",
            "Do not edit project files directly from this steward session; direct the target agents instead.",
            "Each target has stewardship_action. For observe_only targets, do not send tmux input; only summarize state.",
            "For conservative_nudge_allowed targets, if they can continue without a human decision, send at most one concise, conservative instruction with tmux send-keys.",
            "Prefer instructions such as: review the recent diff, run the smallest relevant test, inspect logs, reproduce the error, verify the current result, or write a status summary.",
            "If a target needs credentials, product judgment, or missing context, leave it alone and report that.",
            "Do not repeatedly send the same instruction if the tail already shows a recent steward nudge.",
            "When sending to a target, use literal tmux input and then Enter.",
            "Ask target agents to finish their replies with CODEX_STATUS so the monitor can classify them.",
            "Targets:",
            *target_blocks,
        ]
    )


def build_steward_report_prompt(state: ManagedModeState, now: datetime) -> str:
    last_targets = ", ".join(state.last_targets) if state.last_targets else "none"
    return "\n\n".join(
        [
            "# AgentMonitor Managed Mode Final Report",
            f"timestamp_utc: {now.astimezone(timezone.utc).isoformat()}",
            "Managed Mode has been disabled. Stop sending instructions to other sessions.",
            "Write a concise Chinese stewardship report in this steward session.",
            "Report sections:",
            "- 托管范围与目标",
            "- 你发送过的指令或采取过的协调动作",
            "- 各目标 session 的当前状态与证据",
            "- 仍然需要用户决策的事项",
            "- 建议用户回来后优先做的下一步",
            "Be factual. If you did not take an action, say so. Do not invent outcomes.",
            "Do not edit files, run project commands, or send more tmux input while writing this report.",
            f"last_known_targets: {last_targets}",
            "Finish with CODEX_STATUS status=done.",
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
    return True


def _stewardship_action(status: SessionStatus) -> str:
    if status in ACTIONABLE_STATUSES:
        return "conservative_nudge_allowed"
    return "observe_only"


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
            f"stewardship_action: {_stewardship_action(session.status)}",
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


def _is_codex_update_prompt(text: str) -> bool:
    return all(marker in text for marker in CODEX_UPDATE_PROMPT_MARKERS)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
