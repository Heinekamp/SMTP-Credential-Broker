"""The scheduled counterpart to the manual "Test Connection" button —
periodically re-tests every enabled upstream account, gated on an
admin-configurable interval (relay_settings.connection_test_interval_minutes,
None = disabled/manual-only)."""

import asyncio
import datetime

from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.clock import utcnow
from app.core.encryption import DecryptionFailed, EncryptionKeyNotConfigured, decrypt_secret
from app.core.settings_store import get_background_job_state, get_relay_settings
from app.core.test_connection import test_upstream_connection
from app.core.upstream_testing import apply_test_result
from app.db.session import SessionLocal
from app.models.upstream import UpstreamAccount


def run_connection_test_batch(db: Session) -> int:
    """Tests every enabled upstream account, persists results the same way
    the manual route does, and records one audit entry for the whole
    batch. Returns the number of accounts tested."""
    accounts = db.query(UpstreamAccount).filter(UpstreamAccount.enabled.is_(True)).all()
    failure_count = 0
    tested_count = 0

    for account in accounts:
        try:
            password = decrypt_secret(account.encrypted_password)
        except (EncryptionKeyNotConfigured, DecryptionFailed):
            # Can't test what can't be decrypted — skip rather than crash
            # the whole batch over one account's undecryptable secret.
            continue

        result = test_upstream_connection(
            host=account.host,
            port=account.port,
            tls_mode=account.tls_mode,
            username=account.username,
            password=password,
        )
        apply_test_result(account, result)
        tested_count += 1
        if not result.success:
            failure_count += 1

    if tested_count:
        # admin_user_id=None matches the existing triggered_by_admin_id
        # precedent on ConfigGeneration for system-triggered work.
        record_audit(
            db,
            admin_user_id=None,
            action="upstream_account.scheduled_test",
            detail={"tested": tested_count, "failures": failure_count},
        )
    db.commit()
    return tested_count


def _connection_test_tick_sync() -> None:
    db = SessionLocal()
    try:
        settings_row = get_relay_settings(db)
        interval = settings_row.connection_test_interval_minutes
        if interval is None:
            return

        state = get_background_job_state(db)
        if state.connection_test_last_run_at is not None:
            elapsed = utcnow() - state.connection_test_last_run_at
            if elapsed < datetime.timedelta(minutes=interval):
                return

        run_connection_test_batch(db)
        state.connection_test_last_run_at = utcnow()
        db.commit()
    finally:
        db.close()


async def connection_test_tick() -> None:
    # run_connection_test_batch does blocking smtplib I/O (up to a 10s
    # timeout per step) for every enabled upstream account, one at a time
    # — running that directly on this coroutine would block the single
    # asyncio event loop that also serves every HTTP request, freezing the
    # whole app for the batch's full duration whenever an upstream is slow
    # or unreachable. to_thread moves the entire synchronous body (DB
    # session included — it's only ever touched from this one thread for
    # the duration of the call, so there's no cross-thread sharing) off
    # the event loop.
    await asyncio.to_thread(_connection_test_tick_sync)
