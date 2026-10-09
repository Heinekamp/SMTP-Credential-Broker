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


def test_anonymous_health_has_no_internal_detail_but_admins_do(
    client: TestClient, admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test for #175: the public endpoint used to return raw
    control-socket and database error text to anyone."""

    def _boom():
        raise PostfixControlError("Could not reach the Postfix control surface at /shared-config/control.sock")

    monkeypatch.setattr("app.core.health.postfix_control.status", _boom)

    admin_body = admin_client.get("/api/health").json()
    assert "control.sock" in admin_body["postfix_reachable"]["detail"]

    admin_client.cookies.delete("session")
    anonymous_body = admin_client.get("/api/health").json()
    assert anonymous_body["status"] == "degraded"
    assert anonymous_body["postfix_reachable"] == {"ok": False, "detail": ""}
    assert all(anonymous_body[k]["detail"] == "" for k in ("database", "postfix_running", "config_in_sync"))


def test_anonymous_health_reuses_a_recent_report(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every full check RPCs the single-threaded control surface — anonymous
    polling mustn't be able to keep it busy (#175)."""
    calls = {"count": 0}

    def _status():
        calls["count"] += 1
        return PostfixStatus(running=True, detail="running")

    monkeypatch.setattr("app.core.health.postfix_control.status", _status)
    for _ in range(5):
        assert client.get("/api/health").status_code == 200
    assert calls["count"] == 1
