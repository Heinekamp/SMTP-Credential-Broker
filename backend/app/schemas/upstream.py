import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import TestResult, TlsMode


class UpstreamAccountCreate(BaseModel):
    name: str
    host: str
    port: int = Field(gt=0, le=65535)
    tls_mode: TlsMode = TlsMode.starttls
    username: str
    password: str = Field(min_length=1)


class UpstreamAccountUpdate(BaseModel):
    """All fields optional — only supplied fields are changed. `password`
    omitted or blank means "keep the current password" (the write-only
    field contract from claude-design-prompt.md's Upstream Accounts form:
    the stored password is never pre-filled, never returned, and editing
    without retyping it must not clear it)."""

    name: str | None = None
    host: str | None = None
    port: int | None = Field(default=None, gt=0, le=65535)
    tls_mode: TlsMode | None = None
    username: str | None = None
    password: str | None = None
    enabled: bool | None = None


class UpstreamAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    host: str
    port: int
    tls_mode: TlsMode
    username: str
    enabled: bool
    last_test_at: datetime.datetime | None
    last_test_result: TestResult | None
    last_test_error: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    # encrypted_password is deliberately absent — no field is ever defined
    # for it on an output schema (security-model.md §5's enforcement by
    # omission, not a redaction step applied at serialization time).


class DeletePrecheck(BaseModel):
    """What deleting this account would break — the concrete blast-radius
    warning claude-design-prompt.md's delete confirmation requires."""

    dependent_sender_addresses: list[str]


class TestConnectionStep(BaseModel):
    name: str
    passed: bool
    detail: str


class TestConnectionResponse(BaseModel):
    success: bool
    steps: list[TestConnectionStep]
