import datetime

import time_machine
from sqlalchemy.orm import Session

from app.core.rate_limit import check_rate_limit, record_login_attempt
from app.models.admin import AdminUser

FROZEN = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)


def _make_admin(db_session: Session, email: str) -> AdminUser:
    admin = AdminUser(email=email, password_hash="irrelevant-for-this-test")
    db_session.add(admin)
    db_session.flush()
    return admin


def test_no_attempts_is_not_locked(db_session: Session) -> None:
    admin = _make_admin(db_session, "a@example.com")
    status = check_rate_limit(db_session, admin_user_id=admin.id, ip_address="1.2.3.4")
    assert status.locked is False


def test_five_failures_locks_the_account(db_session: Session) -> None:
    admin = _make_admin(db_session, "a@example.com")
    with time_machine.travel(FROZEN):
        for _ in range(5):
            record_login_attempt(
                db_session, email=admin.email, admin_user_id=admin.id, ip_address="10.0.0.1", success=False
            )
        db_session.commit()

        status = check_rate_limit(db_session, admin_user_id=admin.id, ip_address="10.0.0.1")
        assert status.locked is True
        assert 0 < status.retry_after_seconds <= 60


def test_lockout_expires_after_its_window(db_session: Session) -> None:
    admin = _make_admin(db_session, "a@example.com")
    with time_machine.travel(FROZEN) as traveller:
        for _ in range(5):
            record_login_attempt(
                db_session, email=admin.email, admin_user_id=admin.id, ip_address="10.0.0.1", success=False
            )
        db_session.commit()
        assert check_rate_limit(db_session, admin_user_id=admin.id, ip_address="10.0.0.1").locked is True

        traveller.shift(datetime.timedelta(seconds=61))
        assert check_rate_limit(db_session, admin_user_id=admin.id, ip_address="10.0.0.1").locked is False


def test_lockout_is_isolated_per_account(db_session: Session) -> None:
    admin_a = _make_admin(db_session, "a@example.com")
    admin_b = _make_admin(db_session, "b@example.com")
    with time_machine.travel(FROZEN):
        for _ in range(5):
            record_login_attempt(
                db_session,
                email=admin_a.email,
                admin_user_id=admin_a.id,
                ip_address="10.0.0.1",
                success=False,
            )
        db_session.commit()

        # A different account from a different IP is unaffected.
        status = check_rate_limit(db_session, admin_user_id=admin_b.id, ip_address="10.0.0.2")
        assert status.locked is False


def test_ip_lockout_catches_a_spray_across_unknown_accounts(db_session: Session) -> None:
    with time_machine.travel(FROZEN):
        for _ in range(5):
            # admin_user_id=None: the email doesn't correspond to any real
            # account, as in a spray attack guessing addresses.
            record_login_attempt(
                db_session, email="guess@example.com", admin_user_id=None, ip_address="6.6.6.6", success=False
            )
        db_session.commit()

        # A distinct (also-unknown) account from the same IP is still locked.
        status = check_rate_limit(db_session, admin_user_id=None, ip_address="6.6.6.6")
        assert status.locked is True


def test_success_resets_the_per_account_counter(db_session: Session) -> None:
    admin = _make_admin(db_session, "a@example.com")
    with time_machine.travel(FROZEN) as traveller:
        for _ in range(4):  # below the 5-failure threshold on its own
            record_login_attempt(
                db_session, email=admin.email, admin_user_id=admin.id, ip_address="10.0.0.1", success=False
            )
        traveller.shift(datetime.timedelta(seconds=1))
        record_login_attempt(
            db_session, email=admin.email, admin_user_id=admin.id, ip_address="10.0.0.1", success=True
        )
        db_session.commit()

        status = check_rate_limit(db_session, admin_user_id=admin.id, ip_address="10.0.0.1")
        assert status.locked is False
