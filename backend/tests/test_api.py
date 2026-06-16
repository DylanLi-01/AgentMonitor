import unittest

from fastapi.testclient import TestClient

from app import main
from app.managed_mode import ManagedModeError
from app.models import ManagedModeStatus
from app.tmux_client import TmuxError


class FakeTmuxClient:
    def __init__(self, names: list[str]) -> None:
        self.names = names
        self.calls: list[tuple[str, str, str, bool | None]] = []

    def list_sessions(self) -> list[str]:
        return self.names

    def send_text(self, name: str, text: str, enter: bool = True) -> None:
        self.calls.append(("text", name, text, enter))

    def send_key(self, name: str, key: str) -> None:
        self.calls.append(("key", name, key, None))


class ExplodingTmuxClient(FakeTmuxClient):
    def send_key(self, name: str, key: str) -> None:
        raise TmuxError("tmux send failed")


class FakeMetadataStore:
    def __init__(self) -> None:
        self.updates: list[tuple[str, object]] = []

    def update(self, name: str, patch: object) -> object:
        self.updates.append((name, patch))
        return patch


class FakeManagedModeController:
    def __init__(self) -> None:
        self.enabled_values: list[bool] = []

    def status(self) -> ManagedModeStatus:
        return ManagedModeStatus(enabled=False, steward_running=False)

    def set_enabled(self, enabled: bool) -> ManagedModeStatus:
        self.enabled_values.append(enabled)
        return ManagedModeStatus(enabled=enabled, steward_running=enabled)


class ExplodingManagedModeController(FakeManagedModeController):
    def set_enabled(self, enabled: bool) -> ManagedModeStatus:
        raise ManagedModeError("managed mode failed")


class SessionInputApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_tmux_client = main.tmux_client
        self.original_metadata_store = main.metadata_store
        self.original_managed_mode_controller = main.managed_mode_controller
        main.metadata_store = FakeMetadataStore()
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        main.tmux_client = self.original_tmux_client
        main.metadata_store = self.original_metadata_store
        main.managed_mode_controller = self.original_managed_mode_controller

    def test_send_session_input_posts_literal_text_and_enter(self) -> None:
        fake = FakeTmuxClient(["codex"])
        main.tmux_client = fake

        response = self.client.post(
            "/api/sessions/codex/input",
            json={"text": "hello; rm -rf nope", "enter": True},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        self.assertEqual(
            fake.calls,
            [
                ("text", "codex", "hello; rm -rf nope", False),
                ("key", "codex", "Enter", None),
            ],
        )

    def test_send_session_input_rejects_empty_payload(self) -> None:
        fake = FakeTmuxClient(["codex"])
        main.tmux_client = fake

        response = self.client.post("/api/sessions/codex/input", json={})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "Input payload is empty"})
        self.assertEqual(fake.calls, [])

    def test_send_session_input_requires_existing_session(self) -> None:
        fake = FakeTmuxClient(["other"])
        main.tmux_client = fake

        response = self.client.post(
            "/api/sessions/codex/input",
            json={"text": "hello", "enter": True},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Session 'codex' not found"})
        self.assertEqual(fake.calls, [])

    def test_send_session_input_surfaces_tmux_errors(self) -> None:
        main.tmux_client = ExplodingTmuxClient(["codex"])

        response = self.client.post(
            "/api/sessions/codex/input",
            json={"key": "Enter"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "tmux send failed"})

    def test_managed_mode_status(self) -> None:
        main.managed_mode_controller = FakeManagedModeController()

        response = self.client.get("/api/managed-mode")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["enabled"])
        self.assertFalse(response.json()["steward_running"])

    def test_update_managed_mode(self) -> None:
        fake = FakeManagedModeController()
        main.managed_mode_controller = fake

        response = self.client.post("/api/managed-mode", json={"enabled": True})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["enabled"])
        self.assertTrue(response.json()["steward_running"])
        self.assertEqual(fake.enabled_values, [True])

    def test_update_managed_mode_surfaces_errors(self) -> None:
        main.managed_mode_controller = ExplodingManagedModeController()

        response = self.client.post("/api/managed-mode", json={"enabled": True})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "managed mode failed"})


if __name__ == "__main__":
    unittest.main()
