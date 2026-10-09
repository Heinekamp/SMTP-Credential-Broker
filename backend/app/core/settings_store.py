"""Get-or-create-row-1 helpers for the singleton settings tables."""

from sqlalchemy import insert
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.settings import BackgroundJobState, RelaySettings
from app.models.tls import TlsCertificateState, TlsPendingManualChallenge


def get_or_create_singleton[T: Base](db: Session, model: type[T], **defaults: object) -> T:
    """Row 1 of a singleton table, created on first use. Created with
    INSERT … ON CONFLICT DO NOTHING rather than add()+flush(): background
    ticks run in their own threads and sessions, and two of them reaching
    this on a fresh database both used to insert — the loser failing with
    "UNIQUE constraint failed" (#193). Column defaults declared on the
    model apply to the Core insert as well."""
    row = db.get(model, 1)
    if row is not None:
        return row
    dialect = db.get_bind().dialect.name
    values = {"id": 1, **defaults}
    if dialect == "sqlite":
        db.execute(sqlite.insert(model).values(**values).on_conflict_do_nothing(index_elements=["id"]))
    elif dialect == "postgresql":
        db.execute(postgresql.insert(model).values(**values).on_conflict_do_nothing(index_elements=["id"]))
    else:  # no portable upsert — at least as good as before
        db.execute(insert(model).values(**values))
    return db.get(model, 1)


def get_relay_settings(db: Session) -> RelaySettings:
    return get_or_create_singleton(db, RelaySettings)


def get_background_job_state(db: Session) -> BackgroundJobState:
    return get_or_create_singleton(db, BackgroundJobState)


def get_tls_certificate_state(db: Session) -> TlsCertificateState:
    return get_or_create_singleton(db, TlsCertificateState)


def get_tls_pending_manual_challenge(db: Session) -> TlsPendingManualChallenge | None:
    """Unlike the singletons above, absence is a normal state (no manual
    DNS-01 challenge currently in progress) — no auto-create here."""
    return db.get(TlsPendingManualChallenge, 1)


def upsert_tls_pending_manual_challenge(db: Session, **fields: object) -> TlsPendingManualChallenge:
    row = db.get(TlsPendingManualChallenge, 1)
    if row is None:
        row = TlsPendingManualChallenge(id=1, **fields)
        db.add(row)
    else:
        for key, value in fields.items():
            setattr(row, key, value)
    db.flush()
    return row


def clear_tls_pending_manual_challenge(db: Session) -> None:
    row = db.get(TlsPendingManualChallenge, 1)
    if row is not None:
        db.delete(row)
        db.flush()
