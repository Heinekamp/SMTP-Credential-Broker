from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from tests.conftest import csrf_headers


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
    assert body["notify_on_health_degraded"] is True


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
