import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  Archive,
  ArchiveRestore,
  Bot,
  ChevronDown,
  ChevronRight,
  CornerDownLeft,
  Eye,
  EyeOff,
  Folder,
  Pencil,
  Power,
  Save,
  Send,
  X,
} from "lucide-react";
import {
  fetchHealth,
  fetchManagedMode,
  fetchSession,
  fetchSessions,
  patchSessionMetadata,
  sendSessionInput,
  updateManagedMode,
} from "./api";
import type {
  ManagedModeStatus,
  SessionMetadata,
  SessionMetadataPatch,
  HealthResponse,
  SessionDetail,
  SessionInputKey,
  SessionStatus,
  SessionSummary,
} from "./types";

const STATUS_LABELS: Record<SessionStatus, string> = {
  error: "Error",
  needs_input: "Needs Input",
  blocked: "Blocked",
  partial: "Partial",
  done: "Done",
  working: "Working",
  idle: "Inactive",
  unknown: "Unknown",
};

const STATUS_ORDER: SessionStatus[] = [
  "error",
  "needs_input",
  "blocked",
  "partial",
  "done",
  "working",
  "idle",
  "unknown",
];

const DASHBOARD_STATUS_ORDER: SessionStatus[] = [
  "error",
  "needs_input",
  "blocked",
  "working",
  "partial",
  "unknown",
  "idle",
  "done",
];

function App() {
  const path = useLocationPath();
  const detailMatch = path.match(/^\/session\/(.+)$/);

  if (detailMatch) {
    return <SessionDetailPage name={decodeURIComponent(detailMatch[1])} />;
  }

  return <OverviewPage />;
}

function OverviewPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [managedMode, setManagedMode] = useState<ManagedModeStatus | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [managedModeError, setManagedModeError] = useState<string | null>(null);
  const [managedModeBusy, setManagedModeBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [showArchived, setShowArchived] = useState(false);
  const [collapsedGroups, setCollapsedGroups] = useState<string[]>([]);

  useEffect(() => {
    let alive = true;
    let controller: AbortController | null = null;

    async function load() {
      controller?.abort();
      controller = new AbortController();
      try {
        const [healthResult, sessionsResult, managedModeResult] = await Promise.all([
          fetchHealth(controller.signal),
          fetchSessions(controller.signal),
          fetchManagedMode(controller.signal),
        ]);
        if (!alive) return;
        setHealth(healthResult);
        setSessions(sessionsResult.sessions);
        setManagedMode(managedModeResult);
        setError(null);
      } catch (err) {
        if (!alive || (err instanceof DOMException && err.name === "AbortError")) return;
        setError(err instanceof Error ? err.message : "Unable to load sessions");
      } finally {
        if (alive) setLoading(false);
      }
    }

    void load();
    const timer = window.setInterval(load, 2000);
    return () => {
      alive = false;
      controller?.abort();
      window.clearInterval(timer);
    };
  }, []);

  async function toggleManagedMode(enabled: boolean) {
    setManagedModeBusy(true);
    setManagedModeError(null);
    try {
      const result = await updateManagedMode({ enabled });
      setManagedMode(result);
    } catch (err) {
      setManagedModeError(err instanceof Error ? err.message : "Unable to update managed mode");
    } finally {
      setManagedModeBusy(false);
    }
  }

  async function updateMetadata(name: string, patch: SessionMetadataPatch) {
    const metadata = await patchSessionMetadata(name, patch);
    setSessions((current) =>
      current.map((session) => (session.name === name ? applyMetadata(session, metadata) : session)),
    );
    return metadata;
  }

  const visibleSessions = useMemo(
    () => sessions.filter((session) => showArchived || !session.archived),
    [sessions, showArchived],
  );
  const archivedCount = useMemo(
    () => sessions.filter((session) => session.archived).length,
    [sessions],
  );
  const counts = useMemo(() => countByStatus(visibleSessions), [visibleSessions]);
  const groupedSessions = useMemo(() => groupSessions(visibleSessions), [visibleSessions]);

  function toggleGroup(key: string) {
    setCollapsedGroups((current) =>
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key],
    );
  }

  return (
    <main className="app-shell">
      <Header health={health} />

      <ManagedModePanel
        status={managedMode}
        busy={managedModeBusy}
        error={managedModeError}
        onToggle={toggleManagedMode}
      />

      <section className="overview-band" aria-label="Session status summary">
        <div className="summary-grid">
          {STATUS_ORDER.map((status) => (
            <button className={`summary-item summary-${status}`} key={status} type="button">
              <span className={`status-dot status-${status}`} />
              <span className="summary-count">{counts[status] ?? 0}</span>
              <span className="summary-label">{STATUS_LABELS[status]}</span>
            </button>
          ))}
        </div>
      </section>

      {error ? <div className="alert">{error}</div> : null}

      <DenseDashboard sessions={visibleSessions} loading={loading} />

      <section className="session-list" aria-label="tmux sessions">
        <div className="list-head">
          <h2>Sessions</h2>
          <div className="list-actions">
            <span>
              {loading
                ? "Loading"
                : `${visibleSessions.length} visible / ${sessions.length} total`}
            </span>
            <button
              className={`toggle-button ${showArchived ? "is-on" : ""}`}
              type="button"
              onClick={() => setShowArchived((value) => !value)}
            >
              {showArchived ? <EyeOff size={16} /> : <Eye size={16} />}
              {showArchived ? "Hide archived" : `Show archived (${archivedCount})`}
            </button>
          </div>
        </div>

        {visibleSessions.length === 0 && !loading ? (
          <div className="empty-state">
            <strong>{sessions.length === 0 ? "No tmux sessions found" : "No visible sessions"}</strong>
            <span>
              {sessions.length === 0
                ? "Start a tmux session and this page will pick it up on the next refresh."
                : "Archived sessions are hidden. Toggle archived sessions to bring them back."}
            </span>
          </div>
        ) : null}

        <div className="group-list">
          {groupedSessions.map((group) => {
            const collapsed = collapsedGroups.includes(group.key);
            return (
              <section className="session-group" key={group.key}>
                <button
                  className="group-header"
                  type="button"
                  onClick={() => toggleGroup(group.key)}
                >
                  <span className="group-title">
                    {collapsed ? <ChevronRight size={17} /> : <ChevronDown size={17} />}
                    <Folder size={17} />
                    <strong>{group.name}</strong>
                    <span>{group.sessions.length} sessions</span>
                  </span>
                  <span className="group-statuses">
                    {STATUS_ORDER.filter((status) => group.counts[status] > 0).map((status) => (
                      <span className="group-status" key={status}>
                        <span className={`status-dot status-${status}`} />
                        {group.counts[status]}
                      </span>
                    ))}
                  </span>
                </button>

                {collapsed ? null : (
                  <div className="session-grid">
                    {group.sessions.map((session) => (
                      <SessionCard session={session} key={session.name} onPatch={updateMetadata} />
                    ))}
                  </div>
                )}
              </section>
            );
          })}
        </div>
      </section>
    </main>
  );
}

