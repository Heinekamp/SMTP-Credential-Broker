import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import ValidationResult


class GenerationResult(BaseModel):
    generation_id: int
    success: bool
    validation_detail: str
    reloaded: bool
    warnings: list[str]


class ConfigGenerationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    generated_at: datetime.datetime
    triggered_by_admin_id: int | None
    checksum: str
    maps_checksum: str
    validation_result: ValidationResult
    validation_detail: str | None
    applied: bool
    reload_triggered: bool
