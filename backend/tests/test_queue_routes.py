import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.postfix_control import PostfixControlError
from app.models.audit import AuditLog
from tests.conftest import csrf_headers

_RAW_ENTRY = {
    "queue_name": "deferred",
    "queue_id": "4XYZ000001",
    "arrival_time": 1_700_000_000,
    "message_size": 1234,
    "sender": "printer@example.com",
    "recipients": [{"address": "dest@example.net", "delay_reason": "Connection timed out"}],
}


def test_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/queue").status_code == 401


def test_list_queue_returns_entries(admin_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.routes.queue.queue_list", lambda: [_RAW_ENTRY])

    response = admin_client.get("/api/queue")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["queue_id"] == "4XYZ000001"
    assert body[0]["recipients"][0]["delay_reason"] == "Connection timed out"


def test_list_queue_unreachable_control_surface_is_503(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom():
        raise PostfixControlError("unreachable")

    monkeypatch.setattr("app.api.routes.queue.queue_list", _boom)
    response = admin_client.get("/api/queue")
    assert response.status_code == 503


def test_retry_requires_csrf(admin_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr("app.api.routes.queue.queue_requeue", lambda queue_id: calls.append(queue_id))

    response = admin_client.post("/api/queue/4XYZ000001/retry")
    assert response.status_code == 403
    assert calls == []

    response = admin_client.post("/api/queue/4XYZ000001/retry", headers=csrf_headers(admin_client))
    assert response.status_code == 204
    assert calls == ["4XYZ000001"]


def test_delete_requires_csrf(admin_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr("app.api.routes.queue.queue_delete", lambda queue_id: calls.append(queue_id))

    response = admin_client.delete("/api/queue/4XYZ000001")
    assert response.status_code == 403

    response = admin_client.delete("/api/queue/4XYZ000001", headers=csrf_headers(admin_client))
    assert response.status_code == 204
    assert calls == ["4XYZ000001"]


@pytest.mark.parametrize("method", ["post", "delete"])
def test_queue_id_all_is_rejected_before_reaching_postfix(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    """Regression test for #159: `postsuper -d ALL` deletes every queued
    message — a single-message endpoint must never pass it through."""
    monkeypatch.setattr("app.api.routes.queue.queue_delete", lambda _id: pytest.fail("must not be called"))
    monkeypatch.setattr("app.api.routes.queue.queue_requeue", lambda _id: pytest.fail("must not be called"))
    path = "/api/queue/ALL/retry" if method == "post" else "/api/queue/ALL"
    response = getattr(admin_client, method)(path, headers=csrf_headers(admin_client))
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("method", "path", "patched", "action"),
    [
        ("post", "/api/queue/4XYZ000001/retry", "queue_requeue", "queue.retry"),
        ("delete", "/api/queue/4XYZ000001", "queue_delete", "queue.delete"),
    ],
)
def test_queue_actions_are_audited(
    admin_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    patched: str,
    action: str,
) -> None:
    monkeypatch.setattr(f"app.api.routes.queue.{patched}", lambda queue_id: None)

    response = getattr(admin_client, method)(path, headers=csrf_headers(admin_client))
    assert response.status_code == 204
    row = db_session.query(AuditLog).filter(AuditLog.action == action).one()
    assert row.target_type == "queue_message"
    assert row.detail == {"queue_id": "4XYZ000001"}
    assert row.admin_user_id is not None


def test_failed_queue_action_is_not_audited(
    admin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(queue_id: str) -> None:
        raise PostfixControlError("unreachable")

    monkeypatch.setattr("app.api.routes.queue.queue_delete", _boom)
    response = admin_client.delete("/api/queue/4XYZ000001", headers=csrf_headers(admin_client))
    assert response.status_code == 503
    assert db_session.query(AuditLog).filter(AuditLog.action == "queue.delete").count() == 0