function ManagedModePanel({
  status,
  busy,
  error,
  onToggle,
}: {
  status: ManagedModeStatus | null;
  busy: boolean;
  error: string | null;
  onToggle: (enabled: boolean) => Promise<void>;
}) {
  const enabled = status?.enabled ?? false;
  const visibleError = error || status?.last_error || null;
  const reportLines = status?.report_requested_at ? status.steward_tail : [];

  return (
    <section className={`managed-panel ${enabled ? "is-on" : ""}`} aria-label="Managed mode">
      <div className="managed-main">
        <div className="managed-title">
          <span className="managed-icon">
            <Bot size={18} />
          </span>
          <div>
            <h2>Managed Mode</h2>
            <p>
              {enabled
                ? "Conservative steward is supervising active agents"
                : status?.report_requested_at
                  ? "Steward report requested"
                  : "Steward is off"}
            </p>
          </div>
        </div>
        <button
          className={`toggle-button managed-toggle ${enabled ? "is-on" : ""}`}
          type="button"
          disabled={busy || status === null}
          onClick={() => void onToggle(!enabled)}
        >
          <Power size={16} />
          {busy ? "Updating" : enabled ? "End & report" : "Enable"}
        </button>
      </div>

      <div className="managed-grid">
        <ManagedMetric label="Status" value={enabled ? "Enabled" : status ? "Off" : "Loading"} />
        <ManagedMetric
          label="Steward"
          value={status?.steward_running ? status.steward_session : "Stopped"}
        />
        <ManagedMetric
          label="Interval"
          value={status ? formatInterval(status.interval_seconds) : "Loading"}
        />
        <ManagedMetric
          label="Last Dispatch"
          value={status?.last_dispatch_at ? formatTime(status.last_dispatch_at) : "None"}
        />
        <ManagedMetric
          label="Report"
          value={status?.report_requested_at ? formatTime(status.report_requested_at) : "None"}
        />
      </div>

      {status?.last_summary ? <p className="managed-summary">{status.last_summary}</p> : null}

      {status?.last_targets.length ? (
        <div className="managed-targets" aria-label="Last managed targets">
          {status.last_targets.map((target) => (
            <span key={target}>{target}</span>
          ))}
        </div>
      ) : null}

      {visibleError ? <div className="managed-error">{visibleError}</div> : null}

      {reportLines.length ? (
        <div className="managed-report" aria-label="Managed mode report tail">
          {reportLines.map((line, index) => (
            <div key={`${index}-${line}`}>
              <code>{line || " "}</code>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function ManagedMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="managed-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function DenseDashboard({
  sessions,
  loading,
}: {
  sessions: SessionSummary[];
  loading: boolean;
}) {
  const orderedSessions = useMemo(
    () => [...sessions].sort(compareDashboardSessions),
    [sessions],
  );

  return (
    <section className="dense-dashboard" aria-label="Session progress dashboard">
      <div className="dense-head">
        <h2>Dashboard</h2>
        <span>{loading ? "Loading" : `${sessions.length} visible`}</span>
      </div>

      {orderedSessions.length > 0 ? (
        <div className="dense-grid">
          {orderedSessions.map((session) => (
            <AppLink
              className={`dense-card is-${session.status} ${session.archived ? "is-archived" : ""}`}
              href={`/session/${encodeURIComponent(session.name)}`}
              key={session.name}
            >
              <span className={`status-dot status-${session.status}`} />
              <span className="dense-main">
                <span className="dense-title-row">
                  <strong>{getSessionDisplayName(session)}</strong>
                  <span className={`dense-status dense-status-${session.status}`}>
                    {STATUS_LABELS[session.status]}
                  </span>
                </span>
                <span className="dense-preview">{getSessionSignal(session)}</span>
              </span>
              <span className="dense-meta">
                <span>{formatIdleCompact(session.idle_seconds)}</span>
                <span>{session.group || "Ungrouped"}</span>
              </span>
            </AppLink>
          ))}
        </div>
      ) : (
        <div className="dense-empty">{loading ? "Loading sessions" : "No visible sessions"}</div>
      )}
    </section>
  );
}

function SessionDetailPage({ name }: { name: string }) {
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    let controller: AbortController | null = null;

    async function load() {
      controller?.abort();
      controller = new AbortController();
      try {
        const result = await fetchSession(name, controller.signal);
        if (!alive) return;
        setSession(result);
        setError(null);
      } catch (err) {
        if (!alive || (err instanceof DOMException && err.name === "AbortError")) return;
        setError(err instanceof Error ? err.message : "Unable to load session");
      }
    }

    void load();
    const timer = window.setInterval(load, 1000);
    return () => {
      alive = false;
      controller?.abort();
      window.clearInterval(timer);
    };
  }, [name]);

  async function updateMetadata(targetName: string, patch: SessionMetadataPatch) {
    const metadata = await patchSessionMetadata(targetName, patch);
    setSession((current) =>
      current && current.name === targetName ? applyMetadata(current, metadata) : current,
    );
    return metadata;
  }

  return (
    <main className="app-shell detail-shell">
      <div className="back-row">
        <AppLink className="back-link" href="/">
          Back
        </AppLink>
      </div>

      {error ? <div className="alert">{error}</div> : null}

      <section className="detail-header">
        <div>
          <p className="eyebrow">Session</p>
          <h1>{session ? getSessionDisplayName(session) : name}</h1>
          {session?.note ? <p className="session-subtitle">{session.name}</p> : null}
        </div>
        <div className="detail-actions">
          {session ? (
            <>
              <StatusBadge status={session.status} />
              <SessionControls session={session} onPatch={updateMetadata} />
            </>
          ) : (
            <span className="badge">Loading</span>
          )}
        </div>
      </section>

      {session ? (
        <>
          <section className="detail-note" aria-label="Session annotations">
            <GroupEditor session={session} onPatch={updateMetadata} />
            <NoteEditor session={session} onPatch={updateMetadata} />
          </section>

          <section className="detail-meta" aria-label="Session metadata">
            <MetaItem label="tmux Session" value={session.name} />
            <MetaItem label="Idle" value={formatIdle(session.idle_seconds)} />
            <MetaItem label="Last Activity" value={formatTime(session.last_activity)} />
            <MetaItem label="Command" value={session.current_command ?? "Unknown"} />
            <MetaItem label="Attention" value={session.attention_reason ?? "None"} />
          </section>

          <section className="tail-panel" aria-label="Live tail">
            <div className="tail-head">
              <h2>Live Tail</h2>
              <span>Refreshes every 1s</span>
            </div>
            <div className="tail-output" role="log" aria-live="polite">
              {session.tail.length > 0 ? (
                session.tail.map((line, index) => (
                  <div className="tail-line" key={`${index}-${line}`}>
                    <span className="line-number">{index + 1}</span>
                    <code>{line || " "}</code>
                  </div>
                ))
              ) : (
                <div className="tail-line">
                  <span className="line-number">1</span>
                  <code>No recent output</code>
                </div>
              )}
            </div>
          </section>

          <SessionComposer session={session} />
        </>
      ) : null}
    </main>
  );
}

function SessionComposer({ session }: { session: SessionDetail }) {
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [sentAt, setSentAt] = useState<Date | null>(null);

  useEffect(() => {
    setDraft("");
    setSendError(null);
    setSentAt(null);
  }, [session.name]);

  async function sendText() {
    if (sending || !draft.trim()) return;
    setSending(true);
    setSendError(null);
    try {
      await sendSessionInput(session.name, { text: draft, enter: true });
      setDraft("");
      setSentAt(new Date());
    } catch (err) {
      setSendError(err instanceof Error ? err.message : "Unable to send input");
    } finally {
      setSending(false);
    }
  }

  async function sendKey(key: SessionInputKey) {
    setSending(true);
    setSendError(null);
    try {
      await sendSessionInput(session.name, { key });
      setSentAt(new Date());
    } catch (err) {
      setSendError(err instanceof Error ? err.message : "Unable to send key");
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="interaction-panel" aria-label="Session input">
      <div className="interaction-head">
        <h2>Interact</h2>
        {sentAt ? <span>Sent {formatTime(sentAt.toISOString())}</span> : null}
      </div>
      <form
        className="interaction-form"
        onSubmit={(event) => {
          event.preventDefault();
          void sendText();
        }}
      >
        <textarea
          aria-label="Input for session"
          placeholder="Message or command"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void sendText();
            }
          }}
        />
        <div className="interaction-actions">
          <ActionButton label="Send input" type="submit" disabled={sending || !draft.trim()}>
            <Send size={16} />
            <span>Send</span>
          </ActionButton>
          <ActionButton label="Send Enter" disabled={sending} onClick={() => void sendKey("Enter")}>
            <CornerDownLeft size={16} />
            <span>Enter</span>
          </ActionButton>
          <ActionButton label="Send Ctrl-C" disabled={sending} onClick={() => void sendKey("C-c")}>
            <X size={16} />
            <span>Ctrl+C</span>
          </ActionButton>
        </div>
        {sendError ? <div className="interaction-error">{sendError}</div> : null}
      </form>
    </section>
  );
}

function Header({ health }: { health: HealthResponse | null }) {
  return (
    <header className="topbar">
      <div>
        <p className="eyebrow">tmux control plane</p>
        <h1>Codex tmux Monitor</h1>
      </div>
      <div className="health-group">
        <span className={`health-pill ${health?.tmux_available ? "is-ok" : "is-warn"}`}>
          tmux {health?.tmux_available ? "available" : "missing"}
        </span>
        <span className="health-pill">{health ? `${health.session_count} sessions` : "Checking"}</span>
      </div>
    </header>
  );
}

function SessionCard({
  session,
  onPatch,
}: {
  session: SessionSummary;
  onPatch: (name: string, patch: SessionMetadataPatch) => Promise<SessionMetadata>;
}) {
  const displayName = getSessionDisplayName(session);

  return (
    <article
      className={`session-card is-${session.status} ${session.collapsed ? "is-collapsed" : ""} ${
        session.archived ? "is-archived" : ""
      }`}
    >
      <div className="card-main">
        <AppLink className="session-title" href={`/session/${encodeURIComponent(session.name)}`}>
          <span className={`status-dot status-${session.status}`} />
          <span className="session-title-text">
            <strong>{displayName}</strong>
            {session.note ? <small>{session.name}</small> : null}
          </span>
        </AppLink>
        <div className="card-actions">
          <StatusBadge status={session.status} />
          <SessionControls session={session} onPatch={onPatch} />
        </div>
      </div>
      <div className="session-body">
        <div className="session-annotations">
          <GroupEditor session={session} onPatch={onPatch} compact />
          <NoteEditor session={session} onPatch={onPatch} compact />
        </div>
        {session.collapsed ? null : <p className="preview">{session.preview}</p>}
      </div>
      <div className="card-meta">
        <span>{formatIdle(session.idle_seconds)}</span>
        <span>{formatTime(session.last_activity)}</span>
        {session.note ? <span>{session.name}</span> : null}
        <span>{session.current_command ?? "Unknown command"}</span>
        {session.group ? <span>{session.group}</span> : null}
        {session.archived ? <span>Archived</span> : null}
      </div>
    </article>
  );
}

function SessionControls({
  session,
  onPatch,
}: {
  session: SessionSummary;
  onPatch: (name: string, patch: SessionMetadataPatch) => Promise<SessionMetadata>;
}) {
  const [busy, setBusy] = useState<string | null>(null);

  async function run(key: string, patch: SessionMetadataPatch) {
    setBusy(key);
    try {
      await onPatch(session.name, patch);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="session-actions">
      <ActionButton
        label={session.collapsed ? "Expand session" : "Collapse session"}
        disabled={busy !== null}
        onClick={() => void run("collapsed", { collapsed: !session.collapsed })}
      >
        {session.collapsed ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
        <span>{session.collapsed ? "Expand" : "Collapse"}</span>
      </ActionButton>
      <ActionButton
        label={session.archived ? "Restore session" : "Archive session"}
        disabled={busy !== null}
        onClick={() => void run("archived", { archived: !session.archived })}
      >
        {session.archived ? <ArchiveRestore size={16} /> : <Archive size={16} />}
        <span>{session.archived ? "Restore" : "Archive"}</span>
      </ActionButton>
    </div>
  );
}

function GroupEditor({
  session,
  onPatch,
  compact = false,
}: {
  session: SessionSummary;
  onPatch: (name: string, patch: SessionMetadataPatch) => Promise<SessionMetadata>;
  compact?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(session.group);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!editing) setDraft(session.group);
  }, [editing, session.group]);

  async function saveGroup() {
    setSaving(true);
    try {
      await onPatch(session.name, { group: draft });
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  async function clearGroup() {
    setSaving(true);
    try {
      await onPatch(session.name, { group: "" });
      setDraft("");
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  if (editing) {
    return (
      <form
        className={`group-editor ${compact ? "is-compact" : ""}`}
        onSubmit={(event) => {
          event.preventDefault();
          void saveGroup();
        }}
      >
        <input
          aria-label="Session group"
          maxLength={120}
          placeholder="Project or group name"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <IconButton label="Save group" type="submit" disabled={saving}>
          <Save size={16} />
        </IconButton>
        <IconButton
          label="Cancel group edit"
          disabled={saving}
          onClick={() => {
            setDraft(session.group);
            setEditing(false);
          }}
        >
          <X size={16} />
        </IconButton>
      </form>
    );
  }

  return (
    <div className={`group-row ${compact ? "is-compact" : ""} ${session.group ? "" : "is-empty"}`}>
      <p>
        <Folder size={15} />
        <span>{session.group || "Ungrouped"}</span>
      </p>
      <div className="group-row-actions">
        <ActionButton label={session.group ? "Edit group" : "Set group"} onClick={() => setEditing(true)}>
          <Pencil size={16} />
          <span>{session.group ? "Edit group" : "Set group"}</span>
        </ActionButton>
        {session.group ? (
          <ActionButton label="Clear group" disabled={saving} onClick={() => void clearGroup()}>
            <X size={16} />
            <span>Clear</span>
          </ActionButton>
        ) : null}
      </div>
    </div>
  );
}

function NoteEditor({
  session,
  onPatch,
  compact = false,
}: {
  session: SessionSummary;
  onPatch: (name: string, patch: SessionMetadataPatch) => Promise<SessionMetadata>;
  compact?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(session.note);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!editing) setDraft(session.note);
  }, [editing, session.note]);

  async function saveNote() {
    setSaving(true);
    try {
      await onPatch(session.name, { note: draft });
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  if (editing) {
    return (
      <form
        className={`note-editor ${compact ? "is-compact" : ""}`}
        onSubmit={(event) => {
          event.preventDefault();
          void saveNote();
        }}
      >
        <input
          aria-label="Session display name"
          maxLength={1000}
          placeholder="Display name"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <IconButton label="Save display name" type="submit" disabled={saving}>
          <Save size={16} />
        </IconButton>
        <IconButton
          label="Cancel display name edit"
          disabled={saving}
          onClick={() => {
            setDraft(session.note);
            setEditing(false);
          }}
        >
          <X size={16} />
        </IconButton>
      </form>
    );
  }

  return (
    <div className={`note-row ${compact ? "is-compact" : ""}`}>
      <ActionButton
        label={session.note ? "Rename session" : "Set display name"}
        onClick={() => setEditing(true)}
      >
        <Pencil size={16} />
        <span>{session.note ? "Rename" : "Set name"}</span>
      </ActionButton>
    </div>
  );
}

function ActionButton({
  label,
  children,
  disabled,
  onClick,
  type = "button",
}: {
  label: string;
  children: ReactNode;
  disabled?: boolean;
  onClick?: () => void;
  type?: "button" | "submit";
}) {
  return (
    <button
      className="action-button"
      type={type}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function IconButton({
  label,
  children,
  disabled,
  onClick,
  type = "button",
}: {
  label: string;
  children: ReactNode;
  disabled?: boolean;
  onClick?: () => void;
  type?: "button" | "submit";
}) {
  return (
    <button
      className="icon-button"
      type={type}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function StatusBadge({ status }: { status: SessionStatus }) {
  return <span className={`badge badge-${status}`}>{STATUS_LABELS[status]}</span>;
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="meta-item">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function AppLink({
  href,
  className,
  children,
}: {
  href: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <a
      className={className}
      href={href}
      onClick={(event) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        window.history.pushState({}, "", href);
        window.dispatchEvent(new Event("codex-monitor:navigate"));
      }}
    >
      {children}
    </a>
  );
}

function useLocationPath() {
  const [path, setPath] = useState(window.location.pathname);

  useEffect(() => {
    const update = () => setPath(window.location.pathname);
    window.addEventListener("popstate", update);
    window.addEventListener("codex-monitor:navigate", update);
    return () => {
      window.removeEventListener("popstate", update);
      window.removeEventListener("codex-monitor:navigate", update);
    };
  }, []);

  return path;
}

function countByStatus(sessions: SessionSummary[]) {
  return sessions.reduce<Record<SessionStatus, number>>(
    (acc, session) => {
      acc[session.status] += 1;
      return acc;
    },
    {
      error: 0,
      needs_input: 0,
      blocked: 0,
      partial: 0,
      done: 0,
      working: 0,
      idle: 0,
      unknown: 0,
    },
  );
}

function applyMetadata<T extends SessionSummary>(session: T, metadata: SessionMetadata): T {
  return {
    ...session,
    archived: metadata.archived,
    collapsed: metadata.collapsed,
    group: metadata.group,
    note: metadata.note,
  };
}

function getSessionDisplayName(session: SessionSummary) {
  return session.note.trim() || session.name;
}

interface SessionGroup {
  key: string;
  name: string;
  sessions: SessionSummary[];
  counts: Record<SessionStatus, number>;
}

function groupSessions(sessions: SessionSummary[]): SessionGroup[] {
  const grouped = new Map<string, SessionSummary[]>();
  for (const session of sessions) {
    const groupName = session.group.trim() || "Ungrouped";
    grouped.set(groupName, [...(grouped.get(groupName) ?? []), session]);
  }

  return Array.from(grouped.entries())
    .map(([name, groupSessionsValue]) => ({
      key: name,
      name,
      sessions: groupSessionsValue,
      counts: countByStatus(groupSessionsValue),
    }))
    .sort((a, b) => {
      if (a.name === "Ungrouped") return 1;
      if (b.name === "Ungrouped") return -1;
      const priorityDelta = highestGroupPriority(a) - highestGroupPriority(b);
      if (priorityDelta !== 0) return priorityDelta;
      return a.name.localeCompare(b.name);
    });
}

function highestGroupPriority(group: SessionGroup) {
  for (let index = 0; index < STATUS_ORDER.length; index += 1) {
    if (group.counts[STATUS_ORDER[index]] > 0) return index;
  }
  return STATUS_ORDER.length;
}

function compareDashboardSessions(a: SessionSummary, b: SessionSummary) {
  const priorityDelta = dashboardStatusPriority(a.status) - dashboardStatusPriority(b.status);
  if (priorityDelta !== 0) return priorityDelta;

  const groupDelta = (a.group || "Ungrouped").localeCompare(b.group || "Ungrouped");
  if (groupDelta !== 0) return groupDelta;

  return getSessionDisplayName(a).localeCompare(getSessionDisplayName(b));
}

function dashboardStatusPriority(status: SessionStatus) {
  const index = DASHBOARD_STATUS_ORDER.indexOf(status);
  return index === -1 ? DASHBOARD_STATUS_ORDER.length : index;
}

function getSessionSignal(session: SessionSummary) {
  return session.attention_reason || session.preview || session.current_command || "No recent output";
}

function formatIdle(seconds: number) {
  if (seconds < 60) return `${seconds}s idle`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m idle`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m idle`;
}

function formatIdleCompact(seconds: number) {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes > 0 ? `${hours}h ${remainingMinutes}m` : `${hours}h`;
}

function formatInterval(seconds: number) {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h`;
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

export default App;
