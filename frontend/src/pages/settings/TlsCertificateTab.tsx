import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, Icon, Select, StatusBadge, Switch, TextInput } from "../../design-system/components";
import { copyToClipboard } from "../../lib/clipboard";
import { parseApiDate } from "../../lib/apiDate";
import { ApiError } from "../../lib/apiClient";
import {
  confirmManualDnsChallenge,
  fetchTlsSettings,
  issueCertificateNow,
  startManualDnsChallenge,
  updateTlsSettings,
  verifyCloudflareAccess,
  type ManualDnsChallenge,
  type TlsActionResult,
  type TlsSettingsUpdate,
} from "../../lib/api/tlsSettings";

const RENEWAL_THRESHOLD_DAYS = 30;

const fieldLabelStyle = {
  fontSize: "var(--text-2xs)",
  color: "var(--text-muted)",
  textTransform: "uppercase" as const,
  letterSpacing: "var(--tracking-label)",
  marginBottom: 4,
};

const rowStyle = { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 };

function resultBanner(result: TlsActionResult | null, pending: boolean) {
  if (!result || pending) return null;
  return (
    <p
      role="alert"
      style={{
        marginTop: 8,
        marginBottom: 0,
        fontSize: "var(--text-sm)",
        color: result.success ? "var(--text-body)" : "var(--status-fault)",
      }}
    >
      {result.detail}
    </p>
  );
}

