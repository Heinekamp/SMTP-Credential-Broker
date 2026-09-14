from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_db, require_csrf
from app.config import get_settings
from app.core import postfix_control
from app.core.clock import utcnow
from app.core.password_generation import generate_password
from app.core.permissions import grant_permission, revoke_permission
from app.core.postfix_control import PostfixControlError
from app.core.security import hash_password
from app.models.admin import AdminUser
from app.models.local_user import LocalSmtpUser, UserSenderPermission
from app.models.sender import Sender
from app.schemas.local_user import (
    ConnectionDetails,
    DeleteUserPrecheck,
    LocalUserCreate,
    LocalUserCreateResponse,
    LocalUserRead,
    LocalUserUpdate,
    LocalUserUpdateResponse,
    PasswordRevealResponse,
    PermissionListEntry,
    UserPermissionsView,
)

router = APIRouter(prefix="/local-users", tags=["local-users"], dependencies=[Depends(get_current_admin)])


def _get_or_404(db: Session, user_id: int) -> LocalSmtpUser:
    user = db.get(LocalSmtpUser, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Local SMTP user not found")
    return user


def _allowed_sender_count(db: Session, user_id: int) -> int:
    return (
        db.query(UserSenderPermission).filter(UserSenderPermission.local_smtp_user_id == user_id).count()
    )


def _to_read(db: Session, user: LocalSmtpUser) -> LocalUserRead:
    return LocalUserRead(
        id=user.id,
        name=user.name,
        username=user.username,
        enabled=user.enabled,
        created_at=user.created_at,
        password_last_rotated_at=user.password_last_rotated_at,
        allowed_sender_count=_allowed_sender_count(db, user.id),
    )


def _set_sasl_or_503(username: str, password: str) -> None:
    try:
        postfix_control.sasl_set_user(username, password)
    except PostfixControlError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


def _delete_sasl_or_503(username: str) -> None:
    try:
        postfix_control.sasl_delete_user(username)
    except PostfixControlError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.get("", response_model=list[LocalUserRead])
def list_users(db: Session = Depends(get_db)) -> list[LocalUserRead]:
    users = db.query(LocalSmtpUser).order_by(LocalSmtpUser.name).all()
    return [_to_read(db, u) for u in users]


@router.post(
    "",
    response_model=LocalUserCreateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_user(payload: LocalUserCreate, db: Session = Depends(get_db)) -> LocalUserCreateResponse:
    if db.query(LocalSmtpUser).filter(LocalSmtpUser.username == payload.username).one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already in use")

    password = generate_password()
    user = LocalSmtpUser(
        name=payload.name,
        username=payload.username,
        password_hash=hash_password(password),
        password_last_rotated_at=utcnow(),
    )
    db.add(user)
    db.flush()  # surfaces DB-level errors before the external sasldb2 call

    # sasldb2 (the security-enforcing side) is set before commit: if it
    # fails, the transaction rolls back and no half-created user is left
    # behind (security-model.md §4).
    _set_sasl_or_503(user.username, password)

    db.commit()
    db.refresh(user)
    return LocalUserCreateResponse(user=_to_read(db, user), password=password)


@router.get("/{user_id}", response_model=LocalUserRead)
def get_user(user_id: int, db: Session = Depends(get_db)) -> LocalUserRead:
    return _to_read(db, _get_or_404(db, user_id))


@router.patch("/{user_id}", response_model=LocalUserUpdateResponse, dependencies=[Depends(require_csrf)])
def update_user(user_id: int, payload: LocalUserUpdate, db: Session = Depends(get_db)) -> LocalUserUpdateResponse:
    """`enabled` transitions are the interesting case:

    - true -> false ("disable"): sasldb2 entry is deleted immediately —
      matches database-schema.md's "disabling removes the user from
      sasldb2 on next generation, immediately revoking SMTP AUTH."
    - false -> true ("re-enable"): there is no plaintext password to
      restore (only an Argon2 hash is ever stored — security-model.md §5),
      so re-enabling issues a *new* credential, exactly like Regenerate.
      The response's `password` field carries it, one time, same as
      create/regenerate.
    """
    user = _get_or_404(db, user_id)
    data = payload.model_dump(exclude_unset=True)
    new_password: str | None = None

    if "enabled" in data and data["enabled"] != user.enabled:
        if data["enabled"] is False:
            _delete_sasl_or_503(user.username)
        else:
            new_password = generate_password()
            _set_sasl_or_503(user.username, new_password)
            user.password_hash = hash_password(new_password)
            user.password_last_rotated_at = utcnow()
        user.enabled = data["enabled"]

    if "name" in data and data["name"] is not None:
        user.name = data["name"]

    db.commit()
    db.refresh(user)
    return LocalUserUpdateResponse(user=_to_read(db, user), password=new_password)


@router.post(
    "/{user_id}/regenerate-password",
    response_model=PasswordRevealResponse,
    dependencies=[Depends(require_csrf)],
)
def regenerate_password(user_id: int, db: Session = Depends(get_db)) -> PasswordRevealResponse:
    user = _get_or_404(db, user_id)
    password = generate_password()
    _set_sasl_or_503(user.username, password)
    user.password_hash = hash_password(password)
    user.password_last_rotated_at = utcnow()
    db.commit()
    return PasswordRevealResponse(password=password)


@router.get("/{user_id}/delete-precheck", response_model=DeleteUserPrecheck)
def delete_precheck(user_id: int, db: Session = Depends(get_db)) -> DeleteUserPrecheck:
    _get_or_404(db, user_id)
    addresses = (
        db.query(Sender.address)
        .join(UserSenderPermission, UserSenderPermission.sender_id == Sender.id)
        .filter(UserSenderPermission.local_smtp_user_id == user_id)
        .all()
    )
    return DeleteUserPrecheck(allowed_sender_addresses=[a for (a,) in addresses])


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)])
def delete_user(user_id: int, db: Session = Depends(get_db)) -> None:
    user = _get_or_404(db, user_id)
    _delete_sasl_or_503(user.username)  # revoke AUTH before removing bookkeeping — fail closed
    db.delete(user)  # cascades user_sender_permissions (ondelete=CASCADE)
    db.commit()


