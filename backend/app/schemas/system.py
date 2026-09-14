from pydantic import BaseModel


class SystemStatus(BaseModel):
    encryption_key_configured: bool
    app_version: str
