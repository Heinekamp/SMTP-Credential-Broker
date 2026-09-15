import datetime
import hashlib
import secrets

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.clock import utcnow
from app.models.admin import AdminSession, AdminUser

settings = get_settings()


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_session(
    db: Session,
    admin: AdminUser,
    ip_address: str | None,
    user_agent: str | None,
) -> str:
    """Creates a session row and returns the RAW token — the only place the
    raw value ever exists outside the client's cookie. Only its hash is
    persisted (security-model.md §5)."""
    raw_token = secrets.token_urlsafe(32)
    now = utcnow()
    session = AdminSession(
        admin_user_id=admin.id,
        token_hash=_hash_token(raw_token),
        created_at=now,
        expires_at=now + datetime.timedelta(seconds=settings.session_ttl_seconds),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(session)
    db.flush()
    return raw_token


def get_session_by_token(db: Session, raw_token: str) -> AdminSession | None:
    if not raw_token:
        return None
    token_hash = _hash_token(raw_token)
    session = (
        db.query(AdminSession)
        .filter(
            AdminSession.token_hash == token_hash,
            AdminSession.revoked_at.is_(None),
        )
        .one_or_none()
    )
    if session is None:
        return None
    if session.expires_at <= utcnow():
        return None
    return session


def revoke_session(db: Session, raw_token: str) -> None:
    token_hash = _hash_token(raw_token)
    session = db.query(AdminSession).filter(AdminSession.token_hash == token_hash).one_or_none()
    if session is not None and session.revoked_at is None:
        session.revoked_at = utcnow()
        db.flush()


def revoke_all_sessions_for_admin(db: Session, admin_user_id: int, *, except_token: str | None = None) -> None:
    """Called whenever a credential materially changes (password, TOTP
    enrolled/removed) so a session cookie stolen before the change can't
    keep working after the legitimate admin "fixes" it from a different
    session (security-model.md's stolen-session-token row didn't cover
    this — the token itself stayed valid until it naturally expired).

    `except_token`, when given, keeps the session that made this very
    request alive — otherwise the admin would be logged out by the same
    request that changed their own password."""
    except_hash = _hash_token(except_token) if except_token else None
    now = utcnow()
    query = db.query(AdminSession).filter(
        AdminSession.admin_user_id == admin_user_id,
        AdminSession.revoked_at.is_(None),
    )
    if except_hash is not None:
        query = query.filter(AdminSession.token_hash != except_hash)
    for session in query.all():
        session.revoked_at = now
    db.flush()
