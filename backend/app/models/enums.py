import enum

from sqlalchemy import Enum as SAEnum


def str_enum[E: enum.Enum](enum_cls: type[E], name: str) -> SAEnum:
    """A SQLAlchemy Enum column type that stores each member's *value*
    (e.g. "pass") rather than its Python name (e.g. "pass_", needed since
    `pass` is a reserved word) — keeps the on-disk representation identical
    to database-schema.md's plain-string enum definitions."""
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda cls: [member.value for member in cls],
    )


class TlsMode(enum.StrEnum):
    starttls = "starttls"
    implicit = "implicit"


class TestResult(enum.StrEnum):
    unknown = "unknown"
    success = "success"
    failure = "failure"


class MailStatus(enum.StrEnum):
    queued = "queued"
    sent = "sent"
    deferred = "deferred"
    bounced = "bounced"
    rejected = "rejected"


class ValidationResult(enum.StrEnum):
    pass_ = "pass"
    fail = "fail"
