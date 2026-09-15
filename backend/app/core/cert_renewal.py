"""Checks daily whether the relay's TLS certificate needs renewing
(core/acme_tls.py) — the same interval-gated, self-contained-session tick
pattern as core/retention.py. Does nothing when Let's Encrypt issuance
isn't enabled; a self-signed or soon-to-expire certificate is renewed
automatically, with the outcome recorded either way."""

import asyncio
import datetime

from app.core.acme_tls import issue_or_renew, sync_certificate_to_postfix
from app.core.audit import record_audit
from app.core.clock import utcnow
from app.core.logging_config import get_logger
from app.core.settings_store import get_background_job_state, get_relay_settings, get_tls_certificate_state
from app.db.session import SessionLocal

_logger = get_logger("cert_renewal")

_CHECK_INTERVAL = datetime.timedelta(hours=24)
_RENEWAL_THRESHOLD = datetime.timedelta(days=30)  # standard Let's Encrypt guidance


def _cert_renewal_tick_sync() -> None:
    db = SessionLocal()
    try:
        settings_row = get_relay_settings(db)
        if not settings_row.tls_acme_enabled:
            return  # not configured — nothing to do, and no reason to touch background_job_state

        state = get_background_job_state(db)
        if state.cert_renewal_last_checked_at is not None:
            elapsed = utcnow() - state.cert_renewal_last_checked_at
            if elapsed < _CHECK_INTERVAL:
                return

        sync_certificate_to_postfix(db)  # cheap self-heal against a lost postfix_tls volume

        cert_state = get_tls_certificate_state(db)
        due = (
            cert_state.source != "lets_encrypt"
            or cert_state.not_after is None
            or (cert_state.not_after - utcnow()) < _RENEWAL_THRESHOLD
        )
        state.cert_renewal_last_checked_at = utcnow()
        if not due:
            db.commit()
            return

        state.cert_last_renewal_attempt_at = utcnow()
        result = issue_or_renew(db)
        if result.success:
            state.cert_last_renewal_error = None
            record_audit(
                db, admin_user_id=None, action="tls_certificate.renewed", detail={"domain": settings_row.tls_domain}
            )
            _logger.info("renewed TLS certificate for %s", settings_row.tls_domain)
        else:
            state.cert_last_renewal_error = result.detail
            record_audit(
                db,
                admin_user_id=None,
                action="tls_certificate.renewal_failed",
                detail={"detail": result.detail},
            )
            _logger.warning("TLS certificate renewal failed: %s", result.detail)
        db.commit()
    finally:
        db.close()


async def cert_renewal_tick() -> None:
    # issue_or_renew makes blocking network calls (Let's Encrypt, the DNS
    # provider) — see connection_test_tick's identical rationale for why
    # this can't run directly on the event loop.
    await asyncio.to_thread(_cert_renewal_tick_sync)
