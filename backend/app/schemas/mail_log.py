import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import MailStatus


class MailLogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    queue_id: str
    timestamp: datetime.datetime
    local_smtp_user_id: int | None
    envelope_sender: str
    recipients: list[str]
    upstream_account_id: int | None
    status: MailStatus
    error: str | None


class MailLogPage(BaseModel):
    entries: list[MailLogEntry]
    total: int
