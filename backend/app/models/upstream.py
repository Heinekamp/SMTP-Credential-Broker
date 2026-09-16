import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import utcnow
from app.db.base import Base
from app.models.enums import TestResult, TlsMode, str_enum

if TYPE_CHECKING:
    from app.models.sender import Sender


class UpstreamAccount(Base):
    __tablename__ = "upstream_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(nullable=False)
    tls_mode: Mapped[TlsMode] = mapped_column(
        str_enum(TlsMode, "tls_mode"), nullable=False, default=TlsMode.starttls
    )
    username: Mapped[str] = mapped_column(String(320), nullable=False)
    # AES-256-GCM ciphertext + nonce (security-model.md §2). Deliberately
    # never exposed by any Pydantic response schema — see schemas/.
    encrypted_password: Mapped[bytes] = mapped_column(nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    last_test_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)
    last_test_result: Mapped[TestResult | None] = mapped_column(
        str_enum(TestResult, "test_result"), nullable=True
    )
    last_test_error: Mapped[str | None] = mapped_column(nullable=True)
    # None = unlimited (today's behavior) — translated into a per-account
    # smtp_destination_rate_delay on a synthetic Postfix transport
    # (core/config_generator.py), pacing outbound deliveries rather than
    # rejecting anything, so excess mail just sits in Postfix's own queue.
    rate_limit_per_hour: Mapped[int | None] = mapped_column(nullable=True, default=None)
    created_at: Mapped[datetime.datetime] = mapped_column(
        default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    senders: Mapped[list["Sender"]] = relationship(back_populates="upstream_account")
