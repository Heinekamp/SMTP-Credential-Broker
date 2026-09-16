import datetime
from importlib.metadata import version

import pytest
from sqlalchemy.orm import Session

from app.core.alerts import compute_active_alerts
from app.core.clock import utcnow
from app.core.encryption import encrypt_secret
from app.core.health import CheckResult, HealthReport
from app.core.postfix_control import PostfixControlError
from app.core.settings_store import get_background_job_state, get_relay_settings
from app.models.enums import TestResult as ConnTestResult
from app.models.enums import TlsMode
from app.models.local_user import LocalSmtpUser
from app.models.upstream import UpstreamAccount

_HEALTHY = HealthReport(
    status="ok",
    database=CheckResult(ok=True),
    postfix_reachable=CheckResult(ok=True),
    postfix_running=CheckResult(ok=True),
    last_generation_result="pass",
    config_in_sync=CheckResult(ok=True),
)
_DEGRADED = HealthReport(
    status="degraded",
    database=CheckResult(ok=True),
    postfix_reachable=CheckResult(ok=True),
    postfix_running=CheckResult(ok=False, detail="not running"),
    last_generation_result="pass",
    config_in_sync=CheckResult(ok=True),
)


@pytest.fixture(autouse=True)
def _healthy_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.alerts.run_health_check", lambda db: _HEALTHY)
    monkeypatch.setattr("app.core.alerts.postfix_control.version", lambda: None)


def test_no_alerts_in_a_clean_state(db_session: Session) -> None:
    assert compute_active_alerts(db_session) == []


def test_degraded_health_produces_an_alert(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.alerts.run_health_check", lambda db: _DEGRADED)
    alerts = compute_active_alerts(db_session)
    assert [a.kind for a in alerts] == ["health_degraded"]
    assert alerts[0].acknowledgeable is False


def _failing_account(db: Session, name: str = "acct") -> UpstreamAccount:
    account = UpstreamAccount(
        name=name,
        host="smtp.example.com",
        port=587,
        tls_mode=TlsMode.starttls,
        username="user@example.com",
        encrypted_password=encrypt_secret("hunter2"),
        last_test_result=ConnTestResult.failure,
        last_test_error="AUTH: bad credentials",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def test_failing_upstream_account_produces_one_alert_per_account(db_session: Session) -> None:
    a1 = _failing_account(db_session, "acct-1")
    a2 = _failing_account(db_session, "acct-2")

    alerts = compute_active_alerts(db_session)

    keys = {a.key for a in alerts}
    assert keys == {f"upstream_test_failure:{a1.id}", f"upstream_test_failure:{a2.id}"}
    assert all(a.target_type == "upstream_account" for a in alerts)


def test_passing_upstream_account_produces_no_alert(db_session: Session) -> None:
    account = _failing_account(db_session)
    account.last_test_result = ConnTestResult.success
    db_session.commit()

    assert compute_active_alerts(db_session) == []


def test_app_update_available_when_latest_is_newer(db_session: Session) -> None:
    state = get_background_job_state(db_session)
    state.latest_app_version = "999.0.0"
    db_session.commit()

    alerts = compute_active_alerts(db_session)

    assert [a.kind for a in alerts] == ["app_update_available"]
    assert alerts[0].acknowledgeable is True
    assert alerts[0].acknowledged is False
    assert version("relay") in alerts[0].detail


def test_no_app_update_alert_when_latest_equals_installed(db_session: Session) -> None:
    state = get_background_job_state(db_session)
    state.latest_app_version = version("relay")
    db_session.commit()

    assert compute_active_alerts(db_session) == []


def test_app_update_alert_is_acknowledged_when_version_matches(db_session: Session) -> None:
    state = get_background_job_state(db_session)
    state.latest_app_version = "999.0.0"
    state.app_update_acknowledged_version = "999.0.0"
    db_session.commit()

    alerts = compute_active_alerts(db_session)
    assert alerts[0].acknowledged is True


def test_app_update_alert_reactivates_on_a_newer_release_than_the_acknowledged_one(db_session: Session) -> None:
    state = get_background_job_state(db_session)
    state.latest_app_version = "999.0.1"
    state.app_update_acknowledged_version = "999.0.0"
    db_session.commit()

    alerts = compute_active_alerts(db_session)
    assert alerts[0].acknowledged is False


def test_postfix_update_available_when_control_surface_reachable_and_newer(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.core.alerts.postfix_control.version", lambda: "3.7.0")
    state = get_background_job_state(db_session)
    state.latest_postfix_version = "3.9.1"
    db_session.commit()

    alerts = compute_active_alerts(db_session)

    assert [a.kind for a in alerts] == ["postfix_update_available"]


def test_no_postfix_update_alert_when_control_surface_unreachable(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom() -> str:
        raise PostfixControlError("unreachable")

    monkeypatch.setattr("app.core.alerts.postfix_control.version", _boom)
    state = get_background_job_state(db_session)
    state.latest_postfix_version = "3.9.1"
    db_session.commit()

    assert compute_active_alerts(db_session) == []


def _throttled_user(db: Session, *, minutes_ago: float, enabled: bool = True, name: str = "Printer") -> LocalSmtpUser:
    user = LocalSmtpUser(
        name=name,
        username=name.lower().replace(" ", "-"),
        password_hash="x",
        enabled=enabled,
        rate_limit_per_hour=10,
        rate_limit_defer_streak_started_at=utcnow() - datetime.timedelta(minutes=minutes_ago),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_no_rate_limit_abuse_alert_below_the_threshold(db_session: Session) -> None:
    _throttled_user(db_session, minutes_ago=1)  # default threshold is 10 minutes
    assert compute_active_alerts(db_session) == []


def test_no_rate_limit_abuse_alert_without_a_streak(db_session: Session) -> None:
    user = _throttled_user(db_session, minutes_ago=20)
    user.rate_limit_defer_streak_started_at = None
    db_session.commit()
    assert compute_active_alerts(db_session) == []


def test_rate_limit_abuse_alert_once_past_the_threshold(db_session: Session) -> None:
    user = _throttled_user(db_session, minutes_ago=20)

    alerts = compute_active_alerts(db_session)

    assert [a.kind for a in alerts] == ["rate_limit_abuse"]
    assert alerts[0].key == f"rate_limit_abuse:{user.id}"
    assert alerts[0].target_type == "local_smtp_user"
    assert alerts[0].target_id == user.id
    assert "investigate" in alerts[0].detail


def test_rate_limit_abuse_alert_mentions_auto_disabled_when_no_longer_enabled(db_session: Session) -> None:
    _throttled_user(db_session, minutes_ago=20, enabled=False)

    alerts = compute_active_alerts(db_session)

    assert "Automatically disabled" in alerts[0].detail


def test_rate_limit_abuse_threshold_is_configurable(db_session: Session) -> None:
    _throttled_user(db_session, minutes_ago=3)
    get_relay_settings(db_session).rate_limit_abuse_threshold_minutes = 2
    db_session.commit()

    alerts = compute_active_alerts(db_session)

    assert [a.kind for a in alerts] == ["rate_limit_abuse"]


def test_one_alert_per_throttled_user(db_session: Session) -> None:
    u1 = _throttled_user(db_session, minutes_ago=20, name="Printer")
    u2 = _throttled_user(db_session, minutes_ago=30, name="Scanner")

    alerts = compute_active_alerts(db_session)

    keys = {a.key for a in alerts}
    assert keys == {f"rate_limit_abuse:{u1.id}", f"rate_limit_abuse:{u2.id}"}
