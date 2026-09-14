import { apiFetch } from "../apiClient";

export interface Alert {
  kind: string;
  key: string;
  title: string;
  detail: string;
  target_type: string | null;
  target_id: number | null;
  acknowledgeable: boolean;
  acknowledged: boolean;
}

export interface AlertsResponse {
  alerts: Alert[];
  active_count: number;
}

export function fetchAlerts(): Promise<AlertsResponse> {
  return apiFetch<AlertsResponse>("/api/alerts");
}

export function acknowledgeAlert(kind: string): Promise<void> {
  return apiFetch<void>(`/api/alerts/${encodeURIComponent(kind)}/acknowledge`, { method: "POST" });
}
