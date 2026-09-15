import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_db
from app.models.admin import AdminUser
from app.models.audit import AuditLog
from app.schemas.audit_log import AuditLogEntry, AuditLogPage

router = APIRouter(prefix="/audit-log", tags=["audit-log"], dependencies=[Depends(get_current_admin)])


def _naive_utc(value: datetime.datetime | None) -> datetime.datetime | None:
    """AuditLog.timestamp is naive UTC (core/clock.py's convention,
    followed everywhere in this codebase) — a client-supplied timestamp
    with an explicit offset must be normalized the same way, or SQLite
    would compare it against stored rows as a plain string mismatch
    rather than a real datetime comparison."""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(datetime.UTC).replace(tzinfo=None)


@router.get("", response_model=AuditLogPage)
def list_audit_log(
    db: Session = Depends(get_db),
    action: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    admin_user_id: int | None = Query(default=None),
    since: datetime.datetime | None = Query(default=None, description="Only rows at or after this timestamp"),
    until: datetime.datetime | None = Query(default=None, description="Only rows at or before this timestamp"),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> AuditLogPage:
    """Read side of the audit trail every mutating route already writes
    to (core/audit.py) — this was the one piece missing: the data was
    always captured, just never surfaced anywhere short of `sqlite3
    app.db`. Modeled directly on mail_log.py's list endpoint."""
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if target_type:
        query = query.filter(AuditLog.target_type == target_type)
    if admin_user_id is not None:
        query = query.filter(AuditLog.admin_user_id == admin_user_id)
    since = _naive_utc(since)
    until = _naive_utc(until)
    if since is not None:
        query = query.filter(AuditLog.timestamp >= since)
    if until is not None:
        query = query.filter(AuditLog.timestamp <= until)

    total = query.count()
    rows = query.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).offset(offset).limit(limit).all()

    admin_ids = {row.admin_user_id for row in rows if row.admin_user_id is not None}
    email_by_id: dict[int, str] = {}
    if admin_ids:
        email_by_id = dict(
            db.query(AdminUser.id, AdminUser.email).filter(AdminUser.id.in_(admin_ids)).all()
        )

    entries = [
        AuditLogEntry(
            id=row.id,
            timestamp=row.timestamp,
            admin_user_id=row.admin_user_id,
            admin_email=email_by_id.get(row.admin_user_id) if row.admin_user_id is not None else None,
            action=row.action,
            target_type=row.target_type,
            target_id=row.target_id,
            detail=row.detail,
            ip_address=row.ip_address,
        )
        for row in rows
    ]
    return AuditLogPage(entries=entries, total=total)
