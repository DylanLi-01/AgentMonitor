export type SessionStatus =
  | "working"
  | "idle"
  | "needs_input"
  | "blocked"
  | "partial"
  | "error"
  | "done"
  | "unknown";

export interface HealthResponse {
  ok: boolean;
  tmux_available: boolean;
  session_count: number;
}

export interface SessionSummary {
  name: string;
  status: SessionStatus;
  idle_seconds: number;
  last_activity: string;
  preview: string;
  attention_reason: string | null;
  current_command: string | null;
  archived: boolean;
  collapsed: boolean;
  group: string;
  note: string;
}

export interface SessionsResponse {
  sessions: SessionSummary[];
}

export interface SessionDetail extends SessionSummary {
  tail: string[];
}

export interface SessionMetadata {
  archived: boolean;
  collapsed: boolean;
  group: string;
  note: string;
}

export interface SessionMetadataPatch {
  archived?: boolean;
  collapsed?: boolean;
  group?: string;
  note?: string;
}

export type SessionInputKey = "Enter" | "Tab" | "Escape" | "C-c";

export interface SessionInputRequest {
  text?: string;
  enter?: boolean;
  key?: SessionInputKey;
}

export interface SessionInputResponse {
  ok: boolean;
}

export interface ManagedModeStatus {
  enabled: boolean;
  steward_session: string;
  interval_seconds: number;
  last_dispatch_at: string | null;
  report_requested_at: string | null;
  last_error: string | null;
  last_summary: string;
  last_targets: string[];
  updated_at: string;
  steward_running: boolean;
  steward_tail: string[];
}

export interface ManagedModePatch {
  enabled?: boolean;
  interval_seconds?: number;
}
