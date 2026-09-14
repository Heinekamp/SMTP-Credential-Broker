from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_db, require_csrf
from app.core.audit import client_ip, record_audit
from app.core.permissions import grant_permission, revoke_permission
from app.models.admin import AdminUser
from app.models.local_user import LocalSmtpUser, UserSenderPermission
from app.models.sender import Sender
from app.models.upstream import UpstreamAccount
from app.schemas.sender import (
    DeleteSenderPrecheck,
    PermissionListEntry,
    SenderCreate,
    SenderPermissionsView,
    SenderRead,
    SenderUpdate,
)

router = APIRouter(prefix="/senders", tags=["senders"], dependencies=[Depends(get_current_admin)])


def _get_or_404(db: Session, sender_id: int) -> Sender:
    sender = db.get(Sender, sender_id)
    if sender is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sender not found")
    return sender


def _allowed_user_count(db: Session, sender_id: int) -> int:
    return db.query(UserSenderPermission).filter(UserSenderPermission.sender_id == sender_id).count()


def _to_read(db: Session, sender: Sender) -> SenderRead:
    return SenderRead(
        id=sender.id,
        address=sender.address,
        upstream_account_id=sender.upstream_account_id,
        enabled=sender.enabled,
        description=sender.description,
        created_at=sender.created_at,
        updated_at=sender.updated_at,
        allowed_local_user_count=_allowed_user_count(db, sender.id),
    )


def _require_upstream_account(db: Session, upstream_account_id: int) -> None:
    if db.get(UpstreamAccount, upstream_account_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown upstream_account_id")


@router.get("", response_model=list[SenderRead])
def list_senders(db: Session = Depends(get_db)) -> list[SenderRead]:
    senders = db.query(Sender).order_by(Sender.address).all()
    return [_to_read(db, s) for s in senders]


@router.post("", response_model=SenderRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)])
def create_sender(
    payload: SenderCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> SenderRead:
    _require_upstream_account(db, payload.upstream_account_id)
    sender = Sender(
        address=payload.address,
        upstream_account_id=payload.upstream_account_id,
        enabled=payload.enabled,
        description=payload.description,
    )
    db.add(sender)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A sender with this address already exists") from exc
    db.refresh(sender)
    # A separate commit, deliberately after the create has already
    # succeeded — see upstream_accounts.py's delete_account for why.
    record_audit(
        db,
        admin_user_id=admin.id,
        action="sender.create",
        target_type="sender",
        target_id=sender.id,
        detail={"address": sender.address},
        ip_address=client_ip(request),
    )
    db.commit()
    return _to_read(db, sender)


@router.get("/{sender_id}", response_model=SenderRead)
def get_sender(sender_id: int, db: Session = Depends(get_db)) -> SenderRead:
    return _to_read(db, _get_or_404(db, sender_id))


@router.patch("/{sender_id}", response_model=SenderRead, dependencies=[Depends(require_csrf)])
def update_sender(
    sender_id: int,
    payload: SenderUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> SenderRead:
    sender = _get_or_404(db, sender_id)
    data = payload.model_dump(exclude_unset=True)
    if "upstream_account_id" in data and data["upstream_account_id"] is not None:
        _require_upstream_account(db, data["upstream_account_id"])
    for field, value in data.items():
        setattr(sender, field, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A sender with this address already exists") from exc
    db.refresh(sender)
    record_audit(
        db,
        admin_user_id=admin.id,
        action="sender.update",
        target_type="sender",
        target_id=sender.id,
        detail={"fields": sorted(data.keys())},
        ip_address=client_ip(request),
    )
    db.commit()
    return _to_read(db, sender)


@router.get("/{sender_id}/delete-precheck", response_model=DeleteSenderPrecheck)
def delete_precheck(sender_id: int, db: Session = Depends(get_db)) -> DeleteSenderPrecheck:
    _get_or_404(db, sender_id)
    names = (
        db.query(LocalSmtpUser.name)
        .join(UserSenderPermission, UserSenderPermission.local_smtp_user_id == LocalSmtpUser.id)
        .filter(UserSenderPermission.sender_id == sender_id)
        .all()
    )
    return DeleteSenderPrecheck(allowed_local_user_names=[n for (n,) in names])


@router.delete("/{sender_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)])
def delete_sender(
    sender_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> None:
    sender = _get_or_404(db, sender_id)
    address = sender.address
    db.delete(sender)  # cascades user_sender_permissions (ondelete=CASCADE)
    record_audit(
        db,
        admin_user_id=admin.id,
        action="sender.delete",
        target_type="sender",
        target_id=sender_id,
        detail={"address": address},
        ip_address=client_ip(request),
    )
    db.commit()


@router.get("/{sender_id}/permissions", response_model=SenderPermissionsView)
def get_permissions(sender_id: int, db: Session = Depends(get_db)) -> SenderPermissionsView:
    sender = _get_or_404(db, sender_id)
    granted_ids = {
        uid
        for (uid,) in db.query(UserSenderPermission.local_smtp_user_id).filter(
            UserSenderPermission.sender_id == sender_id
        )
    }
    users = db.query(LocalSmtpUser).order_by(LocalSmtpUser.name).all()
    return SenderPermissionsView(
        sender=_to_read(db, sender),
        local_users=[
            PermissionListEntry(id=u.id, name=u.name, username=u.username, allowed=u.id in granted_ids)
            for u in users
        ],
    )


@router.put(
    "/{sender_id}/permissions/{local_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
def grant(
    sender_id: int,
    local_user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> None:
    sender = _get_or_404(db, sender_id)
    local_user = db.get(LocalSmtpUser, local_user_id)
    if local_user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Local SMTP user not found")
    grant_permission(db, local_smtp_user_id=local_user_id, sender_id=sender_id, granted_by_admin_id=admin.id)
    record_audit(
        db,
        admin_user_id=admin.id,
        action="permission.grant",
        target_type="user_sender_permission",
        target_id=sender_id,
        detail={"sender": sender.address, "local_user": local_user.username},
        ip_address=client_ip(request),
    )
    db.commit()


@router.delete(
    "/{sender_id}/permissions/{local_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
def revoke(
    sender_id: int,
    local_user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> None:
    sender = _get_or_404(db, sender_id)
    local_user = db.get(LocalSmtpUser, local_user_id)
    revoke_permission(db, local_smtp_user_id=local_user_id, sender_id=sender_id)
    record_audit(
        db,
        admin_user_id=admin.id,
        action="permission.revoke",
        target_type="user_sender_permission",
        target_id=sender_id,
        detail={"sender": sender.address, "local_user": local_user.username if local_user else None},
        ip_address=client_ip(request),
    )
    db.commit()
