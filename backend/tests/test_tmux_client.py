import subprocess
import unittest

from app.tmux_client import TmuxClient


class NoServerTmuxClient(TmuxClient):
    def tmux_available(self) -> bool:
        return True

    def _run(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            ["tmux", *args],
            1,
            "",
            "error connecting to /tmp/tmux-1000/default (No such file or directory)",
        )


class RecordingTmuxClient(TmuxClient):
    def __init__(self) -> None:
        object.__setattr__(self, "calls", [])

    def _run(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        return subprocess.CompletedProcess(["tmux", *args], 0, "", "")


class TmuxClientTest(unittest.TestCase):
    def test_missing_tmux_server_is_empty_session_list(self) -> None:
        self.assertEqual(NoServerTmuxClient().list_sessions(), [])

    def test_send_text_uses_literal_mode_and_enter(self) -> None:
        client = RecordingTmuxClient()

        client.send_text("codex", "hello; rm -rf nope", enter=True)

        self.assertEqual(
            client.calls,
            [
                ["send-keys", "-t", "codex", "-l", "hello; rm -rf nope"],
                ["send-keys", "-t", "codex", "Enter"],
            ],
        )

    def test_send_key_sends_named_key(self) -> None:
        client = RecordingTmuxClient()

        client.send_key("codex", "C-c")

        self.assertEqual(client.calls, [["send-keys", "-t", "codex", "C-c"]])

    def test_new_session_uses_start_directory_and_command(self) -> None:
        client = RecordingTmuxClient()

        client.new_session("steward", "codex --no-alt-screen", start_directory="/tmp/project")

        self.assertEqual(
            client.calls,
            [["new-session", "-d", "-s", "steward", "-c", "/tmp/project", "codex --no-alt-screen"]],
        )

    def test_kill_session_ignores_missing_session(self) -> None:
        class MissingSessionTmuxClient(TmuxClient):
            def _run(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(
                    ["tmux", *args],
                    1,
                    "",
                    "can't find session: missing",
                )

        MissingSessionTmuxClient().kill_session("missing")


if __name__ == "__main__":
    unittest.main()
