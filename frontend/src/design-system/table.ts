import type { CSSProperties } from "react";

// The design handoff's DataTable "pattern" (design-system/components-reference/
// data/data-table/DataTable.jsx) is deliberately not a component to wrap with —
// "implemented here as plain <table> markup ... so custom cells (badges,
// switches, action buttons) could be composed per-row." These are the shared
// style constants every list screen's own <table> uses, copied verbatim from
// that reference so every list looks identical without a shared component
// forcing a one-size-fits-all cell renderer.

export const tableStyle: CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  margin: "12px 0",
  fontFamily: "var(--font-ui)",
};

export const thStyle: CSSProperties = {
  textAlign: "left",
  color: "var(--text-muted)",
  fontSize: "var(--text-2xs)",
  textTransform: "uppercase",
  letterSpacing: "0.04em",
  padding: 8,
  borderBottom: "1px solid var(--border-default)",
};

export const tdStyle: CSSProperties = {
  padding: 8,
  borderBottom: "1px solid var(--border-default)",
  color: "var(--text-body)",
};

export const emptyCellStyle: CSSProperties = {
  ...tdStyle,
  color: "var(--text-muted)",
  fontStyle: "italic",
};

export const skeletonBarStyle: CSSProperties = {
  height: 16,
  borderRadius: "var(--radius-sm)",
  background: "var(--surface-well)",
  animation: "relay-skel-pulse 1.6s ease-in-out infinite",
  margin: "12px 0",
};
