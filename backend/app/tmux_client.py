from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


class TmuxError(RuntimeError):
    pass


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

    def _run(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                ["tmux", *args],
                capture_output=True,
                check=check,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise TmuxError(f"tmux command timed out: {' '.join(args)}") from exc
        except subprocess.CalledProcessError as exc:
            raise TmuxError(exc.stderr.strip() or f"tmux command failed: {' '.join(args)}") from exc

        return result
