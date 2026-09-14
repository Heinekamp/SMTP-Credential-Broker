from fastapi.testclient import TestClient


def test_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/system-status").status_code == 401


def test_reports_encryption_key_configured(admin_client: TestClient) -> None:
    # conftest.py sets RELAY_ENCRYPTION_KEY for the whole test session.
    response = admin_client.get("/api/system-status")
    assert response.status_code == 200
    assert response.json() == {"encryption_key_configured": True}


def test_reports_not_configured_when_key_is_missing(
    admin_client: TestClient, monkeypatch
) -> None:
    from app.config import get_settings

    monkeypatch.delenv("RELAY_ENCRYPTION_KEY", raising=False)
    get_settings.cache_clear()
    try:
        response = admin_client.get("/api/system-status")
        assert response.json() == {"encryption_key_configured": False}
    finally:
        get_settings.cache_clear()
