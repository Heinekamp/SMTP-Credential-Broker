import { apiFetch } from "../apiClient";
import type { LoginResponse } from "../apiClient";

export interface SetupRequiredResponse {
  setup_required: boolean;
}

export function fetchSetupRequired(): Promise<SetupRequiredResponse> {
  return apiFetch<SetupRequiredResponse>("/api/auth/setup-required");
}

export function submitSetup(email: string, password: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>("/api/auth/setup", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}
