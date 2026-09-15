import csv
import io

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import TlsMode
from app.models.local_user import LocalSmtpUser
from app.models.sender import Sender
from app.models.upstream import UpstreamAccount
from tests.conftest import csrf_headers


def _seed(db_session: Session) -> tuple[Sender, LocalSmtpUser]:
    account = UpstreamAccount(
        name="STRATO",
        host="smtp.strato.de",
        port=587,
        tls_mode=TlsMode.starttls,
        username="noreply@example.com",
        encrypted_password=b"ciphertext",
        enabled=True,
    )
    db_session.add(account)
    db_session.commit()
    sender = Sender(address="noreply@example.com", upstream_account_id=account.id, enabled=True)
    db_session.add(sender)
    user = LocalSmtpUser(name="InvenTree", username="inventree", password_hash="x", enabled=True)
    db_session.add(user)
    db_session.commit()
    return sender, user


def _rows(response) -> list[list[str]]:
    return list(csv.reader(io.StringIO(response.text)))


def test_export_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/exports/senders.csv").status_code == 401
    assert client.get("/api/exports/local-users.csv").status_code == 401
    assert client.get("/api/exports/permissions.csv").status_code == 401


def test_export_senders_csv(admin_client: TestClient, db_session: Session) -> None:
    sender, _user = _seed(db_session)

    response = admin_client.get("/api/exports/senders.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="senders.csv"' in response.headers["content-disposition"]

    rows = _rows(response)
    assert rows[0] == ["address", "upstream_account", "enabled", "allowed_local_user_count", "description"]
    assert rows[1] == [sender.address, "STRATO", "yes", "0", ""]


def test_export_local_users_csv(admin_client: TestClient, db_session: Session) -> None:
    _sender, user = _seed(db_session)

    response = admin_client.get("/api/exports/local-users.csv")
    assert response.status_code == 200
    assert 'filename="local-users.csv"' in response.headers["content-disposition"]

    rows = _rows(response)
    assert rows[0] == ["name", "username", "enabled", "allowed_sender_count", "password_last_rotated_at"]
    assert rows[1] == [user.name, user.username, "yes", "0", ""]


def test_export_permissions_csv_reflects_active_grants(admin_client: TestClient, db_session: Session) -> None:
    sender, user = _seed(db_session)

    empty = _rows(admin_client.get("/api/exports/permissions.csv"))
    assert empty == [["sender_address", "local_user_name", "local_user_username", "granted_at"]]

    admin_client.put(f"/api/senders/{sender.id}/permissions/{user.id}", headers=csrf_headers(admin_client))

    rows = _rows(admin_client.get("/api/exports/permissions.csv"))
    assert rows[0] == ["sender_address", "local_user_name", "local_user_username", "granted_at"]
    assert rows[1][:3] == [sender.address, user.name, user.username]
    assert rows[1][3]  # a non-empty ISO timestamp


def test_export_senders_csv_reflects_permission_count(admin_client: TestClient, db_session: Session) -> None:
    sender, user = _seed(db_session)
    admin_client.put(f"/api/senders/{sender.id}/permissions/{user.id}", headers=csrf_headers(admin_client))

    rows = _rows(admin_client.get("/api/exports/senders.csv"))
    assert rows[1] == [sender.address, "STRATO", "yes", "1", ""]
