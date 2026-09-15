from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_db, require_csrf
from app.core.alert_email import resolve_notification_sender, send_test_alert
from app.core.audit import client_ip, record_audit
from app.core.settings_store import get_relay_settings
from app.models.admin import AdminUser
from app.schemas.notification_settings import NotificationSettingsRead, NotificationSettingsUpdate, TestAlertResponse

router = APIRouter(
    prefix="/notification-settings", tags=["notification-settings"], dependencies=[Depends(get_current_admin)]
)


def _to_read(settings_row) -> NotificationSettingsRead:
    return NotificationSettingsRead(
        connection_test_interval_minutes=settings_row.connection_test_interval_minutes,
        update_check_enabled=settings_row.update_check_enabled,
        notify_recipients=settings_row.notify_recipients,
        notify_sender_id=settings_row.notify_sender_id,
        notify_from_name=settings_row.notify_from_name,
        notify_on_health_degraded=settings_row.notify_on_health_degraded,
        notify_on_upstream_test_failure=settings_row.notify_on_upstream_test_failure,
        notify_on_app_update_available=settings_row.notify_on_app_update_available,
        notify_on_postfix_update_available=settings_row.notify_on_postfix_update_available,
        mail_log_retention_days=settings_row.mail_log_retention_days,
        audit_log_retention_days=settings_row.audit_log_retention_days,
    )


@router.get("", response_model=NotificationSettingsRead)
def get_notification_settings(db: Session = Depends(get_db)) -> NotificationSettingsRead:
    return _to_read(get_relay_settings(db))


@router.patch("", response_model=NotificationSettingsRead, dependencies=[Depends(require_csrf)])
def update_notification_settings(
    payload: NotificationSettingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> NotificationSettingsRead:
    settings_row = get_relay_settings(db)
    # exclude_unset (not exclude_none) — a field explicitly sent as null
    # (e.g. clearing connection_test_interval_minutes back to "disabled")
    # must still be applied; only fields the client didn't send at all
    # should be left untouched.
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(settings_row, field, value)

    record_audit(
        db,
        admin_user_id=admin.id,
        action="notification_settings.update",
        target_type="relay_settings",
        target_id=settings_row.id,
        detail={"fields": list(updates.keys())},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(settings_row)
    return _to_read(settings_row)


@router.post("/test", response_model=TestAlertResponse, dependencies=[Depends(require_csrf)])
def send_test_notification(
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> TestAlertResponse:
    """Sends one real alert email right now, using whatever
    recipients/sender/from-name are currently configured — proves the
    pipeline actually works without waiting for a real degraded/failure
    condition to trigger it. A precondition that makes sending flatly
    impossible (no recipients, no usable sender) is a 400; an actual send
    failure (bad credentials, unreachable upstream) is reported as
    success: false with the real error, the same "diagnostic report, not
    an exception" contract the Test Connection button already uses."""
    settings_row = get_relay_settings(db)
    if not settings_row.notify_recipients:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Configure at least one recipient first.")
    sender = resolve_notification_sender(db, settings_row.notify_sender_id)
    if sender is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Select a sender with a working upstream account first.")

    success, detail = send_test_alert(
        db,
        sender=sender,
        recipients=list(settings_row.notify_recipients),
        from_name=settings_row.notify_from_name,
    )
    record_audit(
        db,
        admin_user_id=admin.id,
        action="notification_settings.test_alert",
        target_type="relay_settings",
        target_id=settings_row.id,
        detail={"success": success},
        ip_address=client_ip(request),
    )
    db.commit()
    return TestAlertResponse(success=success, detail=detail)
