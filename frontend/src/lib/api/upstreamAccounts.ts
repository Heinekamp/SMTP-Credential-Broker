import { apiFetch } from "../apiClient";

export type TlsMode = "starttls" | "implicit";
export type TestResult = "unknown" | "success" | "failure" | null;

export interface UpstreamAccount {
  id: number;
  name: string;
  host: string;
  port: number;
  tls_mode: TlsMode;
  username: string;
  enabled: boolean;
  last_test_at: string | null;
  last_test_result: TestResult;
  last_test_error: string | null;
  created_at: string;
  updated_at: string;
  /** null = unlimited. */
  rate_limit_per_hour: number | null;
  /** A real delivery count over the last hour (mail_log), not the pacing
   * computation itself. */
  sent_this_hour: number;
}

export interface UpstreamAccountInput {
  name: string;
  host: string;
  port: number;
  tls_mode: TlsMode;
  username: string;
  /** Omitted (undefined) on edit means "keep the current password" — the
   * write-only field contract (design handoff §5). */
  password?: string;
  enabled?: boolean;
  /** null = unlimited. */
  rate_limit_per_hour?: number | null;
}

export interface DeletePrecheck {
  dependent_sender_addresses: string[];
}

export interface TestConnectionStep {
  name: string;
  passed: boolean;
  detail: string;
}

export interface TestConnectionResponse {
  success: boolean;
  steps: TestConnectionStep[];
}

export function listUpstreamAccounts(): Promise<UpstreamAccount[]> {
  return apiFetch<UpstreamAccount[]>("/api/upstream-accounts");
}

export function getUpstreamAccount(id: number): Promise<UpstreamAccount> {
  return apiFetch<UpstreamAccount>(`/api/upstream-accounts/${id}`);
}

export function createUpstreamAccount(input: UpstreamAccountInput): Promise<UpstreamAccount> {
  return apiFetch<UpstreamAccount>("/api/upstream-accounts", { method: "POST", body: JSON.stringify(input) });
}

export function updateUpstreamAccount(id: number, input: Partial<UpstreamAccountInput>): Promise<UpstreamAccount> {
  return apiFetch<UpstreamAccount>(`/api/upstream-accounts/${id}`, { method: "PATCH", body: JSON.stringify(input) });
}

export function deleteUpstreamAccountPrecheck(id: number): Promise<DeletePrecheck> {
  return apiFetch<DeletePrecheck>(`/api/upstream-accounts/${id}/delete-precheck`);
}

export function deleteUpstreamAccount(id: number): Promise<void> {
  return apiFetch<void>(`/api/upstream-accounts/${id}`, { method: "DELETE" });
}

export function testUpstreamAccountConnection(id: number): Promise<TestConnectionResponse> {
  return apiFetch<TestConnectionResponse>(`/api/upstream-accounts/${id}/test-connection`, { method: "POST" });
}
