import type {
  HealthResponse,
  ManagedModePatch,
  ManagedModeStatus,
  SessionInputRequest,
  SessionInputResponse,
  SessionDetail,
  SessionMetadata,
  SessionMetadataPatch,
  SessionsResponse,
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    const message = await response.text();
    throw new Error(extractErrorMessage(message) || `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function extractErrorMessage(message: string): string {
  if (!message) return "";
  try {
    const parsed = JSON.parse(message) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
  } catch {
    return message;
  }
  return message;
}

export function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return request<HealthResponse>("/api/health", { signal });
}

export function fetchSessions(signal?: AbortSignal): Promise<SessionsResponse> {
  return request<SessionsResponse>("/api/sessions", { signal });
}

export function fetchManagedMode(signal?: AbortSignal): Promise<ManagedModeStatus> {
  return request<ManagedModeStatus>("/api/managed-mode", { signal });
}

export function updateManagedMode(
  patch: ManagedModePatch,
  signal?: AbortSignal,
): Promise<ManagedModeStatus> {
  return request<ManagedModeStatus>("/api/managed-mode", {
    body: JSON.stringify(patch),
    headers: {
      "Content-Type": "application/json",
    },
    method: "POST",
    signal,
  });
}

export function fetchSession(name: string, signal?: AbortSignal): Promise<SessionDetail> {
  return request<SessionDetail>(`/api/sessions/${encodeURIComponent(name)}`, { signal });
}

export function patchSessionMetadata(
  name: string,
  patch: SessionMetadataPatch,
  signal?: AbortSignal,
): Promise<SessionMetadata> {
  return request<SessionMetadata>(`/api/sessions/${encodeURIComponent(name)}/metadata`, {
    body: JSON.stringify(patch),
    headers: {
      "Content-Type": "application/json",
    },
    method: "PATCH",
    signal,
  });
}

export function sendSessionInput(
  name: string,
  payload: SessionInputRequest,
  signal?: AbortSignal,
): Promise<SessionInputResponse> {
  return request<SessionInputResponse>(`/api/sessions/${encodeURIComponent(name)}/input`, {
    body: JSON.stringify(payload),
    headers: {
      "Content-Type": "application/json",
    },
    method: "POST",
    signal,
  });
}
