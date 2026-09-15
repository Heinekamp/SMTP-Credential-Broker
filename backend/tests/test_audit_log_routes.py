import datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.security import hash_password
from app.models.admin import AdminUser
from app.models.audit import AuditLog
from tests.conftest import ADMIN_EMAIL

# admin_client's own login already writes one admin_login.success row
# (core/rate_limit.py, target_type="admin_user") before any test body
# runs — every query below scopes to a target_type/action the login
# can't produce, so that row never leaks into an assertion.


def _record(db_session: Session, **overrides) -> None:
    defaults = dict(admin_user_id=None, action="sender.create", target_type="sender", target_id=1)
    defaults.update(overrides)
    record_audit(db_session, **defaults)
    db_session.commit()


def test_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/audit-log").status_code == 401


def test_lists_entries_newest_first(admin_client: TestClient, db_session: Session) -> None:
    _record(db_session, action="sender.create", target_id=1)
    _record(db_session, action="sender.delete", target_id=1)

    response = admin_client.get("/api/audit-log", params={"target_type": "sender"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [e["action"] for e in body["entries"]] == ["sender.delete", "sender.create"]


def test_includes_the_acting_admins_email(admin_client: TestClient, db_session: Session) -> None:
    admin = db_session.query(AdminUser).filter_by(email=ADMIN_EMAIL).one()
    _record(db_session, admin_user_id=admin.id, action="admin.change_password", target_type=None, target_id=None)

    entries = admin_client.get("/api/audit-log", params={"action": "admin.change_password"}).json()["entries"]
    assert entries[0]["admin_email"] == ADMIN_EMAIL


def test_system_triggered_rows_have_no_admin_email(admin_client: TestClient, db_session: Session) -> None:
    _record(db_session, admin_user_id=None, action="upstream_account.scheduled_test", target_type=None, target_id=None)

    entries = admin_client.get(
        "/api/audit-log", params={"action": "upstream_account.scheduled_test"}
    ).json()["entries"]
    assert entries[0]["admin_user_id"] is None
    assert entries[0]["admin_email"] is None


def test_filters_by_action_and_target_type(admin_client: TestClient, db_session: Session) -> None:
    _record(db_session, action="sender.create", target_type="sender", target_id=1)
    _record(db_session, action="local_user.create", target_type="local_smtp_user", target_id=2)

    response = admin_client.get("/api/audit-log", params={"action": "sender.create"})
    assert [e["action"] for e in response.json()["entries"]] == ["sender.create"]

    response = admin_client.get("/api/audit-log", params={"target_type": "local_smtp_user"})
    assert [e["action"] for e in response.json()["entries"]] == ["local_user.create"]


def test_filters_by_admin_user_id(admin_client: TestClient, db_session: Session) -> None:
    admin = db_session.query(AdminUser).filter_by(email=ADMIN_EMAIL).one()
    other = AdminUser(email="other@example.com", password_hash=hash_password("x"))
    db_session.add(other)
    db_session.commit()

    _record(db_session, admin_user_id=admin.id, action="admin.change_password", target_type=None, target_id=None)
    _record(db_session, admin_user_id=other.id, action="admin.totp_remove", target_type=None, target_id=None)

    response = admin_client.get("/api/audit-log", params={"admin_user_id": other.id})
    assert [e["action"] for e in response.json()["entries"]] == ["admin.totp_remove"]


def test_filters_by_since_and_until(admin_client: TestClient, db_session: Session) -> None:
    db_session.add(
        AuditLog(
            timestamp=datetime.datetime(2026, 1, 1, 0, 0, 0),
            admin_user_id=None,
            action="probe.old",
            target_type="probe",
        )
    )
    db_session.add(
        AuditLog(
            timestamp=datetime.datetime(2026, 6, 1, 0, 0, 0),
            admin_user_id=None,
            action="probe.new",
            target_type="probe",
        )
    )
    db_session.commit()

    response = admin_client.get(
        "/api/audit-log", params={"target_type": "probe", "since": "2026-03-01T00:00:00"}
    )
    assert [e["action"] for e in response.json()["entries"]] == ["probe.new"]

    response = admin_client.get(
        "/api/audit-log", params={"target_type": "probe", "until": "2026-03-01T00:00:00"}
    )
    assert [e["action"] for e in response.json()["entries"]] == ["probe.old"]


def test_pagination(admin_client: TestClient, db_session: Session) -> None:
    for i in range(3):
        _record(db_session, action=f"action.{i}", target_type="pagination-probe", target_id=i)

    response = admin_client.get(
        "/api/audit-log", params={"target_type": "pagination-probe", "limit": 1, "offset": 1}
    )
    body = response.json()
    assert body["total"] == 3
    assert len(body["entries"]) == 1
