"""Get-or-create-row-1 helpers for the singleton settings tables,
matching mail_log_ingest.py's `_get_state` pattern."""

from sqlalchemy.orm import Session

from app.models.settings import BackgroundJobState, RelaySettings
from app.models.tls import TlsCertificateState, TlsPendingManualChallenge


def get_relay_settings(db: Session) -> RelaySettings:
    settings_row = db.get(RelaySettings, 1)
    if settings_row is None:
        settings_row = RelaySettings(id=1)
        db.add(settings_row)
        db.flush()
    return settings_row


def get_background_job_state(db: Session) -> BackgroundJobState:
    state = db.get(BackgroundJobState, 1)
    if state is None:
        state = BackgroundJobState(id=1)
        db.add(state)
        db.flush()
    return state


def get_tls_certificate_state(db: Session) -> TlsCertificateState:
    state = db.get(TlsCertificateState, 1)
    if state is None:
        state = TlsCertificateState(id=1)
        db.add(state)
        db.flush()
    return state


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
