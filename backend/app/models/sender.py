import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import utcnow
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.local_user import UserSenderPermission
    from app.models.upstream import UpstreamAccount


class Sender(Base):
    __tablename__ = "senders"

    id: Mapped[int] = mapped_column(primary_key=True)
    address: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    # One sender -> one upstream account by design (architecture.md §9,
    # database-schema.md notes) — not a join table.
    upstream_account_id: Mapped[int] = mapped_column(
        ForeignKey("upstream_accounts.id"), nullable=False, index=True
    )
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    description: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    upstream_account: Mapped["UpstreamAccount"] = relationship(back_populates="senders")
    # passive_deletes=True: user_sender_permissions.sender_id is part of
    # that table's composite primary key, and its FK already has
    # ondelete="CASCADE" (local_user.py) with PRAGMA foreign_keys=ON set
    # (db/session.py) — without this, SQLAlchemy's unit-of-work tries to
    # null out that column itself before deleting the parent, which is
    # impossible for a primary-key column and raises an AssertionError.
    # This tells it to leave cascading to the database instead.
    permissions: Mapped[list["UserSenderPermission"]] = relationship(
        back_populates="sender", passive_deletes=True
    )
