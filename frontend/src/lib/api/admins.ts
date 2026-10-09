import { ApiError, apiFetch } from "../apiClient";

export interface AdminRead {
  id: number;
  email: string;
  totp_enabled: boolean;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export function listAdmins(): Promise<AdminRead[]> {
  return apiFetch<AdminRead[]>("/api/admins");
}

export function createAdmin(email: string, password: string): Promise<AdminRead> {
  return apiFetch<AdminRead>("/api/admins", { method: "POST", body: JSON.stringify({ email, password }) });
}

export function setAdminActive(id: number, isActive: boolean): Promise<AdminRead> {
  return apiFetch<AdminRead>(`/api/admins/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ is_active: isActive }),
  });
}

export function changeOwnPassword(currentPassword: string, newPassword: string): Promise<void> {
  return apiFetch<void>("/api/admins/me/change-password", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
}

export interface TotpEnrollResponse {
  secret: string;
  otpauth_uri: string;
}

export function enrollTotp(): Promise<TotpEnrollResponse> {
  return apiFetch<TotpEnrollResponse>("/api/admins/me/totp/enroll", { method: "POST" });
}

/** Both TOTP changes need the current password (#169) — a session alone
 * must not be able to add or strip the account's second factor. */
export function confirmTotp(secret: string, code: string, currentPassword: string): Promise<void> {
  return apiFetch<void>("/api/admins/me/totp/confirm", {
    method: "POST",
    body: JSON.stringify({ secret, code, current_password: currentPassword }),
  });
}

export function removeTotp(currentPassword: string): Promise<void> {
  return apiFetch<void>("/api/admins/me/totp/remove", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword }),
  });
}

/** Mirrors the API's minimum for new admin passwords (#169). */
export const MIN_ADMIN_PASSWORD_LENGTH = 12;

/** The API's error text for a failed re-authentication or rate limit. */
export function accountErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (typeof err.detail === "string") return err.detail;
    if (err.status === 429) return "Too many attempts. Try again later.";
  }
  return fallback;
}
