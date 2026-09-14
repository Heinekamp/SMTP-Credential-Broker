import pytest
from sqlalchemy.orm import Session

from app.core.config_generator import _build_maps, generate_and_apply
from app.core.permissions import grant_permission
from app.core.postfix_control import ApplyConfigResult
from app.models.enums import TlsMode
from app.models.local_user import LocalSmtpUser
from app.models.sender import Sender
from app.models.upstream import UpstreamAccount


def _upstream(db: Session, name: str, username: str, *, enabled: bool = True) -> UpstreamAccount:
    from app.core.encryption import encrypt_secret

    account = UpstreamAccount(
        name=name,
        host="smtp.strato.de",
        port=587,
        tls_mode=TlsMode.starttls,
        username=username,
        encrypted_password=encrypt_secret("upstream-secret"),
        enabled=enabled,
    )
    db.add(account)
    db.flush()
    return account


def _sender(db: Session, address: str, account: UpstreamAccount, *, enabled: bool = True) -> Sender:
    sender = Sender(address=address, upstream_account_id=account.id, enabled=enabled)
    db.add(sender)
    db.flush()
    return sender


def _user(db: Session, username: str) -> LocalSmtpUser:
    user = LocalSmtpUser(name=username, username=username, password_hash="x")
    db.add(user)
    db.flush()
    return user


def test_build_maps_matches_the_worked_example(db_session: Session) -> None:
    """Reproduces postfix-architecture.md §1's exact example: two STRATO
    mailboxes plus a second provider, with alerts@ sharing server@'s
    upstream credentials."""
    strato_printer = _upstream(db_session, "STRATO printer", "printer@example.com")
    strato_noreply = _upstream(db_session, "STRATO noreply", "noreply@example.com")
    hosting_alerts = _upstream(db_session, "Example Hosting alerts", "server@example.com")

    printer = _sender(db_session, "printer@example.com", strato_printer)
    noreply = _sender(db_session, "noreply@example.com", strato_noreply)
    server = _sender(db_session, "server@example.com", hosting_alerts)
    alerts = _sender(db_session, "alerts@example.com", hosting_alerts)

    printer_service = _user(db_session, "printer-service")
    inventree = _user(db_session, "inventree")
    monitoring = _user(db_session, "monitoring")

    grant_permission(db_session, local_smtp_user_id=printer_service.id, sender_id=printer.id, granted_by_admin_id=None)
    grant_permission(db_session, local_smtp_user_id=inventree.id, sender_id=noreply.id, granted_by_admin_id=None)
    grant_permission(db_session, local_smtp_user_id=monitoring.id, sender_id=server.id, granted_by_admin_id=None)
    grant_permission(db_session, local_smtp_user_id=monitoring.id, sender_id=alerts.id, granted_by_admin_id=None)

    maps, warnings = _build_maps(db_session)
    assert warnings == []

    login_lines = set(maps["sender_login"].splitlines())
    assert login_lines == {
        "printer@example.com\tprinter-service",
        "noreply@example.com\tinventree",
        "server@example.com\tmonitoring",
        "alerts@example.com\tmonitoring",
    }

    relayhost_lines = set(maps["sender_relayhost"].splitlines())
    assert relayhost_lines == {
        "printer@example.com\t[smtp.strato.de]:587",
        "noreply@example.com\t[smtp.strato.de]:587",
        "server@example.com\t[smtp.strato.de]:587",
        "alerts@example.com\t[smtp.strato.de]:587",
    }

    sasl_lines = set(maps["sasl_passwd"].splitlines())
    assert "alerts@example.com\tserver@example.com:upstream-secret" in sasl_lines
    assert "server@example.com\tserver@example.com:upstream-secret" in sasl_lines


def test_multiple_users_on_one_sender_are_comma_joined(db_session: Session) -> None:
    account = _upstream(db_session, "STRATO", "server@example.com")
    sender = _sender(db_session, "server@example.com", account)
    monitoring = _user(db_session, "monitoring")
    webapp = _user(db_session, "webapp")
    grant_permission(db_session, local_smtp_user_id=monitoring.id, sender_id=sender.id, granted_by_admin_id=None)
    grant_permission(db_session, local_smtp_user_id=webapp.id, sender_id=sender.id, granted_by_admin_id=None)

    maps, _ = _build_maps(db_session)
    assert maps["sender_login"].strip() == "server@example.com\tmonitoring,webapp"


def test_orphaned_sender_produces_a_warning_and_is_excluded(db_session: Session) -> None:
    disabled_account = _upstream(db_session, "STRATO", "printer@example.com", enabled=False)
    _sender(db_session, "printer@example.com", disabled_account)

    maps, warnings = _build_maps(db_session)
    assert maps["sender_relayhost"] == ""
    assert maps["sasl_passwd"] == ""
    assert len(warnings) == 1
    assert "printer@example.com" in warnings[0]
    assert "disabled" in warnings[0]


def test_dry_run_never_calls_the_control_surface(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(**kwargs):
        raise AssertionError("apply_config should not be called during a dry run")

    monkeypatch.setattr("app.core.config_generator.postfix_control.apply_config", _boom)

    outcome = generate_and_apply(db_session, triggered_by_admin_id=None, dry_run=True)
    assert outcome.success is True
    assert outcome.generation_id == -1
    assert "Dry run" in outcome.validation_detail


def test_generation_is_recorded_on_success(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.config_generator.postfix_control.apply_config",
        lambda **kwargs: ApplyConfigResult(success=True, validation_detail="postconf: OK", reloaded=True),
    )

    outcome = generate_and_apply(db_session, triggered_by_admin_id=None)
    assert outcome.success is True
    assert outcome.reloaded is True

    from app.models.config_generation import ConfigGeneration

    row = db_session.get(ConfigGeneration, outcome.generation_id)
    assert row is not None
    assert row.validation_result == "pass"
    assert row.applied is True
    assert row.reload_triggered is True


def test_generation_failure_is_recorded_and_reported_without_raising(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.core.config_generator.postfix_control.apply_config",
        lambda **kwargs: ApplyConfigResult(
            success=False, validation_detail="postconf: unknown parameter: bogus", reloaded=False
        ),
    )

    outcome = generate_and_apply(db_session, triggered_by_admin_id=None)
    assert outcome.success is False
    assert "bogus" in outcome.validation_detail

    from app.models.config_generation import ConfigGeneration

    row = db_session.get(ConfigGeneration, outcome.generation_id)
    assert row.validation_result == "fail"
    assert row.applied is False


def test_reload_flag_is_true_on_first_generation_then_false_when_unchanged(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[bool] = []

    def _fake_apply(**kwargs):
        calls.append(kwargs["reload_if_main_changed"])
        return ApplyConfigResult(success=True, validation_detail="ok", reloaded=kwargs["reload_if_main_changed"])

    monkeypatch.setattr("app.core.config_generator.postfix_control.apply_config", _fake_apply)

    generate_and_apply(db_session, triggered_by_admin_id=None)
    generate_and_apply(db_session, triggered_by_admin_id=None)

    assert calls == [True, False]
