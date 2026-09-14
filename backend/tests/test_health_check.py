import pytest
from sqlalchemy.orm import Session

from app.core.encryption import encrypt_secret
from app.core.health import run_health_check
from app.core.postfix_control import ApplyConfigResult, PostfixControlError, PostfixStatus
from app.models.enums import TlsMode
from app.models.sender import Sender
from app.models.upstream import UpstreamAccount


def _fake_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.health.postfix_control.status", lambda: PostfixStatus(running=True, detail="ok"))


def test_never_configured_is_ok_but_reports_the_underlying_facts(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.core.health.postfix_control.status", lambda: PostfixStatus(running=False, detail="not running")
    )
    report = run_health_check(db_session)
    assert report.status == "ok"
    assert report.postfix_running.ok is False
    assert report.last_generation_result == "none"
    assert report.config_in_sync.ok is False


def test_unreachable_control_surface_degrades_status(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom():
        raise PostfixControlError("unreachable")

    monkeypatch.setattr("app.core.health.postfix_control.status", _boom)
    report = run_health_check(db_session)
    assert report.status == "degraded"
    assert report.postfix_reachable.ok is False


def test_after_successful_generation_everything_is_in_sync(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_running(monkeypatch)
    monkeypatch.setattr(
        "app.core.config_generator.postfix_control.apply_config",
        lambda **kwargs: ApplyConfigResult(success=True, validation_detail="postconf: OK", reloaded=True),
    )
    from app.core.config_generator import generate_and_apply

    outcome = generate_and_apply(db_session, triggered_by_admin_id=None)
    assert outcome.success is True

    report = run_health_check(db_session)
    assert report.status == "ok"
    assert report.last_generation_result == "pass"
    assert report.config_in_sync.ok is True


def test_db_change_after_generation_marks_config_out_of_sync(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_running(monkeypatch)
    monkeypatch.setattr(
        "app.core.config_generator.postfix_control.apply_config",
        lambda **kwargs: ApplyConfigResult(success=True, validation_detail="postconf: OK", reloaded=True),
    )
    from app.core.config_generator import generate_and_apply

    generate_and_apply(db_session, triggered_by_admin_id=None)

    # DB state changes (a new sender is added) without ever regenerating —
    # this is exactly the "generation succeeded but drifted since" case
    # architecture.md §7 calls out.
    account = UpstreamAccount(
        name="STRATO",
        host="smtp.strato.de",
        port=587,
        tls_mode=TlsMode.starttls,
        username="printer@example.com",
        encrypted_password=encrypt_secret("secret"),
        enabled=True,
    )
    db_session.add(account)
    db_session.flush()
    db_session.add(Sender(address="printer@example.com", upstream_account_id=account.id, enabled=True))
    db_session.commit()

    report = run_health_check(db_session)
    assert report.status == "degraded"
    assert report.config_in_sync.ok is False


def test_latest_failed_attempt_degrades_status_even_with_a_good_config_active(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_running(monkeypatch)
    from app.core.config_generator import generate_and_apply

    monkeypatch.setattr(
        "app.core.config_generator.postfix_control.apply_config",
        lambda **kwargs: ApplyConfigResult(success=True, validation_detail="postconf: OK", reloaded=True),
    )
    generate_and_apply(db_session, triggered_by_admin_id=None)

    monkeypatch.setattr(
        "app.core.config_generator.postfix_control.apply_config",
        lambda **kwargs: ApplyConfigResult(success=False, validation_detail="postconf: broken", reloaded=False),
    )
    generate_and_apply(db_session, triggered_by_admin_id=None)

    report = run_health_check(db_session)
    assert report.last_generation_result == "fail"
    assert report.status == "degraded"
