import { useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { Icon, StatusBadge } from "../design-system/components";
import { logout } from "../lib/apiClient";
import { fetchHealth } from "../lib/api/health";
import { type ThemeChoice, useTheme } from "../lib/theme";
import { SESSION_QUERY_KEY, useSession } from "../lib/useSession";
import { BrandLogo } from "./BrandLogo";
import { ChangePasswordModal } from "./ChangePasswordModal";
import { NotificationBell } from "./NotificationBell";

const THEME_OPTIONS: { value: ThemeChoice; label: string }[] = [
  { value: "dark", label: "Dark" },
  { value: "light", label: "Light" },
  { value: "system", label: "System" },
];

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
  const { theme, setTheme } = useTheme();
  const [menuOpen, setMenuOpen] = useState(false);
  const [changingPassword, setChangingPassword] = useState(false);
  const menuId = useId();
  const menuRef = useRef<HTMLDivElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  // The account menu used to stay open until its button was clicked again
  // (#211): close it on Escape (focus back on the button) or a click outside.
  useEffect(() => {
    if (!menuOpen) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      setMenuOpen(false);
      menuButtonRef.current?.focus();
    }
    function onPointerDown(e: PointerEvent) {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    }
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [menuOpen]);

  // The menu item that opened the modal is gone by now, so ModalFrame can't
  // hand focus back to it — return it to the account button instead.
  function closeChangePassword() {
    setChangingPassword(false);
    menuButtonRef.current?.focus();
  }

  async function handleLogout() {
    try {
      await logout();
    } catch {
      // An already-expired session can't be logged out server-side (the
      // endpoint itself needs one) — that must not leave the button dead (#207).
    } finally {
      await queryClient.invalidateQueries({ queryKey: SESSION_QUERY_KEY });
      navigate("/login", { replace: true });
    }
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
        <BrandLogo height={28} width={28} />
        SMTP Credential Broker
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

        <div ref={menuRef} style={{ position: "relative" }}>
          <button
            ref={menuButtonRef}
            type="button"
            aria-expanded={menuOpen}
            aria-controls={menuOpen ? menuId : undefined}
            aria-label={session?.email ? `Account menu: ${session.email}` : "Account menu"}
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
              id={menuId}
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
              <div style={{ padding: "8px 14px", borderBottom: "1px solid var(--border-default)" }}>
                <div
                  style={{
                    fontSize: "var(--text-2xs)",
                    color: "var(--text-muted)",
                    textTransform: "uppercase",
                    letterSpacing: "var(--tracking-label)",
                    marginBottom: 6,
                  }}
                >
                  Appearance
                </div>
                <div role="group" aria-label="Appearance" style={{ display: "flex", gap: 4 }}>
                  {THEME_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      aria-pressed={theme === opt.value}
                      onClick={() => setTheme(opt.value)}
                      style={{
                        flex: 1,
                        padding: "4px 0",
                        fontSize: "var(--text-2xs)",
                        fontFamily: "var(--font-ui)",
                        borderRadius: "var(--radius-sm)",
                        border: "1px solid var(--border-default)",
                        cursor: "pointer",
                        background: theme === opt.value ? "var(--accent)" : "var(--surface-control)",
                        color: theme === opt.value ? "var(--text-on-accent)" : "var(--text-body)",
                      }}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>
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
        <ChangePasswordModal onDone={closeChangePassword} onCancel={closeChangePassword} />
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
