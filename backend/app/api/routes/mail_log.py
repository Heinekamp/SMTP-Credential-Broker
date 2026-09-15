import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, cast
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_db
from app.core.mail_log_ingest import ingest_new_log_lines
from app.core.postfix_control import PostfixControlError
from app.models.enums import MailStatus
from app.models.mail_log import MailLog
from app.schemas.mail_log import MailLogEntry, MailLogPage

router = APIRouter(prefix="/mail-log", tags=["mail-log"], dependencies=[Depends(get_current_admin)])


def _naive_utc(value: datetime.datetime | None) -> datetime.datetime | None:
    """MailLog.timestamp is naive UTC (core/clock.py's convention) — see
    audit_log.py's identical helper for why an aware value needs this."""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(datetime.UTC).replace(tzinfo=None)


@router.get("", response_model=MailLogPage)
def list_mail_log(
    db: Session = Depends(get_db),
    envelope_sender: str | None = Query(default=None, description="Substring match, case-insensitive"),
    recipient: str | None = Query(default=None, description="Substring match against any recipient"),
    local_smtp_user_id: int | None = Query(default=None),
    status: MailStatus | None = Query(default=None),
    since: datetime.datetime | None = Query(default=None, description="Only rows at or after this timestamp"),
    until: datetime.datetime | None = Query(default=None, description="Only rows at or before this timestamp"),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> MailLogPage:
    try:
        # Ingested on-demand rather than by a standing background worker
        # (spec doesn't require sub-second freshness, and a worker thread
        # would need its own coordination story across multiple uvicorn
        # workers) — best-effort: an unreachable Postfix container means a
        # stale-but-still-servable log view, not a broken page.
        ingest_new_log_lines(db)
    except PostfixControlError:
        pass

    query = db.query(MailLog)
    if envelope_sender:
        query = query.filter(MailLog.envelope_sender.ilike(f"%{envelope_sender}%"))
    if recipient:
        # recipients is a JSON list, not a plain string column — no native
        # "array contains substring" operator that works the same way
        # across SQLAlchemy's JSON support, so this matches against the
        # column's serialized text form instead. Good enough for an admin
        # searching "did this address receive anything," which is the
        # actual use case; not a precise structured query.
        query = query.filter(cast(MailLog.recipients, String).ilike(f"%{recipient}%"))
    if local_smtp_user_id is not None:
        query = query.filter(MailLog.local_smtp_user_id == local_smtp_user_id)
    if status is not None:
        query = query.filter(MailLog.status == status)
    since = _naive_utc(since)
    until = _naive_utc(until)
    if since is not None:
        query = query.filter(MailLog.timestamp >= since)
    if until is not None:
        query = query.filter(MailLog.timestamp <= until)

    total = query.count()
    entries = query.order_by(MailLog.timestamp.desc(), MailLog.id.desc()).offset(offset).limit(limit).all()
    return MailLogPage(entries=[MailLogEntry.model_validate(e) for e in entries], total=total)
