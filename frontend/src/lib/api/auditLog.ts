import { apiFetch } from "../apiClient";

export interface AuditLogEntry {
  id: number;
  timestamp: string;
  admin_user_id: number | null;
  admin_email: string | null;
  action: string;
  target_type: string | null;
  target_id: number | null;
  detail: Record<string, unknown> | null;
  ip_address: string | null;
}

export interface AuditLogPage {
  entries: AuditLogEntry[];
  total: number;
}

export interface AuditLogFilter {
  action?: string;
  target_type?: string;
  admin_user_id?: number;
  since?: string;
  until?: string;
  limit?: number;
  offset?: number;
}

export function listAuditLog(filter: AuditLogFilter = {}): Promise<AuditLogPage> {
  const params = new URLSearchParams();
  if (filter.action) params.set("action", filter.action);
  if (filter.target_type) params.set("target_type", filter.target_type);
  if (filter.admin_user_id !== undefined) params.set("admin_user_id", String(filter.admin_user_id));
  if (filter.since) params.set("since", filter.since);
  if (filter.until) params.set("until", filter.until);
  if (filter.limit !== undefined) params.set("limit", String(filter.limit));
  if (filter.offset !== undefined) params.set("offset", String(filter.offset));
  const query = params.toString();
  return apiFetch<AuditLogPage>(`/api/audit-log${query ? `?${query}` : ""}`);
}
