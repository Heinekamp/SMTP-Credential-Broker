import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.encryption import encrypt_secret
from app.models.audit import AuditLog
from app.models.enums import TlsMode
from app.models.sender import Sender
from app.models.upstream import UpstreamAccount
from tests.conftest import csrf_headers


def _configured_sender(db_session: Session) -> Sender:
    account = UpstreamAccount(
        name="alert-account",
        host="smtp.example.com",
        port=587,
        tls_mode=TlsMode.starttls,
        username="alerts@example.com",
        encrypted_password=encrypt_secret("hunter2"),
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)
    sender = Sender(address="alerts@example.com", upstream_account_id=account.id)
    db_session.add(sender)
    db_session.commit()
    db_session.refresh(sender)
    return sender


def test_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/notification-settings").status_code == 401


def test_get_returns_defaults_on_a_fresh_install(admin_client: TestClient) -> None:
    response = admin_client.get("/api/notification-settings")
    assert response.status_code == 200
    body = response.json()
    assert body["connection_test_interval_minutes"] is None
    assert body["update_check_enabled"] is False
    assert body["notify_recipients"] == []
    assert body["notify_sender_id"] is None
    assert body["notify_from_name"] is None
    assert body["notify_on_health_degraded"] is True
    assert body["notify_on_rate_limit_abuse"] is False
    assert body["rate_limit_abuse_auto_disable_enabled"] is False
    assert body["rate_limit_abuse_threshold_minutes"] == 10
    assert body["mail_log_retention_days"] is None
    assert body["audit_log_retention_days"] is None


