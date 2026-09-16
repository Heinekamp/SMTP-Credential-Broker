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
  const { data } = useQuery({ queryKey: ["branding"], queryFn: fetchBranding });
  const src = data?.has_custom_logo ? "/api/branding/logo" : "/logo.png";
  return <img src={src} alt="" style={{ height, width, objectFit: "contain" }} />;
}
