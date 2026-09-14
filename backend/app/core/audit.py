"""Records an admin action to `audit_log` and emits one correlated
structured log line for it (security-model.md §8, database-schema.md §9).
The only place that constructs either — every mutating route calls this
instead of writing AuditLog rows or logging ad hoc, so the "detail is
always non-secret" discipline lives in one spot rather than being
re-trusted at every call site.
"""

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.logging_config import get_logger
from app.models.audit import AuditLog

_logger = get_logger("audit")


def client_ip(request: Request) -> str | None:
    """Shared by every route that calls record_audit — the same
    extraction auth.py's login route already used before this module
    existed."""
    return request.client.host if request.client else None


def record_audit(
    db: Session,
    *,
    admin_user_id: int | None,
    action: str,
    target_type: str | None = None,
    target_id: int | None = None,
    detail: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """`detail` must only ever contain plain, already-safe-to-log values
    (IDs, names, booleans, addresses) — never a password, encrypted blob,
    or TOTP secret. Flushed, not committed: callers already control their
    own transaction boundary (usually committing this alongside the
    change it describes)."""
    db.add(
        AuditLog(
            admin_user_id=admin_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            ip_address=ip_address,
        )
    )
    db.flush()
    # `detail` is deliberately not included in the log line, only in the
    # DB row above — the DB is already the access-controlled place for it;
    # keeping it out of the log stream too is defense in depth against a
    # future call site being less careful than this docstring asks.
    _logger.info(
        action,
        extra={
            "admin_user_id": admin_user_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "ip_address": ip_address,
        },
    )
