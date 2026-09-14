import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { Button, Card, StatusBadge } from "../../design-system/components";
import { parseApiDate } from "../../lib/apiDate";
import { listLocalUsers } from "../../lib/api/localUsers";
import { listMailLog } from "../../lib/api/mailLog";
import { listUpstreamAccounts } from "../../lib/api/upstreamAccounts";
import { MAIL_STATUS_BADGE } from "./statusMapping";

// Design handoff §8's detail view — full field list, then (only when the
// row has an error) a distinct error panel with the full raw error text,
// so an auth problem, a permission problem, and an upstream/recipient
// problem all stay tellable apart at a glance.
export function MailLogDetail() {
  const params = useParams<{ id: string }>();
  const entryId = Number(params.id);
  const navigate = useNavigate();

  // Shares the same query key/cache as the list screen — no separate
  // by-id endpoint exists (or is needed): the list response already
  // carries every field this view shows.
  const { data } = useQuery({ queryKey: ["mail-log", "recent"], queryFn: () => listMailLog({ limit: 200 }) });
  const { data: localUsers } = useQuery({ queryKey: ["local-users"], queryFn: listLocalUsers });
  const { data: upstreamAccounts } = useQuery({ queryKey: ["upstream-accounts"], queryFn: listUpstreamAccounts });

  const entry = data?.entries.find((e) => e.id === entryId);

  if (!entry) {
    return (
      <Card style={{ maxWidth: 560 }}>
        <p style={{ margin: 0, color: "var(--text-muted)" }}>
          This entry isn't in the currently loaded mail log window.
        </p>
        <Button variant="default" onClick={() => navigate("/mail-log")} style={{ marginTop: 16 }}>
          Back to Mail Log
        </Button>
      </Card>
    );
  }

  const badge = MAIL_STATUS_BADGE[entry.status];
  const user = entry.local_smtp_user_id ? localUsers?.find((u) => u.id === entry.local_smtp_user_id) : undefined;
  const account = entry.upstream_account_id ? upstreamAccounts?.find((a) => a.id === entry.upstream_account_id) : undefined;

  return (
    <Card style={{ maxWidth: 560 }}>
      <h1 style={{ fontSize: "var(--text-lg)", fontWeight: 600, marginTop: 0, marginBottom: 16 }}>Mail Log Entry</h1>

      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 16 }}>
        <Field label="Time" value={parseApiDate(entry.timestamp).toLocaleString()} />
        <Field label="Local User" value={user ? `${user.name} (${user.username})` : "—"} />
        <Field label="Sender" value={entry.envelope_sender} />
        <Field label="Recipients" value={entry.recipients.join(", ")} />
        <Field label="Upstream" value={account?.name ?? "—"} />
        <div>
          <FieldLabel>Status</FieldLabel>
          <StatusBadge status={badge.status} label={badge.label} />
        </div>
        <Field label="Queue ID" value={entry.queue_id} mono />
      </div>

      {entry.error && (
        <div
          style={{
            background: "var(--surface-well)",
            borderRadius: "var(--radius-md)",
            padding: 14,
            marginBottom: 16,
          }}
        >
          <div style={{ fontSize: "var(--text-2xs)", textTransform: "uppercase", letterSpacing: "var(--tracking-label)", color: "var(--text-muted)", marginBottom: 6 }}>
            Error
          </div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-sm)", color: "var(--status-fault)", whiteSpace: "pre-wrap" }}>
            {entry.error}
          </div>
        </div>
      )}

      <Button variant="default" onClick={() => navigate("/mail-log")}>
        Back to Mail Log
      </Button>
    </Card>
  );
}

function FieldLabel({ children }: { children: string }) {
  return (
    <div style={{ fontSize: "var(--text-2xs)", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "var(--tracking-label)" }}>
      {children}
    </div>
  );
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <FieldLabel>{label}</FieldLabel>
      <div style={{ fontSize: "var(--text-sm)", fontFamily: mono ? "var(--font-mono)" : undefined }}>{value}</div>
    </div>
  );
}
