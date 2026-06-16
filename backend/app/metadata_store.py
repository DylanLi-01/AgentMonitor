from __future__ import annotations

import json
import threading
from pathlib import Path

from .models import SessionMetadata, SessionMetadataPatch


class MetadataStore:
    """Small JSON-backed store for user annotations and visibility choices."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._items: dict[str, SessionMetadata] = {}
        self._load()

    def get(self, name: str) -> SessionMetadata:
        with self._lock:
            return self._items.get(name, SessionMetadata()).model_copy()

    def update(self, name: str, patch: SessionMetadataPatch) -> SessionMetadata:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Session name cannot be empty")

        with self._lock:
            current = self._items.get(clean_name, SessionMetadata())
            update_data = patch.model_dump(exclude_unset=True)
            if "note" in update_data and update_data["note"] is None:
                update_data["note"] = ""
            if "note" in update_data and isinstance(update_data["note"], str):
                update_data["note"] = update_data["note"].strip()
            if "group" in update_data and update_data["group"] is None:
                update_data["group"] = ""
            if "group" in update_data and isinstance(update_data["group"], str):
                update_data["group"] = " ".join(update_data["group"].split())

            next_value = current.model_copy(update=update_data)
            self._items[clean_name] = next_value
            self._save_locked()
            return next_value.model_copy()

    def _load(self) -> None:
        if not self._path.exists():
            return

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        if not isinstance(raw, dict):
            return

        items: dict[str, SessionMetadata] = {}
        for name, value in raw.items():
            if not isinstance(name, str) or not isinstance(value, dict):
                continue
            try:
                items[name] = SessionMetadata.model_validate(value)
            except ValueError:
                continue

        self._items = items

    def _save_locked(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {
            name: metadata.model_dump()
            for name, metadata in sorted(self._items.items(), key=lambda item: item[0].lower())
        }
        self._path.write_text(
            json.dumps(serializable, indent=2, sort_keys=True),
            encoding="utf-8",
        )
