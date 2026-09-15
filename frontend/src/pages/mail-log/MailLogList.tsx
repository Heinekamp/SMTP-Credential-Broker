import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { Button, Card, Select, StatusBadge, TextInput } from "../../design-system/components";
import { skeletonBarStyle, tableStyle, tdStyle, thStyle } from "../../design-system/table";
import { parseApiDate } from "../../lib/apiDate";
import { listLocalUsers } from "../../lib/api/localUsers";
import { listMailLog, type MailStatus } from "../../lib/api/mailLog";
import { listUpstreamAccounts } from "../../lib/api/upstreamAccounts";
import { MAIL_STATUS_BADGE } from "./statusMapping";

const PAGE_SIZE = 100;

/** Delays applying a fast-changing value (a search box) so a query only
 * re-fires once typing pauses, rather than once per keystroke. */
function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

// Design handoff §8. Previously fetched one fixed window of the 200 most
// recent rows and filtered client-side — the backend's GET /api/mail-log
// only supported exact envelope_sender equality and a numeric
// local_smtp_user_id, so there was no way to search or page further back.
// Now filters and pages server-side, matching what the API actually
// supports (substring search on sender/recipient, a date range, real
// offset/limit pagination).
export function MailLogList() {
  const navigate = useNavigate();

  const [status, setStatus] = useState<MailStatus | "all">("all");
  const [senderFilter, setSenderFilter] = useState("");
  const [recipientFilter, setRecipientFilter] = useState("");
  const [localUserId, setLocalUserId] = useState("");
  const [offset, setOffset] = useState(0);

  const debouncedSender = useDebounced(senderFilter, 300);
  const debouncedRecipient = useDebounced(recipientFilter, 300);

  const { data: localUsers } = useQuery({ queryKey: ["local-users"], queryFn: listLocalUsers });
  const { data: upstreamAccounts } = useQuery({ queryKey: ["upstream-accounts"], queryFn: listUpstreamAccounts });
  const localUserById = useMemo(() => new Map((localUsers ?? []).map((u) => [u.id, u])), [localUsers]);
  const accountById = new Map((upstreamAccounts ?? []).map((a) => [a.id, a]));

  const filter = {
    status: status === "all" ? undefined : status,
    envelope_sender: debouncedSender.trim() || undefined,
    recipient: debouncedRecipient.trim() || undefined,
    local_smtp_user_id: localUserId ? Number(localUserId) : undefined,
    limit: PAGE_SIZE,
    offset,
  };

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["mail-log", filter],
    queryFn: () => listMailLog(filter),
  });

  function resetAndFilter(apply: () => void) {
    apply();
    setOffset(0);
  }

  const total = data?.total ?? 0;
  const showingFrom = total === 0 ? 0 : offset + 1;
  const showingTo = Math.min(offset + PAGE_SIZE, total);

  return (
    <div style={{ maxWidth: 1300 }}>
      <h1 style={{ fontSize: "var(--text-lg)", fontWeight: 600, marginBottom: 12 }}>Mail Log</h1>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
        <Select
          value={status}
          onChange={(e) => resetAndFilter(() => setStatus(e.target.value as MailStatus | "all"))}
        >
          <option value="all">All statuses</option>
          <option value="sent">Sent</option>
          <option value="queued">Queued</option>
          <option value="deferred">Deferred</option>
          <option value="bounced">Bounced</option>
          <option value="rejected">Rejected</option>
        </Select>
        <TextInput
          placeholder="Sender contains…"
          value={senderFilter}
          onChange={(e) => {
            setSenderFilter(e.target.value);
            setOffset(0);
          }}
          aria-label="Filter by sender"
        />
        <TextInput
          placeholder="Recipient contains…"
          value={recipientFilter}
          onChange={(e) => {
            setRecipientFilter(e.target.value);
            setOffset(0);
          }}
          aria-label="Filter by recipient"
        />
        <Select
          value={localUserId}
          onChange={(e) => resetAndFilter(() => setLocalUserId(e.target.value))}
          aria-label="Filter by local user"
        >
          <option value="">All local users</option>
          {(localUsers ?? []).map((u) => (
            <option key={u.id} value={u.id}>
              {u.name}
            </option>
          ))}
        </Select>
      </div>

      {isLoading && (
        <Card>
          <div style={skeletonBarStyle} />
          <div style={skeletonBarStyle} />
          <div style={skeletonBarStyle} />
        </Card>
      )}

      {isError && (
        <Card style={{ borderLeft: "3px solid var(--status-fault)" }}>
          <p style={{ margin: 0, fontWeight: 600 }}>Couldn't load the mail log.</p>
          <p style={{ margin: "4px 0 12px", color: "var(--text-muted)", fontSize: "var(--text-sm)" }}>
            This is a connectivity/API issue, not a sign that there's no data.
          </p>
          <button type="button" onClick={() => refetch()} style={{ cursor: "pointer" }}>
            Retry
          </button>
        </Card>
      )}

      {data && data.entries.length === 0 && (
        <Card style={{ maxWidth: 480 }}>
          <p style={{ margin: 0, color: "var(--text-muted)" }}>No mail log entries match the current filters.</p>
        </Card>
      )}

      {data && data.entries.length > 0 && (
        <>
          <table style={tableStyle}>
            <thead>
              <tr>
                {["Time", "Local User", "Sender", "Recipients", "Upstream", "Status", "Queue ID", ""].map((label) => (
                  <th key={label} style={thStyle}>
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.entries.map((entry) => {
                const badge = MAIL_STATUS_BADGE[entry.status];
                const user = entry.local_smtp_user_id ? localUserById.get(entry.local_smtp_user_id) : undefined;
                const account = entry.upstream_account_id ? accountById.get(entry.upstream_account_id) : undefined;
                return (
                  <tr key={entry.id}>
                    <td style={tdStyle}>{parseApiDate(entry.timestamp).toLocaleString()}</td>
                    <td style={tdStyle}>{user?.name ?? "—"}</td>
                    <td style={tdStyle}>{entry.envelope_sender}</td>
                    <td style={tdStyle}>{entry.recipients.join(", ")}</td>
                    <td style={tdStyle}>{account?.name ?? "—"}</td>
                    <td style={tdStyle}>
                      <StatusBadge status={badge.status} label={badge.label} size="sm" />
                    </td>
                    <td style={{ ...tdStyle, fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
                      {entry.queue_id}
                    </td>
                    <td style={tdStyle}>
                      <button
                        type="button"
                        onClick={() => navigate(`/mail-log/${entry.id}`)}
                        style={detailsButtonStyle}
                      >
                        Details
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 12 }}>
            <Button variant="default" onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} disabled={offset === 0}>
              Previous
            </Button>
            <Button
              variant="default"
              onClick={() => setOffset(offset + PAGE_SIZE)}
              disabled={offset + PAGE_SIZE >= total}
            >
              Next
            </Button>
            <span style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)" }}>
              {showingFrom}–{showingTo} of {total}
            </span>
          </div>
        </>
      )}
    </div>
  );
}

const detailsButtonStyle = {
  background: "var(--surface-control)",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--radius-md)",
  padding: "6px 10px",
  color: "var(--text-body)",
  cursor: "pointer",
  fontSize: "var(--text-sm)",
  fontFamily: "var(--font-ui)",
};
