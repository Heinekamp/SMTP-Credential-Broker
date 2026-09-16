import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.models.local_user import LocalSmtpUser, UserSenderPermission
from tests.conftest import csrf_headers


def _create_upstream_and_sender(client: TestClient, address: str = "noreply@example.com") -> int:
    account = client.post(
        "/api/upstream-accounts",
        json={
            "name": "STRATO",
            "host": "smtp.strato.de",
            "port": 587,
            "tls_mode": "starttls",
            "username": address,
            "password": "upstream-secret",
        },
        headers=csrf_headers(client),
    ).json()
    sender = client.post(
        "/api/senders",
        json={"address": address, "upstream_account_id": account["id"]},
        headers=csrf_headers(client),
    ).json()
    return sender["id"]


def test_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/local-users").status_code == 401


def test_create_returns_password_once_and_hashes_it_in_the_db(
    admin_client: TestClient, db_session: Session, fake_postfix_control: list
) -> None:
    response = admin_client.post(
        "/api/local-users",
        json={"name": "InvenTree", "username": "inventree"},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 201
    body = response.json()
    password = body["password"]
    assert len(password) == 24
    assert "password" not in body["user"]
    assert "password_hash" not in body["user"]

    row = db_session.query(LocalSmtpUser).filter_by(username="inventree").one()
    assert verify_password(row.password_hash, password) is True

    assert fake_postfix_control == [("set", "inventree", password)]


def test_create_rejects_a_username_with_a_leading_hyphen(
    admin_client: TestClient, fake_postfix_control: list
) -> None:
    """Regression test: username is passed as saslpasswd2's trailing argv
    element (postfix/control_surface.py) — a leading '-' could be read as
    a flag by its own argument parsing rather than as a userid."""
    response = admin_client.post(
        "/api/local-users",
        json={"name": "Evil", "username": "-f"},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 422
    assert fake_postfix_control == []


def test_create_rejects_a_username_containing_a_tab(admin_client: TestClient, fake_postfix_control: list) -> None:
    """Regression test: username is comma-joined into Postfix's
    sender_login lookup-map source file (permissions.py's
    sender_login_map) — a literal tab here would inject an extra record."""
    response = admin_client.post(
        "/api/local-users",
        json={"name": "Evil", "username": "inventree\tinjected"},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 422
    assert fake_postfix_control == []


def test_duplicate_username_is_rejected(admin_client: TestClient, fake_postfix_control: list) -> None:
    payload = {"name": "InvenTree", "username": "inventree"}
    assert admin_client.post("/api/local-users", json=payload, headers=csrf_headers(admin_client)).status_code == 201
    dup = admin_client.post("/api/local-users", json=payload, headers=csrf_headers(admin_client))
    assert dup.status_code == 409
    # Only one sasldb2 write should have happened — the duplicate must be
    # rejected before ever touching the control surface.
    assert len(fake_postfix_control) == 1


def test_regenerate_password_updates_sasldb_and_hash(
    admin_client: TestClient, db_session: Session, fake_postfix_control: list
) -> None:
    created = admin_client.post(
        "/api/local-users",
        json={"name": "InvenTree", "username": "inventree"},
        headers=csrf_headers(admin_client),
    ).json()
    user_id = created["user"]["id"]
    old_hash = db_session.get(LocalSmtpUser, user_id).password_hash

    response = admin_client.post(
        f"/api/local-users/{user_id}/regenerate-password", headers=csrf_headers(admin_client)
    )
    assert response.status_code == 200
    new_password = response.json()["password"]

    db_session.expire_all()
    row = db_session.get(LocalSmtpUser, user_id)
    assert row.password_hash != old_hash
    assert verify_password(row.password_hash, new_password) is True
    assert fake_postfix_control[-1] == ("set", "inventree", new_password)


def test_regenerate_never_touches_sasldb2_before_the_new_hash_is_flushed_to_the_db(
    admin_client: TestClient, db_session: Session, fake_postfix_control: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same ordering bug as the re-enable regression test above, in the
    sibling endpoint that has the identical shape."""
    created = admin_client.post(
        "/api/local-users",
        json={"name": "InvenTree", "username": "inventree"},
        headers=csrf_headers(admin_client),
    ).json()
    user_id = created["user"]["id"]
    fake_postfix_control.clear()

    def failing_flush() -> None:
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(db_session, "flush", failing_flush)

    with pytest.raises(RuntimeError):
        admin_client.post(f"/api/local-users/{user_id}/regenerate-password", headers=csrf_headers(admin_client))

    assert fake_postfix_control == []


def test_create_accepts_a_rate_limit(admin_client: TestClient, fake_postfix_control: list) -> None:
    response = admin_client.post(
        "/api/local-users",
        json={"name": "Printer", "username": "printer-service", "rate_limit_per_hour": 20},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 201
    body = response.json()["user"]
    assert body["rate_limit_per_hour"] == 20
    assert body["sent_this_hour"] == 0


def test_create_defaults_to_unlimited(admin_client: TestClient, fake_postfix_control: list) -> None:
    response = admin_client.post(
        "/api/local-users",
        json={"name": "Printer", "username": "printer-service"},
        headers=csrf_headers(admin_client),
    )
    assert response.json()["user"]["rate_limit_per_hour"] is None


def test_create_rejects_a_non_positive_rate_limit(admin_client: TestClient, fake_postfix_control: list) -> None:
    response = admin_client.post(
        "/api/local-users",
        json={"name": "Printer", "username": "printer-service", "rate_limit_per_hour": 0},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 422
    assert fake_postfix_control == []


def test_update_sets_and_clears_the_rate_limit(
    admin_client: TestClient, db_session: Session, fake_postfix_control: list
) -> None:
    created = admin_client.post(
        "/api/local-users",
        json={"name": "Printer", "username": "printer-service"},
        headers=csrf_headers(admin_client),
    ).json()
    user_id = created["user"]["id"]

    response = admin_client.patch(
        f"/api/local-users/{user_id}", json={"rate_limit_per_hour": 20}, headers=csrf_headers(admin_client)
    )
    assert response.status_code == 200
    assert response.json()["user"]["rate_limit_per_hour"] == 20

    response = admin_client.patch(
        f"/api/local-users/{user_id}", json={"rate_limit_per_hour": None}, headers=csrf_headers(admin_client)
    )
    assert response.status_code == 200
    assert response.json()["user"]["rate_limit_per_hour"] is None
    db_session.expire_all()
    assert db_session.get(LocalSmtpUser, user_id).rate_limit_per_hour is None


def test_sent_this_hour_reflects_the_current_window_counter(
    admin_client: TestClient, db_session: Session, fake_postfix_control: list
) -> None:
    from app.core.clock import utcnow
    from app.core.rate_limit_policy import _window_start
    from app.models.rate_limit import LocalUserRateLimitCounter

    created = admin_client.post(
        "/api/local-users",
        json={"name": "Printer", "username": "printer-service", "rate_limit_per_hour": 20},
        headers=csrf_headers(admin_client),
    ).json()
    user_id = created["user"]["id"]
    db_session.add(
        LocalUserRateLimitCounter(local_smtp_user_id=user_id, window_start=_window_start(utcnow()), count=3)
    )
    db_session.commit()

    response = admin_client.get(f"/api/local-users/{user_id}")
    assert response.json()["sent_this_hour"] == 3


def test_disable_deletes_sasl_entry(admin_client: TestClient, fake_postfix_control: list) -> None:
    created = admin_client.post(
        "/api/local-users",
        json={"name": "InvenTree", "username": "inventree"},
        headers=csrf_headers(admin_client),
    ).json()
    user_id = created["user"]["id"]

    response = admin_client.patch(
        f"/api/local-users/{user_id}", json={"enabled": False}, headers=csrf_headers(admin_client)
    )
    assert response.status_code == 200
    assert response.json()["password"] is None
    assert response.json()["user"]["enabled"] is False
    assert fake_postfix_control[-1] == ("delete", "inventree")


def test_re_enable_issues_a_new_password(
    admin_client: TestClient, db_session: Session, fake_postfix_control: list
) -> None:
    """There is no plaintext to restore (only an Argon2 hash is ever
    stored) — re-enabling a disabled user must generate a fresh credential,
    exactly like Regenerate, not silently fail to restore SMTP AUTH."""
    created = admin_client.post(
        "/api/local-users",
        json={"name": "InvenTree", "username": "inventree"},
        headers=csrf_headers(admin_client),
    ).json()
    user_id = created["user"]["id"]
    admin_client.patch(f"/api/local-users/{user_id}", json={"enabled": False}, headers=csrf_headers(admin_client))

    response = admin_client.patch(
        f"/api/local-users/{user_id}", json={"enabled": True}, headers=csrf_headers(admin_client)
    )
    assert response.status_code == 200
    new_password = response.json()["password"]
    assert new_password is not None
    assert new_password != created["password"]
    assert response.json()["user"]["enabled"] is True
    assert fake_postfix_control[-1] == ("set", "inventree", new_password)

    db_session.expire_all()
    row = db_session.get(LocalSmtpUser, user_id)
    assert verify_password(row.password_hash, new_password) is True


def test_re_enable_never_touches_sasldb2_before_the_new_state_is_flushed_to_the_db(
    admin_client: TestClient, db_session: Session, fake_postfix_control: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test: the new password used to be written to sasldb2
    *before* the DB transaction was ever touched — a commit failure
    afterward left a live, working credential whose password was never
    returned to anyone, while the DB still showed the user disabled with
    the old hash. Simulating a flush failure proves sasldb2 is never
    called until the new state has already been staged in the DB
    transaction (same ordering fix applied to regenerate_password)."""
    created = admin_client.post(
        "/api/local-users",
        json={"name": "InvenTree", "username": "inventree"},
        headers=csrf_headers(admin_client),
    ).json()
    user_id = created["user"]["id"]
    admin_client.patch(f"/api/local-users/{user_id}", json={"enabled": False}, headers=csrf_headers(admin_client))
    fake_postfix_control.clear()

    def failing_flush() -> None:
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(db_session, "flush", failing_flush)

    with pytest.raises(RuntimeError):
        admin_client.patch(f"/api/local-users/{user_id}", json={"enabled": True}, headers=csrf_headers(admin_client))

    assert fake_postfix_control == []


def test_delete_revokes_sasl_before_removing_the_row(admin_client: TestClient, fake_postfix_control: list) -> None:
    created = admin_client.post(
        "/api/local-users",
        json={"name": "InvenTree", "username": "inventree"},
        headers=csrf_headers(admin_client),
    ).json()
    user_id = created["user"]["id"]

    response = admin_client.delete(f"/api/local-users/{user_id}", headers=csrf_headers(admin_client))
    assert response.status_code == 204
    assert fake_postfix_control[-1] == ("delete", "inventree")
    assert admin_client.get(f"/api/local-users/{user_id}").status_code == 404


def test_delete_succeeds_and_cascades_when_a_permission_grant_is_still_active(
    admin_client: TestClient, db_session: Session, fake_postfix_control: list
) -> None:
    """Regression test: deleting a local user with an active permission
    grant used to crash with a 500 for the identical reason a sender
    delete did (see test_senders_routes.py's equivalent test) —
    user_sender_permissions.local_smtp_user_id is also part of that
    table's composite primary key."""
    sender_id = _create_upstream_and_sender(admin_client)
    created = admin_client.post(
        "/api/local-users",
        json={"name": "InvenTree", "username": "inventree"},
        headers=csrf_headers(admin_client),
    ).json()
    user_id = created["user"]["id"]
    admin_client.put(f"/api/local-users/{user_id}/permissions/{sender_id}", headers=csrf_headers(admin_client))

    response = admin_client.delete(f"/api/local-users/{user_id}", headers=csrf_headers(admin_client))

    assert response.status_code == 204
    assert db_session.query(UserSenderPermission).filter_by(local_smtp_user_id=user_id).count() == 0


def test_connection_details_never_include_password(admin_client: TestClient, fake_postfix_control: list) -> None:
    sender_id = _create_upstream_and_sender(admin_client)
    created = admin_client.post(
        "/api/local-users",
        json={"name": "InvenTree", "username": "inventree"},
        headers=csrf_headers(admin_client),
    ).json()
    user_id = created["user"]["id"]
    admin_client.put(f"/api/local-users/{user_id}/permissions/{sender_id}", headers=csrf_headers(admin_client))

    details = admin_client.get(f"/api/local-users/{user_id}/connection-details").json()
    assert "password" not in details
    assert details["username"] == "inventree"
    assert details["from_addresses"] == ["noreply@example.com"]
    assert details["tls_mode"] == "STARTTLS"


def test_permission_view_from_user_side(admin_client: TestClient, fake_postfix_control: list) -> None:
    sender_id = _create_upstream_and_sender(admin_client)
    created = admin_client.post(
        "/api/local-users",
        json={"name": "InvenTree", "username": "inventree"},
        headers=csrf_headers(admin_client),
    ).json()
    user_id = created["user"]["id"]

    view = admin_client.get(f"/api/local-users/{user_id}/permissions").json()
    assert view["senders"] == [{"id": sender_id, "address": "noreply@example.com", "allowed": False}]

    admin_client.put(f"/api/local-users/{user_id}/permissions/{sender_id}", headers=csrf_headers(admin_client))
    view = admin_client.get(f"/api/local-users/{user_id}/permissions").json()
    assert view["senders"][0]["allowed"] is True
    assert view["user"]["allowed_sender_count"] == 1