// The relay ships with a self-signed placeholder certificate on the
// submission port (587) — real clients (e.g. PHPMailer-based mailers)
// reject it during STARTTLS. This tab lets an admin provision a real
// Let's Encrypt certificate via a DNS-01 challenge (no inbound port
// 80/443 needed), with automatic renewal in the background
// (core/cert_renewal.py) once configured.
export function TlsCertificateTab() {
  const queryClient = useQueryClient();
  const { data: settings } = useQuery({ queryKey: ["tls-settings"], queryFn: fetchTlsSettings });

  const [enabled, setEnabled] = useState(false);
  const [domain, setDomain] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [dnsProvider, setDnsProvider] = useState<"cloudflare" | "manual">("cloudflare");
  const [zoneId, setZoneId] = useState("");
  const [apiToken, setApiToken] = useState("");
  const [saved, setSaved] = useState(false);

  const [verifyResult, setVerifyResult] = useState<TlsActionResult | null>(null);
  const [issueResult, setIssueResult] = useState<TlsActionResult | null>(null);
  const [manualChallenge, setManualChallenge] = useState<ManualDnsChallenge | null>(null);
  const [manualConfirmResult, setManualConfirmResult] = useState<TlsActionResult | null>(null);
  const [manualCopyState, setManualCopyState] = useState<"idle" | "copied" | "failed">("idle");

  // Adjusts local state when the fetched settings change, without an
  // Effect — https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
  const [prevSettings, setPrevSettings] = useState(settings);
  if (settings !== prevSettings) {
    setPrevSettings(settings);
    if (settings) {
      setEnabled(settings.acme_enabled);
      setDomain(settings.domain ?? "");
      setContactEmail(settings.contact_email ?? "");
      setDnsProvider(settings.dns_provider === "manual" ? "manual" : "cloudflare");
      setZoneId(settings.cloudflare_zone_id ?? "");
      if (settings.manual_dns_pending && settings.manual_dns_record_name && settings.manual_dns_record_value) {
        setManualChallenge({
          success: true,
          detail: "Add this TXT record, then click Verify & Continue.",
          record_name: settings.manual_dns_record_name,
          record_value: settings.manual_dns_record_value,
          expires_at: settings.manual_dns_expires_at,
        });
      }
    }
  }

  const save = useMutation({
    mutationFn: (update: TlsSettingsUpdate) => updateTlsSettings(update),
    onSuccess: (data) => {
      queryClient.setQueryData(["tls-settings"], data);
      setApiToken("");
      setSaved(true);
    },
  });

  function apiErrorResult(err: unknown): TlsActionResult {
    const detail = err instanceof ApiError && typeof err.detail === "string" ? err.detail : "Could not reach the server.";
    return { success: false, detail };
  }

  const verify = useMutation({
    mutationFn: () => verifyCloudflareAccess(),
    onSuccess: (result) => setVerifyResult(result),
    onError: (err) => setVerifyResult(apiErrorResult(err)),
  });

  const issue = useMutation({
    mutationFn: () => issueCertificateNow(),
    onSuccess: (result) => {
      setIssueResult(result);
      queryClient.invalidateQueries({ queryKey: ["tls-settings"] });
    },
    onError: (err) => setIssueResult(apiErrorResult(err)),
  });

  const startManual = useMutation({
    mutationFn: () => startManualDnsChallenge(),
    onSuccess: (result) => {
      setManualCopyState("idle");
      setManualConfirmResult(null);
      if (result.success) {
        setManualChallenge(result);
      } else {
        setManualConfirmResult({ success: false, detail: result.detail });
      }
    },
    onError: (err) => setManualConfirmResult(apiErrorResult(err)),
  });

  const confirmManual = useMutation({
    mutationFn: () => confirmManualDnsChallenge(),
    onSuccess: (result) => {
      setManualConfirmResult(result);
      if (result.success) {
        setManualChallenge(null);
        queryClient.invalidateQueries({ queryKey: ["tls-settings"] });
      }
      // On failure, manualChallenge is deliberately left in place so the
      // admin can wait for DNS to propagate and just click Verify again.
    },
    onError: (err) => setManualConfirmResult(apiErrorResult(err)),
  });

  function handleSave() {
    setSaved(false);
    const update: TlsSettingsUpdate = {
      acme_enabled: enabled,
      domain: domain.trim() === "" ? null : domain.trim(),
      contact_email: contactEmail.trim() === "" ? null : contactEmail.trim(),
      dns_provider: dnsProvider,
      cloudflare_zone_id: zoneId.trim() === "" ? null : zoneId.trim(),
    };
    if (apiToken.trim() !== "") update.cloudflare_api_token = apiToken.trim();
    save.mutate(update);
  }

  function copyManualRecord() {
    setManualCopyState(copyToClipboard(manualChallenge?.record_value ?? "") ? "copied" : "failed");
  }

  const canAct =
    enabled &&
    domain.trim() !== "" &&
    (dnsProvider === "manual" || settings?.cloudflare_api_token_configured || apiToken.trim() !== "");
  const expiresAt = settings?.cert_not_after ? parseApiDate(settings.cert_not_after) : null;
  // Date.now() is impure and can't be called directly in the render body —
  // a lazy useState initializer runs once per mount, outside render proper.
  const [now] = useState(() => Date.now());
  const expiringSoon = expiresAt ? expiresAt.getTime() - now < RENEWAL_THRESHOLD_DAYS * 24 * 60 * 60 * 1000 : false;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 12 }}>
      <Card title="Certificate Status">
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={rowStyle}>
            <span style={{ fontSize: "var(--text-sm)" }}>Source</span>
            <StatusBadge
              status={settings?.cert_source === "lets_encrypt" ? "idle" : "waiting"}
              label={settings?.cert_source === "lets_encrypt" ? "Let's Encrypt" : "Self-signed placeholder"}
              size="sm"
            />
          </div>
          {settings?.cert_domain && (
            <div style={rowStyle}>
              <span style={{ fontSize: "var(--text-sm)" }}>Domain</span>
              <span style={{ fontSize: "var(--text-sm)" }}>{settings.cert_domain}</span>
            </div>
          )}
          {expiresAt && (
            <div style={rowStyle}>
              <span style={{ fontSize: "var(--text-sm)" }}>Expires</span>
              <span style={{ fontSize: "var(--text-sm)", color: expiringSoon ? "var(--status-fault)" : undefined }}>
                {expiresAt.toLocaleString()}
              </span>
            </div>
          )}
          {settings?.last_checked_at && (
            <div style={rowStyle}>
              <span style={{ fontSize: "var(--text-sm)" }}>Last renewal check</span>
              <span style={{ fontSize: "var(--text-sm)" }}>{parseApiDate(settings.last_checked_at).toLocaleString()}</span>
            </div>
          )}
          {settings?.last_renewal_error && (
            <p role="alert" style={{ color: "var(--status-fault)", fontSize: "var(--text-sm)", margin: 0 }}>
              Last automatic renewal failed: {settings.last_renewal_error}
            </p>
          )}
        </div>
      </Card>

      <Card title="Let's Encrypt Configuration" wide>
        <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)", marginTop: 0 }}>
          Provisions a real, auto-renewing certificate via a DNS-01 challenge — no inbound port 80/443 needed.
          Cloudflare can be automated end-to-end; any other DNS host works too via the manual workflow below.
        </p>

        <div style={rowStyle}>
          <span style={{ fontSize: "var(--text-sm)" }}>Enable Let's Encrypt</span>
          <Switch checked={enabled} onChange={setEnabled} />
        </div>

        <div style={{ marginTop: 12 }}>
          <div style={fieldLabelStyle}>Domain</div>
          <TextInput
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            placeholder="smtp-relay.example.com"
            style={{ width: "100%" }}
          />
          <p style={{ color: "var(--text-muted)", fontSize: "var(--text-2xs)", marginTop: 4, marginBottom: 12 }}>
            The hostname clients will connect to and validate the certificate against — independent of this
            relay's own submission hostname (RELAY_SUBMISSION_HOST). TLS only checks that this matches what the
            client typed in, not the SMTP greeting.
          </p>

          <div style={fieldLabelStyle}>Contact email (optional)</div>
          <TextInput
            value={contactEmail}
            onChange={(e) => setContactEmail(e.target.value)}
            placeholder="ops@example.com"
            style={{ width: "100%", marginBottom: 12 }}
          />

          <div style={fieldLabelStyle}>DNS Provider</div>
          <Select
            value={dnsProvider}
            onChange={(e) => setDnsProvider(e.target.value === "manual" ? "manual" : "cloudflare")}
            style={{ width: "100%", marginBottom: 12 }}
          >
            <option value="cloudflare">Cloudflare</option>
            <option value="manual">Manual (any DNS provider)</option>
          </Select>

          {dnsProvider === "cloudflare" ? (
            <>
              <div style={fieldLabelStyle}>Cloudflare API Token</div>
              <TextInput
                type="password"
                value={apiToken}
                onChange={(e) => setApiToken(e.target.value)}
                placeholder={settings?.cloudflare_api_token_configured ? "Leave blank to keep the current token" : ""}
                style={{ width: "100%" }}
              />
              <p style={{ color: "var(--text-muted)", fontSize: "var(--text-2xs)", marginTop: 4, marginBottom: 12 }}>
                This field is write-only and never shows the stored token. Needs Zone:DNS:Edit permission scoped to
                the zone above.
              </p>

              <div style={fieldLabelStyle}>Cloudflare Zone ID (optional)</div>
              <TextInput
                value={zoneId}
                onChange={(e) => setZoneId(e.target.value)}
                placeholder="Auto-detected from the domain if left blank"
                style={{ width: "100%" }}
              />
            </>
          ) : (
            <p style={{ color: "var(--text-muted)", fontSize: "var(--text-2xs)", marginTop: 0, marginBottom: 0 }}>
              No credentials needed — you'll add a TXT record yourself at whatever DNS provider hosts this domain.
            </p>
          )}
        </div>

        <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--border-default)" }}>
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

        {dnsProvider === "cloudflare" ? (
          <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--border-default)" }}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <Button
                variant="default"
                onClick={() => {
                  setVerifyResult(null);
                  verify.mutate();
                }}
                disabled={verify.isPending || domain.trim() === ""}
              >
                {verify.isPending ? "Checking…" : "Verify Cloudflare Access"}
              </Button>
              <Button
                variant="default"
                onClick={() => {
                  setIssueResult(null);
                  issue.mutate();
                }}
                disabled={issue.isPending || !canAct}
              >
                {issue.isPending ? "Issuing…" : "Issue / Renew Now"}
              </Button>
            </div>
            <p style={{ color: "var(--text-muted)", fontSize: "var(--text-2xs)", marginTop: 8, marginBottom: 0 }}>
              Verify is a read-only check against Cloudflare and never costs a Let's Encrypt attempt — try it first.
              Issue/Renew makes a real request against Let's Encrypt's rate-limited production API using whatever
              is currently saved — save first if you just changed something above.
            </p>
            {resultBanner(verifyResult, verify.isPending)}
            {resultBanner(issueResult, issue.isPending)}
          </div>
        ) : (
          <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--border-default)" }}>
            {!manualChallenge ? (
              <>
                <Button
                  variant="default"
                  onClick={() => {
                    setManualConfirmResult(null);
                    startManual.mutate();
                  }}
                  disabled={startManual.isPending || !canAct}
                >
                  {startManual.isPending ? "Starting…" : "Start DNS-01 Challenge"}
                </Button>
                <p style={{ color: "var(--text-muted)", fontSize: "var(--text-2xs)", marginTop: 8, marginBottom: 0 }}>
                  Makes a real request against Let's Encrypt's rate-limited production API and shows the TXT
                  record to add — save first if you just changed something above.
                </p>
                {resultBanner(manualConfirmResult, startManual.isPending)}
              </>
            ) : (
              <>
                <div
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 10,
                    borderTop: "3px solid var(--brand-yellow)",
                    padding: "12px 14px",
                    borderRadius: "var(--radius-sm)",
                    background: "var(--surface-well)",
                    marginBottom: 16,
                  }}
                >
                  <Icon name="alert-triangle" size={18} color="var(--brand-yellow)" />
                  <p style={{ margin: 0, fontSize: "var(--text-sm)" }}>
                    Add this TXT record at your DNS provider before continuing. It can take a few minutes to
                    propagate — Verify &amp; Continue can be retried as many times as needed.
                  </p>
                </div>

                <div style={fieldLabelStyle}>TXT record name</div>
                <div
                  style={{
                    background: "var(--surface-well)",
                    border: "1px solid var(--border-default)",
                    borderRadius: "var(--radius-sm)",
                    padding: "10px 12px",
                    marginBottom: 12,
                    fontFamily: "var(--font-mono)",
                    fontSize: "var(--text-sm)",
                    wordBreak: "break-all",
                  }}
                >
                  {manualChallenge.record_name}
                </div>

                <div style={fieldLabelStyle}>TXT record value</div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    background: "var(--surface-well)",
                    border: "1px solid var(--border-default)",
                    borderRadius: "var(--radius-sm)",
                    padding: "10px 12px",
                    marginBottom: 16,
                  }}
                >
                  <code style={{ flex: 1, fontFamily: "var(--font-mono)", fontSize: "var(--text-sm)", wordBreak: "break-all" }}>
                    {manualChallenge.record_value}
                  </code>
                  <Button variant="default" onClick={copyManualRecord}>
                    {manualCopyState === "copied" ? "Copied" : "Copy"}
                  </Button>
                </div>
                {manualCopyState === "failed" && (
                  <p role="alert" style={{ color: "var(--status-fault)", fontSize: "var(--text-sm)", marginTop: -8, marginBottom: 16 }}>
                    Couldn't copy automatically — select the value above and copy it manually (Ctrl+C).
                  </p>
                )}

                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <Button
                    variant="accent"
                    onClick={() => {
                      setManualConfirmResult(null);
                      confirmManual.mutate();
                    }}
                    disabled={confirmManual.isPending}
                  >
                    {confirmManual.isPending ? "Verifying…" : "Verify & Continue"}
                  </Button>
                  <Button
                    variant="default"
                    onClick={() => {
                      setManualChallenge(null);
                      setManualConfirmResult(null);
                    }}
                    disabled={confirmManual.isPending}
                  >
                    Cancel
                  </Button>
                </div>
                {resultBanner(manualConfirmResult, confirmManual.isPending)}
              </>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
