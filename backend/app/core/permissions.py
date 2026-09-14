from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.models.local_user import LocalSmtpUser, UserSenderPermission
from app.models.sender import Sender
from app.models.upstream import UpstreamAccount


def sender_login_map(db: Session) -> dict[str, list[str]]:
    """address -> local SMTP usernames allowed to use it — exactly the
    content of the generated `smtpd_sender_login_maps` table
    (postfix-architecture.md §4). Disabled senders and disabled local
    users are excluded entirely, not just marked; a disabled entity must
    never appear as an owner in the generated map."""
    rows = (
        db.query(Sender.address, LocalSmtpUser.username)
        .join(UserSenderPermission, UserSenderPermission.sender_id == Sender.id)
        .join(LocalSmtpUser, LocalSmtpUser.id == UserSenderPermission.local_smtp_user_id)
        .filter(Sender.enabled.is_(True), LocalSmtpUser.enabled.is_(True))
        .order_by(Sender.address, LocalSmtpUser.username)
        .all()
    )
    result: dict[str, list[str]] = {}
    for address, username in rows:
        result.setdefault(address, []).append(username)
    return result


def enabled_senders_with_upstream(db: Session) -> list[Sender]:
    """Senders whose upstream account both exist and are enabled — a
    sender pointing at a disabled upstream account is excluded rather than
    rendering a relayhost/credential entry Postfix would never be able to
    use anyway (architecture.md's "flagged as an invariant violation rather
    than silently rendering broken config")."""
    return (
        db.query(Sender)
        .join(UpstreamAccount, UpstreamAccount.id == Sender.upstream_account_id)
        .filter(Sender.enabled.is_(True), UpstreamAccount.enabled.is_(True))
        .order_by(Sender.address)
        .all()
    )


def grant_permission(
    db: Session, *, local_smtp_user_id: int, sender_id: int, granted_by_admin_id: int | None
) -> None:
    """Idempotent: granting an already-granted permission is a no-op, not
    an error — the UI's checklist toggles are immediate-commit
    (claude-design-prompt.md's permission views), so a double-click must
    never surface a conflict."""
    existing = (
        db.query(UserSenderPermission)
        .filter(
            UserSenderPermission.local_smtp_user_id == local_smtp_user_id,
            UserSenderPermission.sender_id == sender_id,
        )
        .one_or_none()
    )
    if existing is None:
        db.add(
            UserSenderPermission(
                local_smtp_user_id=local_smtp_user_id,
                sender_id=sender_id,
                granted_at=utcnow(),
                granted_by_admin_id=granted_by_admin_id,
            )
        )
        db.commit()


def revoke_permission(db: Session, *, local_smtp_user_id: int, sender_id: int) -> None:
    """Idempotent: revoking a permission that isn't granted is a no-op."""
    (
        db.query(UserSenderPermission)
        .filter(
            UserSenderPermission.local_smtp_user_id == local_smtp_user_id,
            UserSenderPermission.sender_id == sender_id,
        )
        .delete()
    )
    db.commit()
