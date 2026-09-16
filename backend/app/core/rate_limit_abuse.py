"""Auto-disables a local user once they've been continuously throttled —
never once successfully sent — for longer than
`RelaySettings.rate_limit_abuse_threshold_minutes`. Strictly opt-in
(`rate_limit_abuse_auto_disable_enabled`, default off): revoking a
credential without a human in the loop is a real escalation, not
something an upgrade should ever start doing silently.

Deliberately independent of the alert itself. `core/alerts.py` surfaces
the same threshold crossing on the notification bell/email unconditionally
(alerts.py's `notify_on_rate_limit_abuse` gates the email, never the
bell), computed purely from `LocalSmtpUser.rate_limit_defer_streak_started_at`
— so that stays accurate whether or not this tick ever manages to act on
it, and it's its own tick (not folded into rate_limit_cleanup.py) since
this touches a security-relevant state transition with its own audit
trail, not pure housekeeping.

Disabling a user removes them from this tick's own candidate query on the
next run (it only looks at `enabled=True` rows) — no separate
"already handled" bookkeeping needed, unlike alert_email.py's edge
triggers, which track a persisting *email* transition rather than a
one-time action."""

import asyncio
import datetime

from sqlalchemy.orm import Session

from app.core import postfix_control
from app.core.audit import record_audit
from app.core.clock import utcnow
from app.core.logging_config import get_logger
from app.core.postfix_control import PostfixControlError
from app.core.settings_store import get_relay_settings
from app.db.session import SessionLocal
from app.models.local_user import LocalSmtpUser

_logger = get_logger("rate_limit_abuse")


def run_rate_limit_abuse_detection(db: Session) -> list[LocalSmtpUser]:
    """Disables every currently-enabled user whose defer streak has
    crossed the configured threshold and returns the ones actually
    disabled (a control-surface failure skips that user, retried next
    tick, without raising). Does not commit — same division of
    responsibility as run_retention_cleanup."""
    settings_row = get_relay_settings(db)
    if not settings_row.rate_limit_abuse_auto_disable_enabled:
        return []

    cutoff = utcnow() - datetime.timedelta(minutes=settings_row.rate_limit_abuse_threshold_minutes)
    candidates = (
        db.query(LocalSmtpUser)
        .filter(
            LocalSmtpUser.enabled.is_(True),
            LocalSmtpUser.rate_limit_defer_streak_started_at.is_not(None),
            LocalSmtpUser.rate_limit_defer_streak_started_at <= cutoff,
        )
        .all()
    )

    disabled: list[LocalSmtpUser] = []
    for user in candidates:
        try:
            postfix_control.sasl_delete_user(user.username)
        except PostfixControlError:
            _logger.warning(
                "could not reach the postfix control surface to auto-disable %r — will retry next tick",
                user.username,
                exc_info=True,
            )
            continue
        user.enabled = False
        record_audit(
            db,
            admin_user_id=None,
            action="local_user.rate_limit_abuse_auto_disabled",
            target_type="local_smtp_user",
            target_id=user.id,
            detail={
                "username": user.username,
                "throttled_since": user.rate_limit_defer_streak_started_at.isoformat(),
            },
        )
        disabled.append(user)
    return disabled


def _rate_limit_abuse_tick_sync() -> None:
    db = SessionLocal()
    try:
        disabled = run_rate_limit_abuse_detection(db)
        if disabled:
            _logger.info(
                "auto-disabled %d local user(s) for sustained rate-limit abuse: %s",
                len(disabled),
                ", ".join(u.username for u in disabled),
            )
        db.commit()
    finally:
        db.close()


async def rate_limit_abuse_tick() -> None:
    # sasl_delete_user is a blocking Unix-socket call — see
    # connection_test_tick's identical rationale for why this can't run
    # directly on the event loop.
    await asyncio.to_thread(_rate_limit_abuse_tick_sync)
