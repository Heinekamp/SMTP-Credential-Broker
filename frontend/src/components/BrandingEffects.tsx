import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";

import { pickInkColor } from "../lib/color";
import { fetchBranding } from "../lib/api/branding";

// Mounted once near the app root (issue #53). Applies the admin-chosen
// accent color as inline overrides on the root element, which win over
// the CSS tokens in colors.css without needing per-theme duplication —
// clearing both when no custom color is set falls back to the fixed
// brand green automatically.
export function BrandingEffects() {
  const { data } = useQuery({ queryKey: ["branding"], queryFn: fetchBranding });

  useEffect(() => {
    const root = document.documentElement.style;
    if (data?.accent_color) {
      root.setProperty("--accent", data.accent_color);
      root.setProperty("--text-on-accent", pickInkColor(data.accent_color));
    } else {
      root.removeProperty("--accent");
      root.removeProperty("--text-on-accent");
    }
  }, [data?.accent_color]);

  return null;
}
