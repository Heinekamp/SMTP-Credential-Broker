"""run_rate_limit_abuse_detection is exercised against the db_session
fixture. rate_limit_abuse_tick opens its own real app.db.session.SessionLocal
internally, so those tests use that shared engine instead, matching
test_rate_limit_cleanup.py's identical split."""

import asyncio
import datetime

import pytest
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.postfix_control import PostfixControlError
from app.core.rate_limit_abuse import rate_limit_abuse_tick, run_rate_limit_abuse_detection
from app.core.settings_store import get_relay_settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.audit import AuditLog
from app.models.local_user import LocalSmtpUser
from app.models.settings import RelaySettings


def _throttled_user(
    db: Session, *, minutes_ago: float, enabled: bool = True, username: str = "printer-service"
) -> LocalSmtpUser:
    user = LocalSmtpUser(
        name="Printer",
        username=username,
        password_hash="x",
        enabled=enabled,
        rate_limit_per_hour=10,
        rate_limit_defer_streak_started_at=utcnow() - datetime.timedelta(minutes=minutes_ago),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _enable_auto_disable(db: Session, *, threshold_minutes: int = 10) -> None:
    settings_row = get_relay_settings(db)
    settings_row.rate_limit_abuse_auto_disable_enabled = True
    settings_row.rate_limit_abuse_threshold_minutes = threshold_minutes
    db.commit()


def test_does_nothing_when_disabled_by_default(db_session: Session, fake_postfix_control: list) -> None:
    _throttled_user(db_session, minutes_ago=20)

    disabled = run_rate_limit_abuse_detection(db_session)

    assert disabled == []
    assert fake_postfix_control == []


def test_disables_a_user_past_the_threshold(db_session: Session, fake_postfix_control: list) -> None:
    _enable_auto_disable(db_session)
    user = _throttled_user(db_session, minutes_ago=20)

    disabled = run_rate_limit_abuse_detection(db_session)

    assert [u.id for u in disabled] == [user.id]
    assert user.enabled is False
    assert fake_postfix_control == [("delete", "printer-service")]


def test_leaves_a_user_under_the_threshold_alone(db_session: Session, fake_postfix_control: list) -> None:
    _enable_auto_disable(db_session)
    user = _throttled_user(db_session, minutes_ago=2)

    disabled = run_rate_limit_abuse_detection(db_session)

    assert disabled == []
    assert user.enabled is True
    assert fake_postfix_control == []


def test_leaves_an_already_disabled_user_alone(db_session: Session, fake_postfix_control: list) -> None:
    _enable_auto_disable(db_session)
    _throttled_user(db_session, minutes_ago=20, enabled=False)

    disabled = run_rate_limit_abuse_detection(db_session)

    assert disabled == []
    assert fake_postfix_control == []


def test_records_an_audit_entry(db_session: Session, fake_postfix_control: list) -> None:
    _enable_auto_disable(db_session)
    user = _throttled_user(db_session, minutes_ago=20)

    run_rate_limit_abuse_detection(db_session)

    entry = db_session.query(AuditLog).filter_by(action="local_user.rate_limit_abuse_auto_disabled").one()
    assert entry.admin_user_id is None
    assert entry.target_id == user.id
    assert entry.detail["username"] == "printer-service"


def test_a_control_surface_failure_is_skipped_without_stopping_other_users(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_auto_disable(db_session)
    stuck = _throttled_user(db_session, minutes_ago=20, username="stuck-user")
    healthy_target = _throttled_user(db_session, minutes_ago=30, username="other-user")

    def _flaky(username: str) -> None:
        if username == "stuck-user":
            raise PostfixControlError("unreachable")

    monkeypatch.setattr("app.core.postfix_control.sasl_delete_user", _flaky)

    disabled = run_rate_limit_abuse_detection(db_session)

    assert [u.id for u in disabled] == [healthy_target.id]
    db_session.refresh(stuck)
    assert stuck.enabled is True  # left alone, retried next tick


@pytest.fixture(autouse=True)
def _clean_shared_db() -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        db.query(AuditLog).delete()
        db.query(LocalSmtpUser).delete()
        db.query(RelaySettings).delete()
        db.commit()
    finally:
        db.close()


def test_tick_disables_a_throttled_user_when_enabled(fake_postfix_control: list) -> None:
    db = SessionLocal()
    _enable_auto_disable(db)
    user = _throttled_user(db, minutes_ago=20)
    user_id = user.id
    db.close()

    asyncio.run(rate_limit_abuse_tick())

    db = SessionLocal()
    assert db.get(LocalSmtpUser, user_id).enabled is False
    db.close()


def test_tick_does_nothing_when_disabled() -> None:
    db = SessionLocal()
    user = _throttled_user(db, minutes_ago=20)
    user_id = user.id
    db.close()

    asyncio.run(rate_limit_abuse_tick())

    db = SessionLocal()
    assert db.get(LocalSmtpUser, user_id).enabled is True
    db.close()
