export interface SwitchProps {
  checked?: boolean;
  onChange?: (checked: boolean) => void;
  disabled?: boolean;
  /** Accessible name — the visible text beside a switch isn't associated
   * with it, so without this a screen reader announces just "switch". */
  ariaLabel?: string;
}

// Ported from design-system/components-reference/core/switch/Switch.jsx.
export function Switch({ checked, onChange, disabled, ariaLabel }: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={() => onChange && onChange(!checked)}
      style={{
        width: 44,
        height: 24,
        borderRadius: 12,
        border: "1px solid var(--border-default)",
        background: checked ? "var(--accent)" : "var(--surface-well)",
        position: "relative",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.4 : 1,
        flexShrink: 0,
        padding: 0,
      }}
    >
      <span
        style={{
          position: "absolute",
          top: 2,
          left: checked ? 22 : 2,
          width: 18,
          height: 18,
          borderRadius: "50%",
          background: checked ? "var(--text-on-accent)" : "var(--text-muted)",
        }}
      />
    </button>
  );
}
