import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "../design-system/components";
import { ApiError } from "../lib/apiClient";
import { generateConfig } from "../lib/api/config";
import { fetchHealth } from "../lib/api/health";

// Configuration reaches Postfix only when it's applied (Generate & Apply,
// Settings → System) — a deliberate manual step. Changes to senders,
// permissions or upstream accounts therefore aren't live until then, and
// nothing outside the System tab used to say so (#177). This shows on every
// page while the health check reports drift, with a one-click apply. Shares
// the ["health"] query with the title bar; main.tsx refreshes it after
// every successful change so the banner appears straight away.
export function PendingConfigBanner() {
  const queryClient = useQueryClient();
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: fetchHealth, refetchInterval: 30_000 });
  const [error, setError] = useState<string | null>(null);

  const apply = useMutation({
    mutationFn: generateConfig,
    onSuccess: (result) => {
      setError(result.success ? null : `Postfix rejected the new configuration: ${result.validation_detail}`);
      queryClient.invalidateQueries({ queryKey: ["health"] });
    },
    onError: (err) =>
      setError(err instanceof ApiError && typeof err.detail === "string" ? err.detail : "Could not apply the configuration."),
  });

  // Only meaningful while Postfix is reachable — otherwise the title bar's
  // degraded status already says what's wrong, and applying can't work.
  if (!health || health.config_in_sync.ok || !health.postfix_reachable.ok) {
    return null;
  }

  return (
    <div
      role="status"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        flexWrap: "wrap",
        padding: "10px 14px",
        marginBottom: 16,
        border: "1px solid var(--status-armed)",
        borderRadius: "var(--radius-sm)",
        background: "var(--surface-well)",
        fontSize: "var(--text-sm)",
      }}
    >
      <span style={{ flex: 1, minWidth: 240 }}>
        <strong style={{ color: "var(--status-armed)" }}>Pending configuration changes.</strong> Changes to senders,
        permissions or upstream accounts aren't live in Postfix until the configuration is applied.
        {error && (
          <span role="alert" style={{ display: "block", color: "var(--status-fault)", marginTop: 4 }}>
            {error}
          </span>
        )}
      </span>
      <Button variant="accent" onClick={() => apply.mutate()} disabled={apply.isPending}>
        {apply.isPending ? "Applying…" : "Apply now"}
      </Button>
    </div>
  );
}
