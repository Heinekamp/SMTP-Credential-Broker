import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_db, require_csrf
from app.core.audit import client_ip, record_audit
from app.core.postfix_control import PostfixControlError, queue_delete, queue_list, queue_requeue
from app.models.admin import AdminUser
from app.schemas.queue import QueueEntry, QueueRecipient

router = APIRouter(prefix="/queue", tags=["queue"], dependencies=[Depends(get_current_admin)])

# A single Postfix queue ID (short or long format). Rejects postsuper's
# special `ALL`, which would retry or delete every queued message (#159);
# control_surface.py enforces the same rule on its side.
QueueId = Path(pattern=r"^[0-9A-Za-z]{6,20}$")


def _to_entry(raw: dict) -> QueueEntry:
    return QueueEntry(
        queue_id=raw["queue_id"],
        queue_name=raw.get("queue_name", ""),
        arrival_time=datetime.datetime.fromtimestamp(raw["arrival_time"], tz=datetime.UTC),
        message_size=raw.get("message_size", 0),
        sender=raw.get("sender", ""),
        recipients=[
            QueueRecipient(address=r.get("address", ""), delay_reason=r.get("delay_reason"))
            for r in raw.get("recipients", [])
        ],
    )


@router.get("", response_model=list[QueueEntry])
def list_queue() -> list[QueueEntry]:
    try:
        raw_entries = queue_list()
    except PostfixControlError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return [_to_entry(e) for e in raw_entries]


def _audit(db: Session, admin: AdminUser, request: Request, action: str, queue_id: str) -> None:
    # Deleting a queued message throws real mail away, so like every other
    # admin action it leaves an audit row (#217). Queue IDs aren't integers,
    # so the ID goes in `detail` rather than `target_id`.
    record_audit(
        db,
        admin_user_id=admin.id,
        action=action,
        target_type="queue_message",
        detail={"queue_id": queue_id},
        ip_address=client_ip(request),
    )
    db.commit()


@router.post("/{queue_id}/retry", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)])
def retry_message(
    request: Request,
    queue_id: str = QueueId,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> None:
    try:
        queue_requeue(queue_id)
    except PostfixControlError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    _audit(db, admin, request, "queue.retry", queue_id)


@router.delete("/{queue_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)])
def delete_message(
    request: Request,
    queue_id: str = QueueId,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> None:
    try:
        queue_delete(queue_id)
    except PostfixControlError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    _audit(db, admin, request, "queue.delete", queue_id)
