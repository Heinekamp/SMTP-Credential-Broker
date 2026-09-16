import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import utcnow
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.admin import AdminUser
    from app.models.sender import Sender


class LocalSmtpUser(Base):
    __tablename__ = "local_smtp_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    username: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    # Argon2id hash kept ONLY for the web UI's own "was this ever
    # (re)generated" bookkeeping — the authoritative check happens in
    # Cyrus SASL's sasldb2 (security-model.md §4), not here.
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        default=utcnow, nullable=False
    )
    password_last_rotated_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)
    # None = unlimited (today's behavior) — enforced by a Postfix
    # policy-delegation service keyed on sasl_username
    # (core/rate_limit_policy.py), not Postfix's own anvil limiter, which
    # only keys on client IP and can't distinguish local users sharing one.
    rate_limit_per_hour: Mapped[int | None] = mapped_column(nullable=True, default=None)

    # passive_deletes=True: see the identical comment on Sender.permissions
    # (sender.py) — user_sender_permissions.local_smtp_user_id is part of
    # that table's composite primary key, so SQLAlchemy must defer to the
    # database's own ON DELETE CASCADE rather than trying to null it out
    # itself.
    permissions: Mapped[list["UserSenderPermission"]] = relationship(
        back_populates="local_smtp_user", passive_deletes=True
    )


class UserSenderPermission(Base):
    __tablename__ = "user_sender_permissions"
    __table_args__ = (PrimaryKeyConstraint("local_smtp_user_id", "sender_id"),)

    local_smtp_user_id: Mapped[int] = mapped_column(
        ForeignKey("local_smtp_users.id", ondelete="CASCADE"), nullable=False
    )
    sender_id: Mapped[int] = mapped_column(ForeignKey("senders.id", ondelete="CASCADE"), nullable=False)
    granted_at: Mapped[datetime.datetime] = mapped_column(
        default=utcnow, nullable=False
    )
    granted_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admin_users.id"), nullable=True
    )

    local_smtp_user: Mapped[LocalSmtpUser] = relationship(back_populates="permissions")
    sender: Mapped["Sender"] = relationship(back_populates="permissions")
    granted_by_admin: Mapped["AdminUser | None"] = relationship()
