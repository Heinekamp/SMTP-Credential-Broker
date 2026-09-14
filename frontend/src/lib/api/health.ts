import { apiFetch } from "../apiClient";

export interface HealthCheckDetail {
  ok: boolean;
  detail: string;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  database: HealthCheckDetail;
  postfix_reachable: HealthCheckDetail;
  postfix_running: HealthCheckDetail;
  last_generation_result: "pass" | "fail" | "none";
  config_in_sync: HealthCheckDetail;
}

export function fetchHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/api/health");
}
