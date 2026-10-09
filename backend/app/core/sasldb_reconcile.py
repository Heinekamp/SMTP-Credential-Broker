"""Startup reconciliation of the live sasldb2 against the database (#185).

The database is the source of truth for which local users may SMTP-AUTH.
sasldb2 can drift from it: a delete that succeeded live but failed to sync
to the volume copy used to leave the revoked credential to be restored on
the next postfix container start. This removes every sasldb2 user that's
missing from the database or disabled there. It never adds anyone — a
password can't be recovered from the stored hash, so a user missing from
sasldb2 has to be fixed by regenerating its password, as before.
"""

from sqlalchemy.orm import Session

from app.core import postfix_control
from app.core.logging_config import get_logger
from app.core.postfix_control import PostfixControlError
from app.models.local_user import LocalSmtpUser

_logger = get_logger("sasldb_reconcile")


def reconcile_sasldb(db: Session) -> list[str]:
    """Deletes sasldb2 users with no enabled local user behind them and
    returns their usernames. Best-effort: an unreachable control surface is
    logged and skipped (the next app start tries again), never raised."""
    try:
        live = postfix_control.sasl_list_users()
    except PostfixControlError:
        _logger.warning("could not reach the postfix control surface to reconcile sasldb2", exc_info=True)
        return []

    allowed = {username for (username,) in db.query(LocalSmtpUser.username).filter(LocalSmtpUser.enabled.is_(True))}
    removed: list[str] = []
    for username in live:
        if username in allowed:
            continue
        try:
            postfix_control.sasl_delete_user(username)
        except PostfixControlError:
            _logger.warning("could not remove stale sasldb2 user %r", username, exc_info=True)
            continue
        _logger.warning("removed sasldb2 user %r: not an enabled local user in the database", username)
        removed.append(username)
    return removed
