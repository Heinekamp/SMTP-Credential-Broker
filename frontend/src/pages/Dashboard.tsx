import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { Button, Card, StatTile, StatusBadge } from "../design-system/components";
import { compactTimestamp, parseApiDate } from "../lib/apiDate";
import { fetchHealth } from "../lib/api/health";
import { listMailLog, type MailLogEntry } from "../lib/api/mailLog";
import { listQueue } from "../lib/api/queue";
import { listSenders } from "../lib/api/senders";
import { listLocalUsers } from "../lib/api/localUsers";
import { listUpstreamAccounts, type UpstreamAccount } from "../lib/api/upstreamAccounts";
import { MAIL_STATUS_BADGE } from "./mail-log/statusMapping";

const FAILURE_STATUSES = new Set(["deferred", "bounced", "rejected"]);

function relayStatusMessage(health: { status: string } | undefined, accounts: UpstreamAccount[] | undefined) {
  if (!health || health.status === "ok") {
    return { label: "Operational — all upstream accounts healthy", status: "idle" as const };
  }
  const failing = accounts?.find((a) => a.last_test_result === "failure");
  return {
    label: failing ? `Degraded — "${failing.name}" is failing AUTH` : "Degraded — see Settings for details",
    status: "armed" as const,
  };
}

// Design handoff screen 4. Two mutually exclusive states: guided-empty
// (a genuinely fresh install, nothing created yet) and normal.
export function Dashboard() {
  const navigate = useNavigate();
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: fetchHealth });
  const { data: accounts } = useQuery({ queryKey: ["upstream-accounts"], queryFn: listUpstreamAccounts });
  const { data: senders } = useQuery({ queryKey: ["senders"], queryFn: listSenders });
  const { data: localUsers } = useQuery({ queryKey: ["local-users"], queryFn: listLocalUsers });
  const { data: queue } = useQuery({ queryKey: ["queue"], queryFn: listQueue });
  const { data: recentMail } = useQuery({
    queryKey: ["mail-log", "dashboard-recent"],
    queryFn: () => listMailLog({ limit: 50 }),
  });

  const loaded = accounts && senders && localUsers;
  const isEmpty = loaded && accounts.length === 0 && senders.length === 0 && localUsers.length === 0;

  if (isEmpty) {
    return (
      <Card style={{ maxWidth: 640 }}>
        <h1 style={{ fontSize: "var(--text-lg)", fontWeight: 600, marginTop: 0 }}>
          Welcome — let's get this relay set up.
        </h1>
        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 16 }}>
          <GuidedStep
            title="1. Add an upstream account"
            description="Connect an externally-hosted SMTP mailbox (e.g. a STRATO account) this relay will send through."
            onGo={() => navigate("/upstream-accounts/new")}
          />
          <GuidedStep
            title="2. Add a sender"
            description="Define an address that's allowed to send, tied to one of your upstream accounts."
            onGo={() => navigate("/senders/new")}
          />
          <GuidedStep
            title="3. Create a local SMTP user"
            description="Issue scoped credentials for an internal service and grant it permission to use a sender."
            onGo={() => navigate("/local-users/new")}
          />
        </div>
      </Card>
    );
  }

  const relayStatus = relayStatusMessage(health, accounts);
  const failures = (recentMail?.entries ?? []).filter((e) => FAILURE_STATUSES.has(e.status)).slice(0, 5);
  const successes = (recentMail?.entries ?? []).filter((e) => e.status === "sent").slice(0, 5);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 1200 }}>
      <Card style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <StatusBadge status={relayStatus.status} label={relayStatus.label} />
      </Card>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
        <StatTile label="Upstream Accounts" value={accounts?.length ?? "—"} />
        <StatTile label="Senders" value={senders?.length ?? "—"} />
        <StatTile label="Local SMTP Users" value={localUsers?.length ?? "—"} />
        <StatTile label="Queue Depth" value={queue?.length ?? "—"} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: 12 }}>
        <Card title="Upstream Account Health">
          {(accounts ?? []).length === 0 && (
            <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)" }}>No upstream accounts yet.</p>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {(accounts ?? []).map((account) => (
              <div key={account.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: "var(--text-sm)" }}>{account.name}</span>
                <div style={{ textAlign: "right" }}>
                  <StatusBadge
                    status={account.last_test_result === "failure" ? "fault" : account.last_test_result === "success" ? "idle" : "waiting"}
                    label={account.last_test_result === "failure" ? "Failing" : account.last_test_result === "success" ? "OK" : "Untested"}
                    size="sm"
                  />
                  {account.last_test_at && (
                    <div style={{ color: "var(--text-muted)", fontSize: "var(--text-2xs)" }}>
                      {parseApiDate(account.last_test_at).toLocaleString()}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card title="Recent Delivery Failures">
          {failures.length === 0 && (
            <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)" }}>No recent failures.</p>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {failures.map((entry) => (
              <button
                key={entry.id}
                type="button"
                onClick={() => navigate(`/mail-log?status=${entry.status}`)}
                style={rowButtonStyle}
              >
                <MailRow entry={entry} />
              </button>
            ))}
          </div>
        </Card>

        <Card title="Recent Deliveries">
          {successes.length === 0 && (
            <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)" }}>No recent deliveries.</p>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {successes.map((entry) => (
              <div key={entry.id} style={rowButtonStyle}>
                <MailRow entry={entry} />
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

function GuidedStep({ title, description, onGo }: { title: string; description: string; onGo: () => void }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        gap: 12,
        background: "var(--surface-well)",
        borderRadius: "var(--radius-md)",
        padding: "14px 16px",
      }}
    >
      <div>
        <div style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>{title}</div>
        <div style={{ color: "var(--text-muted)", fontSize: "var(--text-2xs)", marginTop: 2 }}>{description}</div>
      </div>
      <Button variant="accent" onClick={onGo}>
        Go
      </Button>
    </div>
  );
}

const rowButtonStyle = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  gap: 8,
  width: "100%",
  background: "none",
  border: "none",
  padding: 0,
  cursor: "pointer",
  color: "var(--text-body)",
  fontFamily: "var(--font-ui)",
  fontSize: "var(--text-sm)",
  textAlign: "left" as const,
};

// Shared by both Recent Delivery Failures and Recent Deliveries — design
// handoff screen 4: sender -> recipient (truncated, never wrapped, so a
// long address can't push the status badge off the card), the send time
// beneath it, and the status badge each mail_log status already has a
// fixed color/label mapping for (statusMapping.ts).
function MailRow({ entry }: { entry: MailLogEntry }) {
  const badge = MAIL_STATUS_BADGE[entry.status];
  return (
    <>
      <div style={{ minWidth: 0 }}>
        <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {entry.envelope_sender} &rarr; {entry.recipients.join(", ") || "—"}
        </div>
        <div style={{ color: "var(--text-muted)", fontSize: "var(--text-2xs)" }}>
          {compactTimestamp(parseApiDate(entry.timestamp))}
        </div>
      </div>
      <span style={{ flexShrink: 0 }}>
        <StatusBadge status={badge.status} label={badge.label} size="sm" />
      </span>
    </>
  );
}
