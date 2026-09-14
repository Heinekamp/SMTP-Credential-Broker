import { apiFetch } from "../apiClient";

export interface NotificationSettings {
  connection_test_interval_minutes: number | null;
  update_check_enabled: boolean;
  notify_recipients: string[];
  notify_sender_id: number | null;
  notify_on_health_degraded: boolean;
  notify_on_upstream_test_failure: boolean;
  notify_on_app_update_available: boolean;
  notify_on_postfix_update_available: boolean;
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
