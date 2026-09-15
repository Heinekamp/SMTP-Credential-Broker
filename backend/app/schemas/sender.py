import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class SenderCreate(BaseModel):
    # EmailStr (not plain str): this address is tab-joined with other
    # fields into Postfix lookup-map source files (config_generator.py's
    # sender_login/sender_relayhost/sasl_passwd) — a literal tab or
    # newline here would inject an extra, attacker-chosen record into the
    # map Postfix loads. Only admins can set this today, so this is
    # defense-in-depth against a misconfiguration/typo, not a
    # cross-privilege exploit.
    address: EmailStr
    upstream_account_id: int
    enabled: bool = True
    description: str | None = None


class SenderUpdate(BaseModel):
    address: EmailStr | None = None
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
