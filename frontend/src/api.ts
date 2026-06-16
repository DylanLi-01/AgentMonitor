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
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch (err) {
    if (isAbortError(err, init.signal)) throw err;
    throw new Error(formatNetworkError(err));
  }

  if (!response.ok) {
    const message = await response.text();
    throw new Error(extractErrorMessage(message) || `Request failed with ${response.status}`);
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    const message = await response.text();
    throw new Error(extractUnexpectedContentMessage(message, response.url, contentType));
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

export function isAbortError(err: unknown, signal?: AbortSignal | null): boolean {
  if (signal?.aborted) return true;
  if (err instanceof DOMException && err.name === "AbortError") return true;
  if (!(err instanceof Error)) return false;
  return err.name === "AbortError";
}

function formatNetworkError(err: unknown): string {
  const message = err instanceof Error ? err.message : "";
  if (message === "Load failed" || message === "Failed to fetch") {
    return "Network request failed. If this is the Highway URL, refresh the page and re-authenticate with Cloudflare Access.";
  }
  return message || "Network request failed.";
}

function extractUnexpectedContentMessage(message: string, url: string, contentType: string): string {
  if (message.includes("Cloudflare Access") || url.includes("cloudflareaccess.com")) {
    return "Highway authentication expired. Refresh the page and re-authenticate with Cloudflare Access.";
  }
  return `Expected JSON from the API but received ${contentType || "unknown content type"}.`;
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
