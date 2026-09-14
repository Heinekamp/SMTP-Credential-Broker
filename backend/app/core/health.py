"""The real capability checks behind `GET /api/health` and `relay doctor`
(architecture.md §7, spec §28) — process liveness alone doesn't answer
"can this relay actually deliver mail right now."
"""

import dataclasses

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core import postfix_control
from app.core.config_generator import current_state_checksums
from app.models.config_generation import ConfigGeneration
from app.models.enums import ValidationResult


@dataclasses.dataclass
class CheckResult:
    ok: bool
    detail: str = ""


@dataclasses.dataclass
class HealthReport:
    status: str  # "ok" | "degraded"
    database: CheckResult
    postfix_reachable: CheckResult
    postfix_running: CheckResult
    last_generation_result: str  # "pass" | "fail" | "none"
    config_in_sync: CheckResult


def _check_database(db: Session) -> CheckResult:
    try:
        db.execute(text("SELECT 1"))
        return CheckResult(ok=True)
    except SQLAlchemyError as exc:
        return CheckResult(ok=False, detail=str(exc))


def run_health_check(db: Session) -> HealthReport:
    database = _check_database(db)

    try:
        postfix_status = postfix_control.status()
        postfix_reachable = CheckResult(ok=True)
        postfix_running = CheckResult(ok=postfix_status.running, detail=postfix_status.detail)
    except postfix_control.PostfixControlError as exc:
        postfix_reachable = CheckResult(ok=False, detail=str(exc))
        postfix_running = CheckResult(ok=False, detail="control surface unreachable")

    last_good = (
        db.query(ConfigGeneration)
        .filter(ConfigGeneration.validation_result == ValidationResult.pass_, ConfigGeneration.applied.is_(True))
        .order_by(ConfigGeneration.generated_at.desc())
        .first()
    )
    latest = db.query(ConfigGeneration).order_by(ConfigGeneration.generated_at.desc()).first()
    last_generation_result = "none" if latest is None else latest.validation_result.value

    # A relay that has never had a config successfully applied yet is a
    # normal starting state (a fresh install, before the first sender is
    # even created), not a fault — Postfix legitimately isn't running yet
    # either (nothing else starts it; see control_surface.py's
    # _apply_config) and there's nothing meaningful to be "in sync" with.
    # Both checks are still reported truthfully below, just excluded from
    # the overall status while this is the case.
    never_configured = last_good is None

    if never_configured:
        config_in_sync = CheckResult(ok=False, detail="no configuration has ever been successfully applied yet")
    else:
        main_master_checksum, maps_checksum = current_state_checksums(db)
        in_sync = main_master_checksum == last_good.checksum and maps_checksum == last_good.maps_checksum
        config_in_sync = CheckResult(
            ok=in_sync,
            detail=(
                ""
                if in_sync
                else "current database state differs from the last applied configuration — regenerate to apply"
            ),
        )

    healthy = (
        database.ok
        and postfix_reachable.ok
        and last_generation_result != "fail"
        and (never_configured or postfix_running.ok)
        and (never_configured or config_in_sync.ok)
    )

    return HealthReport(
        status="ok" if healthy else "degraded",
        database=database,
        postfix_reachable=postfix_reachable,
        postfix_running=postfix_running,
        last_generation_result=last_generation_result,
        config_in_sync=config_in_sync,
    )
