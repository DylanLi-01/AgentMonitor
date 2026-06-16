from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from typing import Optional

from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    ERROR = "error"
    NEEDS_INPUT = "needs_input"
    BLOCKED = "blocked"
    PARTIAL = "partial"
    DONE = "done"
    WORKING = "working"
    IDLE = "idle"
    UNKNOWN = "unknown"


STATUS_PRIORITY: dict[SessionStatus, int] = {
    SessionStatus.ERROR: 0,
    SessionStatus.NEEDS_INPUT: 1,
    SessionStatus.BLOCKED: 2,
    SessionStatus.PARTIAL: 3,
    SessionStatus.DONE: 4,
    SessionStatus.WORKING: 5,
    SessionStatus.IDLE: 6,
    SessionStatus.UNKNOWN: 7,
}


class HealthResponse(BaseModel):
    ok: bool = True
    tmux_available: bool
    session_count: int = 0


class SessionSummary(BaseModel):
    name: str
    status: SessionStatus
    idle_seconds: int = Field(ge=0)
    last_activity: datetime
    preview: str
    attention_reason: Optional[str] = None
    current_command: Optional[str] = None
    archived: bool = False
    collapsed: bool = False
    group: str = ""
    note: str = ""


class SessionsResponse(BaseModel):
    sessions: list[SessionSummary]


class SessionDetail(BaseModel):
    name: str
    status: SessionStatus
    idle_seconds: int = Field(ge=0)
    last_activity: datetime
    preview: str
    attention_reason: Optional[str] = None
    current_command: Optional[str] = None
    archived: bool = False
    collapsed: bool = False
    group: str = ""
    note: str = ""
    tail: list[str]


class SessionMetadata(BaseModel):
    archived: bool = False
    collapsed: bool = False
    group: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=1000)


class SessionMetadataPatch(BaseModel):
    archived: Optional[bool] = None
    collapsed: Optional[bool] = None
    group: Optional[str] = Field(default=None, max_length=120)
    note: Optional[str] = Field(default=None, max_length=1000)


class SessionInputRequest(BaseModel):
    text: str = Field(default="", max_length=20000)
    enter: bool = False
    key: Optional[Literal["Enter", "Tab", "Escape", "C-c"]] = None


class SessionInputResponse(BaseModel):
    ok: bool = True
