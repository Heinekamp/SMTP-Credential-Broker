from typing import Annotated, Any, ClassVar

from pydantic import AfterValidator, BaseModel, Field, model_validator


class PartialUpdate(BaseModel):
    """Base for PATCH schemas, where every field is optional so it can be
    left out. Leaving a field out means "unchanged"; an explicit `null` is
    only allowed where null *means* something (unset, keep forever,
    unlimited, keep the current password). For the fields listed in
    NON_NULLABLE it used to reach the database as NULL — a 500 from a
    NOT NULL constraint, or a misleading 409 (#189)."""

    NON_NULLABLE: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_null(cls, data: Any) -> Any:
        if isinstance(data, dict):
            nulled = sorted(name for name in cls.NON_NULLABLE if name in data and data[name] is None)
            if nulled:
                raise ValueError(f"{', '.join(nulled)} cannot be null — omit a field to leave it unchanged")
        return data


def _no_control_characters(value: str) -> str:
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise ValueError("must not contain control characters such as line breaks or tabs")
    return value


def _no_surrounding_whitespace(value: str) -> str:
    if value != value.strip():
        raise ValueError("must not start or end with whitespace")
    return value


# Display names that end up in email subjects (alert_email.py) and CSV
# exports — a CR/LF there broke every alert send (#175).
SingleLineName = Annotated[str, Field(min_length=1, max_length=200), AfterValidator(_no_control_characters)]

# An upstream SMTP password lands in the tab/newline-separated sasl_passwd
# map, where a separator would inject a record and postmap silently trims
# surrounding whitespace, leaving a password that never matches (#175).
UpstreamPassword = Annotated[
    str,
    Field(min_length=1),
    AfterValidator(_no_control_characters),
    AfterValidator(_no_surrounding_whitespace),
]
