import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_admin_optional, get_db, require_csrf
from app.config import get_settings
from app.core.clock import utcnow
from app.core.csrf import CSRF_COOKIE_NAME, generate_csrf_token
from app.core.encryption import DecryptionFailed, EncryptionKeyNotConfigured, decrypt_secret
from app.core.rate_limit import check_rate_limit, record_login_attempt
from app.core.security import hash_password, verify_password
from app.core.sessions import create_session, revoke_session
from app.models.admin import AdminUser
from app.schemas.auth import LoginRequest, LoginResponse, SessionInfo, SetupRequest, SetupRequiredResponse

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

SESSION_COOKIE_NAME = "session"

# A fixed, never-matching hash to run Argon2 verification against when the
# email doesn't correspond to a real account — keeps unknown-email login
# attempts taking roughly the same time as a real wrong-password attempt,
# so a timing side-channel can't be used to enumerate valid admin emails.
_DUMMY_HASH = hash_password("this-is-not-a-real-password-just-a-timing-decoy")


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _issue_session_cookies(response: Response, db: Session, admin: AdminUser, request: Request) -> None:
    """Shared by login's success path and /setup's bootstrap-and-log-in
    path — both end the same way: a fresh session + CSRF cookie pair."""
    raw_token = create_session(db, admin, _client_ip(request), request.headers.get("user-agent"))
    db.commit()
    response.set_cookie(
        SESSION_COOKIE_NAME,
        raw_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=settings.session_ttl_seconds,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        generate_csrf_token(),
        httponly=False,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=settings.session_ttl_seconds,
        path="/",
    )


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse:
    ip_address = _client_ip(request)
    admin = db.query(AdminUser).filter(AdminUser.email == payload.email).one_or_none()
    admin_id = admin.id if admin else None

    status_check = check_rate_limit(db, admin_user_id=admin_id, ip_address=ip_address)
    if status_check.locked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "message": "Too many attempts. Try again later.",
                "retry_after_seconds": status_check.retry_after_seconds,
            },
        )

    password_ok = verify_password(admin.password_hash if admin else _DUMMY_HASH, payload.password)
    account_usable = admin is not None and admin.is_active and password_ok

    if not account_usable:
        record_login_attempt(
            db, email=payload.email, admin_user_id=admin_id, ip_address=ip_address, success=False
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    if admin.totp_secret_encrypted is not None:
        if not payload.totp_code:
            # First phase of a two-step login — password was correct, but
            # no code was submitted yet. Not itself a failed attempt (the
            # frontend's "totp" stage is about to ask for one), so this
            # doesn't count against the rate limiter.
            return LoginResponse(totp_required=True)

        try:
            secret = decrypt_secret(admin.totp_secret_encrypted)
        except (EncryptionKeyNotConfigured, DecryptionFailed) as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

        if not pyotp.TOTP(secret).verify(payload.totp_code, valid_window=1):
            # Brute-forcing the code is covered by the same rate limiter as
            # brute-forcing the password — this is the only place a wrong
            # TOTP code is actually checked, so without this the "totp
            # required" step would have offered zero real protection.
            record_login_attempt(
                db, email=payload.email, admin_user_id=admin.id, ip_address=ip_address, success=False
            )
            db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication code")

    admin.last_login_at = utcnow()
    record_login_attempt(
        db, email=payload.email, admin_user_id=admin.id, ip_address=ip_address, success=True
    )
    _issue_session_cookies(response, db, admin, request)
    return LoginResponse(totp_required=False, email=admin.email)


@router.post("/logout", dependencies=[Depends(require_csrf)])
def logout(
    request: Request,
    response: Response,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token:
        revoke_session(db, session_token)
        db.commit()
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/session", response_model=SessionInfo)
def session_info(admin: AdminUser | None = Depends(get_current_admin_optional)) -> SessionInfo:
    if admin is None:
        return SessionInfo(authenticated=False)
    return SessionInfo(authenticated=True, email=admin.email)


@router.get("/setup-required", response_model=SetupRequiredResponse)
def setup_required(db: Session = Depends(get_db)) -> SetupRequiredResponse:
    """Public and unauthenticated by design — the frontend needs this
    answer *before* anyone can possibly be logged in yet, to decide
    whether to route a fresh visitor to /setup or /login."""
    return SetupRequiredResponse(setup_required=db.query(AdminUser).count() == 0)


@router.post("/setup", response_model=LoginResponse)
def setup(payload: SetupRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> LoginResponse:
    """Creates the first admin account and logs them straight in — the
    only way to bootstrap an admin without shelling into the container to
    run `relay create-admin` (Stage 1's CLI-only path). Gated strictly on
    "no admin exists yet" so this can never become a second, ongoing
    account-creation backdoor once a relay is actually set up. (A
    concurrent double-submit racing past this check is an accepted,
    negligible risk for a one-time, single-operator, first-run action —
    not something worth a DB-level lock for.)"""
    if db.query(AdminUser).count() > 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Setup has already been completed")

    admin = AdminUser(email=payload.email, password_hash=hash_password(payload.password))
    db.add(admin)
    db.flush()
    admin.last_login_at = utcnow()
    _issue_session_cookies(response, db, admin, request)
    return LoginResponse(totp_required=False, email=admin.email)
