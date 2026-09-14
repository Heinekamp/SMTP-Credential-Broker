import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Icon, StatusBadge } from "../design-system/components";
import { acknowledgeAlert, fetchAlerts } from "../lib/api/alerts";

const ALERTS_QUERY_KEY = ["alerts"];

// The design handoff never specified an alerts/notifications UI (it
// didn't exist yet) — this follows Titlebar.tsx's existing account-menu
// popover pattern (position: absolute, surface-card, same border/radius
// tokens) rather than inventing a new primitive. A persistent bell +
// dropdown, not a transient toast: most of what it lists (degraded
// health, a failing upstream account, an available update) is an ongoing
// condition, not a one-off event, so it needs to stay discoverable until
// resolved or acknowledged, not disappear after a few seconds.
export function NotificationBell() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const { data } = useQuery({ queryKey: ALERTS_QUERY_KEY, queryFn: fetchAlerts, refetchInterval: 30_000 });

  const acknowledge = useMutation({
    mutationFn: acknowledgeAlert,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ALERTS_QUERY_KEY }),
  });

  const alerts = data?.alerts ?? [];
  const activeCount = data?.active_count ?? 0;

  return (
    <div style={{ position: "relative" }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="Notifications"
        style={{
          position: "relative",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          width: 32,
          height: 32,
          background: "none",
          border: "none",
          borderRadius: "var(--radius-md)",
          color: "var(--text-muted)",
          cursor: "pointer",
        }}
      >
        <Icon name="bell" size={18} />
        {activeCount > 0 && (
          <span
            style={{
              position: "absolute",
              top: 2,
              right: 2,
              minWidth: 14,
              height: 14,
              padding: "0 3px",
              borderRadius: 7,
              background: "var(--status-fault)",
              color: "#fff",
              fontSize: 10,
              lineHeight: "14px",
              textAlign: "center",
            }}
          >
            {activeCount}
          </span>
        )}
      </button>

      {open && (
        <div
          style={{
            position: "absolute",
            right: 0,
            top: "calc(100% + 6px)",
            background: "var(--surface-card)",
            border: "1px solid var(--border-default)",
            borderRadius: "var(--radius-md)",
            minWidth: 320,
            maxWidth: 400,
            maxHeight: 400,
            overflowY: "auto",
            zIndex: 50,
          }}
        >
          {alerts.length === 0 ? (
            <p style={{ margin: 0, padding: 16, color: "var(--text-muted)", fontSize: "var(--text-sm)" }}>
              No active alerts.
            </p>
          ) : (
            alerts.map((alert) => (
              <div
                key={alert.key}
                style={{
                  padding: "10px 14px",
                  borderBottom: "1px solid var(--border-default)",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                  <StatusBadge status={alert.acknowledged ? "waiting" : "fault"} label="" size="sm" />
                  <span style={{ fontSize: "var(--text-sm)", fontWeight: 600 }}>{alert.title}</span>
                </div>
                {alert.detail && (
                  <p style={{ margin: "0 0 6px", fontSize: "var(--text-2xs)", color: "var(--text-muted)" }}>
                    {alert.detail}
                  </p>
                )}
                {alert.acknowledgeable && !alert.acknowledged && (
                  <button
                    type="button"
                    onClick={() => acknowledge.mutate(alert.kind)}
                    disabled={acknowledge.isPending}
                    style={{
                      background: "none",
                      border: "none",
                      color: "var(--brand-green)",
                      fontSize: "var(--text-2xs)",
                      cursor: "pointer",
                      padding: 0,
                    }}
                  >
                    Acknowledge
                  </button>
                )}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
