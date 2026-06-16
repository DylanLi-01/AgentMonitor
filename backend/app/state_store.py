from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class SessionState:
    last_hash: str
    last_activity: datetime
    last_seen: datetime


class StateStore:
    """In-memory activity tracker for tmux sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def observe(
        self,
        name: str,
        tail_text: str,
        external_activity: datetime | None = None,
        now: datetime | None = None,
    ) -> tuple[bool, int, datetime]:
        observed_at = now or datetime.now(timezone.utc)
        normalized_external_activity = _normalize_activity_time(external_activity, observed_at)
        digest = hashlib.sha256(tail_text.encode("utf-8")).hexdigest()
        existing = self._sessions.get(name)

        if existing is None:
            last_activity = normalized_external_activity or observed_at
            self._sessions[name] = SessionState(
                last_hash=digest,
                last_activity=last_activity,
                last_seen=observed_at,
            )
            idle_seconds = max(0, int((observed_at - last_activity).total_seconds()))
            return False, idle_seconds, last_activity

        changed = existing.last_hash != digest
        if changed:
            existing.last_hash = digest
            existing.last_activity = observed_at
        elif normalized_external_activity and normalized_external_activity > existing.last_activity:
            existing.last_activity = normalized_external_activity

        existing.last_seen = observed_at
        idle_seconds = max(0, int((observed_at - existing.last_activity).total_seconds()))
        return changed, idle_seconds, existing.last_activity

    def prune(self, active_names: set[str]) -> None:
        stale_names = set(self._sessions) - active_names
        for name in stale_names:
            del self._sessions[name]


def _normalize_activity_time(
    activity_time: datetime | None,
    observed_at: datetime,
) -> datetime | None:
    if activity_time is None:
        return None

    if activity_time.tzinfo is None:
        activity_time = activity_time.replace(tzinfo=timezone.utc)

    # tmux activity can be one or two seconds ahead of the app clock on skewed hosts.
    if activity_time > observed_at:
        return observed_at

    return activity_time
