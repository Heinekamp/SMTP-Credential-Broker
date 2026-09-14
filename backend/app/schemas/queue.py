import datetime

from pydantic import BaseModel


class QueueRecipient(BaseModel):
    address: str
    delay_reason: str | None = None


class QueueEntry(BaseModel):
    queue_id: str
    queue_name: str
    arrival_time: datetime.datetime
    message_size: int
    sender: str
    recipients: list[QueueRecipient]
