from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    totp_code: str | None = None


class LoginResponse(BaseModel):
    """Never includes a password, token, or TOTP secret field — enforced by
    omission, matching the "no field defined for it" approach used
    throughout (security-model.md §5)."""

    totp_required: bool
    email: str | None = None


class SessionInfo(BaseModel):
    authenticated: bool
    email: str | None = None


class SetupRequiredResponse(BaseModel):
    setup_required: bool


class SetupRequest(BaseModel):
    email: EmailStr
    password: str
