import type { ChangeEvent, CSSProperties } from "react";

export interface CheckboxProps {
  checked?: boolean;
  onChange?: (e: ChangeEvent<HTMLInputElement>) => void;
  disabled?: boolean;
  style?: CSSProperties;
}

// Ported from design-system/components-reference/core/checkbox/Checkbox.jsx —
// a native checkbox, no custom skin.
export function Checkbox({ checked, onChange, disabled, style }: CheckboxProps) {
  return (
    <input
      type="checkbox"
      checked={checked}
      onChange={onChange}
      disabled={disabled}
      style={{ width: 16, height: 16, accentColor: "var(--brand-green)", ...style }}
    />
  );
}
