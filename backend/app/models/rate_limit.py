import datetime

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LocalUserRateLimitCounter(Base):
    """One row per (local user, hourly window) — backs the synchronous
    accept/defer decision in core/rate_limit_policy.py. `window_start` is
    the top of the clock hour (UTC); a window rolling over is simply a new
    row starting at count=0, no explicit reset needed. Only local users
    need this: the upstream-account side paces deliveries natively via a
    Postfix transport (core/config_generator.py), so it needs no counter
    of its own. Rows older than a couple of windows are inert and swept up
    by core/rate_limit_cleanup.py."""

    __tablename__ = "local_user_rate_limit_counters"
    __table_args__ = (
        UniqueConstraint(
            "local_smtp_user_id", "window_start", name="uq_local_user_rate_limit_counters_local_smtp_user_id"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    local_smtp_user_id: Mapped[int] = mapped_column(
        ForeignKey("local_smtp_users.id", ondelete="CASCADE"), nullable=False
    )
    window_start: Mapped[datetime.datetime] = mapped_column(nullable=False)
    count: Mapped[int] = mapped_column(default=0, nullable=False)
