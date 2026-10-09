import time

import pyotp
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, csrf_headers


def test_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/admins").status_code == 401


def test_list_includes_the_logged_in_admin(admin_client: TestClient) -> None:
    response = admin_client.get("/api/admins")
    assert response.status_code == 200
    emails = [a["email"] for a in response.json()]
    assert ADMIN_EMAIL in emails
    admin = next(a for a in response.json() if a["email"] == ADMIN_EMAIL)
    assert admin["totp_enabled"] is False
    assert "password_hash" not in admin


def test_create_admin(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/admins",
        json={"email": "second@example.com", "password": "Sup3rSecret!"},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 201
    assert response.json()["email"] == "second@example.com"


def test_create_admin_duplicate_email_is_409(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/admins",
        json={"email": ADMIN_EMAIL, "password": "Sup3rSecret!"},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 409


def test_create_admin_requires_csrf(admin_client: TestClient) -> None:
    response = admin_client.post("/api/admins", json={"email": "third@example.com", "password": "x"})
    assert response.status_code == 403


def test_deactivate_and_reactivate_another_admin(admin_client: TestClient) -> None:
    created = admin_client.post(
        "/api/admins",
        json={"email": "second@example.com", "password": "Sup3rSecret!"},
        headers=csrf_headers(admin_client),
    ).json()

    response = admin_client.patch(
        f"/api/admins/{created['id']}", json={"is_active": False}, headers=csrf_headers(admin_client)
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    response = admin_client.patch(
        f"/api/admins/{created['id']}", json={"is_active": True}, headers=csrf_headers(admin_client)
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is True


def test_deactivating_the_last_active_admin_is_409(admin_client: TestClient) -> None:
    me = next(a for a in admin_client.get("/api/admins").json() if a["email"] == ADMIN_EMAIL)

    response = admin_client.patch(
        f"/api/admins/{me['id']}", json={"is_active": False}, headers=csrf_headers(admin_client)
    )
    assert response.status_code == 409


def test_deactivating_one_of_two_active_admins_is_allowed(admin_client: TestClient) -> None:
    created = admin_client.post(
        "/api/admins",
        json={"email": "second@example.com", "password": "Sup3rSecret!"},
        headers=csrf_headers(admin_client),
    ).json()

    response = admin_client.patch(
        f"/api/admins/{created['id']}", json={"is_active": False}, headers=csrf_headers(admin_client)
    )
    assert response.status_code == 200

    # Now only the original admin is active — deactivating them, too,
    # must be rejected.
    me = next(a for a in admin_client.get("/api/admins").json() if a["email"] == ADMIN_EMAIL)
    response = admin_client.patch(
        f"/api/admins/{me['id']}", json={"is_active": False}, headers=csrf_headers(admin_client)
    )
    assert response.status_code == 409


def test_deactivating_an_admin_revokes_their_sessions(admin_client: TestClient) -> None:
    created = admin_client.post(
        "/api/admins",
        json={"email": "second@example.com", "password": "Sup3rSecret!"},
        headers=csrf_headers(admin_client),
    ).json()

    other_client = TestClient(app)
    login = other_client.post("/api/auth/login", json={"email": "second@example.com", "password": "Sup3rSecret!"})
    assert login.status_code == 200
    assert other_client.get("/api/admins").status_code == 200

    admin_client.patch(f"/api/admins/{created['id']}", json={"is_active": False}, headers=csrf_headers(admin_client))

    assert other_client.get("/api/admins").status_code == 401


def test_deactivated_admin_cannot_log_back_in(admin_client: TestClient) -> None:
    created = admin_client.post(
        "/api/admins",
        json={"email": "second@example.com", "password": "Sup3rSecret!"},
        headers=csrf_headers(admin_client),
    ).json()
    admin_client.patch(f"/api/admins/{created['id']}", json={"is_active": False}, headers=csrf_headers(admin_client))

    other_client = TestClient(app)
    login = other_client.post("/api/auth/login", json={"email": "second@example.com", "password": "Sup3rSecret!"})
    assert login.status_code == 401


def test_update_missing_admin_is_404(admin_client: TestClient) -> None:
    response = admin_client.patch("/api/admins/999999", json={"is_active": False}, headers=csrf_headers(admin_client))
    assert response.status_code == 404


def test_update_admin_requires_csrf(admin_client: TestClient) -> None:
    response = admin_client.patch("/api/admins/1", json={"is_active": False})
    assert response.status_code == 403


def test_change_own_password(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/admins/me/change-password",
        json={"current_password": ADMIN_PASSWORD, "new_password": "New-Sup3rSecret!"},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 204

    # The old password no longer works; the new one does.
    admin_client.post("/api/auth/logout", headers=csrf_headers(admin_client))
    failed = admin_client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert failed.status_code == 401
    succeeded = admin_client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": "New-Sup3rSecret!"}
    )
    assert succeeded.status_code == 200


def test_change_own_password_revokes_other_sessions_but_keeps_this_one(admin_client: TestClient) -> None:
    """Regression test: a session cookie stolen before a password change
    used to keep working after it — nothing correlated sessions to the
    admin row and revoked them on a credential change. The session that
    made the change itself must survive, though, or the admin would be
    logged out by their own password change."""
    other_client = TestClient(app)
    login = other_client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert login.status_code == 200
    assert other_client.get("/api/admins").status_code == 200

    response = admin_client.post(
        "/api/admins/me/change-password",
        json={"current_password": ADMIN_PASSWORD, "new_password": "New-Sup3rSecret!"},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 204

    assert other_client.get("/api/admins").status_code == 401
    assert admin_client.get("/api/admins").status_code == 200


def test_change_own_password_wrong_current_password_is_401(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/admins/me/change-password",
        json={"current_password": "definitely-wrong", "new_password": "New-Sup3rSecret!"},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 401


def test_totp_enroll_persists_nothing(admin_client: TestClient) -> None:
    response = admin_client.post("/api/admins/me/totp/enroll", headers=csrf_headers(admin_client))
    assert response.status_code == 200
    body = response.json()
    assert "secret" in body
    assert body["otpauth_uri"].startswith("otpauth://totp/")

    admins = admin_client.get("/api/admins").json()
    me = next(a for a in admins if a["email"] == ADMIN_EMAIL)
    assert me["totp_enabled"] is False  # enroll alone must not enable it


def test_totp_confirm_with_wrong_code_is_401_and_does_not_enable(admin_client: TestClient) -> None:
    enroll = admin_client.post("/api/admins/me/totp/enroll", headers=csrf_headers(admin_client)).json()
    response = admin_client.post(
        "/api/admins/me/totp/confirm",
        json={"secret": enroll["secret"], "code": "000000", "current_password": ADMIN_PASSWORD},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 401

    admins = admin_client.get("/api/admins").json()
    me = next(a for a in admins if a["email"] == ADMIN_EMAIL)
    assert me["totp_enabled"] is False


def test_totp_confirm_with_correct_code_enables_it(admin_client: TestClient) -> None:
    enroll = admin_client.post("/api/admins/me/totp/enroll", headers=csrf_headers(admin_client)).json()
    code = pyotp.TOTP(enroll["secret"]).now()
    response = admin_client.post(
        "/api/admins/me/totp/confirm",
        json={"secret": enroll["secret"], "code": code, "current_password": ADMIN_PASSWORD},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 204

    admins = admin_client.get("/api/admins").json()
    me = next(a for a in admins if a["email"] == ADMIN_EMAIL)
    assert me["totp_enabled"] is True


def test_totp_remove_disables_it(admin_client: TestClient) -> None:
    enroll = admin_client.post("/api/admins/me/totp/enroll", headers=csrf_headers(admin_client)).json()
    code = pyotp.TOTP(enroll["secret"]).now()
    admin_client.post(
        "/api/admins/me/totp/confirm",
        json={"secret": enroll["secret"], "code": code, "current_password": ADMIN_PASSWORD},
        headers=csrf_headers(admin_client),
    )

    response = admin_client.post(
        "/api/admins/me/totp/remove",
        json={"current_password": ADMIN_PASSWORD},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 204


def test_totp_remove_revokes_other_sessions_but_keeps_this_one(admin_client: TestClient) -> None:
    enroll = admin_client.post("/api/admins/me/totp/enroll", headers=csrf_headers(admin_client)).json()
    code = pyotp.TOTP(enroll["secret"]).now()
    admin_client.post(
        "/api/admins/me/totp/confirm",
        json={"secret": enroll["secret"], "code": code, "current_password": ADMIN_PASSWORD},
        headers=csrf_headers(admin_client),
    )

    # The enrolment code is spent (#169's replay protection) — log in with
    # the next step's code, still inside the accepted drift window.
    next_code = pyotp.TOTP(enroll["secret"]).at(int(time.time()) + 30)
    other_client = TestClient(app)
    login = other_client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "totp_code": next_code}
    )
    assert login.status_code == 200
    assert other_client.get("/api/admins").status_code == 200

    response = admin_client.post(
        "/api/admins/me/totp/remove",
        json={"current_password": ADMIN_PASSWORD},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 204

    assert other_client.get("/api/admins").status_code == 401
    assert admin_client.get("/api/admins").status_code == 200

    admins = admin_client.get("/api/admins").json()
    me = next(a for a in admins if a["email"] == ADMIN_EMAIL)
    assert me["totp_enabled"] is False


# ── Account-security re-authentication and limits (#169) ──────────────


def _enable_totp(client: TestClient) -> str:
    enroll = client.post("/api/admins/me/totp/enroll", headers=csrf_headers(client)).json()
    response = client.post(
        "/api/admins/me/totp/confirm",
        json={
            "secret": enroll["secret"],
            "code": pyotp.TOTP(enroll["secret"]).now(),
            "current_password": ADMIN_PASSWORD,
        },
        headers=csrf_headers(client),
    )
    assert response.status_code == 204
    return enroll["secret"]


def _totp_enabled(client: TestClient) -> bool:
    return next(a for a in client.get("/api/admins").json() if a["email"] == ADMIN_EMAIL)["totp_enabled"]


def test_totp_remove_requires_the_current_password(admin_client: TestClient) -> None:
    """A stolen session alone must not be able to strip the second factor."""
    _enable_totp(admin_client)
    no_password = admin_client.post("/api/admins/me/totp/remove", json={}, headers=csrf_headers(admin_client))
    assert no_password.status_code == 422
    wrong = admin_client.post(
        "/api/admins/me/totp/remove", json={"current_password": "wrong"}, headers=csrf_headers(admin_client)
    )
    assert wrong.status_code == 401
    assert _totp_enabled(admin_client) is True


def test_totp_confirm_requires_the_current_password(admin_client: TestClient) -> None:
    """A stolen session alone must not be able to enrol its own authenticator."""
    enroll = admin_client.post("/api/admins/me/totp/enroll", headers=csrf_headers(admin_client)).json()
    response = admin_client.post(
        "/api/admins/me/totp/confirm",
        json={"secret": enroll["secret"], "code": pyotp.TOTP(enroll["secret"]).now(), "current_password": "wrong"},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 401
    assert _totp_enabled(admin_client) is False


def test_totp_confirm_rejects_a_malformed_secret(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/admins/me/totp/confirm",
        json={"secret": "!!", "code": "123456", "current_password": ADMIN_PASSWORD},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 422


def test_a_totp_code_cannot_be_used_for_two_logins(admin_client: TestClient) -> None:
    secret = _enable_totp(admin_client)
    code = pyotp.TOTP(secret).at(int(time.time()) + 30)  # unspent: enrolment used the current step
    first = TestClient(app).post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "totp_code": code}
    )
    assert first.status_code == 200
    replay = TestClient(app).post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "totp_code": code}
    )
    assert replay.status_code == 401


def test_wrong_current_passwords_are_rate_limited(admin_client: TestClient) -> None:
    """change-password used to be an unthrottled password-guessing oracle
    for anyone holding a session."""
    codes = [
        admin_client.post(
            "/api/admins/me/change-password",
            json={"current_password": "wrong", "new_password": "New-Sup3rSecret!"},
            headers=csrf_headers(admin_client),
        ).status_code
        for _ in range(6)
    ]
    assert codes[:5] == [401] * 5
    assert codes[5] == 429


def test_new_admin_passwords_need_twelve_characters(admin_client: TestClient) -> None:
    short = "Short-1!"
    change = admin_client.post(
        "/api/admins/me/change-password",
        json={"current_password": ADMIN_PASSWORD, "new_password": short},
        headers=csrf_headers(admin_client),
    )
    assert change.status_code == 422
    create = admin_client.post(
        "/api/admins", json={"email": "new@example.com", "password": short}, headers=csrf_headers(admin_client)
    )
    assert create.status_code == 422


def test_two_admins_deactivating_each_other_concurrently_leave_one_active(tmp_path, monkeypatch) -> None:
    """Regression test for #199: both requests used to count two active
    admins and both proceed, leaving none — recoverable only from the CLI."""
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.api import deps
    from app.api.routes import admins as admin_routes
    from app.core.security import hash_password
    from app.db.base import Base
    from app.models.admin import AdminUser

    engine = create_engine(f"sqlite:///{tmp_path / 'admins.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    credentials = {"a@example.com": "Admin-Passw0rd-A", "b@example.com": "Admin-Passw0rd-B"}
    with session_factory() as setup:
        setup.add_all(AdminUser(email=email, password_hash=hash_password(pw)) for email, pw in credentials.items())
        setup.commit()

    def _per_request_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    real_revoke = admin_routes.revoke_all_sessions_for_admin

    def _slow_revoke(*args, **kwargs):
        time.sleep(0.2)  # widen the check-then-act window
        return real_revoke(*args, **kwargs)

    monkeypatch.setattr(admin_routes, "revoke_all_sessions_for_admin", _slow_revoke)
    app.dependency_overrides[deps.get_db] = _per_request_session
    try:
        with TestClient(app) as a, TestClient(app) as b:
            for client, email in ((a, "a@example.com"), (b, "b@example.com")):
                login = client.post("/api/auth/login", json={"email": email, "password": credentials[email]})
                assert login.status_code == 200
            ids = {admin["email"]: admin["id"] for admin in a.get("/api/admins").json()}

            def _deactivate(client: TestClient, target_id: int) -> int:
                return client.patch(
                    f"/api/admins/{target_id}", json={"is_active": False}, headers=csrf_headers(client)
                ).status_code

            jobs = [(a, ids["b@example.com"]), (b, ids["a@example.com"])]
            with ThreadPoolExecutor(max_workers=2) as pool:
                codes = sorted(pool.map(lambda job: _deactivate(*job), jobs))
    finally:
        app.dependency_overrides.clear()

    with session_factory() as check:
        assert check.query(AdminUser).filter(AdminUser.is_active.is_(True)).count() == 1
    assert codes == [200, 409]
    engine.dispose()
