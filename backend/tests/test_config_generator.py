import pytest
from sqlalchemy.orm import Session

from app.core.config_generator import _build_maps, _rate_limited_account_transports, _render_config, generate_and_apply
from app.core.permissions import grant_permission
from app.core.postfix_control import ApplyConfigResult, PostfixControlError, PostfixStatus
from app.models.enums import TlsMode
from app.models.local_user import LocalSmtpUser
from app.models.sender import Sender
from app.models.upstream import UpstreamAccount


def _upstream(
    db: Session,
    name: str,
    username: str,
    *,
    enabled: bool = True,
    tls_mode: TlsMode = TlsMode.starttls,
    port: int = 587,
    rate_limit_per_hour: int | None = None,
) -> UpstreamAccount:
    from app.core.encryption import encrypt_secret

    account = UpstreamAccount(
        name=name,
        host="smtp.strato.de",
        port=port,
        tls_mode=tls_mode,
        username=username,
        encrypted_password=encrypt_secret("upstream-secret"),
        enabled=enabled,
        rate_limit_per_hour=rate_limit_per_hour,
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

    # All-STARTTLS example — no sender needs the wrappermode transport.
    assert maps["sender_transport"] == ""


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
    assert maps["sender_transport"] == ""
    assert len(warnings) == 1
    assert "printer@example.com" in warnings[0]
    assert "disabled" in warnings[0]


def test_implicit_tls_sender_gets_a_sender_transport_entry(db_session: Session) -> None:
    """Regression test for issue #57: an implicit-TLS (e.g. port 465)
    upstream account must route its sender through the wrappermode
    transport, or real mail relay fails with "lost connection ... while
    receiving the initial server greeting" even though Test Connection
    (a different code path) reports success."""
    account = _upstream(db_session, "STRATO implicit", "printer@example.com", tls_mode=TlsMode.implicit, port=465)
    _sender(db_session, "printer@example.com", account)

    maps, _ = _build_maps(db_session)

    assert maps["sender_relayhost"].strip() == "printer@example.com\t[smtp.strato.de]:465"
    assert maps["sender_transport"].strip() == "printer@example.com\tsmtp_implicit_tls:"


def test_starttls_sender_is_absent_from_sender_transport_when_mixed_with_implicit(db_session: Session) -> None:
    starttls_account = _upstream(db_session, "STRATO starttls", "noreply@example.com")
    implicit_account = _upstream(
        db_session, "STRATO implicit", "printer@example.com", tls_mode=TlsMode.implicit, port=465
    )
    _sender(db_session, "noreply@example.com", starttls_account)
    _sender(db_session, "printer@example.com", implicit_account)

    maps, _ = _build_maps(db_session)

    assert maps["sender_transport"].strip() == "printer@example.com\tsmtp_implicit_tls:"


def test_rate_limited_sender_gets_a_synthetic_transport_entry(db_session: Session) -> None:
    account = _upstream(db_session, "STRATO paced", "printer@example.com", rate_limit_per_hour=100)
    _sender(db_session, "printer@example.com", account)

    maps, _ = _build_maps(db_session)

    assert maps["sender_transport"].strip() == f"printer@example.com\trl_acct{account.id}:"


def test_rate_limited_implicit_tls_account_uses_the_combined_transport_not_the_shared_one(
    db_session: Session,
) -> None:
    """A rate-limited account that's also implicit-TLS can't route through
    both the shared smtp_implicit_tls transport and its own rl_acct{id}
    transport at once — the combined one must win, carrying wrappermode
    itself (config_generator._transport_name_for)."""
    account = _upstream(
        db_session,
        "STRATO implicit + paced",
        "printer@example.com",
        tls_mode=TlsMode.implicit,
        port=465,
        rate_limit_per_hour=50,
    )
    _sender(db_session, "printer@example.com", account)

    maps, _ = _build_maps(db_session)

    assert maps["sender_transport"].strip() == f"printer@example.com\trl_acct{account.id}:"


def test_rate_limited_account_transports_dedups_and_computes_ceil_delay(db_session: Session) -> None:
    account = _upstream(db_session, "STRATO paced", "printer@example.com", rate_limit_per_hour=7)
    _sender(db_session, "printer@example.com", account)
    _sender(db_session, "alerts@example.com", account)  # same account, second sender

    transports = _rate_limited_account_transports(db_session)

    assert len(transports) == 1
    assert transports[0].account_id == account.id
    assert transports[0].implicit_tls is False
    assert transports[0].rate_delay_seconds == 515  # ceil(3600 / 7)


def test_render_config_emits_a_synthetic_transport_stanza_for_a_rate_limited_account(
    db_session: Session,
) -> None:
    account = _upstream(db_session, "STRATO paced", "printer@example.com", rate_limit_per_hour=100)
    _sender(db_session, "printer@example.com", account)

    _, master_cf = _render_config(db_session)

    assert f"rl_acct{account.id} unix" in master_cf
    assert "smtp_destination_rate_delay=36s" in master_cf  # ceil(3600/100)
    assert "smtp_destination_concurrency_limit=1" in master_cf


def test_render_config_omits_the_synthetic_transport_when_nothing_is_rate_limited(db_session: Session) -> None:
    account = _upstream(db_session, "STRATO", "printer@example.com")
    _sender(db_session, "printer@example.com", account)

    _, master_cf = _render_config(db_session)

    assert "rl_acct" not in master_cf
    assert "smtp_destination_rate_delay" not in master_cf


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


def test_reload_flag_is_true_on_first_generation_then_false_when_unchanged_and_running(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[bool] = []

    def _fake_apply(**kwargs):
        calls.append(kwargs["reload_if_main_changed"])
        return ApplyConfigResult(success=True, validation_detail="ok", reloaded=kwargs["reload_if_main_changed"])

    monkeypatch.setattr("app.core.config_generator.postfix_control.apply_config", _fake_apply)
    monkeypatch.setattr(
        "app.core.config_generator.postfix_control.status", lambda: PostfixStatus(running=True, detail="running")
    )

    generate_and_apply(db_session, triggered_by_admin_id=None)
    generate_and_apply(db_session, triggered_by_admin_id=None)

    assert calls == [True, False]


@pytest.mark.parametrize(
    "make_status",
    [
        lambda: PostfixStatus(running=False, detail="not running"),
        lambda: (_ for _ in ()).throw(PostfixControlError("unreachable")),
    ],
    ids=["not_running", "control_surface_unreachable"],
)
def test_reload_flag_stays_true_when_unchanged_but_postfix_is_not_actually_running(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, make_status
) -> None:
    """A real bug found via manual testing: checksum-only used to be the
    whole story, which assumes Postfix is already running with that exact
    config. It isn't after the postfix container restarts (a crash, a host
    reboot, `docker compose restart postfix`) without app's own database
    changing — a fresh, un-started Postfix process was never told to
    start at all, with no supported way to recover short of operating on
    the container directly."""
    calls: list[bool] = []

    def _fake_apply(**kwargs):
        calls.append(kwargs["reload_if_main_changed"])
        return ApplyConfigResult(success=True, validation_detail="ok", reloaded=kwargs["reload_if_main_changed"])

    monkeypatch.setattr("app.core.config_generator.postfix_control.apply_config", _fake_apply)

    monkeypatch.setattr(
        "app.core.config_generator.postfix_control.status", lambda: PostfixStatus(running=True, detail="running")
    )
    generate_and_apply(db_session, triggered_by_admin_id=None)

    monkeypatch.setattr("app.core.config_generator.postfix_control.status", lambda: make_status())
    generate_and_apply(db_session, triggered_by_admin_id=None)

    assert calls == [True, True]
