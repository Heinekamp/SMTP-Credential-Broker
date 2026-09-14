import { useQuery } from "@tanstack/react-query";

import { Button, Card, StatusBadge } from "../../design-system/components";
import { skeletonBarStyle, tableStyle, tdStyle, thStyle } from "../../design-system/table";
import { parseApiDate } from "../../lib/apiDate";
import { listConfigGenerations } from "../../lib/api/config";
import { fetchHealth } from "../../lib/api/health";
import { fetchSystemStatus } from "../../lib/api/system";

// Design handoff §10's System tab. Rotate Key stays a disabled control
// permanently, not a deferred one: security-model.md §2 makes
// `relay rotate-encryption-key` the CLI the *only* supported way to
// rotate the key (it needs the old/new key *files* on the host/container
// filesystem, which a browser button click has no way to supply) — see
// core/cli.py's rotate-encryption-key command. "Postfix / System" shows
// only what the app actually knows (no Postfix version is exposed
// anywhere in the API, so it's omitted rather than faked).
export function SystemTab() {
  const { data: systemStatus } = useQuery({ queryKey: ["system-status"], queryFn: fetchSystemStatus });
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: fetchHealth });
  const { data: generations, isLoading } = useQuery({ queryKey: ["config-generations"], queryFn: listConfigGenerations });

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
          {generations && generations.length > 0 && (
            <div>
              <div style={fieldLabelStyle}>Last Generation</div>
              <div style={{ fontSize: "var(--text-sm)" }}>{parseApiDate(generations[0].generated_at).toLocaleString()}</div>
            </div>
          )}
        </div>
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
