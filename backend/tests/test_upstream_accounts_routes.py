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


def test_create_accepts_a_rate_limit(admin_client: TestClient, db_session: Session) -> None:
    created = _create(admin_client, rate_limit_per_hour=100)

    assert created["rate_limit_per_hour"] == 100
    assert created["sent_this_hour"] == 0
    row = db_session.get(UpstreamAccount, created["id"])
    assert row.rate_limit_per_hour == 100


def test_create_defaults_to_unlimited(admin_client: TestClient) -> None:
    created = _create(admin_client)
    assert created["rate_limit_per_hour"] is None


def test_create_verifies_upstream_tls_by_default(admin_client: TestClient) -> None:
    created = _create(admin_client)
    assert created["tls_skip_verify"] is False


def test_tls_skip_verify_can_be_set_and_cleared(admin_client: TestClient, db_session: Session) -> None:
    created = _create(admin_client, tls_skip_verify=True)
    assert created["tls_skip_verify"] is True

    response = admin_client.patch(
        f"/api/upstream-accounts/{created['id']}",
        json={"tls_skip_verify": False},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 200
    assert response.json()["tls_skip_verify"] is False
    db_session.expire_all()
    assert db_session.get(UpstreamAccount, created["id"]).tls_skip_verify is False


def test_create_rejects_a_non_positive_rate_limit(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/upstream-accounts",
        json={**PAYLOAD, "rate_limit_per_hour": 0},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 422


def test_update_sets_and_clears_the_rate_limit(admin_client: TestClient, db_session: Session) -> None:
    created = _create(admin_client)

    response = admin_client.patch(
        f"/api/upstream-accounts/{created['id']}",
        json={"rate_limit_per_hour": 50},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 200
    assert response.json()["rate_limit_per_hour"] == 50

    response = admin_client.patch(
        f"/api/upstream-accounts/{created['id']}",
        json={"rate_limit_per_hour": None},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 200
    assert response.json()["rate_limit_per_hour"] is None
    db_session.expire_all()
    assert db_session.get(UpstreamAccount, created["id"]).rate_limit_per_hour is None


def test_sent_this_hour_reflects_recent_mail_log_deliveries(admin_client: TestClient, db_session: Session) -> None:
    import datetime

    from app.core.clock import utcnow
    from app.models.enums import MailStatus
    from app.models.mail_log import MailLog

    created = _create(admin_client)
    db_session.add(
        MailLog(
            queue_id="Q1",
            timestamp=utcnow() - datetime.timedelta(minutes=10),
            envelope_sender="a@example.com",
            recipients=["b@example.net"],
            status=MailStatus.sent,
            upstream_account_id=created["id"],
        )
    )
    db_session.add(
        MailLog(
            queue_id="Q2",
            timestamp=utcnow() - datetime.timedelta(hours=2),  # outside the 1h window
            envelope_sender="a@example.com",
            recipients=["b@example.net"],
            status=MailStatus.sent,
            upstream_account_id=created["id"],
        )
    )
    db_session.commit()

    response = admin_client.get(f"/api/upstream-accounts/{created['id']}")
    assert response.status_code == 200
    assert response.json()["sent_this_hour"] == 1


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


def _patch(client: TestClient, account_id: int, body: dict):
    return client.patch(f"/api/upstream-accounts/{account_id}", json=body, headers=csrf_headers(client))


def test_changing_the_destination_requires_the_password(admin_client: TestClient, db_session: Session) -> None:
    """Regression test for #165: pointing an account at a new host and then
    running Test Connection used to send the *stored* password there,
    letting any admin session extract it."""
    created = _create(admin_client)
    changes = ({"host": "attacker.example"}, {"port": 2525}, {"username": "x@example.com"}, {"tls_mode": "implicit"})
    for change in changes:
        response = _patch(admin_client, created["id"], change)
        assert response.status_code == 422, change
        assert "Re-enter this account's password" in response.json()["detail"]

    db_session.expire_all()
    assert db_session.get(UpstreamAccount, created["id"]).host == "smtp.strato.de"


def test_changing_the_destination_with_the_password_succeeds(admin_client: TestClient) -> None:
    created = _create(admin_client)
    response = _patch(admin_client, created["id"], {"host": "mail.example.com", "password": "new-secret"})
    assert response.status_code == 200
    assert response.json()["host"] == "mail.example.com"


def test_switching_off_certificate_verification_requires_the_password(admin_client: TestClient) -> None:
    created = _create(admin_client)
    assert _patch(admin_client, created["id"], {"tls_skip_verify": True}).status_code == 422
    assert _patch(admin_client, created["id"], {"tls_skip_verify": True, "password": "pw"}).status_code == 200
    # Switching verification back on only tightens things, so no password needed.
    assert _patch(admin_client, created["id"], {"tls_skip_verify": False}).status_code == 200


def test_resubmitting_unchanged_destination_fields_needs_no_password(admin_client: TestClient) -> None:
    """The edit form always sends every field — saving a rename or a rate
    limit change mustn't demand the password when nothing about the
    destination actually changed."""
    created = _create(admin_client)
    response = _patch(
        admin_client,
        created["id"],
        {
            "name": "Renamed",
            "host": "smtp.strato.de",
            "port": 587,
            "username": "noreply@example.com",
            "tls_mode": "starttls",
            "tls_skip_verify": False,
            "rate_limit_per_hour": 50,
        },
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"


def test_upstream_password_rejects_separators_and_surrounding_whitespace(admin_client: TestClient) -> None:
    """Regression test for #175: a newline or tab would inject a record into
    the sasl_passwd map, and postmap silently trims surrounding whitespace."""
    for bad in ("pass\nother@corp.com\tu:p", "pa\tss", " leading", "trailing "):
        response = admin_client.post(
            "/api/upstream-accounts", json={**PAYLOAD, "password": bad}, headers=csrf_headers(admin_client)
        )
        assert response.status_code == 422, bad
    assert _create(admin_client, password="has inner spaces")["id"]


def test_account_names_reject_line_breaks(admin_client: TestClient) -> None:
    """Names go into alert email subjects, where a CR/LF made every send fail."""
    response = admin_client.post(
        "/api/upstream-accounts",
        json={**PAYLOAD, "name": "evil\r\nBcc: x@example.com"},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 422


def test_explicit_null_on_a_required_account_field_is_a_422_not_a_500(admin_client: TestClient) -> None:
    """Regression test for #189: these reached the database as NULL."""
    created = _create(admin_client)
    for field in ("name", "host", "port", "tls_mode", "username", "enabled", "tls_skip_verify"):
        assert _patch(admin_client, created["id"], {field: None}).status_code == 422, field
    # Null where it means something is still fine.
    assert _patch(admin_client, created["id"], {"rate_limit_per_hour": None}).status_code == 200
    assert _patch(admin_client, created["id"], {"password": None}).status_code == 200
