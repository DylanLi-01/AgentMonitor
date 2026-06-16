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