def test_patch_can_set_rate_limit_abuse_settings(admin_client: TestClient) -> None:
    response = admin_client.patch(
        "/api/notification-settings",
        json={
            "notify_on_rate_limit_abuse": True,
            "rate_limit_abuse_auto_disable_enabled": True,
            "rate_limit_abuse_threshold_minutes": 5,
        },
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["notify_on_rate_limit_abuse"] is True
    assert body["rate_limit_abuse_auto_disable_enabled"] is True
    assert body["rate_limit_abuse_threshold_minutes"] == 5


def test_patch_rejects_a_non_positive_rate_limit_abuse_threshold(admin_client: TestClient) -> None:
    response = admin_client.patch(
        "/api/notification-settings",
        json={"rate_limit_abuse_threshold_minutes": 0},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 422


def test_patch_can_set_and_clear_the_from_name(admin_client: TestClient) -> None:
    response = admin_client.patch(
        "/api/notification-settings",
        json={"notify_from_name": "SMTP Relay Alerts"},
        headers=csrf_headers(admin_client),
    )
    assert response.json()["notify_from_name"] == "SMTP Relay Alerts"

    response = admin_client.patch(
        "/api/notification-settings",
        json={"notify_from_name": None},
        headers=csrf_headers(admin_client),
    )
    assert response.json()["notify_from_name"] is None


def test_patch_only_changes_supplied_fields(admin_client: TestClient) -> None:
    response = admin_client.patch(
        "/api/notification-settings",
        json={"update_check_enabled": True},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["update_check_enabled"] is True
    # Untouched fields keep their defaults.
    assert body["connection_test_interval_minutes"] is None
    assert body["notify_on_health_degraded"] is True


def test_patch_can_explicitly_clear_the_interval_back_to_disabled(admin_client: TestClient) -> None:
    admin_client.patch(
        "/api/notification-settings",
        json={"connection_test_interval_minutes": 60},
        headers=csrf_headers(admin_client),
    )
    response = admin_client.patch(
        "/api/notification-settings",
        json={"connection_test_interval_minutes": None},
        headers=csrf_headers(admin_client),
    )
    assert response.json()["connection_test_interval_minutes"] is None


def test_patch_can_set_and_clear_retention_windows(admin_client: TestClient) -> None:
    response = admin_client.patch(
        "/api/notification-settings",
        json={"mail_log_retention_days": 30, "audit_log_retention_days": 90},
        headers=csrf_headers(admin_client),
    )
    assert response.json()["mail_log_retention_days"] == 30
    assert response.json()["audit_log_retention_days"] == 90

    response = admin_client.patch(
        "/api/notification-settings",
        json={"mail_log_retention_days": None},
        headers=csrf_headers(admin_client),
    )
    assert response.json()["mail_log_retention_days"] is None
    # Untouched — clearing one retention window must not affect the other.
    assert response.json()["audit_log_retention_days"] == 90


def test_patch_rejects_invalid_email_addresses(admin_client: TestClient) -> None:
    response = admin_client.patch(
        "/api/notification-settings",
        json={"notify_recipients": ["not-an-email"]},
        headers=csrf_headers(admin_client),
    )
    assert response.status_code == 422


def test_patch_is_audited(admin_client: TestClient, db_session: Session) -> None:
    admin_client.patch(
        "/api/notification-settings",
        json={"update_check_enabled": True},
        headers=csrf_headers(admin_client),
    )
    entry = db_session.query(AuditLog).filter(AuditLog.action == "notification_settings.update").one()
    assert entry.detail == {"fields": ["update_check_enabled"]}


def test_send_test_alert_requires_at_least_one_recipient(admin_client: TestClient, db_session: Session) -> None:
    sender = _configured_sender(db_session)
    admin_client.patch(
        "/api/notification-settings",
        json={"notify_sender_id": sender.id},
        headers=csrf_headers(admin_client),
    )

    response = admin_client.post("/api/notification-settings/test", headers=csrf_headers(admin_client))
    assert response.status_code == 400


def test_send_test_alert_requires_a_usable_sender(admin_client: TestClient) -> None:
    admin_client.patch(
        "/api/notification-settings",
        json={"notify_recipients": ["admin@example.com"]},
        headers=csrf_headers(admin_client),
    )

    response = admin_client.post("/api/notification-settings/test", headers=csrf_headers(admin_client))
    assert response.status_code == 400


def test_send_test_alert_success(
    admin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    sender = _configured_sender(db_session)
    admin_client.patch(
        "/api/notification-settings",
        json={"notify_sender_id": sender.id, "notify_recipients": ["admin@example.com"]},
        headers=csrf_headers(admin_client),
    )
    monkeypatch.setattr("app.core.alert_email.send_alert_email", lambda **kwargs: None)

    response = admin_client.post("/api/notification-settings/test", headers=csrf_headers(admin_client))
    assert response.status_code == 200
    assert response.json()["success"] is True


def test_send_test_alert_reports_the_real_failure_without_raising(
    admin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same "diagnostic report, not an exception" contract as Test
    Connection — a real send failure (bad credentials, unreachable
    upstream) must come back as success: false with the actual error,
    not a 500."""
    sender = _configured_sender(db_session)
    admin_client.patch(
        "/api/notification-settings",
        json={"notify_sender_id": sender.id, "notify_recipients": ["admin@example.com"]},
        headers=csrf_headers(admin_client),
    )

    def _boom(**kwargs):
        raise RuntimeError("535 bad credentials")

    monkeypatch.setattr("app.core.alert_email.send_alert_email", _boom)

    response = admin_client.post("/api/notification-settings/test", headers=csrf_headers(admin_client))
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert "535 bad credentials" in body["detail"]


def test_send_test_alert_is_audited(
    admin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    sender = _configured_sender(db_session)
    admin_client.patch(
        "/api/notification-settings",
        json={"notify_sender_id": sender.id, "notify_recipients": ["admin@example.com"]},
        headers=csrf_headers(admin_client),
    )
    monkeypatch.setattr("app.core.alert_email.send_alert_email", lambda **kwargs: None)

    admin_client.post("/api/notification-settings/test", headers=csrf_headers(admin_client))

    entry = db_session.query(AuditLog).filter(AuditLog.action == "notification_settings.test_alert").one()
    assert entry.detail == {"success": True}


def test_send_test_alert_requires_csrf(admin_client: TestClient) -> None:
    response = admin_client.post("/api/notification-settings/test")
    assert response.status_code == 403
