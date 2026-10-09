import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# New admin passwords only — existing ones keep working (#169). Shared
# with schemas/auth.py's SetupRequest and the CLI's create-admin /
# reset-admin-password.
MIN_ADMIN_PASSWORD_LENGTH = 12


class AdminCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=MIN_ADMIN_PASSWORD_LENGTH)


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
    new_password: str = Field(min_length=MIN_ADMIN_PASSWORD_LENGTH)


class TotpEnrollResponse(BaseModel):
    """Nothing is persisted yet — see admins.py's /me/totp/confirm. Shown
    to the admin as copyable text (no QR code — see the Stage 8 plan's
    minimal-dependency rationale); most authenticator apps accept manual
    secret entry."""

    secret: str
    otpauth_uri: str


class TotpConfirmRequest(BaseModel):
    # Base32, as pyotp.random_base32() produces in /me/totp/enroll — a
    # malformed secret used to crash base32 decoding with a 500 (#169).
    secret: str = Field(pattern=r"^[A-Z2-7]{16,128}$")
    code: str
    # Re-authentication: a stolen session alone must not be able to put its
    # own authenticator on the account (#169).
    current_password: str


class TotpRemoveRequest(BaseModel):
    # Re-authentication: a stolen session alone must not be able to strip
    # the account's second factor (#169).
    current_password: str
