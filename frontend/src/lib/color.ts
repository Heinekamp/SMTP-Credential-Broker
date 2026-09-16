/** WCAG relative luminance of a "#rrggbb" hex color, used to decide
 * whether black or white text stays readable on top of it — needed
 * because an admin-chosen accent color (issue #53) isn't guaranteed to
 * be dark like the fixed brand green was. */
function relativeLuminance(hex: string): number {
  const r = parseInt(hex.slice(1, 3), 16) / 255;
  const g = parseInt(hex.slice(3, 5), 16) / 255;
  const b = parseInt(hex.slice(5, 7), 16) / 255;
  const channel = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/** Returns a near-black or white ink color, whichever reads better on
 * the given "#rrggbb" background. */
export function pickInkColor(hex: string): string {
  return relativeLuminance(hex) > 0.5 ? "#0b0f16" : "#ffffff";
}
