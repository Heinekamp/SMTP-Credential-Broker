import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class AdminCreate(BaseModel):
    email: EmailStr
    password: str


class AdminRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    # Never the secret itself — just whether one is enrolled (security-model.md §5).
    totp_enabled: bool
    is_active: bool
    created_at: datetime.datetime
    last_login_at: datetime.datetime | None


class AdminUpdate(BaseModel):
    """Only `is_active` is settable here — deliberately not a general
    admin-editing endpoint. There's still no admin-resets-another-admin's-
    password/TOTP path; this is purely for deactivate/reactivate."""

    is_active: bool


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class TotpEnrollResponse(BaseModel):
    """Nothing is persisted yet — see admins.py's /me/totp/confirm. Shown
    to the admin as copyable text (no QR code — see the Stage 8 plan's
    minimal-dependency rationale); most authenticator apps accept manual
    secret entry."""

    secret: str
    otpauth_uri: str


class TotpConfirmRequest(BaseModel):
    secret: str
    code: str
