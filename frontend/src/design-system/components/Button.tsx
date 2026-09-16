import type { CSSProperties, ReactNode } from "react";

export interface ButtonProps {
  children: ReactNode;
  /** default = neutral raised control. accent = primary/affirmative (brand green). danger = destructive. warn = caution (autotune-style yellow). */
  variant?: "default" | "accent" | "danger" | "warn";
  /** Forces the solid-accent "selected" look, used for tab/toggle buttons (e.g. Settings tabs). */
  active?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  type?: "button" | "submit";
  style?: CSSProperties;
  /** Standard HTML title attribute — used to explain *why* a disabled
   * button is disabled (e.g. "lands in the Stage 8 hardening pass"). */
  title?: string;
}

// Ported from design-system/components-reference/core/button/Button.jsx —
// see docs/claude-design-prompt.md and the design handoff README for
// provenance. No pill/rounded-full, no shadow, no hover color beyond
// browser default (matches the source spec exactly).
export function Button({
  children,
  variant = "default",
  active = false,
  disabled = false,
  onClick,
  type = "button",
  style,
  title,
}: ButtonProps) {
  const base: CSSProperties = {
    padding: "8px 14px",
    borderRadius: "var(--radius-md)",
    border: "1px solid var(--border-default)",
    background: "var(--surface-control)",
    color: "var(--text-body)",
    cursor: disabled ? "not-allowed" : "pointer",
    fontSize: "var(--text-sm)",
    fontFamily: "var(--font-ui)",
    fontWeight: 400,
    opacity: disabled ? 0.4 : 1,
    transition: "none",
  };

  const variants: Record<NonNullable<ButtonProps["variant"]>, CSSProperties> = {
    default: {},
    accent: {
      background: "var(--accent)",
      color: "var(--text-on-accent)",
      borderColor: "var(--accent)",
      fontWeight: 600,
    },
    danger: {
      background: "var(--danger)",
      color: "#fff",
      borderColor: "var(--danger)",
    },
    warn: {
      background: "var(--brand-yellow)",
      color: "var(--brand-yellow-ink)",
      borderColor: "var(--brand-yellow)",
      fontWeight: 600,
    },
  };

  const activeStyle: CSSProperties = active
    ? {
        background: "var(--accent)",
        color: "var(--text-on-accent)",
        borderColor: "var(--accent)",
        fontWeight: 600,
      }
    : {};

  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      title={title}
      style={{ ...base, ...variants[variant], ...activeStyle, ...style }}
    >
      {children}
    </button>
  );
}
