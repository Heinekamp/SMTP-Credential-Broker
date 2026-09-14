"""Confirms audit_log actually gets written for the mutating routes
Stage 8 wired it into — database-schema.md §9 documents these actions as
its intended examples, but before this stage only admin_login.success/
failure (core/rate_limit.py) ever wrote a row. One representative
assertion per route file, not exhaustive per-field checks (those already
exist in each route's own test file) — this file's job is coverage of
"does this action get audited at all," not re-testing the route's own
business logic."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from tests.conftest import ADMIN_PASSWORD, csrf_headers


def _actions(db_session: Session) -> list[str]:
    return [a for (a,) in db_session.query(AuditLog.action).all()]


def _upstream_account(client: TestClient, **overrides: object) -> dict:
    payload = {
        "name": "STRATO noreply",
        "host": "smtp.strato.de",
        "port": 587,
        "tls_mode": "starttls",
        "username": "noreply@example.com",
        "password": "upstream-secret",
        **overrides,
    }
    response = client.post("/api/upstream-accounts", json=payload, headers=csrf_headers(client))
    assert response.status_code == 201, response.text
    return response.json()


def test_upstream_account_create_update_delete_are_audited(
    admin_client: TestClient, db_session: Session
) -> None:
    account = _upstream_account(admin_client)
    admin_client.patch(
        f"/api/upstream-accounts/{account['id']}", json={"name": "Renamed"}, headers=csrf_headers(admin_client)
    )
    admin_client.delete(f"/api/upstream-accounts/{account['id']}", headers=csrf_headers(admin_client))

    actions = _actions(db_session)
    assert "upstream_account.create" in actions
    assert "upstream_account.update" in actions
    assert "upstream_account.delete" in actions

    row = db_session.query(AuditLog).filter(AuditLog.action == "upstream_account.create").one()
    assert row.admin_user_id is not None
    assert row.target_type == "upstream_account"
    assert row.detail == {"name": "STRATO noreply", "host": "smtp.strato.de"}


def test_sender_create_update_delete_and_permissions_are_audited(
    admin_client: TestClient, db_session: Session, fake_postfix_control
) -> None:
    account = _upstream_account(admin_client)
    sender = admin_client.post(
        "/api/senders",
        json={"address": "noreply@example.com", "upstream_account_id": account["id"]},
        headers=csrf_headers(admin_client),
    ).json()
    admin_client.patch(f"/api/senders/{sender['id']}", json={"enabled": False}, headers=csrf_headers(admin_client))

    user = admin_client.post(
        "/api/local-users", json={"name": "Svc", "username": "svc"}, headers=csrf_headers(admin_client)
    ).json()["user"]
    admin_client.put(
        f"/api/senders/{sender['id']}/permissions/{user['id']}", headers=csrf_headers(admin_client)
    )
    admin_client.delete(
        f"/api/senders/{sender['id']}/permissions/{user['id']}", headers=csrf_headers(admin_client)
    )
    admin_client.delete(f"/api/senders/{sender['id']}", headers=csrf_headers(admin_client))

    actions = _actions(db_session)
    assert "sender.create" in actions
    assert "sender.update" in actions
    assert "sender.delete" in actions
    assert "permission.grant" in actions
    assert "permission.revoke" in actions


def test_local_user_lifecycle_is_audited(admin_client: TestClient, db_session: Session, fake_postfix_control) -> None:
    user = admin_client.post(
        "/api/local-users", json={"name": "Svc", "username": "svc"}, headers=csrf_headers(admin_client)
    ).json()["user"]
    admin_client.patch(f"/api/local-users/{user['id']}", json={"name": "Renamed"}, headers=csrf_headers(admin_client))
    admin_client.post(f"/api/local-users/{user['id']}/regenerate-password", headers=csrf_headers(admin_client))
    admin_client.delete(f"/api/local-users/{user['id']}", headers=csrf_headers(admin_client))

    actions = _actions(db_session)
    assert "local_user.create" in actions
    assert "local_user.update" in actions
    assert "local_user.regenerate_password" in actions
    assert "local_user.delete" in actions


def test_admin_create_and_change_password_are_audited(admin_client: TestClient, db_session: Session) -> None:
    admin_client.post(
        "/api/admins",
        json={"email": "second@example.com", "password": "Sup3rSecret!"},
        headers=csrf_headers(admin_client),
    )
    admin_client.post(
        "/api/admins/me/change-password",
        json={"current_password": ADMIN_PASSWORD, "new_password": "New-Sup3rSecret!"},
        headers=csrf_headers(admin_client),
    )

    actions = _actions(db_session)
    assert "admin.create" in actions
    assert "admin.change_password" in actions


def test_config_generate_is_audited(admin_client: TestClient, db_session: Session, monkeypatch) -> None:
    from app.core.postfix_control import ApplyConfigResult

    monkeypatch.setattr(
        "app.core.config_generator.postfix_control.apply_config",
        lambda **kwargs: ApplyConfigResult(success=True, validation_detail="postconf: OK", reloaded=True),
    )
    admin_client.post("/api/config/generate", headers=csrf_headers(admin_client))

    row = db_session.query(AuditLog).filter(AuditLog.action == "config.generate").one()
    assert row.target_type == "config_generation"
    assert row.detail == {"success": True, "reloaded": True}


def test_totp_enroll_and_remove_are_audited(admin_client: TestClient, db_session: Session) -> None:
    import pyotp

    enroll = admin_client.post("/api/admins/me/totp/enroll", headers=csrf_headers(admin_client)).json()
    code = pyotp.TOTP(enroll["secret"]).now()
    admin_client.post(
        "/api/admins/me/totp/confirm",
        json={"secret": enroll["secret"], "code": code},
        headers=csrf_headers(admin_client),
    )
    admin_client.post("/api/admins/me/totp/remove", headers=csrf_headers(admin_client))

    actions = _actions(db_session)
    assert "admin.totp_enroll" in actions
    assert "admin.totp_remove" in actions


def test_audit_log_never_contains_a_raw_password(
    admin_client: TestClient, db_session: Session, fake_postfix_control
) -> None:
    account = _upstream_account(admin_client, password="upstream-super-secret-value")
    admin_client.patch(
        f"/api/upstream-accounts/{account['id']}",
        json={"password": "a-different-secret-value"},
        headers=csrf_headers(admin_client),
    )
    created = admin_client.post(
        "/api/local-users", json={"name": "Svc", "username": "svc-nopass"}, headers=csrf_headers(admin_client)
    ).json()
    local_user_password = created["password"]

    for row in db_session.query(AuditLog).all():
        if not row.detail:
            continue
        rendered = str(row.detail)
        assert "upstream-super-secret-value" not in rendered
        assert "a-different-secret-value" not in rendered
        assert local_user_password not in rendered
        # The password.update() branch logs *that* it changed, never the
        # value — a bare boolean/field-name marker, not the secret.
        for key, value in row.detail.items():
            if key == "fields":
                continue
            assert "password" not in key.lower()