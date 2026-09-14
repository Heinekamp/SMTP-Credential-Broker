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
