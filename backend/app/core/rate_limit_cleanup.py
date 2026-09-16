"""Deletes local_user_rate_limit_counters rows once their hourly window
has clearly passed. rate_limit_policy.evaluate() never reads a row for
any window but the current one, so an expired row carries no information
worth keeping — this is pure housekeeping, not correctness-critical, so
unlike retention.py's mail_log/audit_log cleanup there's no admin toggle
and no audit log entry: it always runs, once a day, deleting something
nothing else in the app can ever observe again."""

import asyncio
import datetime

from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.logging_config import get_logger
from app.core.settings_store import get_background_job_state
from app.db.session import SessionLocal
from app.models.rate_limit import LocalUserRateLimitCounter

_logger = get_logger("rate_limit_cleanup")

_CHECK_INTERVAL = datetime.timedelta(hours=24)
# Comfortably past the end of the window a row belongs to before it's
# swept up — plenty of slack for a very late-arriving policy request.
_RETAIN = datetime.timedelta(hours=3)


def run_rate_limit_cleanup(db: Session) -> int:
    """Deletes expired counter rows and returns how many. Does not commit
    itself — same division of responsibility as run_retention_cleanup."""
    cutoff = utcnow() - _RETAIN
    return (
        db.query(LocalUserRateLimitCounter)
        .filter(LocalUserRateLimitCounter.window_start < cutoff)
        .delete(synchronize_session=False)
    )


def _rate_limit_cleanup_tick_sync() -> None:
    db = SessionLocal()
    try:
        state = get_background_job_state(db)
        if state.rate_limit_cleanup_last_run_at is not None:
            elapsed = utcnow() - state.rate_limit_cleanup_last_run_at
            if elapsed < _CHECK_INTERVAL:
                return

        deleted = run_rate_limit_cleanup(db)
        state.rate_limit_cleanup_last_run_at = utcnow()
        if deleted:
            _logger.info("rate limit cleanup deleted %d expired counter row(s)", deleted)
        db.commit()
    finally:
        db.close()


async def rate_limit_cleanup_tick() -> None:
    # Bulk DELETE is blocking DB work — see connection_test_tick's
    # identical rationale for why this can't run directly on the event loop.
    await asyncio.to_thread(_rate_limit_cleanup_tick_sync)
