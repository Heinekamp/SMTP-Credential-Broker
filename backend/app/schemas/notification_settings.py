from pydantic import BaseModel, EmailStr


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


class NotificationSettingsUpdate(BaseModel):
    """All fields optional — only supplied fields are changed, matching
    UpstreamAccountUpdate's existing partial-update convention."""

    connection_test_interval_minutes: int | None = None
    update_check_enabled: bool | None = None
    notify_recipients: list[EmailStr] | None = None
    notify_sender_id: int | None = None
    notify_from_name: str | None = None
    notify_on_health_degraded: bool | None = None
    notify_on_upstream_test_failure: bool | None = None
    notify_on_app_update_available: bool | None = None
    notify_on_postfix_update_available: bool | None = None
