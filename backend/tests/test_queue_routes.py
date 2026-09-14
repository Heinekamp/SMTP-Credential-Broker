import pytest
from fastapi.testclient import TestClient

from app.core.postfix_control import PostfixControlError
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
