import { apiFetch } from "../apiClient";

export interface TlsSettings {
  acme_enabled: boolean;
  domain: string | null;
  contact_email: string | null;
  dns_provider: string;
  cloudflare_zone_id: string | null;
  cloudflare_api_token_configured: boolean;
  cert_source: "self_signed" | "lets_encrypt";
  cert_domain: string | null;
  cert_not_after: string | null;
  cert_issued_at: string | null;
  last_checked_at: string | null;
  last_renewal_attempt_at: string | null;
  last_renewal_error: string | null;
}

export interface TlsSettingsUpdate {
  acme_enabled?: boolean;
  domain?: string | null;
  contact_email?: string | null;
  dns_provider?: string;
  cloudflare_zone_id?: string | null;
  /** Omitted (not sent) keeps the currently stored token — same
   * write-only, "leave blank to keep current" convention as an upstream
   * account's password field. */
  cloudflare_api_token?: string;
}

export interface TlsActionResult {
  success: boolean;
  detail: string;
}

export function fetchTlsSettings(): Promise<TlsSettings> {
  return apiFetch<TlsSettings>("/api/tls-settings");
}

export function updateTlsSettings(update: TlsSettingsUpdate): Promise<TlsSettings> {
  return apiFetch<TlsSettings>("/api/tls-settings", {
    method: "PATCH",
    body: JSON.stringify(update),
  });
}

/** A read-only precheck — confirms the configured Cloudflare token can
 * see and manage the domain's zone, without creating any DNS record or
 * spending a Let's Encrypt rate-limited attempt. */
export function verifyCloudflareAccess(): Promise<TlsActionResult> {
  return apiFetch<TlsActionResult>("/api/tls-settings/verify-dns-access", { method: "POST" });
}

/** Runs one real ACME issuance attempt right now using whatever is
 * currently saved — the caller should Save first if there are unsaved
 * changes. Subject to Let's Encrypt's rate limits. */
export function issueCertificateNow(): Promise<TlsActionResult> {
  return apiFetch<TlsActionResult>("/api/tls-settings/issue", { method: "POST" });
}
