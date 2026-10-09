import dataclasses
import datetime
import threading

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.clock import utcnow
from app.models.audit import AuditLog

settings = get_settings()

_LOGIN_SUCCESS = "admin_login.success"
_LOGIN_FAILURE = "admin_login.failure"

# Distributed guessing against one account, spread across many source
# IPs, is caught by an account-wide counter with thresholds this many
# times higher than the per-source ones — high enough that an attacker
# can't lock a real admin out from everywhere with a handful of bad
# logins (#157), low enough to still cap a botnet's guess rate.
_ACCOUNT_WIDE_FACTOR = 4

# Serializes check → verify → record across concurrent login requests
# (api/routes/auth.py holds it). Without it, a burst of parallel attempts
# all pass check_rate_limit() before any of their failures is recorded,
# multiplying the guesses each lockout window allows (#157). One process
# serves the app (backend/entrypoint.sh runs a single uvicorn worker), so
# a process-local lock is enough.
login_lock = threading.Lock()


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


def _lockout_seconds_for(failure_count: int, *, factor: int = 1) -> int | None:
    lockout: int | None = None
    for threshold, seconds in settings.rate_limit_thresholds:
        if failure_count >= threshold * factor:
            lockout = seconds
    return lockout


def _worst_case(db: Session, filters: list, now: datetime.datetime, *, factor: int = 1) -> int:
    failures = (
        db.query(AuditLog.timestamp)
        .filter(AuditLog.action == _LOGIN_FAILURE, *filters)
        .order_by(AuditLog.timestamp.desc())
        .all()
    )
    if not failures:
        return 0
    lockout = _lockout_seconds_for(len(failures), factor=factor)
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
    """Independent counters, the stricter one wins (#157):

    - Known account, per (account, source IP): failures since that
      account's last success. Stops brute force from one source without
      locking the real admin out when they log in from somewhere else.
    - Known account, account-wide: the same failures from every source,
      with thresholds _ACCOUNT_WIDE_FACTOR times higher — catches guessing
      spread across many IPs.
    - Unknown email, per source IP: failures against emails that match no
      account. Spray protection that never counts, and so never blocks, a
      real account's login. Same thresholds as the (account, IP) counter,
      so the 401-then-429 pattern is identical whether an email exists or
      not, and the lockout can't be used to enumerate admin emails.

    A successful login (or a password change, which goes through one)
    clears an account's own counters."""
    now = utcnow()
    window_start = now - datetime.timedelta(seconds=settings.rate_limit_window_seconds)

    if admin_user_id is None:
        if not ip_address:
            return RateLimitStatus(locked=False)
        retry_after = _worst_case(
            db,
            [
                AuditLog.admin_user_id.is_(None),
                AuditLog.ip_address == ip_address,
                AuditLog.timestamp >= window_start,
            ],
            now,
        )
        return RateLimitStatus(locked=retry_after > 0, retry_after_seconds=retry_after)

    last_success = (
        db.query(AuditLog.timestamp)
        .filter(AuditLog.action == _LOGIN_SUCCESS, AuditLog.admin_user_id == admin_user_id)
        .order_by(AuditLog.timestamp.desc())
        .first()
    )
    since = max(last_success[0], window_start) if last_success else window_start
    account_filters = [AuditLog.admin_user_id == admin_user_id, AuditLog.timestamp >= since]

    retry_after = _worst_case(db, account_filters, now, factor=_ACCOUNT_WIDE_FACTOR)
    if ip_address:
        retry_after = max(retry_after, _worst_case(db, [*account_filters, AuditLog.ip_address == ip_address], now))

    return RateLimitStatus(locked=retry_after > 0, retry_after_seconds=retry_after)
