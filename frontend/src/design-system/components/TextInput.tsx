import type { ChangeEvent, CSSProperties, InputHTMLAttributes } from "react";

export interface TextInputProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "style" | "type"> {
  type?: "text" | "number" | "password";
  value?: string | number;
  onChange?: (e: ChangeEvent<HTMLInputElement>) => void;
  placeholder?: string;
  disabled?: boolean;
  style?: CSSProperties;
}

// Ported from design-system/components-reference/core/input/TextInput.jsx.
// No floating labels, no focus-glow — a simple raised-well field with a
// border, matching the source spec exactly.
export function TextInput({
  type = "text",
  value,
  onChange,
  placeholder,
  disabled,
  style,
  ...rest
}: TextInputProps) {
  return (
    <input
      type={type}
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      disabled={disabled}
      style={{
        padding: "8px",
        background: "var(--surface-well)",
        border: "1px solid var(--border-default)",
        color: "var(--text-body)",
        borderRadius: "var(--radius-sm)",
        fontFamily: "var(--font-ui)",
        fontSize: "var(--text-sm)",
        opacity: disabled ? 0.4 : 1,
        ...style,
      }}
      {...rest}
    />
  );
}
