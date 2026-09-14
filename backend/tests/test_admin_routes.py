from fastapi.testclient import TestClient

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


def test_change_own_password_wrong_current_password_is_401(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/admins/me/change-password",
        json={"current_password": "definitely-wrong", "new_password": "New-Sup3rSecret!"},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 401
