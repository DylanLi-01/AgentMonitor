from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

from .models import SessionStatus


IDLE_AFTER_SECONDS = 120
PREVIEW_LIMIT = 180
FOOTER_STATUS_MAP = {
    "done": SessionStatus.DONE,
    "needs_input": SessionStatus.NEEDS_INPUT,
    "blocked": SessionStatus.BLOCKED,
    "error": SessionStatus.ERROR,
    "working": SessionStatus.WORKING,
    "partial": SessionStatus.PARTIAL,
}


@dataclass(frozen=True)
class AnalysisResult:
    status: SessionStatus
    attention_reason: Optional[str]
    preview: str


def analyze_session(
    tail_text: str,
    idle_seconds: int,
    changed: bool,
    current_command: Optional[str] = None,
) -> AnalysisResult:
    """Classify a tmux session without keyword-matching arbitrary output."""

    preview = make_preview(tail_text)

    if footer := _parse_status_footer(tail_text):
        status = FOOTER_STATUS_MAP.get(footer.status)
        if status:
            return AnalysisResult(
                status,
                _format_footer_reason(footer),
                preview,
            )

    if changed:
        return AnalysisResult(SessionStatus.WORKING, None, preview)

    if idle_seconds >= IDLE_AFTER_SECONDS:
        return AnalysisResult(SessionStatus.IDLE, "No output change for 120s", preview)

    return AnalysisResult(SessionStatus.UNKNOWN, None, preview)


def make_preview(tail_text: str) -> str:
    lines = [line.strip() for line in tail_text.splitlines() if line.strip()]
    if not lines:
        return "No recent output"

    preview = lines[-1]
    if len(preview) <= PREVIEW_LIMIT:
        return preview
    return f"{preview[: PREVIEW_LIMIT - 1]}..."


@dataclass(frozen=True)
class FooterStatus:
    status: str
    summary: str
    needs_user: Optional[bool]
    next_action: str


def _parse_status_footer(tail_text: str) -> Optional[FooterStatus]:
    if footer := _parse_json_status(tail_text):
        return footer
    return _parse_yaml_status(tail_text)


def _parse_yaml_status(tail_text: str) -> Optional[FooterStatus]:
    lines = [line.strip() for line in tail_text.splitlines() if line.strip()]
    start_index = None
    for index in range(len(lines) - 1, -1, -1):
        if lines[index] == "CODEX_STATUS:":
            start_index = index
            break

    if start_index is None:
        return None

    fields: dict[str, str] = {}
    for line in lines[start_index + 1 : start_index + 8]:
        if line.startswith("```"):
            continue
        match = re.match(r"^(status|summary|needs_user|next_action):\s*(.*)$", line)
        if not match:
            continue
        fields[match.group(1)] = _strip_yaml_scalar(match.group(2))

    status = fields.get("status", "").lower()
    if status not in FOOTER_STATUS_MAP:
        return None

    return FooterStatus(
        status=status,
        summary=fields.get("summary", ""),
        needs_user=_parse_bool(fields.get("needs_user")),
        next_action=fields.get("next_action", ""),
    )


def _parse_json_status(tail_text: str) -> Optional[FooterStatus]:
    for block in reversed(_json_candidate_blocks(tail_text)):
        try:
            value = json.loads(block)
        except json.JSONDecodeError:
            continue

        if footer := _footer_from_json_value(value):
            return footer

    return None


def _json_candidate_blocks(tail_text: str) -> list[str]:
    candidates = [
        match.group(1).strip()
        for match in re.finditer(
            r"```(?:json)?\s*\n(.*?)\n```",
            tail_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    ]

    stripped = tail_text.strip()
    if stripped:
        candidates.extend(_trailing_json_candidates(stripped))

    return candidates


def _trailing_json_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        candidate = text[index:].strip()
        if candidate.endswith("}"):
            candidates.append(candidate)
    return candidates[-8:]


def _footer_from_json_value(value: object) -> Optional[FooterStatus]:
    if not isinstance(value, dict):
        return None

    status_object = value.get("CODEX_STATUS", value)
    if not isinstance(status_object, dict):
        return None

    status_value = status_object.get("status")
    if not isinstance(status_value, str):
        return None

    status = status_value.lower()
    if status not in FOOTER_STATUS_MAP:
        return None

    summary_value = status_object.get("summary", "")
    next_action_value = status_object.get("next_action", "")
    needs_user_value = status_object.get("needs_user")
    return FooterStatus(
        status=status,
        summary=summary_value if isinstance(summary_value, str) else "",
        needs_user=needs_user_value if isinstance(needs_user_value, bool) else None,
        next_action=next_action_value if isinstance(next_action_value, str) else "",
    )


def _strip_yaml_scalar(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1]
    return stripped


def _parse_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None


def _format_footer_reason(footer: FooterStatus) -> str:
    parts = [f"CODEX_STATUS={footer.status}"]
    if footer.summary:
        parts.append(footer.summary)
    if footer.needs_user:
        parts.append("needs user")
    if footer.next_action and footer.next_action != "none":
        parts.append(f"next: {footer.next_action}")

    reason = " | ".join(parts)
    if len(reason) > 180:
        reason = f"{reason[:179]}..."
    return reason
