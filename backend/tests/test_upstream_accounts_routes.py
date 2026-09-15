from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.encryption import decrypt_secret
from app.models.sender import Sender
from app.models.upstream import UpstreamAccount
from tests.conftest import csrf_headers

PAYLOAD = {
    "name": "STRATO noreply",
    "host": "smtp.strato.de",
    "port": 587,
    "tls_mode": "starttls",
    "username": "noreply@example.com",
    "password": "upstream-secret",
}


def _create(client: TestClient, **overrides: object) -> dict:
    body = {**PAYLOAD, **overrides}
    response = client.post("/api/upstream-accounts", json=body, headers=csrf_headers(client))
    assert response.status_code == 201, response.text
    return response.json()


def test_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/upstream-accounts")
    assert response.status_code == 401


def test_create_rejects_a_host_containing_a_tab(admin_client: TestClient) -> None:
    """Regression test: host is tab-joined into Postfix lookup-map source
    files (config_generator.py's sasl_passwd/sender_relayhost) — a
    literal tab would inject an extra, attacker-chosen map record."""
    response = admin_client.post(
        "/api/upstream-accounts",
        json={**PAYLOAD, "host": "smtp.strato.de\tevil.example"},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 422


def test_create_rejects_a_username_containing_a_colon(admin_client: TestClient) -> None:
    """Regression test: username is embedded as `username:password` in
    the generated sasl_passwd map line (config_generator.py) — an extra
    colon would shift where Postfix splits username from password."""
    response = admin_client.post(
        "/api/upstream-accounts",
        json={**PAYLOAD, "username": "user:extra"},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 422


def test_create_rejects_a_username_containing_whitespace(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/upstream-accounts",
        json={**PAYLOAD, "username": "user name"},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 422


def test_create_never_returns_password(admin_client: TestClient) -> None:
    account = _create(admin_client)
    assert "password" not in account
    assert "encrypted_password" not in account
    assert account["name"] == "STRATO noreply"
    assert account["tls_mode"] == "starttls"


def test_password_is_encrypted_at_rest(admin_client: TestClient, db_session: Session) -> None:
    account = _create(admin_client)
    row = db_session.get(UpstreamAccount, account["id"])
    assert row is not None
    assert b"upstream-secret" not in row.encrypted_password
    assert decrypt_secret(row.encrypted_password) == "upstream-secret"


def test_list_and_get(admin_client: TestClient) -> None:
    created = _create(admin_client)
    listed = admin_client.get("/api/upstream-accounts").json()
    assert [a["id"] for a in listed] == [created["id"]]

    fetched = admin_client.get(f"/api/upstream-accounts/{created['id']}")
    assert fetched.status_code == 200
    assert "password" not in fetched.json()


def test_get_missing_account_is_404(admin_client: TestClient) -> None:
    assert admin_client.get("/api/upstream-accounts/999").status_code == 404


def test_update_without_password_keeps_existing_password(
    admin_client: TestClient, db_session: Session
) -> None:
    created = _create(admin_client)
    before = db_session.get(UpstreamAccount, created["id"]).encrypted_password

    response = admin_client.patch(
        f"/api/upstream-accounts/{created['id']}",
        json={"name": "STRATO noreply (renamed)"},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 200
    assert response.json()["name"] == "STRATO noreply (renamed)"

    db_session.expire_all()
    after = db_session.get(UpstreamAccount, created["id"]).encrypted_password
    assert before == after


def test_update_with_password_rotates_it(admin_client: TestClient, db_session: Session) -> None:
    created = _create(admin_client)

    response = admin_client.patch(
        f"/api/upstream-accounts/{created['id']}",
        json={"password": "new-upstream-secret"},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 200

    db_session.expire_all()
    row = db_session.get(UpstreamAccount, created["id"])
    assert decrypt_secret(row.encrypted_password) == "new-upstream-secret"


def test_delete_precheck_lists_dependent_senders(admin_client: TestClient, db_session: Session) -> None:
    created = _create(admin_client)
    db_session.add(Sender(address="noreply@example.com", upstream_account_id=created["id"]))
    db_session.commit()

    response = admin_client.get(f"/api/upstream-accounts/{created['id']}/delete-precheck")
    assert response.status_code == 200
    assert response.json() == {"dependent_sender_addresses": ["noreply@example.com"]}


def test_delete_with_dependent_sender_is_rejected(admin_client: TestClient, db_session: Session) -> None:
    created = _create(admin_client)
    db_session.add(Sender(address="noreply@example.com", upstream_account_id=created["id"]))
    db_session.commit()

    response = admin_client.delete(
        f"/api/upstream-accounts/{created['id']}", headers=csrf_headers(admin_client)
    )
    assert response.status_code == 409


def test_delete_without_dependents_succeeds(admin_client: TestClient) -> None:
    created = _create(admin_client)
    response = admin_client.delete(
        f"/api/upstream-accounts/{created['id']}", headers=csrf_headers(admin_client)
    )
    assert response.status_code == 204
    assert admin_client.get(f"/api/upstream-accounts/{created['id']}").status_code == 404


def test_test_connection_persists_result(admin_client: TestClient, db_session: Session, monkeypatch) -> None:
    from app.core.test_connection import StepResult, TestConnectionResult

    created = _create(admin_client)

    fake_result = TestConnectionResult(
        steps=[
            StepResult("DNS resolution", True, "ok"),
            StepResult("TCP connection", True, "ok"),
            StepResult("TLS handshake", True, "ok"),
            StepResult("Server greeting", True, "ok"),
            StepResult("AUTH", False, "535 bad credentials"),
        ]
    )
    monkeypatch.setattr(
        "app.api.routes.upstream_accounts.test_upstream_connection", lambda **kwargs: fake_result
    )

    response = admin_client.post(
        f"/api/upstream-accounts/{created['id']}/test-connection", headers=csrf_headers(admin_client)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["steps"][-1] == {"name": "AUTH", "passed": False, "detail": "535 bad credentials"}

    db_session.expire_all()
    row = db_session.get(UpstreamAccount, created["id"])
    assert row.last_test_result == "failure"
    assert row.last_test_at is not None
    assert "AUTH" in row.last_test_error
