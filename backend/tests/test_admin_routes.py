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
        json={"secret": enroll["secret"], "code": "000000"},
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
        json={"secret": enroll["secret"], "code": code},
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
        json={"secret": enroll["secret"], "code": code},
        headers=csrf_headers(admin_client),
    )

    response = admin_client.post("/api/admins/me/totp/remove", headers=csrf_headers(admin_client))
    assert response.status_code == 204


def test_totp_remove_revokes_other_sessions_but_keeps_this_one(admin_client: TestClient) -> None:
    enroll = admin_client.post("/api/admins/me/totp/enroll", headers=csrf_headers(admin_client)).json()
    code = pyotp.TOTP(enroll["secret"]).now()
    admin_client.post(
        "/api/admins/me/totp/confirm",
        json={"secret": enroll["secret"], "code": code},
        headers=csrf_headers(admin_client),
    )

    other_client = TestClient(app)
    login = other_client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "totp_code": code}
    )
    assert login.status_code == 200
    assert other_client.get("/api/admins").status_code == 200

    response = admin_client.post("/api/admins/me/totp/remove", headers=csrf_headers(admin_client))
    assert response.status_code == 204

    assert other_client.get("/api/admins").status_code == 401
    assert admin_client.get("/api/admins").status_code == 200

    admins = admin_client.get("/api/admins").json()
    me = next(a for a in admins if a["email"] == ADMIN_EMAIL)
    assert me["totp_enabled"] is False
