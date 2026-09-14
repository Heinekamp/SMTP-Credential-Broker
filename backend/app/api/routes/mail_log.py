from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_db
from app.core.mail_log_ingest import ingest_new_log_lines
from app.core.postfix_control import PostfixControlError
from app.models.enums import MailStatus
from app.models.mail_log import MailLog
from app.schemas.mail_log import MailLogEntry, MailLogPage

router = APIRouter(prefix="/mail-log", tags=["mail-log"], dependencies=[Depends(get_current_admin)])


@router.get("", response_model=MailLogPage)
def list_mail_log(
    db: Session = Depends(get_db),
    envelope_sender: str | None = Query(default=None),
    local_smtp_user_id: int | None = Query(default=None),
    status: MailStatus | None = Query(default=None),
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
        query = query.filter(MailLog.envelope_sender == envelope_sender)
    if local_smtp_user_id is not None:
        query = query.filter(MailLog.local_smtp_user_id == local_smtp_user_id)
    if status is not None:
        query = query.filter(MailLog.status == status)

    total = query.count()
    entries = query.order_by(MailLog.timestamp.desc(), MailLog.id.desc()).offset(offset).limit(limit).all()
    return MailLogPage(entries=[MailLogEntry.model_validate(e) for e in entries], total=total)
