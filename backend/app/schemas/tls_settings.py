import datetime

from pydantic import BaseModel, EmailStr


class TlsSettingsRead(BaseModel):
    acme_enabled: bool
    domain: str | None
    contact_email: str | None
    dns_provider: str
    cloudflare_zone_id: str | None
    cloudflare_api_token_configured: bool  # never the token itself
    cert_source: str  # "self_signed" | "lets_encrypt"
    cert_domain: str | None
    cert_not_after: datetime.datetime | None
    cert_issued_at: datetime.datetime | None
    last_checked_at: datetime.datetime | None
    last_renewal_attempt_at: datetime.datetime | None
    last_renewal_error: str | None
    manual_dns_pending: bool
    manual_dns_record_name: str | None
    manual_dns_record_value: str | None
    manual_dns_expires_at: datetime.datetime | None


class TlsSettingsUpdate(BaseModel):
    """All fields optional — only supplied fields are changed, matching
    UpstreamAccountUpdate's existing partial-update convention.
    `cloudflare_api_token` left unset (not sent) keeps the currently
    stored token; there is no way to explicitly clear it back to unset
    other than configuring a new one, same as UpstreamAccountUpdate's
    password field."""

    acme_enabled: bool | None = None
    domain: str | None = None
    contact_email: EmailStr | None = None
    dns_provider: str | None = None
    cloudflare_zone_id: str | None = None
    cloudflare_api_token: str | None = None


class VerifyDnsAccessResponse(BaseModel):
    success: bool
    detail: str


class IssueCertificateResponse(BaseModel):
    success: bool
    detail: str


class ManualDnsChallengeResponse(BaseModel):
    success: bool
    detail: str
    record_name: str | None
    record_value: str | None
    expires_at: datetime.datetime | None
