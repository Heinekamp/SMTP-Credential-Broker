import datetime

from sqlalchemy.orm import Session

from app.core import rate_limit_policy
from app.core.clock import utcnow
from app.models.local_user import LocalSmtpUser
from app.models.rate_limit import LocalUserRateLimitCounter


def _user(db: Session, *, rate_limit_per_hour: int | None, username: str = "printer-service") -> LocalSmtpUser:
    user = LocalSmtpUser(
        name="Printer",
        username=username,
        password_hash="x",
        enabled=True,
        rate_limit_per_hour=rate_limit_per_hour,
    )
    db.add(user)
    db.commit()
    return user


def _counter_for(db: Session, user: LocalSmtpUser) -> LocalUserRateLimitCounter:
    return (
        db.query(LocalUserRateLimitCounter)
        .filter(LocalUserRateLimitCounter.local_smtp_user_id == user.id)
        .one()
    )


def test_evaluate_permits_when_no_sasl_username(db_session: Session) -> None:
    """An unauthenticated session has nothing to key a per-user limit on
    — smtpd_relay_restrictions already rejects those long before
    end-of-data anyway."""
    assert rate_limit_policy.evaluate(db_session, {}) == "action=DUNNO\n\n"


def test_evaluate_permits_an_unknown_username(db_session: Session) -> None:
    assert rate_limit_policy.evaluate(db_session, {"sasl_username": "nobody"}) == "action=DUNNO\n\n"


def test_evaluate_permits_when_unlimited(db_session: Session) -> None:
    _user(db_session, rate_limit_per_hour=None)
    response = rate_limit_policy.evaluate(db_session, {"sasl_username": "printer-service"})
    assert response == "action=DUNNO\n\n"


def test_evaluate_permits_and_counts_under_the_limit(db_session: Session) -> None:
    user = _user(db_session, rate_limit_per_hour=2)

    response = rate_limit_policy.evaluate(db_session, {"sasl_username": "printer-service"})

    assert response == "action=DUNNO\n\n"
    assert _counter_for(db_session, user).count == 1


def test_evaluate_defers_once_the_limit_is_reached(db_session: Session) -> None:
    user = _user(db_session, rate_limit_per_hour=2)
    rate_limit_policy.evaluate(db_session, {"sasl_username": "printer-service"})
    rate_limit_policy.evaluate(db_session, {"sasl_username": "printer-service"})

    response = rate_limit_policy.evaluate(db_session, {"sasl_username": "printer-service"})

    assert response.startswith("action=DEFER")
    assert "2/hour" in response
    # The deferred attempt must not itself count — retrying a legitimate
    # send must never make the situation worse.
    assert _counter_for(db_session, user).count == 2


def test_evaluate_starts_a_fresh_window_once_the_previous_one_has_passed(db_session: Session) -> None:
    user = _user(db_session, rate_limit_per_hour=1)
    stale_window = rate_limit_policy._window_start(utcnow()) - datetime.timedelta(hours=1)
    db_session.add(LocalUserRateLimitCounter(local_smtp_user_id=user.id, window_start=stale_window, count=1))
    db_session.commit()

    response = rate_limit_policy.evaluate(db_session, {"sasl_username": "printer-service"})

    assert response == "action=DUNNO\n\n"


def test_parse_attributes_splits_name_value_lines() -> None:
    lines = [b"sasl_username=printer-service", b"sender=printer@example.com", b"not-a-kv-line"]
    assert rate_limit_policy._parse_attributes(lines) == {
        "sasl_username": "printer-service",
        "sender": "printer@example.com",
    }
