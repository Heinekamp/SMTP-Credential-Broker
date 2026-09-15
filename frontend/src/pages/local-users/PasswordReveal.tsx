import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { Button, Card, Icon } from "../../design-system/components";
import { copyToClipboard } from "../../lib/clipboard";

// Design handoff §7's most security-sensitive screen: a 3px top border in
// --brand-yellow (the "reduced protection, stay alert" caution color —
// deliberately not red/error framing, since this isn't a fault, and not
// celebratory, since a save should stay quiet), a caution-triangle icon,
// bold "This password will not be shown again," the password itself in a
// monospace well next to a Copy button that flips to Copied.
export function PasswordReveal() {
  const navigate = useNavigate();
  const location = useLocation();
  const password = (location.state as { password?: string } | null)?.password;
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");

  function copy() {
    setCopyState(copyToClipboard(password ?? "") ? "copied" : "failed");
  }

  if (!password) {
    // A hard refresh loses navigation state — the password was never
    // stored anywhere it could be re-fetched from (security-model.md §5),
    // so this is the honest outcome, not a bug to work around.
    return (
      <Card style={{ maxWidth: 480 }}>
        <p style={{ margin: 0, color: "var(--text-muted)" }}>
          This password can no longer be shown — it was only ever displayed once, at creation/regeneration time.
        </p>
        <Button variant="default" onClick={() => navigate("/local-users")} style={{ marginTop: 16 }}>
          Back to Local SMTP Users
        </Button>
      </Card>
    );
  }

  return (
    <Card style={{ maxWidth: 480, borderTop: "3px solid var(--brand-yellow)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
        <Icon name="alert-triangle" size={20} color="var(--brand-yellow)" />
        <h1 style={{ fontSize: "var(--text-md)", fontWeight: 600, margin: 0 }}>
          This password will not be shown again
        </h1>
      </div>
      <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)", marginTop: 4, marginBottom: 16 }}>
        Copy it now and store it wherever the service using it keeps its configuration.
      </p>

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
          {password}
        </code>
        <Button variant="default" onClick={copy}>
          {copyState === "copied" ? "Copied" : "Copy"}
        </Button>
      </div>

      {copyState === "failed" && (
        <p role="alert" style={{ color: "var(--status-fault)", fontSize: "var(--text-sm)", marginTop: -8, marginBottom: 16 }}>
          Couldn't copy automatically — select the password above and copy it manually (Ctrl+C).
        </p>
      )}

      <Button variant="accent" onClick={() => navigate("/local-users")}>
        Done
      </Button>
    </Card>
  );
}
