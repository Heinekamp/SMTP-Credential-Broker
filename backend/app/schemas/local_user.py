import datetime

from pydantic import BaseModel, ConfigDict, Field


class LocalUserCreate(BaseModel):
    name: str
    # Restrictive allowlist (not plain str): this username is comma-joined
    # into Postfix's sender_login lookup-map source file
    # (config_generator.py/permissions.py's sender_login_map) alongside a
    # tab-separated sender address, and is also passed as saslpasswd2's
    # trailing argv element (postfix/control_surface.py). A literal tab or
    # newline would inject an extra map record; a leading '-' could be
    # read as a flag by saslpasswd2's own argument parsing, so the pattern
    # requires the first character be alphanumeric. Only admins can set
    # this today, so this is defense-in-depth, not a cross-privilege
    # exploit.
    username: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


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
