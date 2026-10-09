import type { KeyboardEvent, ReactNode } from "react";

export interface TabsProps {
  tabs: { value: string; label: string }[];
  active: string;
  onChange?: (value: string) => void;
  /** Prefix for the tab/panel ids — wrap the active tab's content in a
   * `<TabPanel>` with the same prefix. */
  idPrefix: string;
  ariaLabel?: string;
}

/** The active tab's content, tied to its tab (aria-labelledby / aria-controls). */
export function TabPanel({ idPrefix, value, children }: { idPrefix: string; value: string; children: ReactNode }) {
  return (
    <div role="tabpanel" id={`${idPrefix}-panel-${value}`} aria-labelledby={`${idPrefix}-tab-${value}`}>
      {children}
    </div>
  );
}

// Ported from design-system/components-reference/core/tabs/Tabs.jsx — a row
// of Button-styled tab buttons, not a separate widget class in the source.
// Exposed as a real tablist (#211): roles + aria-selected, one tab stop with
// arrow/Home/End keys moving between tabs, as in the WAI-ARIA tabs pattern.
export function Tabs({ tabs, active, onChange, idPrefix, ariaLabel }: TabsProps) {
  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const index = tabs.findIndex((t) => t.value === active);
    let next: number;
    if (e.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (e.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tabs.length - 1;
    else return;
    e.preventDefault();
    onChange?.(tabs[next].value);
    document.getElementById(`${idPrefix}-tab-${tabs[next].value}`)?.focus();
  }

  return (
    <div role="tablist" aria-label={ariaLabel} onKeyDown={onKeyDown} style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
      {tabs.map((t) => (
        <button
          key={t.value}
          type="button"
          role="tab"
          id={`${idPrefix}-tab-${t.value}`}
          aria-selected={active === t.value}
          aria-controls={`${idPrefix}-panel-${t.value}`}
          tabIndex={active === t.value ? 0 : -1}
          onClick={() => onChange && onChange(t.value)}
          style={{
            padding: "8px 14px",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border-default)",
            fontFamily: "var(--font-ui)",
            fontSize: "var(--text-sm)",
            cursor: "pointer",
            background: active === t.value ? "var(--accent)" : "var(--surface-control)",
            color: active === t.value ? "var(--text-on-accent)" : "var(--text-body)",
            fontWeight: active === t.value ? 600 : 400,
          }}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
