import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import utcnow
from app.db.base import Base


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    # Encrypted the same way upstream passwords are (security-model.md §5) —
    # a TOTP secret is as sensitive as a password. Null = TOTP disabled.
    totp_secret_encrypted: Mapped[bytes | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        default=utcnow, nullable=False
    )
    last_login_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)

    sessions: Mapped[list["AdminSession"]] = relationship(back_populates="admin_user")


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_user_id: Mapped[int] = mapped_column(
        ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # SHA-256 of the raw session token — never the token itself
    # (security-model.md §5: a DB leak alone must not yield a usable token).
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(nullable=False)
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    admin_user: Mapped[AdminUser] = relationship(back_populates="sessions")
