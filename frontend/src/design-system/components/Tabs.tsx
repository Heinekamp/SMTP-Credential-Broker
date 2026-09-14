export interface TabsProps {
  tabs: { value: string; label: string }[];
  active: string;
  onChange?: (value: string) => void;
}

// Ported from design-system/components-reference/core/tabs/Tabs.jsx — a row
// of Button-styled tab buttons, not a separate widget class in the source.
export function Tabs({ tabs, active, onChange }: TabsProps) {
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
      {tabs.map((t) => (
        <button
          key={t.value}
          type="button"
          onClick={() => onChange && onChange(t.value)}
          style={{
            padding: "8px 14px",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border-default)",
            fontFamily: "var(--font-ui)",
            fontSize: "var(--text-sm)",
            cursor: "pointer",
            background: active === t.value ? "var(--brand-green)" : "var(--surface-control)",
            color: active === t.value ? "var(--brand-green-ink)" : "var(--text-body)",
            fontWeight: active === t.value ? 600 : 400,
          }}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
