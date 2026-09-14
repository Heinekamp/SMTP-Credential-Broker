"""Get-or-create-row-1 helpers for the two singleton settings tables,
matching mail_log_ingest.py's `_get_state` pattern."""

from sqlalchemy.orm import Session

from app.models.settings import BackgroundJobState, RelaySettings


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
