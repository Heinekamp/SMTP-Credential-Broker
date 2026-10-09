import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.api.deps import get_current_admin, require_csrf
from app.core.postfix_control import PostfixControlError, queue_delete, queue_list, queue_requeue
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


@router.post("/{queue_id}/retry", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)])
def retry_message(queue_id: str = QueueId) -> None:
    try:
        queue_requeue(queue_id)
    except PostfixControlError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.delete("/{queue_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)])
def delete_message(queue_id: str = QueueId) -> None:
    try:
        queue_delete(queue_id)
    except PostfixControlError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
