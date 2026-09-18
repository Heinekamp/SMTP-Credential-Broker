import { useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, Icon } from "../../design-system/components";
import { getUpstreamAccount, testUpstreamAccountConnection } from "../../lib/api/upstreamAccounts";

// Design handoff §5's Test Connection screen — its own screen, not a
// modal: 5 sequential sub-checks, each a status icon + label + one-line
// detail + a right-aligned Passed/Failed label. On failure, only the
// failing step (and everything after it) shows Failed.
export function TestConnection() {
  const params = useParams<{ id: string }>();
  const accountId = Number(params.id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: account } = useQuery({
    queryKey: ["upstream-accounts", accountId],
    queryFn: () => getUpstreamAccount(accountId),
  });

  const {
    data: result,
    isFetching: running,
    refetch: runTest,
  } = useQuery({
    queryKey: ["test-connection", accountId],
    queryFn: async () => {
      const response = await testUpstreamAccountConnection(accountId);
      // The result is persisted server-side onto the account (for the
      // list/dashboard views) — refresh those caches too.
      queryClient.invalidateQueries({ queryKey: ["upstream-accounts"] });
      return response;
    },
  });

  return (
    <Card style={{ maxWidth: 520 }}>
      <h1 style={{ fontSize: "var(--text-lg)", fontWeight: 600, marginTop: 0, marginBottom: 2 }}>
        {account?.name ?? "Test Connection"}
      </h1>
      {account && (
        <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)", marginTop: 0 }}>
          {account.host}:{account.port}
        </p>
      )}

      {running && !result && <p style={{ color: "var(--text-muted)" }}>Running…</p>}

      {result && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10, margin: "12px 0" }}>
          {result.steps.map((step) => (
            <div key={step.name} style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <Icon
                name={step.passed ? "circle" : "x-circle"}
                size={20}
                color={step.passed ? "var(--status-idle)" : "var(--status-fault)"}
              />
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: "var(--text-sm)" }}>{step.name}</div>
                <div style={{ fontSize: "var(--text-2xs)", color: "var(--text-muted)" }}>{step.detail}</div>
              </div>
              <span
                style={{
                  fontSize: "var(--text-sm)",
                  fontWeight: 600,
                  color: step.passed ? "var(--status-idle)" : "var(--status-fault)",
                }}
              >
                {step.passed ? "Passed" : "Failed"}
              </span>
            </div>
          ))}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <Button variant="accent" onClick={() => runTest()} disabled={running}>
          Run Test Again
        </Button>
        <Button variant="default" onClick={() => navigate("/upstream-accounts")}>
          Done
        </Button>
      </div>
    </Card>
  );
}
