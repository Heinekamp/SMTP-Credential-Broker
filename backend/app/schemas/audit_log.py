import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime.datetime
    admin_user_id: int | None
    # Populated by the route (a join), not the ORM row itself — None both
    # for system-triggered rows (admin_user_id is already None there) and
    # for a since-deleted admin (admin_user_id survives deletion with no
    # ON DELETE action, matching database-schema.md's "audit history
    # outlives the admin" intent).
    admin_email: str | None
    action: str
    target_type: str | None
    target_id: int | None
    detail: dict | None
    ip_address: str | None


class AuditLogPage(BaseModel):
    entries: list[AuditLogEntry]
    total: int
