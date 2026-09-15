from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_db
from app.core.csv_export import csv_response
from app.models.local_user import LocalSmtpUser, UserSenderPermission
from app.models.sender import Sender
from app.models.upstream import UpstreamAccount

router = APIRouter(prefix="/exports", tags=["exports"], dependencies=[Depends(get_current_admin)])


@router.get("/senders.csv")
def export_senders_csv(db: Session = Depends(get_db)) -> Response:
    accounts = {a.id: a for a in db.query(UpstreamAccount).all()}
    senders = db.query(Sender).order_by(Sender.address).all()
    counts = dict(
        db.query(UserSenderPermission.sender_id, func.count()).group_by(UserSenderPermission.sender_id).all()
    )
    rows = [
        [
            s.address,
            accounts[s.upstream_account_id].name if s.upstream_account_id in accounts else "",
            "yes" if s.enabled else "no",
            counts.get(s.id, 0),
            s.description or "",
        ]
        for s in senders
    ]
    return csv_response(
        "senders.csv",
        ["address", "upstream_account", "enabled", "allowed_local_user_count", "description"],
        rows,
    )


@router.get("/local-users.csv")
def export_local_users_csv(db: Session = Depends(get_db)) -> Response:
    users = db.query(LocalSmtpUser).order_by(LocalSmtpUser.name).all()
    counts = dict(
        db.query(UserSenderPermission.local_smtp_user_id, func.count())
        .group_by(UserSenderPermission.local_smtp_user_id)
        .all()
    )
    rows = [
        [
            u.name,
            u.username,
            "yes" if u.enabled else "no",
            counts.get(u.id, 0),
            u.password_last_rotated_at.isoformat() if u.password_last_rotated_at else "",
        ]
        for u in users
    ]
    return csv_response(
        "local-users.csv",
        ["name", "username", "enabled", "allowed_sender_count", "password_last_rotated_at"],
        rows,
    )


@router.get("/permissions.csv")
def export_permissions_csv(db: Session = Depends(get_db)) -> Response:
    """One row per active grant — the permission matrix flattened rather
    than pivoted, since a spreadsheet can pivot it back if wanted and a
    flat list stays simple regardless of how many senders/local users
    exist."""
    granted = (
        db.query(Sender.address, LocalSmtpUser.name, LocalSmtpUser.username, UserSenderPermission.granted_at)
        .join(UserSenderPermission, UserSenderPermission.sender_id == Sender.id)
        .join(LocalSmtpUser, LocalSmtpUser.id == UserSenderPermission.local_smtp_user_id)
        .order_by(Sender.address, LocalSmtpUser.name)
        .all()
    )
    rows = [[address, name, username, granted_at.isoformat()] for address, name, username, granted_at in granted]
    return csv_response(
        "permissions.csv",
        ["sender_address", "local_user_name", "local_user_username", "granted_at"],
        rows,
    )
