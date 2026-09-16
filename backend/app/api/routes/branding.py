from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_db, require_csrf
from app.core.audit import client_ip, record_audit
from app.core.settings_store import get_relay_settings
from app.models.admin import AdminUser
from app.schemas.branding import BrandingRead, BrandingUpdate

router = APIRouter(prefix="/branding", tags=["branding"])

# Logos are small wordmarks/icons, not photos — this is generous headroom,
# not a real limit anyone should hit.
_MAX_LOGO_BYTES = 512 * 1024
_ALLOWED_LOGO_CONTENT_TYPES = {"image/png", "image/jpeg", "image/svg+xml"}
_STATIC_ASSETS_DIR = Path(__file__).resolve().parents[2] / "static_assets"


def _to_read(settings_row) -> BrandingRead:
    return BrandingRead(
        accent_color=settings_row.accent_color,
        has_custom_logo=settings_row.logo_image is not None,
    )


# No auth on the three GETs below — /login and /setup render branding
# before a session exists, matching GET /api/auth/setup-required's
# existing public-endpoint precedent.


@router.get("", response_model=BrandingRead)
def get_branding(db: Session = Depends(get_db)) -> BrandingRead:
    return _to_read(get_relay_settings(db))


@router.get("/logo")
def get_logo(db: Session = Depends(get_db)) -> Response:
    settings_row = get_relay_settings(db)
    if settings_row.logo_image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No custom logo configured")
    return Response(
        content=settings_row.logo_image,
        media_type=settings_row.logo_content_type or "application/octet-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/favicon")
def get_favicon(db: Session = Depends(get_db)) -> Response:
    settings_row = get_relay_settings(db)
    if settings_row.logo_image is not None:
        return Response(
            content=settings_row.logo_image,
            media_type=settings_row.logo_content_type or "application/octet-stream",
            headers={"Cache-Control": "no-cache"},
        )
    default_path = _STATIC_ASSETS_DIR / "favicon.png"
    return Response(
        content=default_path.read_bytes(),
        media_type="image/png",
        headers={"Cache-Control": "no-cache"},
    )


@router.patch("", response_model=BrandingRead, dependencies=[Depends(require_csrf)])
def update_branding(
    payload: BrandingUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> BrandingRead:
    settings_row = get_relay_settings(db)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(settings_row, field, value)

    record_audit(
        db,
        admin_user_id=admin.id,
        action="branding.update",
        target_type="relay_settings",
        target_id=settings_row.id,
        detail={"fields": list(updates.keys())},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(settings_row)
    return _to_read(settings_row)


@router.post("/logo", response_model=BrandingRead, dependencies=[Depends(require_csrf)])
async def upload_logo(
    request: Request,
    file: UploadFile,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> BrandingRead:
    if file.content_type not in _ALLOWED_LOGO_CONTENT_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Logo must be a PNG, JPEG, or SVG image")
    data = await file.read(_MAX_LOGO_BYTES + 1)
    if len(data) > _MAX_LOGO_BYTES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Logo must be 512 KB or smaller")

    settings_row = get_relay_settings(db)
    settings_row.logo_image = data
    settings_row.logo_content_type = file.content_type

    record_audit(
        db,
        admin_user_id=admin.id,
        action="branding.logo_upload",
        target_type="relay_settings",
        target_id=settings_row.id,
        detail={"content_type": file.content_type, "size_bytes": len(data)},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(settings_row)
    return _to_read(settings_row)


@router.delete("/logo", response_model=BrandingRead, dependencies=[Depends(require_csrf)])
def delete_logo(
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> BrandingRead:
    settings_row = get_relay_settings(db)
    settings_row.logo_image = None
    settings_row.logo_content_type = None

    record_audit(
        db,
        admin_user_id=admin.id,
        action="branding.logo_remove",
        target_type="relay_settings",
        target_id=settings_row.id,
        detail={},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(settings_row)
    return _to_read(settings_row)
