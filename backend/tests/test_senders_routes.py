from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.local_user import LocalSmtpUser
from tests.conftest import csrf_headers


def _create_upstream(client: TestClient) -> int:
    response = client.post(
        "/api/upstream-accounts",
        json={
            "name": "STRATO noreply",
            "host": "smtp.strato.de",
            "port": 587,
            "tls_mode": "starttls",
            "username": "noreply@example.com",
            "password": "upstream-secret",
        },
        headers=csrf_headers(client),
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/senders").status_code == 401


def test_create_requires_a_real_upstream_account(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/senders",
        json={"address": "noreply@example.com", "upstream_account_id": 999},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 422


def test_create_and_list(admin_client: TestClient) -> None:
    account_id = _create_upstream(admin_client)
    response = admin_client.post(
        "/api/senders",
        json={"address": "noreply@example.com", "upstream_account_id": account_id},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["address"] == "noreply@example.com"
    assert body["allowed_local_user_count"] == 0

    listed = admin_client.get("/api/senders").json()
    assert [s["id"] for s in listed] == [body["id"]]


def test_duplicate_address_is_rejected(admin_client: TestClient) -> None:
    account_id = _create_upstream(admin_client)
    payload = {"address": "noreply@example.com", "upstream_account_id": account_id}
    assert admin_client.post("/api/senders", json=payload, headers=csrf_headers(admin_client)).status_code == 201
    dup = admin_client.post("/api/senders", json=payload, headers=csrf_headers(admin_client))
    assert dup.status_code == 409


def test_delete_precheck_and_delete_blast_radius(admin_client: TestClient, db_session: Session) -> None:
    account_id = _create_upstream(admin_client)
    sender = admin_client.post(
        "/api/senders",
        json={"address": "noreply@example.com", "upstream_account_id": account_id},
        headers=csrf_headers(admin_client),
    ).json()

    db_session.add(LocalSmtpUser(name="InvenTree", username="inventree", password_hash="x"))
    db_session.commit()
    user = db_session.query(LocalSmtpUser).filter_by(username="inventree").one()

    admin_client.put(
        f"/api/senders/{sender['id']}/permissions/{user.id}", headers=csrf_headers(admin_client)
    )

    precheck = admin_client.get(f"/api/senders/{sender['id']}/delete-precheck")
    assert precheck.json() == {"allowed_local_user_names": ["InvenTree"]}


def test_permission_grant_and_revoke_round_trip(admin_client: TestClient, db_session: Session) -> None:
    account_id = _create_upstream(admin_client)
    sender = admin_client.post(
        "/api/senders",
        json={"address": "noreply@example.com", "upstream_account_id": account_id},
        headers=csrf_headers(admin_client),
    ).json()
    db_session.add(LocalSmtpUser(name="InvenTree", username="inventree", password_hash="x"))
    db_session.commit()
    user = db_session.query(LocalSmtpUser).filter_by(username="inventree").one()

    view = admin_client.get(f"/api/senders/{sender['id']}/permissions").json()
    assert view["local_users"] == [{"id": user.id, "name": "InvenTree", "username": "inventree", "allowed": False}]

    grant = admin_client.put(
        f"/api/senders/{sender['id']}/permissions/{user.id}", headers=csrf_headers(admin_client)
    )
    assert grant.status_code == 204

    view = admin_client.get(f"/api/senders/{sender['id']}/permissions").json()
    assert view["local_users"][0]["allowed"] is True
    assert view["sender"]["allowed_local_user_count"] == 1

    revoke = admin_client.delete(
        f"/api/senders/{sender['id']}/permissions/{user.id}", headers=csrf_headers(admin_client)
    )
    assert revoke.status_code == 204

    view = admin_client.get(f"/api/senders/{sender['id']}/permissions").json()
    assert view["local_users"][0]["allowed"] is False


def test_grant_twice_is_not_an_error(admin_client: TestClient, db_session: Session) -> None:
    account_id = _create_upstream(admin_client)
    sender = admin_client.post(
        "/api/senders",
        json={"address": "noreply@example.com", "upstream_account_id": account_id},
        headers=csrf_headers(admin_client),
    ).json()
    db_session.add(LocalSmtpUser(name="InvenTree", username="inventree", password_hash="x"))
    db_session.commit()
    user = db_session.query(LocalSmtpUser).filter_by(username="inventree").one()

    for _ in range(2):
        response = admin_client.put(
            f"/api/senders/{sender['id']}/permissions/{user.id}", headers=csrf_headers(admin_client)
        )
        assert response.status_code == 204
