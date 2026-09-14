from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.csrf import CSRF_COOKIE_NAME, csrf_valid
from app.core.sessions import get_session_by_token
from app.db.session import get_db
from app.models.admin import AdminUser


def get_current_admin_optional(
    request: Request,
    db: Session = Depends(get_db),
    session: str | None = Cookie(default=None),
) -> AdminUser | None:
    admin_session = get_session_by_token(db, session or "")
    if admin_session is None:
        return None
    admin = admin_session.admin_user
    if not admin.is_active:
        return None
    request.state.session_token = session
    return admin


def get_current_admin(
    admin: AdminUser | None = Depends(get_current_admin_optional),
) -> AdminUser:
    if admin is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return admin


def require_csrf(
    csrf_cookie: str | None = Cookie(default=None, alias=CSRF_COOKIE_NAME),
    csrf_header: str | None = Header(default=None, alias="x-csrf-token"),
) -> None:
    if not csrf_valid(csrf_cookie, csrf_header):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF check failed")
