export interface StatTileProps {
  label: string;
  value: string | number;
}

// Ported from design-system/components-reference/data/stat-tile/StatTile.jsx —
// an inset well with a muted label and a large accent-green value.
export function StatTile({ label, value }: StatTileProps) {
  return (
    <div
      style={{
        flex: 1,
        background: "var(--surface-well)",
        borderRadius: "var(--radius-md)",
        padding: "10px 14px",
        display: "flex",
        flexDirection: "column",
        fontFamily: "var(--font-ui)",
      }}
    >
      <span style={{ color: "var(--text-muted)", fontSize: "var(--text-2xs)" }}>{label}</span>
      <span style={{ fontSize: "var(--text-lg)", fontWeight: 600, color: "var(--accent)" }}>{value}</span>
    </div>
  );
}
