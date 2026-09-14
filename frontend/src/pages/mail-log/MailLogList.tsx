import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { Card, Select, StatusBadge, TextInput } from "../../design-system/components";
import { skeletonBarStyle, tableStyle, tdStyle, thStyle } from "../../design-system/table";
import { parseApiDate } from "../../lib/apiDate";
import { listLocalUsers } from "../../lib/api/localUsers";
import { listMailLog, type MailStatus } from "../../lib/api/mailLog";
import { listUpstreamAccounts } from "../../lib/api/upstreamAccounts";
import { MAIL_STATUS_BADGE } from "./statusMapping";

// Design handoff §8. The backend's GET /api/mail-log only supports exact
// envelope_sender equality and a numeric local_smtp_user_id, not the
// substring/free-text search this filter row calls for — rather than
// growing the API surface for it, this fetches one bounded recent window
// (status included) and applies all four filters client-side, uniformly,
// which also happens to make them genuinely "live" with no extra
// round-trips per keystroke.
export function MailLogList() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const [status, setStatus] = useState<MailStatus | "all">((searchParams.get("status") as MailStatus) || "all");
  const [senderFilter, setSenderFilter] = useState("");
  const [recipientFilter, setRecipientFilter] = useState("");
  const [localUserFilter, setLocalUserFilter] = useState("");

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["mail-log", "recent"],
    queryFn: () => listMailLog({ limit: 200 }),
  });
  const { data: localUsers } = useQuery({ queryKey: ["local-users"], queryFn: listLocalUsers });
  const { data: upstreamAccounts } = useQuery({ queryKey: ["upstream-accounts"], queryFn: listUpstreamAccounts });

  const localUserById = useMemo(() => new Map((localUsers ?? []).map((u) => [u.id, u])), [localUsers]);
  const accountById = new Map((upstreamAccounts ?? []).map((a) => [a.id, a]));

  const filtered = useMemo(() => {
    const entries = data?.entries ?? [];
    const senderNeedle = senderFilter.trim().toLowerCase();
    const recipientNeedle = recipientFilter.trim().toLowerCase();
    const userNeedle = localUserFilter.trim().toLowerCase();

    return entries.filter((entry) => {
      if (status !== "all" && entry.status !== status) return false;
      if (senderNeedle && !entry.envelope_sender.toLowerCase().includes(senderNeedle)) return false;
      if (recipientNeedle && !entry.recipients.some((r) => r.toLowerCase().includes(recipientNeedle))) return false;
      if (userNeedle) {
        const user = entry.local_smtp_user_id ? localUserById.get(entry.local_smtp_user_id) : undefined;
        const haystack = `${user?.name ?? ""} ${user?.username ?? ""}`.toLowerCase();
        if (!haystack.includes(userNeedle)) return false;
      }
      return true;
    });
  }, [data, status, senderFilter, recipientFilter, localUserFilter, localUserById]);

  return (
    <div style={{ maxWidth: 1300 }}>
      <h1 style={{ fontSize: "var(--text-lg)", fontWeight: 600, marginBottom: 12 }}>Mail Log</h1>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
        <Select value={status} onChange={(e) => setStatus(e.target.value as MailStatus | "all")}>
          <option value="all">All statuses</option>
          <option value="sent">Sent</option>
          <option value="queued">Queued</option>
          <option value="deferred">Deferred</option>
          <option value="bounced">Bounced</option>
          <option value="rejected">Rejected</option>
        </Select>
        <TextInput
          placeholder="Sender"
          value={senderFilter}
          onChange={(e) => setSenderFilter(e.target.value)}
          aria-label="Filter by sender"
        />
        <TextInput
          placeholder="Recipient"
          value={recipientFilter}
          onChange={(e) => setRecipientFilter(e.target.value)}
          aria-label="Filter by recipient"
        />
        <TextInput
          placeholder="Local user"
          value={localUserFilter}
          onChange={(e) => setLocalUserFilter(e.target.value)}
          aria-label="Filter by local user"
        />
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

      {data && filtered.length === 0 && (
        <Card style={{ maxWidth: 480 }}>
          <p style={{ margin: 0, color: "var(--text-muted)" }}>No mail log entries match the current filters.</p>
        </Card>
      )}

      {data && filtered.length > 0 && (
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
            {filtered.map((entry) => {
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
                    <button type="button" onClick={() => navigate(`/mail-log/${entry.id}`)} style={detailsButtonStyle}>
                      Details
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
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
