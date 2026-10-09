import threading
import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin_optional, get_db
from app.core.health import CheckResult, HealthReport, run_health_check
from app.models.admin import AdminUser
from app.schemas.health import HealthCheckDetail, HealthResponse

router = APIRouter()

# Anonymous callers (Docker's healthcheck, uptime monitors) get a report at
# most this old. Every full check makes an RPC to the postfix control
# surface, which serves one request at a time — an unauthenticated
# endpoint must not let anyone keep it busy (#175).
_ANONYMOUS_CACHE_SECONDS = 5.0
_anonymous_cache: tuple[float, HealthReport] | None = None
_anonymous_cache_lock = threading.Lock()


def _anonymous_report(db: Session) -> HealthReport:
    global _anonymous_cache
    with _anonymous_cache_lock:
        now = time.monotonic()
        if _anonymous_cache is None or now - _anonymous_cache[0] > _ANONYMOUS_CACHE_SECONDS:
            _anonymous_cache = (now, run_health_check(db))
        return _anonymous_cache[1]


def _detail(check: CheckResult, *, include_detail: bool) -> HealthCheckDetail:
    return HealthCheckDetail(ok=check.ok, detail=check.detail if include_detail else "")


@router.get("/health", response_model=HealthResponse)
def health(
    db: Session = Depends(get_db), admin: AdminUser | None = Depends(get_current_admin_optional)
) -> HealthResponse:
    """A real capability check, not just process liveness (architecture.md
    §7, spec §28). Always returns 200 — the body's `status` field, not the
    HTTP status code, is what reflects health, so a monitoring tool that
    only checks for a 2xx (like this project's own `compose-smoke` CI job)
    doesn't need special-casing, while a real dashboard can inspect the
    per-check detail.

    The per-check `detail` text (postfix status output, control-socket and
    database error messages) is internal, so only a logged-in admin gets
    it, freshly computed. Anyone else gets the status and booleans from a
    short-lived shared cache (#175)."""
    report = run_health_check(db) if admin is not None else _anonymous_report(db)
    include_detail = admin is not None
    return HealthResponse(
        status=report.status,
        database=_detail(report.database, include_detail=include_detail),
        postfix_reachable=_detail(report.postfix_reachable, include_detail=include_detail),
        postfix_running=_detail(report.postfix_running, include_detail=include_detail),
        last_generation_result=report.last_generation_result,
        config_in_sync=_detail(report.config_in_sync, include_detail=include_detail),
    )
