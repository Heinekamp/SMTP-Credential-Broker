"""alert_email_tick opens its own real app.db.session.SessionLocal
internally (same reasoning as test_scheduled_tests.py/test_update_check.py),
so these tests use that shared in-memory engine with the usual autouse
cleanup fixture. compute_active_alerts and send_alert_email are both
monkeypatched so no real health/SMTP work happens."""

import asyncio

import pytest

from app.core.alert_email import alert_email_tick
from app.core.alerts import Alert
from app.core.encryption import encrypt_secret
from app.core.settings_store import get_background_job_state, get_relay_settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.enums import TlsMode
from app.models.sender import Sender
from app.models.settings import BackgroundJobState, RelaySettings
from app.models.upstream import UpstreamAccount


@pytest.fixture(autouse=True)
def _clean_shared_db() -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        db.query(Sender).delete()
        db.query(UpstreamAccount).delete()
        db.query(RelaySettings).delete()
        db.query(BackgroundJobState).delete()
        db.commit()
    finally:
        db.close()


def _configured_sender(db) -> Sender:
    account = UpstreamAccount(
        name="alert-account",
        host="smtp.example.com",
        port=587,
        tls_mode=TlsMode.starttls,
        username="alerts@example.com",
        encrypted_password=encrypt_secret("hunter2"),
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    sender = Sender(address="alerts@example.com", upstream_account_id=account.id)
    db.add(sender)
    db.commit()
    db.refresh(sender)
    return sender


def _configure(db, *, recipients=("admin@example.com",), sender_id=None) -> None:
    settings_row = get_relay_settings(db)
    settings_row.notify_recipients = list(recipients)
    settings_row.notify_sender_id = sender_id
    db.commit()


def _run() -> None:
    asyncio.run(alert_email_tick())


def test_does_nothing_when_no_recipients_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = []
    monkeypatch.setattr("app.core.alert_email.send_alert_email", lambda **kwargs: sent.append(kwargs))
    _run()
    assert sent == []


def test_does_nothing_when_no_sender_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    db = SessionLocal()
    _configure(db, sender_id=None)
    db.close()

    sent = []
    monkeypatch.setattr("app.core.alert_email.send_alert_email", lambda **kwargs: sent.append(kwargs))
    monkeypatch.setattr(
        "app.core.alert_email.compute_active_alerts",
        lambda db: [Alert(kind="health_degraded", key="health_degraded", title="t", detail="d")],
    )
    _run()
    assert sent == []


def test_sends_once_on_resolved_to_active_transition_and_not_again_while_still_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = SessionLocal()
    sender = _configured_sender(db)
    _configure(db, sender_id=sender.id)
    db.close()

    sent = []
    monkeypatch.setattr("app.core.alert_email.send_alert_email", lambda **kwargs: sent.append(kwargs))
    monkeypatch.setattr(
        "app.core.alert_email.compute_active_alerts",
        lambda db: [Alert(kind="health_degraded", key="health_degraded", title="Relay is degraded", detail="d")],
    )

    _run()
    assert len(sent) == 1
    assert sent[0]["to_addrs"] == ["admin@example.com"]

    db = SessionLocal()
    assert get_background_job_state(db).health_degraded_active is True
    db.close()

    _run()  # still active — must not send a second time
    assert len(sent) == 1


def test_resolution_flips_state_back_without_sending_an_email(monkeypatch: pytest.MonkeyPatch) -> None:
    db = SessionLocal()
    sender = _configured_sender(db)
    _configure(db, sender_id=sender.id)
    get_background_job_state(db).health_degraded_active = True
    db.commit()
    db.close()

    sent = []
    monkeypatch.setattr("app.core.alert_email.send_alert_email", lambda **kwargs: sent.append(kwargs))
    monkeypatch.setattr("app.core.alert_email.compute_active_alerts", lambda db: [])

    _run()

    assert sent == []
    db = SessionLocal()
    assert get_background_job_state(db).health_degraded_active is False
    db.close()


def test_disabled_toggle_suppresses_the_email_entirely(monkeypatch: pytest.MonkeyPatch) -> None:
    db = SessionLocal()
    sender = _configured_sender(db)
    _configure(db, sender_id=sender.id)
    get_relay_settings(db).notify_on_health_degraded = False
    db.commit()
    db.close()

    sent = []
    monkeypatch.setattr("app.core.alert_email.send_alert_email", lambda **kwargs: sent.append(kwargs))
    monkeypatch.setattr(
        "app.core.alert_email.compute_active_alerts",
        lambda db: [Alert(kind="health_degraded", key="health_degraded", title="t", detail="d")],
    )
    _run()
    assert sent == []


def test_update_available_sends_once_per_new_version(monkeypatch: pytest.MonkeyPatch) -> None:
    db = SessionLocal()
    sender = _configured_sender(db)
    _configure(db, sender_id=sender.id)
    state = get_background_job_state(db)
    state.latest_app_version = "999.0.0"
    db.commit()
    db.close()

    sent = []
    monkeypatch.setattr("app.core.alert_email.send_alert_email", lambda **kwargs: sent.append(kwargs))
    monkeypatch.setattr(
        "app.core.alert_email.compute_active_alerts",
        lambda db: [
            Alert(
                kind="app_update_available",
                key="app_update_available",
                title="SMTP Manager update available",
                detail="0.1.0 installed, 999.0.0 available",
                acknowledgeable=True,
            )
        ],
    )

    _run()
    assert len(sent) == 1

    _run()  # same version — no resend
    assert len(sent) == 1

    db = SessionLocal()
    assert get_background_job_state(db).app_update_last_emailed_version == "999.0.0"
    db.close()


def test_a_send_failure_does_not_update_state_so_it_retries_next_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    db = SessionLocal()
    sender = _configured_sender(db)
    _configure(db, sender_id=sender.id)
    db.close()

    def _boom(**kwargs):
        raise RuntimeError("smtp unreachable")

    monkeypatch.setattr("app.core.alert_email.send_alert_email", _boom)
    monkeypatch.setattr(
        "app.core.alert_email.compute_active_alerts",
        lambda db: [Alert(kind="health_degraded", key="health_degraded", title="t", detail="d")],
    )

    _run()  # must not raise

    db = SessionLocal()
    assert get_background_job_state(db).health_degraded_active is False
    db.close()
