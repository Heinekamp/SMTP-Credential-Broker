"""run_connection_test_batch is exercised against the db_session fixture
(it just takes a Session). connection_test_tick opens its own real
app.db.session.SessionLocal internally (same as the CLI does — see
test_rotate_encryption_key.py's docstring for why), so those tests use
that same shared in-memory engine instead, with an autouse fixture that
creates the schema once and clears the relevant tables before each test.
"""

import datetime

import pytest
from sqlalchemy.orm import Session

from app.core.encryption import encrypt_secret
from app.core.scheduled_tests import connection_test_tick, run_connection_test_batch
from app.core.settings_store import get_background_job_state, get_relay_settings

# Aliased so pytest's collector (default python_classes = "Test*") doesn't
# try to instantiate these as test classes and warn about their __init__.
from app.core.test_connection import StepResult
from app.core.test_connection import TestConnectionResult as ConnResult
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.audit import AuditLog
from app.models.enums import TestResult as ConnTestResult
from app.models.enums import TlsMode
from app.models.settings import BackgroundJobState, RelaySettings
from app.models.upstream import UpstreamAccount

_PASS = ConnResult(steps=[StepResult("AUTH", True, "ok")])
_FAIL = ConnResult(steps=[StepResult("AUTH", False, "535 bad credentials")])


def _account(db: Session, *, enabled: bool = True) -> UpstreamAccount:
    account = UpstreamAccount(
        name="test",
        host="smtp.example.com",
        port=587,
        tls_mode=TlsMode.starttls,
        username="user@example.com",
        encrypted_password=encrypt_secret("hunter2"),
        enabled=enabled,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def test_batch_tests_only_enabled_accounts_and_persists_results(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    enabled = _account(db_session, enabled=True)
    disabled = _account(db_session, enabled=False)

    monkeypatch.setattr("app.core.scheduled_tests.test_upstream_connection", lambda **kwargs: _PASS)

    tested = run_connection_test_batch(db_session)

    assert tested == 1
    db_session.refresh(enabled)
    db_session.refresh(disabled)
    assert enabled.last_test_result == ConnTestResult.success
    assert enabled.last_test_at is not None
    assert disabled.last_test_result is None


def test_batch_records_failure_detail_and_audits_the_batch(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = _account(db_session)
    monkeypatch.setattr("app.core.scheduled_tests.test_upstream_connection", lambda **kwargs: _FAIL)

    run_connection_test_batch(db_session)

    db_session.refresh(account)
    assert account.last_test_result == ConnTestResult.failure
    assert "535 bad credentials" in account.last_test_error

    entry = db_session.query(AuditLog).filter(AuditLog.action == "upstream_account.scheduled_test").one()
    assert entry.admin_user_id is None
    assert entry.detail == {"tested": 1, "failures": 1}


def test_batch_skips_accounts_that_fail_to_decrypt(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    account = _account(db_session)
    account.encrypted_password = b"not valid ciphertext"
    db_session.commit()

    monkeypatch.setattr("app.core.scheduled_tests.test_upstream_connection", lambda **kwargs: _PASS)

    tested = run_connection_test_batch(db_session)

    assert tested == 0
    db_session.refresh(account)
    assert account.last_test_result is None


def test_batch_does_not_audit_when_nothing_was_tested(db_session: Session) -> None:
    run_connection_test_batch(db_session)
    assert db_session.query(AuditLog).filter(AuditLog.action == "upstream_account.scheduled_test").count() == 0


@pytest.fixture(autouse=True)
def _clean_shared_db() -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        db.query(UpstreamAccount).delete()
        db.query(RelaySettings).delete()
        db.query(BackgroundJobState).delete()
        db.commit()
    finally:
        db.close()


def test_tick_does_nothing_when_interval_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[None] = []
    monkeypatch.setattr("app.core.scheduled_tests.run_connection_test_batch", lambda db: calls.append(None) or 0)

    import asyncio

    asyncio.run(connection_test_tick())

    assert calls == []


def test_tick_runs_when_interval_elapsed_and_updates_last_run(monkeypatch: pytest.MonkeyPatch) -> None:
    db = SessionLocal()
    get_relay_settings(db).connection_test_interval_minutes = 30
    db.commit()
    db.close()

    calls: list[None] = []
    monkeypatch.setattr("app.core.scheduled_tests.run_connection_test_batch", lambda db: calls.append(None) or 1)

    import asyncio

    asyncio.run(connection_test_tick())

    assert len(calls) == 1

    db = SessionLocal()
    state = get_background_job_state(db)
    assert state.connection_test_last_run_at is not None
    db.close()


def test_tick_skips_when_interval_has_not_elapsed_yet(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.clock import utcnow

    db = SessionLocal()
    get_relay_settings(db).connection_test_interval_minutes = 30
    get_background_job_state(db).connection_test_last_run_at = utcnow() - datetime.timedelta(minutes=5)
    db.commit()
    db.close()

    calls: list[None] = []
    monkeypatch.setattr("app.core.scheduled_tests.run_connection_test_batch", lambda db: calls.append(None) or 0)

    import asyncio

    asyncio.run(connection_test_tick())

    assert calls == []
