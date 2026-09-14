import datetime

from pydantic import BaseModel, ConfigDict


class LocalUserCreate(BaseModel):
    name: str
    username: str


class LocalUserUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None


class LocalUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    username: str
    enabled: bool
    created_at: datetime.datetime
    password_last_rotated_at: datetime.datetime | None
    allowed_sender_count: int
    # password / password_hash intentionally absent — see local_user.py's
    # model comment and security-model.md §5.


class LocalUserCreateResponse(BaseModel):
    user: LocalUserRead
    password: str


class LocalUserUpdateResponse(BaseModel):
    user: LocalUserRead
    # Populated only when this update re-enabled a previously disabled
    # user — see the route module's comment on why re-enabling must issue
    # a fresh credential rather than resurrecting the old one.
    password: str | None = None


class PasswordRevealResponse(BaseModel):
    password: str


class ConnectionDetails(BaseModel):
    host: str
    port: int
    tls_mode: str
    username: str
    from_addresses: list[str]


class DeleteUserPrecheck(BaseModel):
    allowed_sender_addresses: list[str]


class PermissionListEntry(BaseModel):
    id: int
    address: str
    allowed: bool


class UserPermissionsView(BaseModel):
    user: LocalUserRead
    senders: list[PermissionListEntry]
