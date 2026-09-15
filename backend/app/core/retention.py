"""Deletes mail_log/audit_log rows older than their configured retention
window (relay_settings.mail_log_retention_days /
audit_log_retention_days — None means keep forever, today's behavior,
and is the default so an upgrade never silently starts deleting existing
rows). Runs once a day; unlike connection testing and update checking,
there's no admin-facing interval for this — daily is frequent enough for
a housekeeping job with no real time-sensitivity, and one fewer setting
to expose."""

import asyncio
import datetime

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.clock import utcnow
from app.core.logging_config import get_logger
from app.core.settings_store import get_background_job_state, get_relay_settings
from app.db.session import SessionLocal
from app.models.audit import AuditLog
from app.models.mail_log import MailLog

_logger = get_logger("retention")

_CHECK_INTERVAL = datetime.timedelta(hours=24)


def run_retention_cleanup(db: Session) -> tuple[int, int]:
    """Deletes expired rows and returns (mail_log_deleted, audit_log_deleted).
    Does not audit-log or commit itself — the caller (the tick, or a test)
    controls that, same division of responsibility as
    run_connection_test_batch."""
    settings_row = get_relay_settings(db)
    mail_log_deleted = 0
    audit_log_deleted = 0

    if settings_row.mail_log_retention_days is not None:
        cutoff = utcnow() - datetime.timedelta(days=settings_row.mail_log_retention_days)
        mail_log_deleted = db.query(MailLog).filter(MailLog.timestamp < cutoff).delete(synchronize_session=False)

    if settings_row.audit_log_retention_days is not None:
        cutoff = utcnow() - datetime.timedelta(days=settings_row.audit_log_retention_days)
        audit_log_deleted = (
            db.query(AuditLog).filter(AuditLog.timestamp < cutoff).delete(synchronize_session=False)
        )

    return mail_log_deleted, audit_log_deleted


def _retention_cleanup_tick_sync() -> None:
    db = SessionLocal()
    try:
        settings_row = get_relay_settings(db)
        if settings_row.mail_log_retention_days is None and settings_row.audit_log_retention_days is None:
            return  # neither configured — nothing to do, and no reason to touch background_job_state

        state = get_background_job_state(db)
        if state.retention_cleanup_last_run_at is not None:
            elapsed = utcnow() - state.retention_cleanup_last_run_at
            if elapsed < _CHECK_INTERVAL:
                return

        mail_log_deleted, audit_log_deleted = run_retention_cleanup(db)
        state.retention_cleanup_last_run_at = utcnow()
        if mail_log_deleted or audit_log_deleted:
            # admin_user_id=None matches the existing triggered_by_admin_id
            # precedent on ConfigGeneration for system-triggered work. This
            # row is itself subject to audit_log_retention_days like any
            # other audit row — it does not exempt itself.
            record_audit(
                db,
                admin_user_id=None,
                action="retention.cleanup",
                detail={"mail_log_deleted": mail_log_deleted, "audit_log_deleted": audit_log_deleted},
            )
            _logger.info(
                "retention cleanup deleted %d mail_log row(s) and %d audit_log row(s)",
                mail_log_deleted,
                audit_log_deleted,
            )
        db.commit()
    finally:
        db.close()


async def retention_cleanup_tick() -> None:
    # Bulk DELETEs over potentially large tables are blocking DB work —
    # see connection_test_tick's identical rationale for why this can't
    # run directly on the event loop.
    await asyncio.to_thread(_retention_cleanup_tick_sync)
