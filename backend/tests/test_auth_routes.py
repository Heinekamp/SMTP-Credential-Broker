import pyotp
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.encryption import encrypt_secret
from app.core.security import hash_password
from app.models.admin import AdminUser

EMAIL = "admin@example.com"
PASSWORD = "correct horse battery staple"


def _make_admin(db_session: Session, totp_secret: str | None = None) -> AdminUser:
    admin = AdminUser(
        email=EMAIL,
        password_hash=hash_password(PASSWORD),
        totp_secret_encrypted=encrypt_secret(totp_secret) if totp_secret else None,
    )
    db_session.add(admin)
    db_session.commit()
    return admin


def test_session_is_unauthenticated_before_login(client: TestClient) -> None:
    response = client.get("/api/auth/session")
    assert response.status_code == 200
    assert response.json() == {"authenticated": False, "email": None}


def test_login_with_wrong_password_is_generic_401(client: TestClient, db_session: Session) -> None:
    _make_admin(db_session)
    response = client.post("/api/auth/login", json={"email": EMAIL, "password": "wrong"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_login_with_unknown_email_is_the_same_generic_401(client: TestClient, db_session: Session) -> None:
    response = client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "whatever"}
    )
    assert response.status_code == 401
    # Identical message and status for "wrong password" and "no such
    # account" — must never reveal which part was wrong (design constraint
    # in claude-design-prompt.md's Login screen spec).
    assert response.json()["detail"] == "Invalid email or password"


def test_successful_login_sets_cookies_and_session(client: TestClient, db_session: Session) -> None:
    _make_admin(db_session)
    response = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["totp_required"] is False
    assert body["email"] == EMAIL

    assert "session" in response.cookies
    assert "csrf_token" in response.cookies

    session_response = client.get("/api/auth/session")
    assert session_response.json() == {"authenticated": True, "email": EMAIL}


def test_logout_requires_csrf_header(client: TestClient, db_session: Session) -> None:
    _make_admin(db_session)
    client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})

    response = client.post("/api/auth/logout")
    assert response.status_code == 403


def test_logout_with_csrf_header_revokes_session(client: TestClient, db_session: Session) -> None:
    _make_admin(db_session)
    client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    csrf_token = client.cookies.get("csrf_token")

    response = client.post("/api/auth/logout", headers={"x-csrf-token": csrf_token})
    assert response.status_code == 200

    session_response = client.get("/api/auth/session")
    assert session_response.json()["authenticated"] is False


def test_login_with_totp_enabled_and_no_code_returns_totp_required(client: TestClient, db_session: Session) -> None:
    secret = pyotp.random_base32()
    _make_admin(db_session, totp_secret=secret)
    response = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 200
    assert response.json() == {"totp_required": True, "email": None}
    # No session was actually issued — see security-model.md §5.
    assert "session" not in response.cookies


def test_login_with_wrong_totp_code_is_401_and_never_reaches_the_dashboard(
    client: TestClient, db_session: Session
) -> None:
    secret = pyotp.random_base32()
    _make_admin(db_session, totp_secret=secret)
    response = client.post(
        "/api/auth/login", json={"email": EMAIL, "password": PASSWORD, "totp_code": "000000"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid authentication code"
    assert "session" not in response.cookies


def test_login_with_correct_totp_code_succeeds(client: TestClient, db_session: Session) -> None:
    secret = pyotp.random_base32()
    _make_admin(db_session, totp_secret=secret)
    code = pyotp.TOTP(secret).now()
    response = client.post(
        "/api/auth/login", json={"email": EMAIL, "password": PASSWORD, "totp_code": code}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["totp_required"] is False
    assert body["email"] == EMAIL
    assert "session" in response.cookies


def test_wrong_totp_codes_are_rate_limited_like_wrong_passwords(
    client: TestClient, db_session: Session
) -> None:
    secret = pyotp.random_base32()
    _make_admin(db_session, totp_secret=secret)
    last_response = None
    for _ in range(6):
        last_response = client.post(
            "/api/auth/login", json={"email": EMAIL, "password": PASSWORD, "totp_code": "000000"}
        )
    assert last_response.status_code == 429


def test_repeated_failed_logins_trigger_rate_limit(client: TestClient, db_session: Session) -> None:
    _make_admin(db_session)
    last_response = None
    for _ in range(6):
        last_response = client.post("/api/auth/login", json={"email": EMAIL, "password": "wrong"})

    assert last_response.status_code == 429
    detail = last_response.json()["detail"]
    assert detail["retry_after_seconds"] > 0


def test_lockout_blocks_further_attempts_from_the_same_client(
    client: TestClient, db_session: Session
) -> None:
    _make_admin(db_session)
    for _ in range(6):
        response = client.post("/api/auth/login", json={"email": EMAIL, "password": "wrong"})

    # By the 6th attempt the per-IP threshold (5) has been crossed — every
    # request in this test shares TestClient's single fixed client address,
    # which is exactly the scenario the per-IP counter exists to catch (a
    # spray of attempts from one source, architecture.md's rate-limit
    # design). Per-account/per-IP *isolation* — a different account or a
    # different source IP being unaffected — is covered directly against
    # core/rate_limit.py in test_rate_limit.py, where each IP can actually
    # be controlled.
    assert response.status_code == 429


def test_concurrent_wrong_logins_cannot_exceed_the_lockout(tmp_path, monkeypatch) -> None:
    """Regression test for #157: the rate-limit check used to run before
    the slow Argon2 verify with nothing serializing them, so a burst of
    parallel attempts all passed the check before any failure was counted
    — about 40 guesses per lockout window instead of 5. Each request gets
    its own DB session here (the shared `client` fixture's single session
    isn't thread-safe), and verify is slowed down to make the race wide."""
    import time
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.api import deps
    from app.api.routes import auth as auth_routes
    from app.db.base import Base
    from app.main import app

    engine = create_engine(f"sqlite:///{tmp_path / 'race.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with session_factory() as setup_session:
        setup_session.add(AdminUser(email=EMAIL, password_hash=hash_password(PASSWORD)))
        setup_session.commit()

    def _per_request_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    real_verify = auth_routes.verify_password

    def _slow_verify(password_hash: str, password: str) -> bool:
        time.sleep(0.05)
        return real_verify(password_hash, password)

    monkeypatch.setattr(auth_routes, "verify_password", _slow_verify)
    app.dependency_overrides[deps.get_db] = _per_request_session
    try:
        with TestClient(app) as concurrent_client, ThreadPoolExecutor(max_workers=20) as pool:
            codes = list(
                pool.map(
                    lambda _: concurrent_client.post(
                        "/api/auth/login", json={"email": EMAIL, "password": "wrong"}
                    ).status_code,
                    range(20),
                )
            )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert codes.count(401) == 5, codes
    assert codes.count(429) == 15, codes
