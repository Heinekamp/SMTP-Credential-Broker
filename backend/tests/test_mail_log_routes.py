import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.postfix_control import PostfixControlError
from app.models.enums import MailStatus
from app.models.mail_log import MailLog


def _add_row(db_session: Session, **overrides) -> MailLog:
    defaults = dict(
        queue_id="Q1",
        timestamp=datetime.datetime(2026, 9, 14, 10, 0, 0),
        envelope_sender="printer@example.com",
        recipients=["dest@example.net"],
        status=MailStatus.sent,
    )
    defaults.update(overrides)
    row = MailLog(**defaults)
    db_session.add(row)
    db_session.commit()
    return row


def test_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/mail-log").status_code == 401


def test_lists_entries_newest_first(
    admin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.routes.mail_log.ingest_new_log_lines", lambda db: 0)
    _add_row(db_session, queue_id="Q1", timestamp=datetime.datetime(2026, 9, 14, 10, 0, 0))
    _add_row(db_session, queue_id="Q2", timestamp=datetime.datetime(2026, 9, 14, 11, 0, 0))

    response = admin_client.get("/api/mail-log")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [e["queue_id"] for e in body["entries"]] == ["Q2", "Q1"]


def test_filters_by_status_and_sender(
    admin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.routes.mail_log.ingest_new_log_lines", lambda db: 0)
    _add_row(db_session, queue_id="Q1", envelope_sender="printer@example.com", status=MailStatus.sent)
    _add_row(db_session, queue_id="Q2", envelope_sender="noreply@example.com", status=MailStatus.deferred)

    response = admin_client.get("/api/mail-log", params={"status": "deferred"})
    assert [e["queue_id"] for e in response.json()["entries"]] == ["Q2"]

    response = admin_client.get("/api/mail-log", params={"envelope_sender": "printer@example.com"})
    assert [e["queue_id"] for e in response.json()["entries"]] == ["Q1"]


def test_unreachable_control_surface_still_serves_stale_data(
    admin_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(db):
        raise PostfixControlError("unreachable")

    monkeypatch.setattr("app.api.routes.mail_log.ingest_new_log_lines", _boom)
    _add_row(db_session)

    response = admin_client.get("/api/mail-log")
    assert response.status_code == 200
    assert response.json()["total"] == 1
