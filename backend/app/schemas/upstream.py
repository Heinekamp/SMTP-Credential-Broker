import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import TestResult, TlsMode

# Hostname (RFC 1123 labels) or IPv4 literal — both config_generator.py's
# sasl_passwd/sender_relayhost map lines and control_surface.py's actual
# SMTP connection only make sense with one of these. Also, incidentally,
# rules out the literal tab/newline that would otherwise let a crafted
# host inject an extra record into those tab-separated map files.
_HOST_PATTERN = r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"
# The upstream account's own login name — often an email address, but
# providers vary, so this only excludes what would actually break the
# generated `username:password` sasl_passwd line or inject an extra
# tab-separated map record: whitespace (space/tab/newline/CR) and ':'.
_UPSTREAM_USERNAME_PATTERN = r"^[^\s:]{1,320}$"


class UpstreamAccountCreate(BaseModel):
    name: str
    host: str = Field(pattern=_HOST_PATTERN)
    port: int = Field(gt=0, le=65535)
    tls_mode: TlsMode = TlsMode.starttls
    username: str = Field(pattern=_UPSTREAM_USERNAME_PATTERN)
    password: str = Field(min_length=1)
    # None = unlimited (today's behavior) — paced, not rejected, by a
    # synthetic per-account Postfix transport (core/config_generator.py).
    rate_limit_per_hour: int | None = Field(default=None, ge=1)


class UpstreamAccountUpdate(BaseModel):
    """All fields optional — only supplied fields are changed. `password`
    omitted or blank means "keep the current password" (the write-only
    field contract from claude-design-prompt.md's Upstream Accounts form:
    the stored password is never pre-filled, never returned, and editing
    without retyping it must not clear it)."""

    name: str | None = None
    host: str | None = Field(default=None, pattern=_HOST_PATTERN)
    port: int | None = Field(default=None, gt=0, le=65535)
    tls_mode: TlsMode | None = None
    username: str | None = Field(default=None, pattern=_UPSTREAM_USERNAME_PATTERN)
    password: str | None = None
    enabled: bool | None = None
    rate_limit_per_hour: int | None = Field(default=None, ge=1)


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
    rate_limit_per_hour: int | None
    # How many messages this account has actually sent in the last hour —
    # a real Postfix delivery count (mail_log), not the pacing computation
    # itself; read-only, for the API/UI usage readout.
    sent_this_hour: int
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
