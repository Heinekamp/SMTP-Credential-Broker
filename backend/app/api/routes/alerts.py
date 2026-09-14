from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_db, require_csrf
from app.core.alerts import compute_active_alerts
from app.core.audit import client_ip, record_audit
from app.core.settings_store import get_background_job_state
from app.models.admin import AdminUser
from app.schemas.alerts import AlertRead, AlertsResponse

router = APIRouter(prefix="/alerts", tags=["alerts"], dependencies=[Depends(get_current_admin)])

_ACKNOWLEDGEABLE_KINDS = {
    "app_update_available": "latest_app_version",
    "postfix_update_available": "latest_postfix_version",
}
_ACKNOWLEDGED_FIELD = {
    "app_update_available": "app_update_acknowledged_version",
    "postfix_update_available": "postfix_update_acknowledged_version",
}


@router.get("", response_model=AlertsResponse)
def list_alerts(db: Session = Depends(get_db)) -> AlertsResponse:
    alerts = compute_active_alerts(db)
    active_count = sum(1 for alert in alerts if not alert.acknowledged)
    return AlertsResponse(
        alerts=[AlertRead(**vars(alert)) for alert in alerts],
        active_count=active_count,
    )


@router.post("/{kind}/acknowledge", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)])
def acknowledge_alert(
    kind: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> None:
    """Only the two update-available kinds are acknowledgeable — acks the
    version that's *currently* latest (background_job_state), never an
    arbitrary client-supplied value, so an admin can't acknowledge a
    version that hasn't even been detected yet."""
    if kind not in _ACKNOWLEDGEABLE_KINDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{kind!r} is not an acknowledgeable alert kind")

    state = get_background_job_state(db)
    latest_version = getattr(state, _ACKNOWLEDGEABLE_KINDS[kind])
    setattr(state, _ACKNOWLEDGED_FIELD[kind], latest_version)

    record_audit(
        db,
        admin_user_id=admin.id,
        action="alert.acknowledge",
        target_type="alert",
        target_id=None,
        detail={"kind": kind, "acknowledged_version": latest_version},
        ip_address=client_ip(request),
    )
    db.commit()
