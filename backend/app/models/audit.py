import datetime

from sqlalchemy import JSON, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        # Backs the login rate-limiter's per-account and per-IP queries
        # (core/rate_limit.py) — not called for explicitly in
        # database-schema.md, added here since the rate limiter needs it.
        Index("ix_audit_log_action_ip_ts", "action", "ip_address", "timestamp"),
        Index("ix_audit_log_action_target_ts", "action", "target_type", "target_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime.datetime] = mapped_column(
        default=utcnow, nullable=False
    )
    admin_user_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    target_id: Mapped[int | None] = mapped_column(nullable=True)
    # Structured, non-secret context only — never a password/token/key
    # field (security-model.md §8), enforced by convention at call sites.
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
