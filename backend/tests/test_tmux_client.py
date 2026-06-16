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


class TmuxClientTest(unittest.TestCase):
    def test_missing_tmux_server_is_empty_session_list(self) -> None:
        self.assertEqual(NoServerTmuxClient().list_sessions(), [])


if __name__ == "__main__":
    unittest.main()
