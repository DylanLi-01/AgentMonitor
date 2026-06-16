from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4


class TmuxError(RuntimeError):
    pass


SEND_KEYS_LITERAL_LIMIT = 1000


@dataclass(frozen=True)
class TmuxClient:
    timeout_seconds: float = 3.0

    def tmux_available(self) -> bool:
        return shutil.which("tmux") is not None

    def list_sessions(self) -> list[str]:
        if not self.tmux_available():
            return []

        result = self._run(["list-sessions", "-F", "#{session_name}"], check=False)
        if result.returncode != 0:
            stderr = result.stderr.lower()
            if any(
                phrase in stderr
                for phrase in (
                    "no server running",
                    "failed to connect to server",
                    "no such file or directory",
                    "connection refused",
                )
            ):
                return []
            raise TmuxError(result.stderr.strip() or "tmux list-sessions failed")

        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def capture_session(self, name: str, lines: int = 100) -> str:
        result = self._run(
            ["capture-pane", "-p", "-t", name, "-S", f"-{lines}"],
            check=False,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.rstrip("\n")

    def get_current_command(self, name: str) -> Optional[str]:
        result = self._run(
            ["display-message", "-p", "-t", name, "#{pane_current_command}"],
            check=False,
        )
        if result.returncode != 0:
            return None

        command = result.stdout.strip()
        return command or None

    def get_activity_time(self, name: str) -> Optional[datetime]:
        result = self._run(
            [
                "display-message",
                "-p",
                "-t",
                name,
                "#{session_activity} #{window_activity}",
            ],
            check=False,
        )
        if result.returncode != 0:
            return None

        timestamps = []
        for raw_value in result.stdout.split():
            try:
                timestamp = int(raw_value)
            except ValueError:
                continue
            if timestamp > 0:
                timestamps.append(timestamp)

        if not timestamps:
            return None

        return datetime.fromtimestamp(max(timestamps), tz=timezone.utc)

    def send_text(self, name: str, text: str, enter: bool = True) -> None:
        if text:
            if len(text) <= SEND_KEYS_LITERAL_LIMIT:
                self._run(["send-keys", "-t", name, "-l", text])
            else:
                buffer_name = f"agentmonitor-{uuid4().hex}"
                self._run(["load-buffer", "-b", buffer_name, "-"], input_text=text)
                self._run(["paste-buffer", "-d", "-b", buffer_name, "-t", name])
        if enter:
            self.send_key(name, "Enter")

    def send_key(self, name: str, key: str) -> None:
        self._run(["send-keys", "-t", name, key])

    def new_session(self, name: str, command: str, start_directory: Optional[str] = None) -> None:
        args = ["new-session", "-d", "-s", name]
        if start_directory:
            args.extend(["-c", start_directory])
        args.append(command)
        self._run(args)

    def kill_session(self, name: str) -> None:
        result = self._run(["kill-session", "-t", name], check=False)
        if result.returncode == 0:
            return

        stderr = result.stderr.lower()
        if "can't find session" in stderr or "can't find pane" in stderr:
            return

        raise TmuxError(result.stderr.strip() or f"tmux kill-session failed: {name}")

    def _run(
        self,
        args: list[str],
        check: bool = True,
        input_text: Optional[str] = None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                ["tmux", *args],
                capture_output=True,
                check=check,
                input=input_text,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise TmuxError(f"tmux command timed out: {' '.join(args)}") from exc
        except subprocess.CalledProcessError as exc:
            raise TmuxError(exc.stderr.strip() or f"tmux command failed: {' '.join(args)}") from exc

        return result
