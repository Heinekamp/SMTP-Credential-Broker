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


def _fail(db_session: Session, *, email: str, admin_user_id: int | None, ip: str, times: int) -> None:
    for _ in range(times):
        record_login_attempt(db_session, email=email, admin_user_id=admin_user_id, ip_address=ip, success=False)
    db_session.commit()


def test_failures_from_one_ip_dont_lock_the_account_out_from_another(db_session: Session) -> None:
    """Regression test for #157: an attacker failing against a known admin
    email from their own IP must not be able to lock the real admin out of
    logging in from somewhere else."""
    admin = _make_admin(db_session, "a@example.com")
    with time_machine.travel(FROZEN):
        _fail(db_session, email=admin.email, admin_user_id=admin.id, ip="6.6.6.6", times=10)

        assert check_rate_limit(db_session, admin_user_id=admin.id, ip_address="6.6.6.6").locked is True
        assert check_rate_limit(db_session, admin_user_id=admin.id, ip_address="10.0.0.1").locked is False


def test_account_wide_counter_catches_guessing_spread_across_ips(db_session: Session) -> None:
    admin = _make_admin(db_session, "a@example.com")
    with time_machine.travel(FROZEN):
        for i in range(20):  # 4 per IP, never tripping any one (account, IP) pair
            _fail(db_session, email=admin.email, admin_user_id=admin.id, ip=f"6.6.6.{i // 4}", times=1)

        assert check_rate_limit(db_session, admin_user_id=admin.id, ip_address="10.0.0.1").locked is True


def test_failures_against_unknown_emails_never_block_a_real_account(db_session: Session) -> None:
    """Regression test for #157: everyone behind one reverse proxy shares
    an IP, so a spray of random emails from it must not lock out a real
    admin's correct login from that same IP."""
    admin = _make_admin(db_session, "a@example.com")
    with time_machine.travel(FROZEN):
        _fail(db_session, email="guess@example.com", admin_user_id=None, ip="10.0.0.1", times=15)

        assert check_rate_limit(db_session, admin_user_id=None, ip_address="10.0.0.1").locked is True
        assert check_rate_limit(db_session, admin_user_id=admin.id, ip_address="10.0.0.1").locked is False


def test_known_and_unknown_emails_lock_at_the_same_attempt(db_session: Session) -> None:
    """Regression test for #157: if a real email locked sooner (or later)
    than an unknown one, the 401-vs-429 pattern would reveal which admin
    emails exist."""
    admin = _make_admin(db_session, "a@example.com")
    with time_machine.travel(FROZEN):
        for attempt in range(1, 7):
            _fail(db_session, email=admin.email, admin_user_id=admin.id, ip="6.6.6.6", times=1)
            _fail(db_session, email="nobody@example.com", admin_user_id=None, ip="7.7.7.7", times=1)
            known = check_rate_limit(db_session, admin_user_id=admin.id, ip_address="6.6.6.6").locked
            unknown = check_rate_limit(db_session, admin_user_id=None, ip_address="7.7.7.7").locked
            assert known == unknown, f"diverged after {attempt} failures"
