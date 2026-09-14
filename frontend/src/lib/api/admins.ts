import { apiFetch } from "../apiClient";

export interface AdminRead {
  id: number;
  email: string;
  totp_enabled: boolean;
  created_at: string;
  last_login_at: string | null;
}

export function listAdmins(): Promise<AdminRead[]> {
  return apiFetch<AdminRead[]>("/api/admins");
}

export function createAdmin(email: string, password: string): Promise<AdminRead> {
  return apiFetch<AdminRead>("/api/admins", { method: "POST", body: JSON.stringify({ email, password }) });
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

export function confirmTotp(secret: string, code: string): Promise<void> {
  return apiFetch<void>("/api/admins/me/totp/confirm", {
    method: "POST",
    body: JSON.stringify({ secret, code }),
  });
}

export function removeTotp(): Promise<void> {
  return apiFetch<void>("/api/admins/me/totp/remove", { method: "POST" });
}
