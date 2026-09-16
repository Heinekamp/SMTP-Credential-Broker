import datetime

from sqlalchemy.orm import Session

from app.core import rate_limit_policy
from app.core.clock import utcnow
from app.models.local_user import LocalSmtpUser
from app.models.rate_limit import LocalUserBurstBucket, LocalUserRateLimitCounter


def _user(
    db: Session,
    *,
    rate_limit_per_hour: int | None,
    rate_limit_burst: int | None = None,
    username: str = "printer-service",
) -> LocalSmtpUser:
    user = LocalSmtpUser(
        name="Printer",
        username=username,
        password_hash="x",
        enabled=True,
        rate_limit_per_hour=rate_limit_per_hour,
        rate_limit_burst=rate_limit_burst,
    )
    db.add(user)
    db.commit()
    return user


def _bucket_for(db: Session, user: LocalSmtpUser) -> LocalUserBurstBucket:
    return db.get(LocalUserBurstBucket, user.id)


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


def test_evaluate_permits_up_to_burst_capacity_then_defers(db_session: Session) -> None:
    user = _user(db_session, rate_limit_per_hour=3600, rate_limit_burst=3)

    for _ in range(3):
        assert rate_limit_policy.evaluate(db_session, {"sasl_username": "printer-service"}) == "action=DUNNO\n\n"

    response = rate_limit_policy.evaluate(db_session, {"sasl_username": "printer-service"})

    assert response == "action=DEFER sending too fast — try again in a moment\n\n"
    # No time has elapsed, so no tokens have refilled — still fully spent.
    assert _bucket_for(db_session, user).tokens < 1.0


def test_burst_defer_does_not_consume_a_token(db_session: Session) -> None:
    user = _user(db_session, rate_limit_per_hour=3600, rate_limit_burst=1)
    rate_limit_policy.evaluate(db_session, {"sasl_username": "printer-service"})  # spends the only token
    before = _bucket_for(db_session, user).tokens

    rate_limit_policy.evaluate(db_session, {"sasl_username": "printer-service"})  # deferred

    after = _bucket_for(db_session, user).tokens
    # Only real-time refill (a few ms here) can move it — the deferred
    # attempt itself must never subtract a token.
    assert before <= after < 1.0


def test_burst_refills_after_simulated_time_passes(db_session: Session) -> None:
    """No time mocking — direct timestamp manipulation, matching this
    project's existing idiom (e.g. test_retention.py)."""
    user = _user(db_session, rate_limit_per_hour=3600, rate_limit_burst=1)  # 1 token/sec refill rate
    rate_limit_policy.evaluate(db_session, {"sasl_username": "printer-service"})  # spends the only token
    assert rate_limit_policy.evaluate(db_session, {"sasl_username": "printer-service"}).startswith("action=DEFER")

    bucket = _bucket_for(db_session, user)
    bucket.last_refill_at = utcnow() - datetime.timedelta(seconds=2)
    db_session.commit()

    response = rate_limit_policy.evaluate(db_session, {"sasl_username": "printer-service"})

    assert response == "action=DUNNO\n\n"


def test_burst_is_never_consulted_without_an_hourly_limit(db_session: Session) -> None:
    """rate_limit_burst without rate_limit_per_hour is rejected at the API
    layer (schemas/local_user.py), but evaluate() itself must also be safe
    against it — there is no sensible refill rate to derive without an
    hourly limit, so it must simply never be consulted."""
    _user(db_session, rate_limit_per_hour=None, rate_limit_burst=1)

    response = rate_limit_policy.evaluate(db_session, {"sasl_username": "printer-service"})

    assert response == "action=DUNNO\n\n"
    assert db_session.query(LocalUserBurstBucket).count() == 0


def test_hourly_defer_message_wins_when_both_limits_are_exceeded(db_session: Session) -> None:
    user = _user(db_session, rate_limit_per_hour=1, rate_limit_burst=1)
    rate_limit_policy.evaluate(db_session, {"sasl_username": "printer-service"})  # consumes both budgets

    response = rate_limit_policy.evaluate(db_session, {"sasl_username": "printer-service"})

    assert "1/hour" in response
    assert "sending too fast" not in response
    # The burst bucket's own refill bookkeeping still isn't skipped.
    assert _bucket_for(db_session, user) is not None


def test_current_burst_tokens_reflects_the_stored_bucket(db_session: Session) -> None:
    user = _user(db_session, rate_limit_per_hour=3600, rate_limit_burst=5)

    assert rate_limit_policy.current_burst_tokens(db_session, user.id, 5, 3600) == 5.0

    rate_limit_policy.evaluate(db_session, {"sasl_username": "printer-service"})

    assert rate_limit_policy.current_burst_tokens(db_session, user.id, 5, 3600) < 5.0


def test_parse_attributes_splits_name_value_lines() -> None:
    lines = [b"sasl_username=printer-service", b"sender=printer@example.com", b"not-a-kv-line"]
    assert rate_limit_policy._parse_attributes(lines) == {
        "sasl_username": "printer-service",
        "sender": "printer@example.com",
    }
