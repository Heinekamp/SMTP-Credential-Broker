import { apiFetch } from "../apiClient";

export interface NotificationSettings {
  connection_test_interval_minutes: number | null;
  update_check_enabled: boolean;
  notify_recipients: string[];
  notify_sender_id: number | null;
  notify_from_name: string | null;
  notify_on_health_degraded: boolean;
  notify_on_upstream_test_failure: boolean;
  notify_on_app_update_available: boolean;
  notify_on_postfix_update_available: boolean;
  /** Email once a local user has been throttled continuously past the
   * threshold below. The condition itself always shows on the
   * notification bell regardless of this setting. */
  notify_on_rate_limit_abuse: boolean;
  /** Automatically disables a still-enabled, continuously-throttled
   * local user — a separate escalation on top of the alert above. */
  rate_limit_abuse_auto_disable_enabled: boolean;
  rate_limit_abuse_threshold_minutes: number;
  mail_log_retention_days: number | null;
  audit_log_retention_days: number | null;
}

export type NotificationSettingsUpdate = Partial<NotificationSettings>;

export function fetchNotificationSettings(): Promise<NotificationSettings> {
  return apiFetch<NotificationSettings>("/api/notification-settings");
}

export function updateNotificationSettings(update: NotificationSettingsUpdate): Promise<NotificationSettings> {
  return apiFetch<NotificationSettings>("/api/notification-settings", {
    method: "PATCH",
    body: JSON.stringify(update),
  });
}

export interface TestAlertResult {
  success: boolean;
  detail: string;
}

/** Sends one real alert email right now using whatever is currently
 * saved — the caller should Save first if there are unsaved changes,
 * since this always uses the persisted settings, not the form's local
 * state. */
export function sendTestAlert(): Promise<TestAlertResult> {
  return apiFetch<TestAlertResult>("/api/notification-settings/test", { method: "POST" });
}
