import type { CSSProperties, ReactNode } from "react";

export interface CardProps {
  children: ReactNode;
  /** Spans the full width of a dashboard's auto-fit grid — used for charts/tables/wide content. */
  wide?: boolean;
  /** Renders the small uppercase muted heading. */
  title?: string;
  style?: CSSProperties;
}

// Ported from design-system/components-reference/core/card/Card.jsx —
// flat surface, 1px border, 8px radius, no shadow.
export function Card({ children, wide = false, title, style }: CardProps) {
  return (
    <div
      style={{
        background: "var(--surface-card)",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--radius-lg)",
        padding: "16px",
        gridColumn: wide ? "1 / -1" : undefined,
        fontFamily: "var(--font-ui)",
        color: "var(--text-body)",
        ...style,
      }}
    >
      {title && (
        <h3
          style={{
            margin: "0 0 10px",
            fontSize: "var(--text-base)",
            color: "var(--text-muted)",
            textTransform: "uppercase",
            letterSpacing: "var(--tracking-label)",
            fontWeight: 400,
          }}
        >
          {title}
        </h3>
      )}
      {children}
    </div>
  );
}
