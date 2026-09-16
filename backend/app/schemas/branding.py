import re

from pydantic import BaseModel, field_validator

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class BrandingRead(BaseModel):
    accent_color: str | None
    has_custom_logo: bool


class BrandingUpdate(BaseModel):
    """accent_color: null resets to the bundled default green."""

    accent_color: str | None = None

    @field_validator("accent_color")
    @classmethod
    def _validate_hex(cls, value: str | None) -> str | None:
        if value is not None and not _HEX_COLOR_RE.match(value):
            raise ValueError('accent_color must be a "#rrggbb" hex string')
        return value
