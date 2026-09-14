import pytest
from fastapi.testclient import TestClient

from app.core.postfix_control import ApplyConfigResult, PostfixControlError
from tests.conftest import csrf_headers


def test_requires_authentication(client: TestClient) -> None:
    assert client.post("/api/config/generate").status_code == 401


def test_unreachable_control_surface_is_a_clean_503(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(**kwargs):
        raise PostfixControlError("Could not reach the Postfix control surface: [Errno 2] No such file or directory")

    monkeypatch.setattr("app.core.config_generator.postfix_control.apply_config", _boom)

    response = admin_client.post("/api/config/generate", headers=csrf_headers(admin_client))
    assert response.status_code == 503
    assert "control surface" in response.json()["detail"]


def test_successful_generation_is_listed_in_history(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.core.config_generator.postfix_control.apply_config",
        lambda **kwargs: ApplyConfigResult(success=True, validation_detail="postconf: OK", reloaded=True),
    )

    response = admin_client.post("/api/config/generate", headers=csrf_headers(admin_client))
    assert response.status_code == 200
    assert response.json()["success"] is True

    history = admin_client.get("/api/config/generations").json()
    assert len(history) == 1
    assert history[0]["validation_result"] == "pass"


def test_validate_endpoint_never_touches_the_control_surface(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(**kwargs):
        raise AssertionError("validate must not call apply_config")

    monkeypatch.setattr("app.core.config_generator.postfix_control.apply_config", _boom)

    response = admin_client.post("/api/config/validate", headers=csrf_headers(admin_client))
    assert response.status_code == 200
    assert response.json()["success"] is True
