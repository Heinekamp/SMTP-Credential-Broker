export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : "Request failed");
    this.status = status;
    this.detail = detail;
  }
}

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (MUTATING_METHODS.has(method)) {
    // Double-submit CSRF: the cookie the server set is echoed back as a
    // header. A same-site fetch is the only thing that can read this
    // cookie and attach it — see backend/app/core/csrf.py.
    const csrf = readCookie("csrf_token");
    if (csrf) headers.set("x-csrf-token", csrf);
  }

  const response = await fetch(path, { ...options, method, headers, credentials: "include" });
  // A 204 (every DELETE/PUT-permission endpoint in this app) has no body,
  // but FastAPI still sends a `Content-Type: application/json` header —
  // response.json() on that empty body throws "Unexpected end of JSON
  // input". Reading the raw text first and only parsing it when non-empty
  // handles that regardless of status code, rather than special-casing 204.
  const isJson = response.headers.get("content-type")?.includes("application/json") ?? false;
  const text = await response.text();
  const body = isJson && text ? JSON.parse(text) : undefined;

  if (!response.ok) {
    throw new ApiError(response.status, body?.detail ?? body);
  }
  return body as T;
}

export interface SessionInfo {
  authenticated: boolean;
  email: string | null;
}

export interface LoginResponse {
  totp_required: boolean;
  email: string | null;
}

export interface RateLimitDetail {
  message: string;
  retry_after_seconds: number;
}

export function fetchSession(): Promise<SessionInfo> {
  return apiFetch<SessionInfo>("/api/auth/session");
}

export function login(email: string, password: string, totpCode?: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password, totp_code: totpCode }),
  });
}

export function logout(): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>("/api/auth/logout", { method: "POST" });
}
