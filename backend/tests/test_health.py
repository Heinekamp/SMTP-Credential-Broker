import pytest
from fastapi.testclient import TestClient

from app.core.postfix_control import PostfixControlError, PostfixStatus


def test_health_never_configured_is_still_ok(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fresh install with no config ever generated is a normal starting
    state, not a fault — Postfix legitimately isn't running yet either
    (architecture.md §7 / core/health.py)."""
    monkeypatch.setattr(
        "app.core.health.postfix_control.status", lambda: PostfixStatus(running=False, detail="not running")
    )
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"]["ok"] is True
    assert body["postfix_reachable"]["ok"] is True
    assert body["postfix_running"]["ok"] is False
    assert body["last_generation_result"] == "none"
    assert body["config_in_sync"]["ok"] is False


def test_health_unreachable_control_surface_is_degraded_but_still_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom():
        raise PostfixControlError("Could not reach the Postfix control surface")

    monkeypatch.setattr("app.core.health.postfix_control.status", _boom)
    response = client.get("/api/health")
    # Deliberately not a 503 — see api/routes/health.py's comment on why
    # the body, not the HTTP status, carries health.
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["postfix_reachable"]["ok"] is False
