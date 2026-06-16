import subprocess
import unittest

from app.tmux_client import SEND_KEYS_LITERAL_LIMIT, TmuxClient


class NoServerTmuxClient(TmuxClient):
    def tmux_available(self) -> bool:
        return True

    def _run(
        self,
        args: list[str],
        check: bool = True,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            ["tmux", *args],
            1,
            "",
            "error connecting to /tmp/tmux-1000/default (No such file or directory)",
        )


class RecordingTmuxClient(TmuxClient):
    def __init__(self) -> None:
        object.__setattr__(self, "calls", [])
        object.__setattr__(self, "inputs", [])

    def _run(
        self,
        args: list[str],
        check: bool = True,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        self.inputs.append(input_text)
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
        self.assertEqual(client.inputs, [None, None])

    def test_send_text_uses_buffer_for_long_text(self) -> None:
        client = RecordingTmuxClient()
        long_text = "x" * (SEND_KEYS_LITERAL_LIMIT + 1)

        client.send_text("codex", long_text, enter=True)

        self.assertEqual(client.calls[0][0], "load-buffer")
        self.assertEqual(client.calls[0][1], "-b")
        self.assertTrue(client.calls[0][2].startswith("agentmonitor-"))
        self.assertEqual(client.calls[0][3], "-")
        self.assertEqual(client.inputs[0], long_text)
        self.assertEqual(
            client.calls[1],
            ["paste-buffer", "-d", "-b", client.calls[0][2], "-t", "codex"],
        )
        self.assertEqual(client.calls[2], ["send-keys", "-t", "codex", "Enter"])
        self.assertEqual(client.inputs[1:], [None, None])

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
            def _run(
                self,
                args: list[str],
                check: bool = True,
                input_text: str | None = None,
            ) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(
                    ["tmux", *args],
                    1,
                    "",
                    "can't find session: missing",
                )

        MissingSessionTmuxClient().kill_session("missing")


if __name__ == "__main__":
    unittest.main()
