import { apiFetch } from "../apiClient";

export interface SystemStatus {
  encryption_key_configured: boolean;
  app_version: string;
  postfix_version: string | null;
}

export function fetchSystemStatus(): Promise<SystemStatus> {
  return apiFetch<SystemStatus>("/api/system-status");
}
