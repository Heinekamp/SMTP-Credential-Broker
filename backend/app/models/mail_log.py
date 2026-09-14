import datetime

from sqlalchemy import JSON, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base
from app.models.enums import MailStatus, str_enum


class MailLog(Base):
    __tablename__ = "mail_log"
    __table_args__ = (
        Index("ix_mail_log_timestamp", "timestamp"),
        Index("ix_mail_log_envelope_sender", "envelope_sender"),
        Index("ix_mail_log_local_smtp_user_id", "local_smtp_user_id"),
        Index("ix_mail_log_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    queue_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime.datetime] = mapped_column(nullable=False)
    # Nullable: a log row must remain storable after the referenced local
    # user or upstream account is later deleted (database-schema.md §7).
    local_smtp_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("local_smtp_users.id", ondelete="SET NULL"), nullable=True
    )
    envelope_sender: Mapped[str] = mapped_column(String(320), nullable=False)
    recipients: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    upstream_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("upstream_accounts.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[MailStatus] = mapped_column(str_enum(MailStatus, "mail_status"), nullable=False)
    # Postfix's own diagnostic text — credential-free by construction
    # (security-model.md §8), never a place a password could appear.
    error: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        default=utcnow, nullable=False
    )
