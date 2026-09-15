import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Button, Card, Select, TextInput } from "../../design-system/components";
import { skeletonBarStyle, tableStyle, tdStyle, thStyle } from "../../design-system/table";
import { parseApiDate } from "../../lib/apiDate";
import { listAdmins } from "../../lib/api/admins";
import { listAuditLog } from "../../lib/api/auditLog";

const PAGE_SIZE = 50;

const TARGET_TYPES = [
  "admin_user",
  "alert",
  "config_generation",
  "local_smtp_user",
  "relay_settings",
  "sender",
  "upstream_account",
  "user_sender_permission",
];

export function AuditLogList() {
  const [action, setAction] = useState("");
  const [targetType, setTargetType] = useState("");
  const [adminUserId, setAdminUserId] = useState("");
  const [offset, setOffset] = useState(0);

  const { data: admins } = useQuery({ queryKey: ["admins"], queryFn: listAdmins });

  const filter = {
    action: action.trim() || undefined,
    target_type: targetType || undefined,
    admin_user_id: adminUserId ? Number(adminUserId) : undefined,
    limit: PAGE_SIZE,
    offset,
  };

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["audit-log", filter],
    queryFn: () => listAuditLog(filter),
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
      <h1 style={{ fontSize: "var(--text-lg)", fontWeight: 600, marginBottom: 4 }}>Audit Log</h1>
      <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)", marginTop: 0, marginBottom: 12 }}>
        Every administrative action taken through this console, in order.
      </p>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
        <TextInput
          placeholder="Action (exact, e.g. sender.delete)"
          value={action}
          onChange={(e) => resetAndFilter(() => setAction(e.target.value))}
          aria-label="Filter by action"
          style={{ minWidth: 220 }}
        />
        <Select
          value={targetType}
          onChange={(e) => resetAndFilter(() => setTargetType(e.target.value))}
          aria-label="Filter by target type"
        >
          <option value="">All target types</option>
          {TARGET_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </Select>
        <Select
          value={adminUserId}
          onChange={(e) => resetAndFilter(() => setAdminUserId(e.target.value))}
          aria-label="Filter by admin"
        >
          <option value="">All admins</option>
          {(admins ?? []).map((a) => (
            <option key={a.id} value={a.id}>
              {a.email}
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
          <p style={{ margin: 0, fontWeight: 600 }}>Couldn't load the audit log.</p>
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
          <p style={{ margin: 0, color: "var(--text-muted)" }}>No audit log entries match the current filters.</p>
        </Card>
      )}

      {data && data.entries.length > 0 && (
        <>
          <table style={tableStyle}>
            <thead>
              <tr>
                {["Time", "Admin", "Action", "Target", "Detail", "IP"].map((label) => (
                  <th key={label} style={thStyle}>
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.entries.map((entry) => (
                <tr key={entry.id}>
                  <td style={{ ...tdStyle, whiteSpace: "nowrap" }}>{parseApiDate(entry.timestamp).toLocaleString()}</td>
                  <td style={tdStyle}>{entry.admin_email ?? "System"}</td>
                  <td style={{ ...tdStyle, fontFamily: "var(--font-mono)" }}>{entry.action}</td>
                  <td style={tdStyle}>
                    {entry.target_type ? `${entry.target_type}${entry.target_id !== null ? ` #${entry.target_id}` : ""}` : "—"}
                  </td>
                  <td
                    style={{
                      ...tdStyle,
                      color: "var(--text-muted)",
                      fontSize: "var(--text-2xs)",
                      maxWidth: 320,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                    title={entry.detail ? JSON.stringify(entry.detail) : undefined}
                  >
                    {entry.detail ? JSON.stringify(entry.detail) : "—"}
                  </td>
                  <td style={{ ...tdStyle, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                    {entry.ip_address ?? "—"}
                  </td>
                </tr>
              ))}
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
