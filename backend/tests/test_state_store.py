from datetime import datetime, timedelta, timezone
import unittest

from app.state_store import StateStore


class StateStoreTest(unittest.TestCase):
    def test_first_observation_uses_external_activity(self) -> None:
        store = StateStore()
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        external = now - timedelta(minutes=10)

        changed, idle_seconds, last_activity = store.observe(
            "agent",
            "same tail",
            external_activity=external,
            now=now,
        )

        self.assertFalse(changed)
        self.assertEqual(idle_seconds, 600)
        self.assertEqual(last_activity, external)

    def test_external_activity_updates_without_tail_change(self) -> None:
        store = StateStore()
        start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        newer = start + timedelta(minutes=5)
        now = start + timedelta(minutes=8)

        store.observe("agent", "same tail", external_activity=start, now=start)
        changed, idle_seconds, last_activity = store.observe(
            "agent",
            "same tail",
            external_activity=newer,
            now=now,
        )

        self.assertFalse(changed)
        self.assertEqual(idle_seconds, 180)
        self.assertEqual(last_activity, newer)

    def test_tail_change_uses_observation_time(self) -> None:
        store = StateStore()
        start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        now = start + timedelta(minutes=8)

        store.observe("agent", "old tail", external_activity=start, now=start)
        changed, idle_seconds, last_activity = store.observe(
            "agent",
            "new tail",
            external_activity=start,
            now=now,
        )

        self.assertTrue(changed)
        self.assertEqual(idle_seconds, 0)
        self.assertEqual(last_activity, now)


if __name__ == "__main__":
    unittest.main()
