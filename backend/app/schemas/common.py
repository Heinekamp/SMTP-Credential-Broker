from typing import Annotated

from pydantic import AfterValidator, Field


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
