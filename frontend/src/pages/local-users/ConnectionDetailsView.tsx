import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { Button, Card } from "../../design-system/components";
import { getConnectionDetails } from "../../lib/api/localUsers";
import { copyToClipboard } from "../../lib/clipboard";

// Design handoff §7's Connection Details view — read-only, and password is
// deliberately never shown here (never a second place the secret is
// retrievable); the caption points back at the one-time reveal/regenerate.
export function ConnectionDetailsView() {
  const params = useParams<{ id: string }>();
  const userId = Number(params.id);
  const navigate = useNavigate();
  const { data } = useQuery({
    queryKey: ["local-users", userId, "connection-details"],
    queryFn: () => getConnectionDetails(userId),
  });
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");

  function copyAll() {
    if (!data) return;
    const text = [
      `Host: ${data.host}`,
      `Port: ${data.port} (${data.tls_mode})`,
      `Username: ${data.username}`,
      `From: ${data.from_addresses.join(", ") || "— none allowed yet —"}`,
    ].join("\n");
    setCopyState(copyToClipboard(text) ? "copied" : "failed");
  }

  return (
    <Card style={{ maxWidth: 480 }}>
      <h1 style={{ fontSize: "var(--text-lg)", fontWeight: 600, marginTop: 0, marginBottom: 4 }}>
        Connection Details
      </h1>
      <p style={{ color: "var(--text-muted)", fontSize: "var(--text-2xs)", marginTop: 0, marginBottom: 16 }}>
        The password isn't shown here — copy it from the one-time reveal at creation/regeneration time.
      </p>

      {data && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 16 }}>
          <Field label="Host" value={data.host} />
          <Field label="Port" value={`${data.port} (${data.tls_mode})`} />
          <Field label="Username" value={data.username} />
          <Field label="From" value={data.from_addresses.join(", ") || "— none allowed yet —"} />
        </div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <Button variant="accent" onClick={copyAll}>
          {copyState === "copied" ? "Copied" : "Copy All"}
        </Button>
        <Button variant="default" onClick={() => navigate("/local-users")}>
          Done
        </Button>
      </div>

      {copyState === "failed" && (
        <p role="alert" style={{ color: "var(--status-fault)", fontSize: "var(--text-sm)", marginTop: 8, marginBottom: 0 }}>
          Couldn't copy automatically — select the fields above and copy them manually.
        </p>
      )}
    </Card>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontSize: "var(--text-2xs)", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "var(--tracking-label)" }}>
        {label}
      </div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-sm)" }}>{value}</div>
    </div>
  );
}
