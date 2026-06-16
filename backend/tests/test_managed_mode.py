from datetime import datetime, timezone
import unittest

from app.managed_mode import build_steward_prompt, select_managed_targets
from app.models import SessionStatus, SessionSummary


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


class ManagedModeTest(unittest.TestCase):
    def test_select_managed_targets_only_includes_unarchived_actionable_codex_sessions(self) -> None:
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
            ["error-agent", "needs-input-agent", "idle-agent", "node-codex-agent"],
        )

    def test_build_steward_prompt_contains_target_rules_and_tail(self) -> None:
        targets = [session("idle-agent", SessionStatus.IDLE)]

        prompt = build_steward_prompt(targets, lambda name, lines: f"{name} tail", NOW)

        self.assertIn("AgentMonitor Managed Mode Tick", prompt)
        self.assertIn("Do not touch archived sessions", prompt)
        self.assertIn("## idle-agent", prompt)
        self.assertIn("idle-agent tail", prompt)
        self.assertIn("CODEX_STATUS", prompt)


if __name__ == "__main__":
    unittest.main()
