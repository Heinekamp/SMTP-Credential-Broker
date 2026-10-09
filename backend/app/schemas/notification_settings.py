from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import PartialUpdate


class NotificationSettingsRead(BaseModel):
    connection_test_interval_minutes: int | None
    update_check_enabled: bool
    notify_recipients: list[str]
    notify_sender_id: int | None
    notify_from_name: str | None
    notify_on_health_degraded: bool
    notify_on_upstream_test_failure: bool
    notify_on_app_update_available: bool
    notify_on_postfix_update_available: bool
    notify_on_rate_limit_abuse: bool
    rate_limit_abuse_auto_disable_enabled: bool
    rate_limit_abuse_threshold_minutes: int
    mail_log_retention_days: int | None
    audit_log_retention_days: int | None


class NotificationSettingsUpdate(PartialUpdate):
    """All fields optional — only supplied fields are changed, matching
    UpstreamAccountUpdate's existing partial-update convention."""

    # null = off. 0 used to mean an upstream AUTH attempt every minute (#189).
    connection_test_interval_minutes: int | None = Field(default=None, ge=1)
    update_check_enabled: bool | None = None
    notify_recipients: list[EmailStr] | None = None
    notify_sender_id: int | None = None
    notify_from_name: str | None = None
    notify_on_health_degraded: bool | None = None
    notify_on_upstream_test_failure: bool | None = None
    notify_on_app_update_available: bool | None = None
    notify_on_postfix_update_available: bool | None = None
    notify_on_rate_limit_abuse: bool | None = None
    rate_limit_abuse_auto_disable_enabled: bool | None = None
    rate_limit_abuse_threshold_minutes: int | None = Field(default=None, ge=1)
    # null = keep forever. 0 or less used to make the retention tick delete
    # everything — for the audit log, including the record of this very
    # change and the login failures the brute-force lockout counts (#189).
    mail_log_retention_days: int | None = Field(default=None, ge=1)
    audit_log_retention_days: int | None = Field(default=None, ge=1)

    NON_NULLABLE = frozenset(
        {
            "update_check_enabled",
            "notify_recipients",
            "notify_on_health_degraded",
            "notify_on_upstream_test_failure",
            "notify_on_app_update_available",
            "notify_on_postfix_update_available",
            "notify_on_rate_limit_abuse",
            "rate_limit_abuse_auto_disable_enabled",
            "rate_limit_abuse_threshold_minutes",
        }
    )


class TestAlertResponse(BaseModel):
    success: bool
    detail: str
