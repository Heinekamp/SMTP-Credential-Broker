from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.health import CheckResult, run_health_check
from app.schemas.health import HealthCheckDetail, HealthResponse

router = APIRouter()


def _detail(check: CheckResult) -> HealthCheckDetail:
    return HealthCheckDetail(ok=check.ok, detail=check.detail)


@router.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    """A real capability check, not just process liveness (architecture.md
    §7, spec §28). Always returns 200 — the body's `status` field, not the
    HTTP status code, is what reflects health, so a monitoring tool that
    only checks for a 2xx (like this project's own `compose-smoke` CI job)
    doesn't need special-casing, while a real dashboard can inspect the
    per-check detail."""
    report = run_health_check(db)
    return HealthResponse(
        status=report.status,
        database=_detail(report.database),
        postfix_reachable=_detail(report.postfix_reachable),
        postfix_running=_detail(report.postfix_running),
        last_generation_result=report.last_generation_result,
        config_in_sync=_detail(report.config_in_sync),
    )
