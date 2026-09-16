import { apiFetch, ApiError } from "../apiClient";

export interface Branding {
  accent_color: string | null;
  has_custom_logo: boolean;
}

export type BrandingUpdate = Partial<Branding>;

export function fetchBranding(): Promise<Branding> {
  return apiFetch<Branding>("/api/branding");
}

export function updateBranding(update: BrandingUpdate): Promise<Branding> {
  return apiFetch<Branding>("/api/branding", { method: "PATCH", body: JSON.stringify(update) });
}

function readCsrfCookie(): string | null {
  const match = document.cookie.match(/(?:^|; )csrf_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
}

/** Bypasses apiFetch's JSON Content-Type — a multipart body needs the
 * browser to set its own boundary-including Content-Type header. */
export async function uploadLogo(file: File): Promise<Branding> {
  const formData = new FormData();
  formData.append("file", file);
  const csrf = readCsrfCookie();
  const response = await fetch("/api/branding/logo", {
    method: "POST",
    body: formData,
    credentials: "include",
    headers: csrf ? { "x-csrf-token": csrf } : undefined,
  });
  const text = await response.text();
  const body = text ? JSON.parse(text) : undefined;
  if (!response.ok) throw new ApiError(response.status, body?.detail ?? body);
  return body as Branding;
}

export function deleteLogo(): Promise<Branding> {
  return apiFetch<Branding>("/api/branding/logo", { method: "DELETE" });
}
