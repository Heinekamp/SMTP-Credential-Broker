import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, Select, Switch, TextInput } from "../../design-system/components";
import { ApiError } from "../../lib/apiClient";
import {
  fetchNotificationSettings,
  sendTestAlert,
  updateNotificationSettings,
  type NotificationSettingsUpdate,
  type TestAlertResult,
} from "../../lib/api/notificationSettings";
import { listSenders } from "../../lib/api/senders";

const INTERVAL_OPTIONS: { label: string; value: string }[] = [
  { label: "Off (manual only)", value: "" },
  { label: "Every 15 minutes", value: "15" },
  { label: "Every 30 minutes", value: "30" },
  { label: "Every hour", value: "60" },
  { label: "Every 6 hours", value: "360" },
  { label: "Every 24 hours", value: "1440" },
];

const fieldLabelStyle = {
  fontSize: "var(--text-2xs)",
  color: "var(--text-muted)",
  textTransform: "uppercase" as const,
  letterSpacing: "var(--tracking-label)",
  marginBottom: 4,
};

const rowStyle = { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 };

// Design handoff never covered this screen (it didn't exist until the
// alerting feature was built) — follows SystemTab.tsx's card layout and
// useQuery/useMutation shape. Unlike SystemTab's Generate & Apply
// (single immediate action), this is a proper settings form: local state
// initialized from the fetched settings, one Save button PATCHes
// everything that changed at once.
export function NotificationsTab() {
  const queryClient = useQueryClient();
  const { data: settings } = useQuery({ queryKey: ["notification-settings"], queryFn: fetchNotificationSettings });
  const { data: senders } = useQuery({ queryKey: ["senders"], queryFn: listSenders });

  const [interval, setInterval] = useState("");
  const [updateCheckEnabled, setUpdateCheckEnabled] = useState(false);
  const [recipients, setRecipients] = useState("");
  const [senderId, setSenderId] = useState("");
  const [fromName, setFromName] = useState("");
  const [notifyHealth, setNotifyHealth] = useState(true);
  const [notifyUpstream, setNotifyUpstream] = useState(true);
  const [notifyAppUpdate, setNotifyAppUpdate] = useState(true);
  const [notifyPostfixUpdate, setNotifyPostfixUpdate] = useState(true);
  const [notifyRateLimitAbuse, setNotifyRateLimitAbuse] = useState(false);
  const [autoDisableEnabled, setAutoDisableEnabled] = useState(false);
  const [abuseThresholdMinutes, setAbuseThresholdMinutes] = useState("10");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!settings) return;
    setInterval(settings.connection_test_interval_minutes?.toString() ?? "");
    setUpdateCheckEnabled(settings.update_check_enabled);
    setRecipients(settings.notify_recipients.join(", "));
    setSenderId(settings.notify_sender_id?.toString() ?? "");
    setFromName(settings.notify_from_name ?? "");
    setNotifyHealth(settings.notify_on_health_degraded);
    setNotifyUpstream(settings.notify_on_upstream_test_failure);
    setNotifyAppUpdate(settings.notify_on_app_update_available);
    setNotifyPostfixUpdate(settings.notify_on_postfix_update_available);
    setNotifyRateLimitAbuse(settings.notify_on_rate_limit_abuse);
    setAutoDisableEnabled(settings.rate_limit_abuse_auto_disable_enabled);
    setAbuseThresholdMinutes(String(settings.rate_limit_abuse_threshold_minutes));
  }, [settings]);

  const [testResult, setTestResult] = useState<TestAlertResult | null>(null);

  const save = useMutation({
    mutationFn: (update: NotificationSettingsUpdate) => updateNotificationSettings(update),
    onSuccess: (data) => {
      queryClient.setQueryData(["notification-settings"], data);
      setSaved(true);
    },
  });

  const testAlert = useMutation({
    mutationFn: () => sendTestAlert(),
    onSuccess: (result) => setTestResult(result),
    onError: (err) => {
      const detail =
        err instanceof ApiError && typeof err.detail === "string" ? err.detail : "Could not reach the server.";
      setTestResult({ success: false, detail });
    },
  });

  function handleSave() {
    setSaved(false);
    save.mutate({
      connection_test_interval_minutes: interval === "" ? null : Number(interval),
      update_check_enabled: updateCheckEnabled,
      notify_recipients: recipients
        .split(",")
        .map((r) => r.trim())
        .filter((r) => r.length > 0),
      notify_sender_id: senderId === "" ? null : Number(senderId),
      notify_from_name: fromName.trim() === "" ? null : fromName.trim(),
      notify_on_health_degraded: notifyHealth,
      notify_on_upstream_test_failure: notifyUpstream,
      notify_on_app_update_available: notifyAppUpdate,
      notify_on_postfix_update_available: notifyPostfixUpdate,
      notify_on_rate_limit_abuse: notifyRateLimitAbuse,
      rate_limit_abuse_auto_disable_enabled: autoDisableEnabled,
      rate_limit_abuse_threshold_minutes: abuseThresholdMinutes.trim() === "" ? 10 : Number(abuseThresholdMinutes),
    });
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 12 }}>
      <Card title="Scheduled Connection Testing">
        <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)", marginTop: 0 }}>
          Automatically re-runs the same diagnostic as the manual "Test Connection" button against every
          enabled upstream account.
        </p>
        <div style={fieldLabelStyle}>Interval</div>
        <Select value={interval} onChange={(e) => setInterval(e.target.value)} style={{ width: "100%" }}>
          {INTERVAL_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </Select>
      </Card>

      <Card title="Update Checking">
        <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)", marginTop: 0 }}>
          Checks GitHub for a newer SMTP Manager release and, best-effort, postfix.org for a newer Postfix.
          Off by default — enabling this makes outbound calls to those sites.
        </p>
        <div style={rowStyle}>
          <span style={{ fontSize: "var(--text-sm)" }}>Enable update checking</span>
          <Switch checked={updateCheckEnabled} onChange={setUpdateCheckEnabled} />
        </div>
      </Card>

      <Card title="Alert Email" wide>
        <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)", marginTop: 0 }}>
          Sends an email the moment an alert becomes active (not on every check while it stays active), using
          one of your configured senders. Connects directly to that sender's upstream account — it does not
          go through this relay.
        </p>

        <div style={fieldLabelStyle}>Recipients (comma-separated)</div>
        <TextInput
          value={recipients}
          onChange={(e) => setRecipients(e.target.value)}
          placeholder="admin@example.com, oncall@example.com"
          style={{ width: "100%", marginBottom: 12 }}
        />

        <div style={fieldLabelStyle}>Send from</div>
        <Select value={senderId} onChange={(e) => setSenderId(e.target.value)} style={{ width: "100%", marginBottom: 12 }}>
          <option value="">— No sender configured —</option>
          {senders?.map((sender) => (
            <option key={sender.id} value={sender.id}>
              {sender.address}
            </option>
          ))}
        </Select>

        <div style={fieldLabelStyle}>From name (optional)</div>
        <TextInput
          value={fromName}
          onChange={(e) => setFromName(e.target.value)}
          placeholder="SMTP Relay Alerts"
          style={{ width: "100%", marginBottom: 16 }}
        />
        <p style={{ color: "var(--text-muted)", fontSize: "var(--text-2xs)", marginTop: -12, marginBottom: 16 }}>
          {'Shown as the From display name, e.g. "SMTP Relay Alerts <alerts@example.com>" instead of just the bare address.'}
        </p>

        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={rowStyle}>
            <span style={{ fontSize: "var(--text-sm)" }}>Relay degraded</span>
            <Switch checked={notifyHealth} onChange={setNotifyHealth} />
          </div>
          <div style={rowStyle}>
            <span style={{ fontSize: "var(--text-sm)" }}>Upstream account failing its test</span>
            <Switch checked={notifyUpstream} onChange={setNotifyUpstream} />
          </div>
          <div style={rowStyle}>
            <span style={{ fontSize: "var(--text-sm)" }}>SMTP Manager update available</span>
            <Switch checked={notifyAppUpdate} onChange={setNotifyAppUpdate} />
          </div>
          <div style={rowStyle}>
            <span style={{ fontSize: "var(--text-sm)" }}>Postfix update available</span>
            <Switch checked={notifyPostfixUpdate} onChange={setNotifyPostfixUpdate} />
          </div>
          <div style={rowStyle}>
            <span style={{ fontSize: "var(--text-sm)" }}>Local user throttled continuously (rate-limit abuse)</span>
            <Switch checked={notifyRateLimitAbuse} onChange={setNotifyRateLimitAbuse} />
          </div>
        </div>

        <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--border-default)" }}>
          <Button
            variant="default"
            onClick={() => {
              setTestResult(null);
              testAlert.mutate();
            }}
            disabled={testAlert.isPending}
          >
            {testAlert.isPending ? "Sending…" : "Send Test Alert"}
          </Button>
          <p style={{ color: "var(--text-muted)", fontSize: "var(--text-2xs)", marginTop: 8, marginBottom: 0 }}>
            Sends immediately using the currently saved recipients/sender/from name above — save first if you
            just changed them.
          </p>
          {testResult && !testAlert.isPending && (
            <p
              role="alert"
              style={{
                marginTop: 8,
                marginBottom: 0,
                fontSize: "var(--text-sm)",
                color: testResult.success ? "var(--text-body)" : "var(--status-fault)",
              }}
            >
              {testResult.success ? "Test alert sent — check the configured recipients." : testResult.detail}
            </p>
          )}
        </div>
      </Card>

      <Card title="Rate-Limit Abuse Detection">
        <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)", marginTop: 0 }}>
          A local user that's been continuously throttled — never once sent successfully — for longer than the
          threshold below always shows on the notification bell above, regardless of these settings. These add an
          email (toggle above) and, separately, an automatic disable.
        </p>

        <div style={fieldLabelStyle}>Threshold (minutes)</div>
        <TextInput
          type="number"
          min={1}
          value={abuseThresholdMinutes}
          onChange={(e) => setAbuseThresholdMinutes(e.target.value)}
          style={{ width: "100%", marginBottom: 12 }}
        />

        <div style={rowStyle}>
          <span style={{ fontSize: "var(--text-sm)" }}>Automatically disable the credential</span>
          <Switch checked={autoDisableEnabled} onChange={setAutoDisableEnabled} />
        </div>
        <p style={{ color: "var(--text-muted)", fontSize: "var(--text-2xs)", marginTop: 8, marginBottom: 0 }}>
          Stops <em>all</em> of that credential's mail, not just the excess — a real availability cost if you're
          slow to react, weighed against a stuck sender hammering a shared upstream mailbox indefinitely.
          Re-enabling a disabled user clears the flag and gives it a clean slate.
        </p>
      </Card>

      <div style={{ gridColumn: "1 / -1" }}>
        <Button variant="accent" onClick={handleSave} disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </Button>
        {saved && !save.isPending && (
          <span style={{ marginLeft: 10, color: "var(--text-muted)", fontSize: "var(--text-sm)" }}>Saved.</span>
        )}
        {save.isError && (
          <span style={{ marginLeft: 10, color: "var(--status-fault)", fontSize: "var(--text-sm)" }}>
            Could not save settings.
          </span>
        )}
      </div>
    </div>
  );
}
