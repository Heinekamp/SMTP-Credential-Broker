from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_db, require_csrf
from app.core.security import hash_password, verify_password
from app.models.admin import AdminUser
from app.schemas.admin import AdminCreate, AdminRead, ChangePasswordRequest

router = APIRouter(prefix="/admins", tags=["admins"], dependencies=[Depends(get_current_admin)])


def _to_read(admin: AdminUser) -> AdminRead:
    return AdminRead(
        id=admin.id,
        email=admin.email,
        totp_enabled=admin.totp_secret_encrypted is not None,
        created_at=admin.created_at,
        last_login_at=admin.last_login_at,
    )


@router.get("", response_model=list[AdminRead])
def list_admins(db: Session = Depends(get_db)) -> list[AdminRead]:
    admins = db.query(AdminUser).order_by(AdminUser.email).all()
    return [_to_read(a) for a in admins]


@router.post("", response_model=AdminRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)])
def create_admin(payload: AdminCreate, db: Session = Depends(get_db)) -> AdminRead:
    admin = AdminUser(email=payload.email, password_hash=hash_password(payload.password))
    db.add(admin)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "An admin with this email already exists") from exc
    db.refresh(admin)
    return _to_read(admin)


@router.post("/me/change-password", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)])
def change_own_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> None:
    if not verify_password(admin.password_hash, payload.current_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Current password is incorrect")
    admin.password_hash = hash_password(payload.new_password)
    db.commit()
