import { NavLink } from "react-router-dom";

import { Icon, type IconName } from "../design-system/components";
import "./sidenav.css";

const ITEMS: { to: string; label: string; icon: IconName }[] = [
  { to: "/", label: "Dashboard", icon: "home" },
  { to: "/upstream-accounts", label: "Upstream Accounts", icon: "server" },
  { to: "/senders", label: "Senders", icon: "send" },
  { to: "/local-users", label: "Local SMTP Users", icon: "users" },
  { to: "/mail-log", label: "Mail Log", icon: "activity" },
  { to: "/queue", label: "Queue", icon: "list" },
  { to: "/settings", label: "Settings", icon: "settings" },
];

// Design handoff §3/"Notable Deviations": rebuilt locally (not the generic
// Sidenav reference) purely because this product needs three icons the
// base Icon set doesn't have — everything else (sizing, active-state
// styling) matches the reference exactly.
export function Sidenav() {
  return (
    <nav
      className="relay-sidenav"
      style={{
        background: "var(--surface-card)",
        borderRight: "1px solid var(--border-default)",
        display: "flex",
        flexDirection: "column",
        padding: "12px 0",
        height: "100%",
        boxSizing: "border-box",
      }}
    >
      {ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === "/"}
          style={({ isActive }) => ({
            background: isActive ? "rgba(114,191,68,0.08)" : "none",
            borderLeft: isActive ? "3px solid var(--brand-green)" : "3px solid transparent",
            color: isActive ? "var(--brand-green)" : "var(--text-muted)",
            textDecoration: "none",
            padding: "12px 20px",
            cursor: "pointer",
            fontSize: "var(--text-sm)",
            fontFamily: "var(--font-ui)",
            display: "flex",
            alignItems: "center",
            gap: 10,
          })}
        >
          <Icon name={item.icon} size={18} />
          <span className="relay-sidenav-label">{item.label}</span>
        </NavLink>
      ))}

      <div
        style={{
          marginTop: "auto",
          padding: "12px 20px",
          borderTop: "1px solid var(--border-default)",
          color: "var(--text-muted)",
          fontSize: "var(--text-2xs)",
        }}
      >
        <span className="relay-sidenav-label">v1.0.0</span>
      </div>
    </nav>
  );
}
