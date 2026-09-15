"""cert_renewal_tick opens its own real app.db.session.SessionLocal
internally (same reasoning as test_retention.py/test_update_check.py),
so these tests use that shared engine with an autouse fixture that
creates the schema once and clears the relevant tables before each
test."""

import asyncio
import datetime

import pytest
from sqlalchemy.orm import Session

from app.core.cert_renewal import cert_renewal_tick
from app.core.clock import utcnow
from app.core.settings_store import get_background_job_state, get_relay_settings, get_tls_certificate_state
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.audit import AuditLog
from app.models.settings import BackgroundJobState, RelaySettings
from app.models.tls import TlsCertificateState


@pytest.fixture(autouse=True)
def _clean_shared_db() -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        db.query(AuditLog).delete()
        db.query(RelaySettings).delete()
        db.query(BackgroundJobState).delete()
        db.query(TlsCertificateState).delete()
        db.commit()
    finally:
        db.close()


def _configure_enabled(db: Session) -> None:
    settings_row = get_relay_settings(db)
    settings_row.tls_acme_enabled = True
    settings_row.tls_domain = "smtp-relay.example.com"
    db.commit()


def test_tick_does_nothing_when_not_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr("app.core.cert_renewal.issue_or_renew", lambda db, **kwargs: calls.append(1))
    monkeypatch.setattr("app.core.cert_renewal.sync_certificate_to_postfix", lambda db: calls.append("sync"))

    asyncio.run(cert_renewal_tick())

    assert calls == []
    db = SessionLocal()
    assert get_background_job_state(db).cert_renewal_last_checked_at is None
    db.close()


def test_tick_skips_when_checked_recently(monkeypatch: pytest.MonkeyPatch) -> None:
    db = SessionLocal()
    _configure_enabled(db)
    get_background_job_state(db).cert_renewal_last_checked_at = utcnow() - datetime.timedelta(hours=1)
    db.commit()
    db.close()

    calls = []
    monkeypatch.setattr("app.core.cert_renewal.issue_or_renew", lambda db, **kwargs: calls.append(1))
    monkeypatch.setattr("app.core.cert_renewal.sync_certificate_to_postfix", lambda db: calls.append("sync"))

    asyncio.run(cert_renewal_tick())

    assert calls == []


def test_tick_does_not_renew_a_fresh_certificate(monkeypatch: pytest.MonkeyPatch) -> None:
    db = SessionLocal()
    _configure_enabled(db)
    state = get_tls_certificate_state(db)
    state.source = "lets_encrypt"
    state.not_after = utcnow() + datetime.timedelta(days=60)
    db.commit()
    db.close()

    renew_calls = []
    monkeypatch.setattr("app.core.cert_renewal.issue_or_renew", lambda db, **kwargs: renew_calls.append(1))
    monkeypatch.setattr("app.core.cert_renewal.sync_certificate_to_postfix", lambda db: None)

    asyncio.run(cert_renewal_tick())

    assert renew_calls == []
    db = SessionLocal()
    assert get_background_job_state(db).cert_renewal_last_checked_at is not None
    db.close()


def test_tick_renews_a_still_self_signed_certificate(monkeypatch: pytest.MonkeyPatch) -> None:
    db = SessionLocal()
    _configure_enabled(db)
    db.close()

    monkeypatch.setattr("app.core.cert_renewal.sync_certificate_to_postfix", lambda db: None)

    class _Result:
        success = True
        detail = "Issued."

    monkeypatch.setattr("app.core.cert_renewal.issue_or_renew", lambda db, **kwargs: _Result())

    asyncio.run(cert_renewal_tick())

    db = SessionLocal()
    state = get_background_job_state(db)
    assert state.cert_last_renewal_attempt_at is not None
    assert state.cert_last_renewal_error is None
    entry = db.query(AuditLog).filter_by(action="tls_certificate.renewed").one()
    assert entry.detail == {"domain": "smtp-relay.example.com"}
    db.close()


def test_tick_renews_a_certificate_within_the_renewal_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    db = SessionLocal()
    _configure_enabled(db)
    state = get_tls_certificate_state(db)
    state.source = "lets_encrypt"
    state.not_after = utcnow() + datetime.timedelta(days=10)  # inside the 30-day threshold
    db.commit()
    db.close()

    monkeypatch.setattr("app.core.cert_renewal.sync_certificate_to_postfix", lambda db: None)
    renew_calls = []

    class _Result:
        success = True
        detail = "Issued."

    def fake_issue_or_renew(db, **kwargs):
        renew_calls.append(1)
        return _Result()

    monkeypatch.setattr("app.core.cert_renewal.issue_or_renew", fake_issue_or_renew)

    asyncio.run(cert_renewal_tick())

    assert renew_calls == [1]


def test_tick_records_a_renewal_failure_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    db = SessionLocal()
    _configure_enabled(db)
    db.close()

    monkeypatch.setattr("app.core.cert_renewal.sync_certificate_to_postfix", lambda db: None)

    class _Result:
        success = False
        detail = "No Cloudflare API token configured."

    monkeypatch.setattr("app.core.cert_renewal.issue_or_renew", lambda db, **kwargs: _Result())

    asyncio.run(cert_renewal_tick())

    db = SessionLocal()
    state = get_background_job_state(db)
    assert state.cert_last_renewal_error == "No Cloudflare API token configured."
    entry = db.query(AuditLog).filter_by(action="tls_certificate.renewal_failed").one()
    assert entry.detail == {"detail": "No Cloudflare API token configured."}
    db.close()


def test_tick_calls_sync_before_checking_renewal_due_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression guard: the self-heal push to postfix must happen every
    due check, not only when a renewal actually fires — a lost
    postfix_tls volume should recover even while the cert itself is
    still fresh."""
    db = SessionLocal()
    _configure_enabled(db)
    state = get_tls_certificate_state(db)
    state.source = "lets_encrypt"
    state.not_after = utcnow() + datetime.timedelta(days=60)
    db.commit()
    db.close()

    sync_calls = []
    monkeypatch.setattr("app.core.cert_renewal.sync_certificate_to_postfix", lambda db: sync_calls.append(1))

    asyncio.run(cert_renewal_tick())

    assert sync_calls == [1]
