import datetime

import time_machine
from sqlalchemy.orm import Session

from app.core.sessions import create_session, get_session_by_token, revoke_session
from app.models.admin import AdminUser


def _make_admin(db_session: Session) -> AdminUser:
    admin = AdminUser(email="admin@example.com", password_hash="irrelevant-for-this-test")
    db_session.add(admin)
    db_session.flush()
    return admin


def test_create_and_fetch_session(db_session: Session) -> None:
    admin = _make_admin(db_session)
    raw_token = create_session(db_session, admin, "127.0.0.1", "pytest")
    db_session.commit()

    fetched = get_session_by_token(db_session, raw_token)
    assert fetched is not None
    assert fetched.admin_user_id == admin.id


def test_unknown_token_returns_none(db_session: Session) -> None:
    assert get_session_by_token(db_session, "not-a-real-token") is None


def test_expired_session_is_rejected(db_session: Session) -> None:
    admin = _make_admin(db_session)
    with time_machine.travel(datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)) as traveller:
        raw_token = create_session(db_session, admin, None, None)
        db_session.commit()
        assert get_session_by_token(db_session, raw_token) is not None

        traveller.shift(datetime.timedelta(hours=13))  # past the 12h default TTL
        assert get_session_by_token(db_session, raw_token) is None


def test_revoked_session_is_rejected_immediately(db_session: Session) -> None:
    admin = _make_admin(db_session)
    raw_token = create_session(db_session, admin, None, None)
    db_session.commit()

    revoke_session(db_session, raw_token)
    db_session.commit()

    assert get_session_by_token(db_session, raw_token) is None


def test_session_token_hash_stored_not_raw_token(db_session: Session) -> None:
    admin = _make_admin(db_session)
    raw_token = create_session(db_session, admin, None, None)
    db_session.commit()

    session = get_session_by_token(db_session, raw_token)
    assert session is not None
    assert session.token_hash != raw_token
