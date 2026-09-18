import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, Select, StatusBadge } from "../../design-system/components";
import { skeletonBarStyle, tableStyle, tdStyle, thStyle } from "../../design-system/table";
import { ApiError } from "../../lib/apiClient";
import { parseApiDate } from "../../lib/apiDate";
import { generateConfig, listConfigGenerations } from "../../lib/api/config";
import { fetchHealth } from "../../lib/api/health";
import { fetchNotificationSettings, updateNotificationSettings } from "../../lib/api/notificationSettings";
import { fetchSystemStatus } from "../../lib/api/system";

const RETENTION_OPTIONS: { label: string; value: string }[] = [
  { label: "Keep forever", value: "" },
  { label: "30 days", value: "30" },
  { label: "90 days", value: "90" },
  { label: "365 days", value: "365" },
];

// Design handoff §10's System tab. Rotate Key stays a disabled control
// permanently, not a deferred one: security-model.md §2 makes
// `relay rotate-encryption-key` the CLI the *only* supported way to
// rotate the key (it needs the old/new key *files* on the host/container
// filesystem, which a browser button click has no way to supply) — see
// core/cli.py's rotate-encryption-key command.
export function SystemTab() {
  const queryClient = useQueryClient();
  const { data: systemStatus } = useQuery({ queryKey: ["system-status"], queryFn: fetchSystemStatus });
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: fetchHealth });
  const { data: generations, isLoading } = useQuery({ queryKey: ["config-generations"], queryFn: listConfigGenerations });
  const [generateError, setGenerateError] = useState<string | null>(null);

  const generate = useMutation({
    mutationFn: generateConfig,
    onSuccess: () => {
      setGenerateError(null);
      queryClient.invalidateQueries({ queryKey: ["health"] });
      queryClient.invalidateQueries({ queryKey: ["config-generations"] });
    },
    onError: (err) => {
      setGenerateError(
        err instanceof ApiError && err.status === 503
          ? "Postfix's control surface is unreachable — check that the postfix container is running."
          : "Config generation failed — see the history below for details.",
      );
    },
  });

  const { data: notificationSettings } = useQuery({
    queryKey: ["notification-settings"],
    queryFn: fetchNotificationSettings,
  });
  const [mailLogRetention, setMailLogRetention] = useState("");
  const [auditLogRetention, setAuditLogRetention] = useState("");
  const [retentionSaved, setRetentionSaved] = useState(false);

  // Adjusts local state when the fetched settings change, without an
  // Effect — https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
  const [prevNotificationSettings, setPrevNotificationSettings] = useState(notificationSettings);
  if (notificationSettings !== prevNotificationSettings) {
    setPrevNotificationSettings(notificationSettings);
    if (notificationSettings) {
      setMailLogRetention(notificationSettings.mail_log_retention_days?.toString() ?? "");
      setAuditLogRetention(notificationSettings.audit_log_retention_days?.toString() ?? "");
    }
  }

  const saveRetention = useMutation({
    mutationFn: () =>
      updateNotificationSettings({
        mail_log_retention_days: mailLogRetention === "" ? null : Number(mailLogRetention),
        audit_log_retention_days: auditLogRetention === "" ? null : Number(auditLogRetention),
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["notification-settings"], data);
      setRetentionSaved(true);
    },
  });

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 12 }}>
      <Card title="Encryption Key">
        <StatusBadge
          status={systemStatus?.encryption_key_configured ? "idle" : "fault"}
          label={systemStatus?.encryption_key_configured ? "Configured" : "Not configured"}
        />
        <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)", marginTop: 10 }}>
          Used to encrypt stored upstream credentials. Never displayed, even partially.
        </p>
        <Button variant="warn" disabled title="Run `relay rotate-encryption-key` from the CLI instead — it needs key files on disk, which a browser can't supply">
          Rotate Key
        </Button>
      </Card>

      <Card title="Postfix / System">
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div>
            <div style={fieldLabelStyle}>Postfix Version</div>
            <div style={{ fontSize: "var(--text-sm)" }}>{systemStatus?.postfix_version ?? "Unknown"}</div>
          </div>
          <div>
            <div style={fieldLabelStyle}>Config Validation</div>
            <StatusBadge
              status={health?.last_generation_result === "fail" ? "fault" : "idle"}
              label={health?.last_generation_result === "fail" ? "Failing" : "Passing"}
              size="sm"
            />
          </div>
          <div>
            <div style={fieldLabelStyle}>Postfix Running</div>
            <StatusBadge
              status={health?.postfix_running.ok ? "idle" : "waiting"}
              label={health?.postfix_running.ok ? "Yes" : "No"}
              size="sm"
            />
          </div>
          <div>
            <div style={fieldLabelStyle}>Config In Sync</div>
            <StatusBadge
              status={health?.config_in_sync.ok ? "idle" : "fault"}
              label={health?.config_in_sync.ok ? "Yes" : "Out of sync"}
              size="sm"
            />
            {health && !health.config_in_sync.ok && (
              <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)", marginTop: 6 }}>
                {health.config_in_sync.detail}
              </p>
            )}
          </div>
          {generations && generations.length > 0 && (
            <div>
              <div style={fieldLabelStyle}>Last Generation</div>
              <div style={{ fontSize: "var(--text-sm)" }}>{parseApiDate(generations[0].generated_at).toLocaleString()}</div>
            </div>
          )}
          <div>
            <Button variant="accent" onClick={() => generate.mutate()} disabled={generate.isPending}>
              {generate.isPending ? "Generating…" : "Generate & Apply"}
            </Button>
            {generateError && (
              <p style={{ color: "var(--status-fault)", fontSize: "var(--text-sm)", marginTop: 6 }}>{generateError}</p>
            )}
            {generate.isSuccess && !generateError && (
              <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)", marginTop: 6 }}>
                {generate.data.success ? "Applied." : "Validation failed — see history below."}
              </p>
            )}
          </div>
        </div>
      </Card>

      <Card title="Data Retention">
        <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)", marginTop: 0 }}>
          Automatically deletes old Mail Log and Audit Log entries. Off by default — nothing is ever deleted
          until you set a window here.
        </p>
        <div style={fieldLabelStyle}>Mail Log</div>
        <Select
          value={mailLogRetention}
          onChange={(e) => setMailLogRetention(e.target.value)}
          style={{ width: "100%", marginBottom: 12 }}
        >
          {RETENTION_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </Select>
        <div style={fieldLabelStyle}>Audit Log</div>
        <Select
          value={auditLogRetention}
          onChange={(e) => setAuditLogRetention(e.target.value)}
          style={{ width: "100%", marginBottom: 16 }}
        >
          {RETENTION_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </Select>
        <Button
          variant="accent"
          onClick={() => {
            setRetentionSaved(false);
            saveRetention.mutate();
          }}
          disabled={saveRetention.isPending}
        >
          {saveRetention.isPending ? "Saving…" : "Save"}
        </Button>
        {retentionSaved && !saveRetention.isPending && (
          <span style={{ marginLeft: 10, color: "var(--text-muted)", fontSize: "var(--text-sm)" }}>Saved.</span>
        )}
        {saveRetention.isError && (
          <span style={{ marginLeft: 10, color: "var(--status-fault)", fontSize: "var(--text-sm)" }}>
            Could not save.
          </span>
        )}
      </Card>

      <Card title="Config Generation History" wide>
        {isLoading && <div style={skeletonBarStyle} />}
        {generations && generations.length === 0 && (
          <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)" }}>No generations recorded yet.</p>
        )}
        {generations && generations.length > 0 && (
          <table style={tableStyle}>
            <thead>
              <tr>
                {["Time", "Result", "Applied", "Detail"].map((label) => (
                  <th key={label} style={thStyle}>
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {generations.map((gen) => (
                <tr key={gen.id}>
                  <td style={tdStyle}>{parseApiDate(gen.generated_at).toLocaleString()}</td>
                  <td style={tdStyle}>
                    <StatusBadge
                      status={gen.validation_result === "pass" ? "idle" : "fault"}
                      label={gen.validation_result === "pass" ? "Pass" : "Fail"}
                      size="sm"
                    />
                  </td>
                  <td style={tdStyle}>{gen.applied ? "Yes" : "No"}</td>
                  <td style={tdStyle}>
                    {/* A successful generation's detail is the full
                       `postconf -n` dump (everything that was actually
                       validated), which can run to 30+ lines — capped
                       and scrollable so one row can't push the whole
                       table off-screen, without hiding any of it. */}
                    <pre
                      style={{
                        margin: 0,
                        maxHeight: 120,
                        overflowY: "auto",
                        fontFamily: "var(--font-mono)",
                        fontSize: "var(--text-2xs)",
                        whiteSpace: "pre-wrap",
                      }}
                    >
                      {gen.validation_detail ?? "—"}
                    </pre>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

const fieldLabelStyle = {
  fontSize: "var(--text-2xs)",
  color: "var(--text-muted)",
  textTransform: "uppercase" as const,
  letterSpacing: "var(--tracking-label)",
  marginBottom: 4,
};