@router.get("/{user_id}/connection-details", response_model=ConnectionDetails)
def connection_details(user_id: int, db: Session = Depends(get_db)) -> ConnectionDetails:
    user = _get_or_404(db, user_id)
    settings = get_settings()
    addresses = (
        db.query(Sender.address)
        .join(UserSenderPermission, UserSenderPermission.sender_id == Sender.id)
        .filter(UserSenderPermission.local_smtp_user_id == user_id, Sender.enabled.is_(True))
        .order_by(Sender.address)
        .all()
    )
    return ConnectionDetails(
        host=settings.submission_host,
        port=settings.submission_port,
        tls_mode="STARTTLS",
        username=user.username,
        from_addresses=[a for (a,) in addresses],
    )


@router.get("/{user_id}/permissions", response_model=UserPermissionsView)
def get_permissions(user_id: int, db: Session = Depends(get_db)) -> UserPermissionsView:
    user = _get_or_404(db, user_id)
    granted_ids = {
        sid
        for (sid,) in db.query(UserSenderPermission.sender_id).filter(
            UserSenderPermission.local_smtp_user_id == user_id
        )
    }
    senders = db.query(Sender).order_by(Sender.address).all()
    return UserPermissionsView(
        user=_to_read(db, user),
        senders=[
            PermissionListEntry(id=s.id, address=s.address, allowed=s.id in granted_ids) for s in senders
        ],
    )


@router.put(
    "/{user_id}/permissions/{sender_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
def grant(
    user_id: int,
    sender_id: int,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> None:
    _get_or_404(db, user_id)
    if db.get(Sender, sender_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sender not found")
    grant_permission(db, local_smtp_user_id=user_id, sender_id=sender_id, granted_by_admin_id=admin.id)


@router.delete(
    "/{user_id}/permissions/{sender_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
def revoke(user_id: int, sender_id: int, db: Session = Depends(get_db)) -> None:
    _get_or_404(db, user_id)
    revoke_permission(db, local_smtp_user_id=user_id, sender_id=sender_id)
