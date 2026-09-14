import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { Icon, StatusBadge } from "../design-system/components";
import { logout } from "../lib/apiClient";
import { fetchHealth } from "../lib/api/health";
import { SESSION_QUERY_KEY, useSession } from "../lib/useSession";
import { ChangePasswordModal } from "./ChangePasswordModal";
import { NotificationBell } from "./NotificationBell";

// Design handoff §3/"Notable Deviations": a custom title bar matching the
// base Titlebar component's exact visual spec (56px, surface-card, 1px
// bottom border, same StatusBadge pattern) but with correct product copy
// ("Relay:" not "Oven:") and a real account menu instead of the base
// component's WiFi/IP readout.
export function Titlebar() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: session } = useSession();
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: fetchHealth, refetchInterval: 30_000 });
  const [menuOpen, setMenuOpen] = useState(false);
  const [changingPassword, setChangingPassword] = useState(false);

  async function handleLogout() {
    await logout();
    await queryClient.invalidateQueries({ queryKey: SESSION_QUERY_KEY });
    navigate("/login", { replace: true });
  }

  const operational = health?.status === "ok";

  return (
    <header
      style={{
        height: 56,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 20px",
        background: "var(--surface-card)",
        borderBottom: "1px solid var(--border-default)",
        fontFamily: "var(--font-ui)",
        color: "var(--text-body)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, fontWeight: 600 }}>
        <img src="/logo.png" alt="" style={{ height: 28, width: 28, objectFit: "contain" }} />
        SMTP Relay Console
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 20, color: "var(--text-muted)" }}>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          Relay:{" "}
          {health ? (
            <StatusBadge
              status={operational ? "idle" : "armed"}
              label={operational ? "OPERATIONAL" : "DEGRADED"}
              size="sm"
            />
          ) : (
            <StatusBadge status="waiting" label="CHECKING" size="sm" />
          )}
        </span>

        <NotificationBell />

        <div style={{ position: "relative" }}>
          <button
            type="button"
            onClick={() => setMenuOpen((open) => !open)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              background: "var(--surface-control)",
              border: "1px solid var(--border-default)",
              borderRadius: "var(--radius-md)",
              padding: "6px 10px",
              color: "var(--text-body)",
              fontSize: "var(--text-sm)",
              fontFamily: "var(--font-ui)",
              cursor: "pointer",
            }}
          >
            <Icon name="user" size={16} />
            {session?.email}
            <Icon name="chevron-down" size={14} />
          </button>

          {menuOpen && (
            <div
              style={{
                position: "absolute",
                right: 0,
                top: "calc(100% + 6px)",
                background: "var(--surface-card)",
                border: "1px solid var(--border-default)",
                borderRadius: "var(--radius-md)",
                minWidth: 180,
                overflow: "hidden",
                zIndex: 50,
              }}
            >
              <button
                type="button"
                onClick={() => {
                  setMenuOpen(false);
                  setChangingPassword(true);
                }}
                style={menuItemStyle}
              >
                Change Password
              </button>
              <button type="button" onClick={handleLogout} style={menuItemStyle}>
                Log Out
              </button>
            </div>
          )}
        </div>
      </div>

      {changingPassword && (
        <ChangePasswordModal onDone={() => setChangingPassword(false)} onCancel={() => setChangingPassword(false)} />
      )}
    </header>
  );
}

const menuItemStyle = {
  display: "block",
  width: "100%",
  textAlign: "left" as const,
  padding: "10px 14px",
  background: "none",
  border: "none",
  color: "var(--text-body)",
  fontSize: "var(--text-sm)",
  fontFamily: "var(--font-ui)",
  cursor: "pointer",
};
