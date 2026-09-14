"""Edge-triggered alert email: fires once when a condition transitions
resolved -> active (or, for update-available alerts, once per newly-seen
version), never on every poll while a condition simply persists. Reuses
alerts.py's compute_active_alerts() as its only source of truth for
what's currently wrong, so the bell and the emails can never disagree
about what's active."""

from sqlalchemy.orm import Session

from app.core.alerts import compute_active_alerts
from app.core.logging_config import get_logger
from app.core.mailer import send_alert_email
from app.core.settings_store import get_background_job_state, get_relay_settings
from app.db.session import SessionLocal
from app.models.sender import Sender

_logger = get_logger("alert_email")

# (alert kind, relay_settings toggle attribute, background_job_state
# "currently active" attribute) — the two category-level kinds that are
# edge-triggered on a boolean transition rather than a version change.
_STATE_TRACKED_KINDS = (
    ("health_degraded", "notify_on_health_degraded", "health_degraded_active"),
    ("upstream_test_failure", "notify_on_upstream_test_failure", "upstream_test_failure_active"),
)

# (alert kind, relay_settings toggle attribute, background_job_state
# latest-version attribute, background_job_state last-emailed attribute)
_VERSION_TRACKED_KINDS = (
    ("app_update_available", "notify_on_app_update_available", "latest_app_version", "app_update_last_emailed_version"),
    (
        "postfix_update_available",
        "notify_on_postfix_update_available",
        "latest_postfix_version",
        "postfix_update_last_emailed_version",
    ),
)


def _resolve_sender(db: Session, sender_id: int | None) -> Sender | None:
    if sender_id is None:
        return None
    sender = db.get(Sender, sender_id)
    if sender is None or not sender.enabled or sender.upstream_account is None:
        return None
    return sender


def _send(sender: Sender, recipients: list[str], subject: str, body: str) -> bool:
    try:
        send_alert_email(
            sender=sender, upstream_account=sender.upstream_account, to_addrs=recipients, subject=subject, body=body
        )
        return True
    except Exception:
        # A transient send failure shouldn't suppress the alert forever —
        # the caller leaves "already notified" state unchanged so this
        # retries on the next tick, but shouldn't spam more than once per
        # tick either.
        _logger.warning("alert email send failed", exc_info=True)
        return False


async def alert_email_tick() -> None:
    db = SessionLocal()
    try:
        settings_row = get_relay_settings(db)
        if not settings_row.notify_recipients:
            return
        sender = _resolve_sender(db, settings_row.notify_sender_id)
        if sender is None:
            return

        alerts = compute_active_alerts(db)
        active_kinds = {alert.kind for alert in alerts}
        state = get_background_job_state(db)
        recipients = list(settings_row.notify_recipients)
        changed = False

        for kind, toggle_attr, active_attr in _STATE_TRACKED_KINDS:
            if not getattr(settings_row, toggle_attr):
                continue
            now_active = kind in active_kinds
            was_active = getattr(state, active_attr)
            if now_active and not was_active:
                matching = next((a for a in alerts if a.kind == kind), None)
                subject = f"[SMTP Manager] {matching.title if matching else kind}"
                body = matching.detail if matching else ""
                if _send(sender, recipients, subject, body):
                    setattr(state, active_attr, True)
                    changed = True
            elif not now_active and was_active:
                setattr(state, active_attr, False)
                changed = True

        for kind, toggle_attr, latest_attr, last_emailed_attr in _VERSION_TRACKED_KINDS:
            if not getattr(settings_row, toggle_attr):
                continue
            if kind not in active_kinds:
                continue
            latest_version = getattr(state, latest_attr)
            if latest_version is None or latest_version == getattr(state, last_emailed_attr):
                continue
            matching = next(a for a in alerts if a.kind == kind)
            subject = f"[SMTP Manager] {matching.title}"
            if _send(sender, recipients, subject, matching.detail):
                setattr(state, last_emailed_attr, latest_version)
                changed = True

        if changed:
            db.commit()
    finally:
        db.close()
