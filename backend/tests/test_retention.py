"""run_retention_cleanup is exercised against the db_session fixture (it
just takes a Session). retention_cleanup_tick opens its own real
app.db.session.SessionLocal internally (same reasoning as
test_scheduled_tests.py/test_update_check.py), so those tests use that
shared engine instead, with an autouse fixture that creates the schema
once and clears the relevant tables before each test.
"""

import asyncio
import datetime

import pytest
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.retention import retention_cleanup_tick, run_retention_cleanup
from app.core.settings_store import get_background_job_state, get_relay_settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.audit import AuditLog
from app.models.enums import MailStatus
from app.models.mail_log import MailLog
from app.models.settings import BackgroundJobState, RelaySettings


def _add_mail_log_row(db: Session, *, age_days: int) -> MailLog:
    row = MailLog(
        queue_id=f"Q{age_days}",
        timestamp=utcnow() - datetime.timedelta(days=age_days),
        envelope_sender="printer@example.com",
        recipients=["dest@example.net"],
        status=MailStatus.sent,
    )
    db.add(row)
    db.commit()
    return row


def _add_audit_log_row(db: Session, *, age_days: int) -> AuditLog:
    row = AuditLog(timestamp=utcnow() - datetime.timedelta(days=age_days), admin_user_id=None, action="probe")
    db.add(row)
    db.commit()
    return row


def test_leaves_everything_when_neither_retention_is_configured(db_session: Session) -> None:
    _add_mail_log_row(db_session, age_days=9999)
    _add_audit_log_row(db_session, age_days=9999)

    mail_deleted, audit_deleted = run_retention_cleanup(db_session)

    assert (mail_deleted, audit_deleted) == (0, 0)
    assert db_session.query(MailLog).count() == 1
    assert db_session.query(AuditLog).count() == 1


def test_deletes_only_mail_log_rows_older_than_the_configured_window(db_session: Session) -> None:
    get_relay_settings(db_session).mail_log_retention_days = 30
    db_session.commit()
    _add_mail_log_row(db_session, age_days=45)
    recent = _add_mail_log_row(db_session, age_days=5)

    mail_deleted, audit_deleted = run_retention_cleanup(db_session)

    assert mail_deleted == 1
    assert audit_deleted == 0
    remaining = db_session.query(MailLog).all()
    assert [r.id for r in remaining] == [recent.id]


def test_deletes_only_audit_log_rows_older_than_the_configured_window(db_session: Session) -> None:
    get_relay_settings(db_session).audit_log_retention_days = 90
    db_session.commit()
    _add_audit_log_row(db_session, age_days=100)
    recent = _add_audit_log_row(db_session, age_days=1)

    mail_deleted, audit_deleted = run_retention_cleanup(db_session)

    assert mail_deleted == 0
    assert audit_deleted == 1
    remaining = db_session.query(AuditLog).all()
    assert [r.id for r in remaining] == [recent.id]


@pytest.fixture(autouse=True)
def _clean_shared_db() -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        db.query(MailLog).delete()
        db.query(AuditLog).delete()
        db.query(RelaySettings).delete()
        db.query(BackgroundJobState).delete()
        db.commit()
    finally:
        db.close()


def test_tick_does_nothing_when_neither_retention_is_configured() -> None:
    db = SessionLocal()
    db.add(
        MailLog(
            queue_id="Q1",
            timestamp=utcnow() - datetime.timedelta(days=9999),
            envelope_sender="a@example.com",
            recipients=[],
            status=MailStatus.sent,
        )
    )
    db.commit()
    db.close()

    asyncio.run(retention_cleanup_tick())

    db = SessionLocal()
    assert db.query(MailLog).count() == 1
    db.close()


def test_tick_deletes_expired_rows_and_records_last_run(monkeypatch: pytest.MonkeyPatch) -> None:
    db = SessionLocal()
    get_relay_settings(db).mail_log_retention_days = 30
    db.add(
        MailLog(
            queue_id="Q1",
            timestamp=utcnow() - datetime.timedelta(days=45),
            envelope_sender="a@example.com",
            recipients=[],
            status=MailStatus.sent,
        )
    )
    db.commit()
    db.close()


    asyncio.run(retention_cleanup_tick())

    db = SessionLocal()
    assert db.query(MailLog).count() == 0
    state = get_background_job_state(db)
    assert state.retention_cleanup_last_run_at is not None
    entry = db.query(AuditLog).filter_by(action="retention.cleanup").one()
    assert entry.detail == {"mail_log_deleted": 1, "audit_log_deleted": 0}
    db.close()


def test_tick_skips_when_run_recently() -> None:
    db = SessionLocal()
    get_relay_settings(db).mail_log_retention_days = 30
    get_background_job_state(db).retention_cleanup_last_run_at = utcnow() - datetime.timedelta(hours=1)
    db.add(
        MailLog(
            queue_id="Q1",
            timestamp=utcnow() - datetime.timedelta(days=45),
            envelope_sender="a@example.com",
            recipients=[],
            status=MailStatus.sent,
        )
    )
    db.commit()
    db.close()


    asyncio.run(retention_cleanup_tick())

    db = SessionLocal()
    assert db.query(MailLog).count() == 1  # not yet deleted — last run was too recent
    db.close()
