from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_db, require_csrf
from app.core.audit import client_ip, record_audit
from app.core.encryption import DecryptionFailed, EncryptionKeyNotConfigured, decrypt_secret, encrypt_secret
from app.core.test_connection import test_upstream_connection
from app.core.upstream_testing import apply_test_result
from app.models.admin import AdminUser
from app.models.sender import Sender
from app.models.upstream import UpstreamAccount
from app.schemas.upstream import (
    DeletePrecheck,
    TestConnectionResponse,
    TestConnectionStep,
    UpstreamAccountCreate,
    UpstreamAccountRead,
    UpstreamAccountUpdate,
)

router = APIRouter(
    prefix="/upstream-accounts",
    tags=["upstream-accounts"],
    dependencies=[Depends(get_current_admin)],
)


def _get_or_404(db: Session, account_id: int) -> UpstreamAccount:
    account = db.get(UpstreamAccount, account_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upstream account not found")
    return account


def _encrypt_or_503(password: str) -> bytes:
    try:
        return encrypt_secret(password)
    except EncryptionKeyNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.get("", response_model=list[UpstreamAccountRead])
def list_accounts(db: Session = Depends(get_db)) -> list[UpstreamAccount]:
    return db.query(UpstreamAccount).order_by(UpstreamAccount.name).all()


@router.post(
    "",
    response_model=UpstreamAccountRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_account(
    payload: UpstreamAccountCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> UpstreamAccount:
    account = UpstreamAccount(
        name=payload.name,
        host=payload.host,
        port=payload.port,
        tls_mode=payload.tls_mode,
        username=payload.username,
        encrypted_password=_encrypt_or_503(payload.password),
    )
    db.add(account)
    db.flush()
    record_audit(
        db,
        admin_user_id=admin.id,
        action="upstream_account.create",
        target_type="upstream_account",
        target_id=account.id,
        detail={"name": account.name, "host": account.host},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(account)
    return account


@router.get("/{account_id}", response_model=UpstreamAccountRead)
def get_account(account_id: int, db: Session = Depends(get_db)) -> UpstreamAccount:
    return _get_or_404(db, account_id)


@router.patch("/{account_id}", response_model=UpstreamAccountRead, dependencies=[Depends(require_csrf)])
def update_account(
    account_id: int,
    payload: UpstreamAccountUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> UpstreamAccount:
    account = _get_or_404(db, account_id)
    data = payload.model_dump(exclude_unset=True)
    password = data.pop("password", None)
    for field, value in data.items():
        setattr(account, field, value)
    if password:
        account.encrypted_password = _encrypt_or_503(password)
    changed_fields = sorted([*data.keys(), *(["password"] if password else [])])
    record_audit(
        db,
        admin_user_id=admin.id,
        action="upstream_account.update",
        target_type="upstream_account",
        target_id=account.id,
        # Never the password itself — only which fields changed.
        detail={"fields": changed_fields},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(account)
    return account


@router.get("/{account_id}/delete-precheck", response_model=DeletePrecheck)
def delete_precheck(account_id: int, db: Session = Depends(get_db)) -> DeletePrecheck:
    _get_or_404(db, account_id)
    addresses = [
        sender.address
        for sender in db.query(Sender).filter(Sender.upstream_account_id == account_id).all()
    ]
    return DeletePrecheck(dependent_sender_addresses=addresses)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)])
def delete_account(
    account_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin),
) -> None:
    account = _get_or_404(db, account_id)
    name = account.name
    db.delete(account)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This account is still referenced by one or more senders. "
            "Reassign or delete those senders first.",
        ) from exc
    # A separate commit, deliberately after the delete has already
    # succeeded — auditing a delete that got rolled back (e.g. the
    # IntegrityError above) would be recording something that never
    # actually happened.
    record_audit(
        db,
        admin_user_id=admin.id,
        action="upstream_account.delete",
        target_type="upstream_account",
        target_id=account_id,
        detail={"name": name},
        ip_address=client_ip(request),
    )
    db.commit()


@router.post(
    "/{account_id}/test-connection",
    response_model=TestConnectionResponse,
    dependencies=[Depends(require_csrf)],
)
def test_connection(account_id: int, db: Session = Depends(get_db)) -> TestConnectionResponse:
    """Diagnostic only — DNS/TCP/TLS/greeting/AUTH, never a message send
    (spec §15). Persists the result onto the account for the list/dashboard
    views, same as a real "Test connection" click would."""
    account = _get_or_404(db, account_id)
    try:
        password = decrypt_secret(account.encrypted_password)
    except (EncryptionKeyNotConfigured, DecryptionFailed) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    result = test_upstream_connection(
        host=account.host,
        port=account.port,
        tls_mode=account.tls_mode,
        username=account.username,
        password=password,
    )

    apply_test_result(account, result)
    db.commit()

    return TestConnectionResponse(
        success=result.success,
        steps=[TestConnectionStep(name=s.name, passed=s.passed, detail=s.detail) for s in result.steps],
    )
