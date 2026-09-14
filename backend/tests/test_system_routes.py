from importlib.metadata import version

from fastapi.testclient import TestClient

from app.core.postfix_control import PostfixControlError


def test_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/system-status").status_code == 401


def test_reports_encryption_key_configured(admin_client: TestClient) -> None:
    # conftest.py sets RELAY_ENCRYPTION_KEY for the whole test session. No
    # real control surface exists in this environment, so postfix_version
    # naturally falls back to None here — the reachable case is covered
    # separately below.
    response = admin_client.get("/api/system-status")
    assert response.status_code == 200
    assert response.json() == {
        "encryption_key_configured": True,
        "app_version": version("relay"),
        "postfix_version": None,
    }


def test_reports_not_configured_when_key_is_missing(
    admin_client: TestClient, monkeypatch
) -> None:
    from app.config import get_settings

    monkeypatch.delenv("RELAY_ENCRYPTION_KEY", raising=False)
    get_settings.cache_clear()
    try:
        response = admin_client.get("/api/system-status")
        assert response.json() == {
            "encryption_key_configured": False,
            "app_version": version("relay"),
            "postfix_version": None,
        }
    finally:
        get_settings.cache_clear()


def test_reports_postfix_version_when_reachable(admin_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.system.postfix_control.version", lambda: "3.8.6")
    response = admin_client.get("/api/system-status")
    assert response.json()["postfix_version"] == "3.8.6"


def test_postfix_version_is_none_when_control_surface_unreachable(admin_client: TestClient, monkeypatch) -> None:
    def _boom():
        raise PostfixControlError("unreachable")

    monkeypatch.setattr("app.api.routes.system.postfix_control.version", _boom)
    response = admin_client.get("/api/system-status")
    assert response.status_code == 200
    assert response.json()["postfix_version"] is None
