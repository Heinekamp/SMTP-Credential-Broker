import { useQuery } from "@tanstack/react-query";

import { fetchBranding } from "../lib/api/branding";

interface BrandLogoProps {
  height: number;
  width: number;
}

// Shared by Titlebar/Login/Setup (issue #54) — renders the uploaded
// custom logo once one exists, otherwise the bundled default artwork.
// Public GET /api/branding is safe to call pre-login since /login and
// /setup render this too.
export function BrandLogo({ height, width }: BrandLogoProps) {
  const { data, dataUpdatedAt } = useQuery({ queryKey: ["branding"], queryFn: fetchBranding });
  // Versioned by when branding was last fetched/updated: the logo URL
  // itself never changes, so a fresh upload otherwise kept showing the
  // browser's cached old image until a full reload (#209).
  const src = data?.has_custom_logo ? `/api/branding/logo?v=${dataUpdatedAt}` : "/logo.png";
  return <img src={src} alt="" style={{ height, width, objectFit: "contain" }} />;
}
