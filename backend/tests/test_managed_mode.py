from datetime import datetime, timezone
from pathlib import Path
import subprocess
import tempfile
import unittest

from app.managed_mode import (
    CODEX_UPDATE_SKIP_CHOICE,
    ManagedModeController,
    ManagedModeError,
    ManagedModeStore,
    build_steward_prompt,
    build_steward_report_prompt,
    select_managed_targets,
)
from app.models import SessionStatus, SessionSummary
from app.tmux_client import TmuxClient


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def session(
    name: str,
    status: SessionStatus,
    *,
    archived: bool = False,
    command: str | None = "codex",
    idle_seconds: int = 300,
) -> SessionSummary:
    return SessionSummary(
        name=name,
        status=status,
        idle_seconds=idle_seconds,
        last_activity=NOW,
        preview=f"{name} preview",
        attention_reason=None,
        current_command=command,
        archived=archived,
        collapsed=False,
        group="Project",
        note="",
    )


class RecordingTmuxClient(TmuxClient):
    def __init__(
        self,
        names: list[str],
        *,
        add_session_on_new: bool = True,
        capture_outputs: list[str] | None = None,
    ) -> None:
        object.__setattr__(self, "names", names)
        object.__setattr__(self, "sent_text", [])
        object.__setattr__(self, "killed_sessions", [])
        object.__setattr__(self, "new_sessions", [])
        object.__setattr__(self, "add_session_on_new", add_session_on_new)
        object.__setattr__(self, "capture_outputs", capture_outputs or [])

    def tmux_available(self) -> bool:
        return True

    def list_sessions(self) -> list[str]:
        return self.names

    def capture_session(self, name: str, lines: int = 100) -> str:
        if self.capture_outputs:
            return self.capture_outputs.pop(0)
        return "托管报告草稿"

    def send_text(self, name: str, text: str, enter: bool = True) -> None:
        self.sent_text.append((name, text, enter))

    def new_session(self, name: str, command: str, start_directory: str | None = None) -> None:
        self.new_sessions.append((name, command, start_directory))
        if self.add_session_on_new and name not in self.names:
            self.names.append(name)

    def kill_session(self, name: str) -> None:
        self.killed_sessions.append(name)

    def _run(
        self,
        args: list[str],
        check: bool = True,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["tmux", *args], 0, "", "")


