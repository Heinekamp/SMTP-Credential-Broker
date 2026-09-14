import { apiFetch } from "../apiClient";

export interface Sender {
  id: number;
  address: string;
  upstream_account_id: number;
  enabled: boolean;
  description: string | null;
  created_at: string;
  updated_at: string;
  allowed_local_user_count: number;
}

export interface SenderInput {
  address: string;
  upstream_account_id: number;
  enabled?: boolean;
  description?: string | null;
}

export interface DeleteSenderPrecheck {
  allowed_local_user_names: string[];
}

export interface PermissionListEntry {
  id: number;
  name: string;
  username: string;
  allowed: boolean;
}

export interface SenderPermissionsView {
  sender: Sender;
  local_users: PermissionListEntry[];
}

export function listSenders(): Promise<Sender[]> {
  return apiFetch<Sender[]>("/api/senders");
}

export function getSender(id: number): Promise<Sender> {
  return apiFetch<Sender>(`/api/senders/${id}`);
}

export function createSender(input: SenderInput): Promise<Sender> {
  return apiFetch<Sender>("/api/senders", { method: "POST", body: JSON.stringify(input) });
}

export function updateSender(id: number, input: Partial<SenderInput>): Promise<Sender> {
  return apiFetch<Sender>(`/api/senders/${id}`, { method: "PATCH", body: JSON.stringify(input) });
}

export function deleteSenderPrecheck(id: number): Promise<DeleteSenderPrecheck> {
  return apiFetch<DeleteSenderPrecheck>(`/api/senders/${id}/delete-precheck`);
}

export function deleteSender(id: number): Promise<void> {
  return apiFetch<void>(`/api/senders/${id}`, { method: "DELETE" });
}

export function getSenderPermissions(id: number): Promise<SenderPermissionsView> {
  return apiFetch<SenderPermissionsView>(`/api/senders/${id}/permissions`);
}

export function grantSenderPermission(senderId: number, localUserId: number): Promise<void> {
  return apiFetch<void>(`/api/senders/${senderId}/permissions/${localUserId}`, { method: "PUT" });
}

export function revokeSenderPermission(senderId: number, localUserId: number): Promise<void> {
  return apiFetch<void>(`/api/senders/${senderId}/permissions/${localUserId}`, { method: "DELETE" });
}
