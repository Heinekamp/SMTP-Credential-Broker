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
    created_at: datetime.datetime
    last_login_at: datetime.datetime | None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
