export interface StatusBadgeProps {
  status?: "idle" | "armed" | "running" | "cooling" | "aborting" | "fault" | "autotune" | "waiting";
  label?: string;
  size?: "sm" | "md";
}

const COLORS: Record<NonNullable<StatusBadgeProps["status"]>, string> = {
  idle: "var(--status-idle)",
  armed: "var(--status-armed)",
  running: "var(--status-running)",
  cooling: "var(--status-cooling)",
  aborting: "var(--status-aborting)",
  fault: "var(--status-fault)",
  autotune: "var(--status-autotune)",
  waiting: "var(--status-waiting)",
};

// Ported from design-system/components-reference/core/badge/StatusBadge.jsx —
// colored dot + label, the product's only status indicator. Status color is
// a fixed semantic table — never remapped per use.
export function StatusBadge({ status = "idle", label, size = "md" }: StatusBadgeProps) {
  const color = COLORS[status] ?? COLORS.idle;
  const dot = size === "sm" ? 8 : 10;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontFamily: "var(--font-ui)", color }}>
      <span
        style={{
          width: dot,
          height: dot,
          borderRadius: "50%",
          background: color,
          display: "inline-block",
          flexShrink: 0,
        }}
      />
      {label && <strong style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>{label}</strong>}
    </span>
  );
}
