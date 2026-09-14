import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base
from app.models.enums import ValidationResult, str_enum


class ConfigGeneration(Base):
    """One row per attempted Postfix config generation (not just successful
    ones — architecture.md §5's atomic-install pipeline needs failed
    attempts recorded too, since the previous good config stays active)."""

    __tablename__ = "config_generations"

    id: Mapped[int] = mapped_column(primary_key=True)
    generated_at: Mapped[datetime.datetime] = mapped_column(
        default=utcnow, nullable=False
    )
    triggered_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admin_users.id"), nullable=True
    )
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_result: Mapped[ValidationResult] = mapped_column(
        str_enum(ValidationResult, "validation_result"), nullable=False
    )
    validation_detail: Mapped[str | None] = mapped_column(nullable=True)
    applied: Mapped[bool] = mapped_column(default=False, nullable=False)
    reload_triggered: Mapped[bool] = mapped_column(default=False, nullable=False)
