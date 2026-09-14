from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_db, require_csrf
from app.core.audit import client_ip, record_audit
from app.core.config_generator import generate_and_apply
from app.core.postfix_control import PostfixControlError
from app.models.admin import AdminUser
from app.models.config_generation import ConfigGeneration
from app.schemas.config import ConfigGenerationRead, GenerationResult

router = APIRouter(prefix="/config", tags=["config"], dependencies=[Depends(get_current_admin)])


@router.post("/generate", response_model=GenerationResult, dependencies=[Depends(require_csrf)])
def generate_config(
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> GenerationResult:
    try:
        outcome = generate_and_apply(db, triggered_by_admin_id=admin.id)
    except PostfixControlError as exc:
        # Unreachable control surface is an infrastructure problem, not a
        # bad-config problem — no config_generations row is recorded for
        # it (there was nothing to validate), and the previous config
        # stays live either way.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    # Additive to config_generations, not a replacement for it — this is
    # what lets a unified audit view include "who triggered generation
    # #N" alongside every other admin action.
    record_audit(
        db,
        admin_user_id=admin.id,
        action="config.generate",
        target_type="config_generation",
        target_id=outcome.generation_id,
        detail={"success": outcome.success, "reloaded": outcome.reloaded},
        ip_address=client_ip(request),
    )
    db.commit()
    return GenerationResult(
        generation_id=outcome.generation_id,
        success=outcome.success,
        validation_detail=outcome.validation_detail,
        reloaded=outcome.reloaded,
        warnings=outcome.warnings,
    )


@router.post("/validate", response_model=GenerationResult, dependencies=[Depends(require_csrf)])
def validate_config(db: Session = Depends(get_db)) -> GenerationResult:
    outcome = generate_and_apply(db, triggered_by_admin_id=None, dry_run=True)
    return GenerationResult(
        generation_id=outcome.generation_id,
        success=outcome.success,
        validation_detail=outcome.validation_detail,
        reloaded=outcome.reloaded,
        warnings=outcome.warnings,
    )


@router.get("/generations", response_model=list[ConfigGenerationRead])
def list_generations(db: Session = Depends(get_db)) -> list[ConfigGeneration]:
    return (
        db.query(ConfigGeneration)
        .order_by(ConfigGeneration.generated_at.desc())
        .limit(50)
        .all()
    )
