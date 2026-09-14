import { apiFetch } from "../apiClient";

export interface SystemStatus {
  encryption_key_configured: boolean;
  app_version: string;
}

export function fetchSystemStatus(): Promise<SystemStatus> {
  return apiFetch<SystemStatus>("/api/system-status");
}
