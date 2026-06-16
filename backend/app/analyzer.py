from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .models import SessionStatus


IDLE_AFTER_SECONDS = 120
PREVIEW_LIMIT = 180
SIGNAL_LINE_LIMIT = 16
FOOTER_STATUS_MAP = {
    "done": SessionStatus.DONE,
    "needs_input": SessionStatus.NEEDS_INPUT,
    "blocked": SessionStatus.BLOCKED,
    "error": SessionStatus.ERROR,
    "working": SessionStatus.WORKING,
    "partial": SessionStatus.PARTIAL,
}

NEEDS_INPUT_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"need clarification",
        r"please confirm",
        r"confirm\?",
        r"should i",
        r"which option",
        r"\bchoose\b",
        r"\bselect\b",
        r"continue\?",
        r"\[y/n\]",
    ]
]

ERROR_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\berror\b",
        r"\b[A-Za-z]+Error\b",
        r"\bfailed\b",
        r"\bexception\b",
        r"\bpanic\b",
        r"\bfatal\b",
        r"\btraceback\b",
    ]
]

DONE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\bcompleted\b",
        r"\bdone\b",
        r"\bfinished\b",
        r"\bsuccess\b",
        r"tests passed",
    ]
]

WORKING_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\brunning\b",
        r"\bediting\b",
        r"\bsearching\b",
        r"\banalyzing\b",
        r"\btesting\b",
        r"\bbuilding\b",
    ]
]

NON_ACTIONABLE_ERROR_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"BrokenPipeError",
        r"ConnectionResetError",
        r"Errno 32\].*Broken pipe",
        r"curl: \(23\) Failed writing body",
        r"Failed writing body",
        r"Error response",
        r"\b(errors?|failed|failures?|fatal|exceptions?|tracebacks?)=0\b",
        r"\b0\s+(errors?|failed|failures?|fatal|exceptions?|tracebacks?)\b",
        r"\bno\b.{0,40}\b(error|errors|failed|failure|fatal|exception|traceback)\b",
        r"\bnot\b.{0,40}\b(error|errors|failed|failure|fatal|exception|traceback)\b",
        r"没看到.{0,40}\b(error|errors|failed|failure|fatal|exception|traceback)\b",
        r"没有.{0,40}\b(error|errors|failed|failure|fatal|exception|traceback)\b",
        r"无.{0,40}\b(error|errors|failed|failure|fatal|exception|traceback)\b",
    ]
]

PYTHON_TRACEBACK_LINE_PATTERNS = [
    re.compile(pattern)
    for pattern in [
        r"^Traceback \(most recent call last\):$",
        r'^File ".+", line \d+, in .+',
        r"^\s*self\.",
        r"^\s*super\(\)",
        r"^-{8,}$",
    ]
]


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
    """Classify a tmux session using the architecture's priority order."""

    signal_lines = _signal_lines(tail_text)
    error_lines = _actionable_error_lines(signal_lines)
    searchable_lines = [*signal_lines, current_command or ""]
    preview = make_preview(tail_text)

    if footer := _parse_status_footer(signal_lines):
        status = FOOTER_STATUS_MAP.get(footer.status)
        if status:
            return AnalysisResult(
                status,
                _format_footer_reason(footer),
                preview,
            )

    if match := _first_line_match(ERROR_PATTERNS, error_lines):
        return AnalysisResult(
            SessionStatus.ERROR,
            _format_reason(match.token, match.line),
            preview,
        )

    if match := _first_line_match(NEEDS_INPUT_PATTERNS, searchable_lines):
        return AnalysisResult(
            SessionStatus.NEEDS_INPUT,
            _format_reason(match.token, match.line),
            preview,
        )

    if match := _first_line_match(DONE_PATTERNS, searchable_lines):
        return AnalysisResult(
            SessionStatus.DONE,
            _format_reason(match.token, match.line),
            preview,
        )

    if changed:
        return AnalysisResult(SessionStatus.WORKING, None, preview)

    if idle_seconds >= IDLE_AFTER_SECONDS:
        return AnalysisResult(SessionStatus.IDLE, "No output change for 120s", preview)

    if _first_line_match(WORKING_PATTERNS, searchable_lines):
        return AnalysisResult(SessionStatus.WORKING, None, preview)

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
class PatternMatch:
    token: str
    line: str


@dataclass(frozen=True)
class FooterStatus:
    status: str
    summary: str
    needs_user: Optional[bool]
    next_action: str


def _signal_lines(tail_text: str) -> list[str]:
    lines = [line.strip() for line in tail_text.splitlines() if line.strip()]
    return lines[-SIGNAL_LINE_LIMIT:]


def _parse_status_footer(lines: list[str]) -> Optional[FooterStatus]:
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


def _actionable_error_lines(lines: list[str]) -> list[str]:
    signal_text = "\n".join(lines)
    if not _first_text_match(NON_ACTIONABLE_ERROR_PATTERNS, signal_text):
        return lines

    return [
        line
        for line in lines
        if not _first_text_match(NON_ACTIONABLE_ERROR_PATTERNS, line)
        and not _first_text_match(PYTHON_TRACEBACK_LINE_PATTERNS, line)
    ]


def _first_line_match(
    patterns: list[re.Pattern[str]],
    lines: list[str],
) -> Optional[PatternMatch]:
    for line in reversed(lines):
        for pattern in patterns:
            match = pattern.search(line)
            if match:
                return PatternMatch(token=match.group(0), line=line)
    return None


def _first_text_match(patterns: list[re.Pattern[str]], text: str) -> Optional[str]:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


def _format_reason(token: str, line: str) -> str:
    compact_line = " ".join(line.split())
    if len(compact_line) > 120:
        compact_line = f"{compact_line[:119]}..."
    return f"Matched '{token}' in: {compact_line}"


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
