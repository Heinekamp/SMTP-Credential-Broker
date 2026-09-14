import type { ChangeEvent, CSSProperties, ReactNode } from "react";

export interface SelectProps {
  value?: string | number;
  onChange?: (e: ChangeEvent<HTMLSelectElement>) => void;
  children: ReactNode;
  style?: CSSProperties;
  disabled?: boolean;
}

// Ported from design-system/components-reference/core/select/Select.jsx —
// a plain native dropdown styled to match Button/TextInput's control look.
export function Select({ value, onChange, children, style, disabled }: SelectProps) {
  return (
    <select
      value={value}
      onChange={onChange}
      disabled={disabled}
      style={{
        padding: "8px 14px",
        borderRadius: "var(--radius-md)",
        border: "1px solid var(--border-default)",
        background: "var(--surface-control)",
        color: "var(--text-body)",
        fontFamily: "var(--font-ui)",
        fontSize: "var(--text-sm)",
        opacity: disabled ? 0.4 : 1,
        ...style,
      }}
    >
      {children}
    </select>
  );
}
