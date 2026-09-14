import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.health import CheckResult, HealthReport
from app.core.settings_store import get_background_job_state
from app.models.audit import AuditLog
from tests.conftest import csrf_headers

_HEALTHY = HealthReport(
    status="ok",
    database=CheckResult(ok=True),
    postfix_reachable=CheckResult(ok=True),
    postfix_running=CheckResult(ok=True),
    last_generation_result="pass",
    config_in_sync=CheckResult(ok=True),
)


@pytest.fixture(autouse=True)
def _healthy_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # No real control surface exists in tests — without this, every alert
    # listing would always include health_degraded (postfix unreachable).
    monkeypatch.setattr("app.core.alerts.run_health_check", lambda db: _HEALTHY)
    monkeypatch.setattr("app.core.alerts.postfix_control.version", lambda: None)


def test_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/alerts").status_code == 401


def test_list_alerts_empty_in_a_clean_state(admin_client: TestClient) -> None:
    response = admin_client.get("/api/alerts")
    assert response.status_code == 200
    assert response.json() == {"alerts": [], "active_count": 0}


def test_acknowledge_rejects_an_unknown_kind(admin_client: TestClient) -> None:
    response = admin_client.post("/api/alerts/not_a_real_kind/acknowledge", headers=csrf_headers(admin_client))
    assert response.status_code == 404


def test_acknowledge_sets_the_current_latest_version_and_audits(
    admin_client: TestClient, db_session: Session
) -> None:
    state = get_background_job_state(db_session)
    state.latest_app_version = "999.0.0"
    db_session.commit()

    response = admin_client.post("/api/alerts/app_update_available/acknowledge", headers=csrf_headers(admin_client))
    assert response.status_code == 204

    db_session.refresh(state)
    assert state.app_update_acknowledged_version == "999.0.0"

    entry = db_session.query(AuditLog).filter(AuditLog.action == "alert.acknowledge").one()
    assert entry.detail == {"kind": "app_update_available", "acknowledged_version": "999.0.0"}

    # The alert is now acknowledged, so it no longer counts toward active_count.
    listing = admin_client.get("/api/alerts").json()
    assert listing["active_count"] == 0
    assert listing["alerts"][0]["acknowledged"] is True
