import { apiFetch } from "../apiClient";

export type MailStatus = "queued" | "sent" | "deferred" | "bounced" | "rejected";

export interface MailLogEntry {
  id: number;
  queue_id: string;
  timestamp: string;
  local_smtp_user_id: number | null;
  envelope_sender: string;
  recipients: string[];
  upstream_account_id: number | null;
  status: MailStatus;
  error: string | null;
}

export interface MailLogPage {
  entries: MailLogEntry[];
  total: number;
}

export interface MailLogFilter {
  envelope_sender?: string;
  local_smtp_user_id?: number;
  status?: MailStatus;
  limit?: number;
  offset?: number;
}

export function listMailLog(filter: MailLogFilter = {}): Promise<MailLogPage> {
  const params = new URLSearchParams();
  if (filter.envelope_sender) params.set("envelope_sender", filter.envelope_sender);
  if (filter.local_smtp_user_id !== undefined) params.set("local_smtp_user_id", String(filter.local_smtp_user_id));
  if (filter.status) params.set("status", filter.status);
  if (filter.limit !== undefined) params.set("limit", String(filter.limit));
  if (filter.offset !== undefined) params.set("offset", String(filter.offset));
  const query = params.toString();
  return apiFetch<MailLogPage>(`/api/mail-log${query ? `?${query}` : ""}`);
}