class ManagedModeTest(unittest.TestCase):
    def test_select_managed_targets_includes_all_unarchived_codex_sessions(self) -> None:
        targets = select_managed_targets(
            [
                session("archived", SessionStatus.IDLE, archived=True),
                session("agentmonitor-steward", SessionStatus.IDLE),
                session("codex-tmux-monitor-highway", SessionStatus.IDLE),
                session("plain-shell", SessionStatus.IDLE, command="bash"),
                session("working-agent", SessionStatus.WORKING),
                session("done-agent", SessionStatus.DONE),
                session("idle-agent", SessionStatus.IDLE),
                session("node-codex-agent", SessionStatus.IDLE, command="node"),
                session("needs-input-agent", SessionStatus.NEEDS_INPUT),
                session("error-agent", SessionStatus.ERROR),
            ]
        )

        self.assertEqual(
            [target.name for target in targets],
            [
                "error-agent",
                "needs-input-agent",
                "idle-agent",
                "node-codex-agent",
                "working-agent",
                "done-agent",
            ],
        )

    def test_build_steward_prompt_contains_target_rules_and_tail(self) -> None:
        targets = [
            session("idle-agent", SessionStatus.IDLE),
            session("working-agent", SessionStatus.WORKING),
        ]

        prompt = build_steward_prompt(targets, lambda name, lines: f"{name} tail", NOW)

        self.assertIn("AgentMonitor Managed Mode Tick", prompt)
        self.assertIn("Do not touch archived sessions", prompt)
        self.assertIn("Default posture: observe, review existing code", prompt)
        self.assertIn("Avoid aggressive development", prompt)
        self.assertIn("For observe_only targets, do not send tmux input", prompt)
        self.assertIn("run the smallest relevant test", prompt)
        self.assertIn("## idle-agent", prompt)
        self.assertIn("stewardship_action: conservative_nudge_allowed", prompt)
        self.assertIn("## working-agent", prompt)
        self.assertIn("stewardship_action: observe_only", prompt)
        self.assertIn("idle-agent tail", prompt)
        self.assertIn("CODEX_STATUS", prompt)

    def test_build_steward_report_prompt_requests_chinese_report_without_more_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ManagedModeStore(Path(temp_dir) / "managed.json")
            state = store.update(enabled=True, last_targets=["idle-agent"])

            prompt = build_steward_report_prompt(state, NOW)

        self.assertIn("Managed Mode Final Report", prompt)
        self.assertIn("Write a concise Chinese stewardship report", prompt)
        self.assertIn("托管范围与目标", prompt)
        self.assertIn("Do not edit files, run project commands, or send more tmux input", prompt)
        self.assertIn("last_known_targets: idle-agent", prompt)

    def test_disabling_managed_mode_requests_report_and_keeps_steward_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ManagedModeStore(Path(temp_dir) / "managed.json")
            store.update(
                enabled=True,
                steward_session="steward",
                last_targets=["idle-agent"],
            )
            tmux = RecordingTmuxClient(["steward"])
            controller = ManagedModeController(
                store=store,
                tmux_client=tmux,
                project_root=Path(temp_dir),
                summary_provider=lambda: [],
                tail_provider=lambda name, lines: "",
                codex_binary="codex",
            )

            status = controller.set_enabled(False)

        self.assertFalse(status.enabled)
        self.assertTrue(status.steward_running)
        self.assertIsNotNone(status.report_requested_at)
        self.assertEqual(tmux.killed_sessions, [])
        self.assertEqual(tmux.sent_text[0][0], "steward")
        self.assertIn("Managed Mode Final Report", tmux.sent_text[0][1])
        self.assertIn("idle-agent", tmux.sent_text[0][1])

    def test_steward_start_command_uses_compatible_codex_flags(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ManagedModeStore(Path(temp_dir) / "managed.json")
            store.update(enabled=True, steward_session="steward")
            tmux = RecordingTmuxClient([])
            controller = ManagedModeController(
                store=store,
                tmux_client=tmux,
                project_root=Path(temp_dir),
                summary_provider=lambda: [],
                tail_provider=lambda name, lines: "",
                codex_binary="sh",
                steward_startup_settle_seconds=0,
            )

            controller.dispatch_if_due(force=True)

        self.assertEqual(len(tmux.new_sessions), 1)
        _, command, start_directory = tmux.new_sessions[0]
        self.assertEqual(start_directory, temp_dir)
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
        self.assertIn("--no-alt-screen", command)
        self.assertIn("--cd", command)
        self.assertNotIn("--ask-for-approval", command)
        self.assertNotIn("never", command)

    def test_steward_startup_skips_codex_update_prompt(self) -> None:
        update_prompt = "\n".join(
            [
                "Update available! 0.139.0 -> 0.140.0",
                "1. Update now",
                "2. Skip",
                "Press enter to continue",
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ManagedModeStore(Path(temp_dir) / "managed.json")
            store.update(enabled=True, steward_session="steward")
            tmux = RecordingTmuxClient(
                [],
                capture_outputs=[update_prompt, "Codex ready"],
            )
            controller = ManagedModeController(
                store=store,
                tmux_client=tmux,
                project_root=Path(temp_dir),
                summary_provider=lambda: [],
                tail_provider=lambda name, lines: "",
                codex_binary="sh",
                steward_startup_settle_seconds=0,
            )

            controller.dispatch_if_due(force=True)

        self.assertEqual(tmux.sent_text[0], ("steward", CODEX_UPDATE_SKIP_CHOICE, True))
        self.assertEqual(store.get().last_summary, "No unarchived Codex sessions to monitor.")

    def test_enabling_managed_mode_fails_clearly_when_steward_exits_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ManagedModeStore(Path(temp_dir) / "managed.json")
            tmux = RecordingTmuxClient([], add_session_on_new=False)
            controller = ManagedModeController(
                store=store,
                tmux_client=tmux,
                project_root=Path(temp_dir),
                summary_provider=lambda: [],
                tail_provider=lambda name, lines: "",
                codex_binary="sh",
                steward_startup_timeout_seconds=0,
                steward_startup_settle_seconds=0,
            )

            with self.assertRaises(ManagedModeError) as context:
                controller.set_enabled(True)
            controller.shutdown()

        self.assertIn("Steward session did not start", str(context.exception))
        state = store.get()
        self.assertFalse(state.enabled)
        self.assertIn("Steward session did not start", state.last_error or "")


if __name__ == "__main__":
    unittest.main()
