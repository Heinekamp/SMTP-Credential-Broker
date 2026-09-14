from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.admin import AdminUser


def test_setup_required_true_when_no_admin_exists(client: TestClient) -> None:
    response = client.get("/api/auth/setup-required")
    assert response.status_code == 200
    assert response.json() == {"setup_required": True}


def test_setup_required_false_once_an_admin_exists(client: TestClient, db_session: Session) -> None:
    db_session.add(AdminUser(email="admin@example.com", password_hash=hash_password("x")))
    db_session.commit()

    response = client.get("/api/auth/setup-required")
    assert response.json() == {"setup_required": False}


def test_setup_creates_admin_and_logs_them_in(client: TestClient) -> None:
    response = client.post("/api/auth/setup", json={"email": "admin@example.com", "password": "Sup3rSecret!"})
    assert response.status_code == 200
    assert response.json()["email"] == "admin@example.com"
    assert "session" in response.cookies
    assert "csrf_token" in response.cookies

    session_response = client.get("/api/auth/session")
    assert session_response.json() == {"authenticated": True, "email": "admin@example.com"}


def test_setup_refuses_once_an_admin_already_exists(client: TestClient, db_session: Session) -> None:
    db_session.add(AdminUser(email="existing@example.com", password_hash=hash_password("x")))
    db_session.commit()

    response = client.post("/api/auth/setup", json={"email": "second@example.com", "password": "Sup3rSecret!"})
    assert response.status_code == 409
