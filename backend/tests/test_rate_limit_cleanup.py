"""run_rate_limit_cleanup is exercised against the db_session fixture.
rate_limit_cleanup_tick opens its own real app.db.session.SessionLocal
internally, so those tests use that shared engine instead, matching
test_retention.py's identical split."""

import asyncio
import datetime

import pytest
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.rate_limit_cleanup import rate_limit_cleanup_tick, run_rate_limit_cleanup
from app.core.settings_store import get_background_job_state
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.local_user import LocalSmtpUser
from app.models.rate_limit import LocalUserRateLimitCounter
from app.models.settings import BackgroundJobState


def _add_counter(db: Session, user_id: int, *, age_hours: float) -> LocalUserRateLimitCounter:
    row = LocalUserRateLimitCounter(
        local_smtp_user_id=user_id,
        window_start=utcnow() - datetime.timedelta(hours=age_hours),
        count=1,
    )
    db.add(row)
    db.commit()
    return row


def _add_user(db: Session) -> LocalSmtpUser:
    user = LocalSmtpUser(name="Printer", username="printer-service", password_hash="x")
    db.add(user)
    db.commit()
    return user


def test_deletes_only_counters_older_than_the_retention_window(db_session: Session) -> None:
    user = _add_user(db_session)
    _add_counter(db_session, user.id, age_hours=10)
    recent = _add_counter(db_session, user.id, age_hours=0.5)

    deleted = run_rate_limit_cleanup(db_session)

    assert deleted == 1
    remaining = db_session.query(LocalUserRateLimitCounter).all()
    assert [r.id for r in remaining] == [recent.id]


def test_leaves_everything_when_nothing_is_old_enough(db_session: Session) -> None:
    user = _add_user(db_session)
    _add_counter(db_session, user.id, age_hours=1)

    deleted = run_rate_limit_cleanup(db_session)

    assert deleted == 0
    assert db_session.query(LocalUserRateLimitCounter).count() == 1


@pytest.fixture(autouse=True)
def _clean_shared_db() -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        db.query(LocalUserRateLimitCounter).delete()
        db.query(LocalSmtpUser).delete()
        db.query(BackgroundJobState).delete()
        db.commit()
    finally:
        db.close()


def test_tick_deletes_expired_rows_and_records_last_run() -> None:
    db = SessionLocal()
    user = _add_user(db)
    _add_counter(db, user.id, age_hours=10)
    db.close()

    asyncio.run(rate_limit_cleanup_tick())

    db = SessionLocal()
    assert db.query(LocalUserRateLimitCounter).count() == 0
    state = get_background_job_state(db)
    assert state.rate_limit_cleanup_last_run_at is not None
    db.close()


def test_tick_skips_when_run_recently() -> None:
    db = SessionLocal()
    user = _add_user(db)
    get_background_job_state(db).rate_limit_cleanup_last_run_at = utcnow() - datetime.timedelta(hours=1)
    _add_counter(db, user.id, age_hours=10)
    db.commit()
    db.close()

    asyncio.run(rate_limit_cleanup_tick())

    db = SessionLocal()
    assert db.query(LocalUserRateLimitCounter).count() == 1  # not yet deleted — last run was too recent
    db.close()
