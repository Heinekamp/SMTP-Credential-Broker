import dataclasses
import datetime

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.clock import utcnow
from app.models.audit import AuditLog

settings = get_settings()

_LOGIN_SUCCESS = "admin_login.success"
_LOGIN_FAILURE = "admin_login.failure"


@dataclasses.dataclass
class RateLimitStatus:
    locked: bool
    retry_after_seconds: int = 0


def record_login_attempt(
    db: Session,
    *,
    email: str,
    admin_user_id: int | None,
    ip_address: str | None,
    success: bool,
) -> None:
    """Every login attempt — success or failure — becomes an audit_log row.
    This is the sole data source for rate limiting (security-model.md §5:
    "attempts and lockouts recorded in audit_log"), not a separate in-memory
    counter, so it stays correct across restarts and multiple workers."""
    db.add(
        AuditLog(
            admin_user_id=admin_user_id,
            action=_LOGIN_SUCCESS if success else _LOGIN_FAILURE,
            target_type="admin_user",
            target_id=admin_user_id,
            detail={"email": email},
            ip_address=ip_address,
        )
    )
    db.flush()


def _lockout_seconds_for(failure_count: int) -> int | None:
    lockout: int | None = None
    for threshold, seconds in settings.rate_limit_thresholds:
        if failure_count >= threshold:
            lockout = seconds
    return lockout


def _worst_case(db: Session, filters: list, now: datetime.datetime) -> int:
    failures = (
        db.query(AuditLog.timestamp)
        .filter(AuditLog.action == _LOGIN_FAILURE, *filters)
        .order_by(AuditLog.timestamp.desc())
        .all()
    )
    if not failures:
        return 0
    lockout = _lockout_seconds_for(len(failures))
    if lockout is None:
        return 0
    most_recent = failures[0][0]
    retry_after = (most_recent + datetime.timedelta(seconds=lockout) - now).total_seconds()
    return max(0, int(retry_after))


def check_rate_limit(
    db: Session,
    *,
    admin_user_id: int | None,
    ip_address: str | None,
) -> RateLimitStatus:
    """Two independent counters, the stricter one wins:

    - per-account: failures since that account's last success (so a
      password change / successful login clears the account's own count).
    - per-IP: failures within the sliding window regardless of which
      account was targeted (so a spray across many unknown emails from one
      IP still locks by IP, per architecture.md's stated design)."""
    now = utcnow()
    window_start = now - datetime.timedelta(seconds=settings.rate_limit_window_seconds)

    retry_after = 0

    if admin_user_id is not None:
        last_success = (
            db.query(AuditLog.timestamp)
            .filter(AuditLog.action == _LOGIN_SUCCESS, AuditLog.admin_user_id == admin_user_id)
            .order_by(AuditLog.timestamp.desc())
            .first()
        )
        since = max(last_success[0], window_start) if last_success else window_start
        retry_after = max(
            retry_after,
            _worst_case(
                db,
                [AuditLog.admin_user_id == admin_user_id, AuditLog.timestamp >= since],
                now,
            ),
        )

    if ip_address:
        retry_after = max(
            retry_after,
            _worst_case(
                db,
                [AuditLog.ip_address == ip_address, AuditLog.timestamp >= window_start],
                now,
            ),
        )

    return RateLimitStatus(locked=retry_after > 0, retry_after_seconds=retry_after)
