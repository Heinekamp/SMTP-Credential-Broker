import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_db, require_csrf
from app.api.routes.auth import SESSION_COOKIE_NAME
from app.core.audit import client_ip, record_audit
from app.core.encryption import EncryptionKeyNotConfigured, encrypt_secret
from app.core.security import hash_password, verify_password
from app.core.sessions import revoke_all_sessions_for_admin
from app.models.admin import AdminUser
from app.schemas.admin import (
    AdminCreate,
    AdminRead,
    AdminUpdate,
    ChangePasswordRequest,
    TotpConfirmRequest,
    TotpEnrollResponse,
)

router = APIRouter(prefix="/admins", tags=["admins"], dependencies=[Depends(get_current_admin)])

# The name shown alongside the account in the admin's authenticator app —
# matches the product name the frontend's title bar shows (Titlebar.tsx).
_TOTP_ISSUER = "SMTP Relay Console"


def _to_read(admin: AdminUser) -> AdminRead:
    return AdminRead(
        id=admin.id,
        email=admin.email,
        totp_enabled=admin.totp_secret_encrypted is not None,
        is_active=admin.is_active,
        created_at=admin.created_at,
        last_login_at=admin.last_login_at,
    )


@router.get("", response_model=list[AdminRead])
def list_admins(db: Session = Depends(get_db)) -> list[AdminRead]:
    admins = db.query(AdminUser).order_by(AdminUser.email).all()
    return [_to_read(a) for a in admins]


@router.post("", response_model=AdminRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)])
def create_admin(
    payload: AdminCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> AdminRead:
    new_admin = AdminUser(email=payload.email, password_hash=hash_password(payload.password))
    db.add(new_admin)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "An admin with this email already exists") from exc
    db.refresh(new_admin)
    record_audit(
        db,
        admin_user_id=admin.id,
        action="admin.create",
        target_type="admin_user",
        target_id=new_admin.id,
        detail={"email": new_admin.email},
        ip_address=client_ip(request),
    )
    db.commit()
    return _to_read(new_admin)


@router.patch("/{admin_id}", response_model=AdminRead, dependencies=[Depends(require_csrf)])
def update_admin(
    admin_id: int,
    payload: AdminUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> AdminRead:
    """Deactivate/reactivate another admin without deleting their audit
    history (admin_users.is_active exists for exactly this — until now,
    nothing ever set it). Deactivating revokes every one of their active
    sessions immediately (get_current_admin_optional already rejects a
    request from an inactive admin regardless, but this also means a
    later reactivation doesn't silently hand back access via a session
    that was never explicitly ended)."""
    target = db.get(AdminUser, admin_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Admin not found")

    if payload.is_active != target.is_active:
        if not payload.is_active:
            active_count = db.query(AdminUser).filter(AdminUser.is_active.is_(True)).count()
            if active_count <= 1:
                raise HTTPException(status.HTTP_409_CONFLICT, "Can't deactivate the last active admin")
            revoke_all_sessions_for_admin(db, target.id)
        target.is_active = payload.is_active
        record_audit(
            db,
            admin_user_id=admin.id,
            action="admin.reactivate" if payload.is_active else "admin.deactivate",
            target_type="admin_user",
            target_id=target.id,
            detail={"email": target.email},
            ip_address=client_ip(request),
        )
        db.commit()
        db.refresh(target)
    return _to_read(target)


@router.post("/me/change-password", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)])
def change_own_password(
    payload: ChangePasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> None:
    if not verify_password(admin.password_hash, payload.current_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Current password is incorrect")
    admin.password_hash = hash_password(payload.new_password)
    # A session cookie stolen before this change must not keep working
    # after it — except the one making this very request, so the admin
    # isn't logged out by their own password change.
    revoke_all_sessions_for_admin(db, admin.id, except_token=request.cookies.get(SESSION_COOKIE_NAME))
    record_audit(
        db,
        admin_user_id=admin.id,
        action="admin.change_password",
        target_type="admin_user",
        target_id=admin.id,
        ip_address=client_ip(request),
    )
    db.commit()


@router.post("/me/totp/enroll", response_model=TotpEnrollResponse, dependencies=[Depends(require_csrf)])
def enroll_totp(admin: AdminUser = Depends(get_current_admin)) -> TotpEnrollResponse:
    """Generates a fresh secret and returns it — nothing is persisted
    until /me/totp/confirm proves the admin actually captured it
    correctly (stateless across the two steps by design: a wrong/lost
    secret at this stage just means trying enrollment again, not a
    half-enabled account)."""
    secret = pyotp.random_base32()
    otpauth_uri = pyotp.totp.TOTP(secret).provisioning_uri(name=admin.email, issuer_name=_TOTP_ISSUER)
    return TotpEnrollResponse(secret=secret, otpauth_uri=otpauth_uri)


@router.post("/me/totp/confirm", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)])
def confirm_totp(
    payload: TotpConfirmRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> None:
    if not pyotp.TOTP(payload.secret).verify(payload.code, valid_window=1):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid authentication code")
    try:
        admin.totp_secret_encrypted = encrypt_secret(payload.secret)
    except EncryptionKeyNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    revoke_all_sessions_for_admin(db, admin.id, except_token=request.cookies.get(SESSION_COOKIE_NAME))
    record_audit(
        db,
        admin_user_id=admin.id,
        action="admin.totp_enroll",
        target_type="admin_user",
        target_id=admin.id,
        ip_address=client_ip(request),
    )
    db.commit()


@router.post("/me/totp/remove", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)])
def remove_totp(
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> None:
    admin.totp_secret_encrypted = None
    revoke_all_sessions_for_admin(db, admin.id, except_token=request.cookies.get(SESSION_COOKIE_NAME))
    record_audit(
        db,
        admin_user_id=admin.id,
        action="admin.totp_remove",
        target_type="admin_user",
        target_id=admin.id,
        ip_address=client_ip(request),
    )
    db.commit()
