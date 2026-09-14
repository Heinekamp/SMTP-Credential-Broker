from importlib.metadata import version

from fastapi import APIRouter, Depends

from app.api.deps import get_current_admin
from app.core.encryption import is_encryption_key_configured
from app.schemas.system import SystemStatus

router = APIRouter(prefix="/system-status", tags=["system"], dependencies=[Depends(get_current_admin)])


@router.get("", response_model=SystemStatus)
def system_status() -> SystemStatus:
    """Settings' System tab (design spec §10) reads this for the
    Encryption Key card's Configured/Not-configured badge — Postfix
    status and config-generation history come from the existing
    /api/health and /api/config/generations endpoints instead of being
    duplicated here."""
    return SystemStatus(
        encryption_key_configured=is_encryption_key_configured(),
        app_version=version("relay"),
    )
