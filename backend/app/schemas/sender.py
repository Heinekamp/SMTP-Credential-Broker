import datetime

from pydantic import BaseModel, ConfigDict


class SenderCreate(BaseModel):
    address: str
    upstream_account_id: int
    enabled: bool = True
    description: str | None = None


class SenderUpdate(BaseModel):
    address: str | None = None
    upstream_account_id: int | None = None
    enabled: bool | None = None
    description: str | None = None


class SenderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    address: str
    upstream_account_id: int
    enabled: bool
    description: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    allowed_local_user_count: int


class DeleteSenderPrecheck(BaseModel):
    allowed_local_user_names: list[str]


class PermissionListEntry(BaseModel):
    id: int
    name: str
    username: str
    allowed: bool


class SenderPermissionsView(BaseModel):
    sender: SenderRead
    local_users: list[PermissionListEntry]
