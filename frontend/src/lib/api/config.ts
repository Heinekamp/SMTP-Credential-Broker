import { apiFetch } from "../apiClient";

export interface ConfigGeneration {
  id: number;
  generated_at: string;
  triggered_by_admin_id: number | null;
  checksum: string;
  maps_checksum: string;
  validation_result: "pass" | "fail";
  validation_detail: string | null;
  applied: boolean;
  reload_triggered: boolean;
}

export function listConfigGenerations(): Promise<ConfigGeneration[]> {
  return apiFetch<ConfigGeneration[]>("/api/config/generations");
}
