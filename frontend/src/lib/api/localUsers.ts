import { apiFetch } from "../apiClient";

export interface LocalUser {
  id: number;
  name: string;
  username: string;
  enabled: boolean;
  created_at: string;
  password_last_rotated_at: string | null;
  allowed_sender_count: number;
}

export interface LocalUserCreateResponse {
  user: LocalUser;
  password: string;
}

export interface LocalUserUpdateResponse {
  user: LocalUser;
  password: string | null;
}

export interface ConnectionDetails {
  host: string;
  port: number;
  tls_mode: string;
  username: string;
  from_addresses: string[];
}

export interface DeleteUserPrecheck {
  allowed_sender_addresses: string[];
}

export interface PermissionListEntry {
  id: number;
  address: string;
  allowed: boolean;
}

export interface UserPermissionsView {
  user: LocalUser;
  senders: PermissionListEntry[];
}

export function listLocalUsers(): Promise<LocalUser[]> {
  return apiFetch<LocalUser[]>("/api/local-users");
}

export function getLocalUser(id: number): Promise<LocalUser> {
  return apiFetch<LocalUser>(`/api/local-users/${id}`);
}

export function createLocalUser(name: string, username: string): Promise<LocalUserCreateResponse> {
  return apiFetch<LocalUserCreateResponse>("/api/local-users", { method: "POST", body: JSON.stringify({ name, username }) });
}

export function updateLocalUser(
  id: number,
  input: { name?: string; enabled?: boolean },
): Promise<LocalUserUpdateResponse> {
  return apiFetch<LocalUserUpdateResponse>(`/api/local-users/${id}`, { method: "PATCH", body: JSON.stringify(input) });
}

export function regenerateLocalUserPassword(id: number): Promise<{ password: string }> {
  return apiFetch<{ password: string }>(`/api/local-users/${id}/regenerate-password`, { method: "POST" });
}

export function deleteLocalUserPrecheck(id: number): Promise<DeleteUserPrecheck> {
  return apiFetch<DeleteUserPrecheck>(`/api/local-users/${id}/delete-precheck`);
}

export function deleteLocalUser(id: number): Promise<void> {
  return apiFetch<void>(`/api/local-users/${id}`, { method: "DELETE" });
}

export function getConnectionDetails(id: number): Promise<ConnectionDetails> {
  return apiFetch<ConnectionDetails>(`/api/local-users/${id}/connection-details`);
}

export function getLocalUserPermissions(id: number): Promise<UserPermissionsView> {
  return apiFetch<UserPermissionsView>(`/api/local-users/${id}/permissions`);
}

export function grantLocalUserPermission(userId: number, senderId: number): Promise<void> {
  return apiFetch<void>(`/api/local-users/${userId}/permissions/${senderId}`, { method: "PUT" });
}

export function revokeLocalUserPermission(userId: number, senderId: number): Promise<void> {
  return apiFetch<void>(`/api/local-users/${userId}/permissions/${senderId}`, { method: "DELETE" });
}
