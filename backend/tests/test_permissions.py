from sqlalchemy.orm import Session

from app.core.permissions import (
    enabled_senders_with_upstream,
    grant_permission,
    revoke_permission,
    sender_login_map,
)
from app.models.local_user import LocalSmtpUser
from app.models.sender import Sender
from app.models.upstream import UpstreamAccount


def _make_upstream(db: Session, *, enabled: bool = True) -> UpstreamAccount:
    account = UpstreamAccount(
        name="STRATO noreply",
        host="smtp.strato.de",
        port=587,
        username="noreply@example.com",
        encrypted_password=b"irrelevant-for-this-test",
        enabled=enabled,
    )
    db.add(account)
    db.flush()
    return account


def _make_sender(db: Session, account: UpstreamAccount, address: str, *, enabled: bool = True) -> Sender:
    sender = Sender(address=address, upstream_account_id=account.id, enabled=enabled)
    db.add(sender)
    db.flush()
    return sender


def _make_user(db: Session, username: str, *, enabled: bool = True) -> LocalSmtpUser:
    user = LocalSmtpUser(name=username, username=username, password_hash="x", enabled=enabled)
    db.add(user)
    db.flush()
    return user


def test_sender_login_map_reflects_granted_permissions(db_session: Session) -> None:
    account = _make_upstream(db_session)
    noreply = _make_sender(db_session, account, "noreply@example.com")
    printer = _make_sender(db_session, account, "printer@example.com")
    inventree = _make_user(db_session, "inventree")
    printer_service = _make_user(db_session, "printer-service")

    grant_permission(db_session, local_smtp_user_id=inventree.id, sender_id=noreply.id, granted_by_admin_id=None)
    grant_permission(
        db_session, local_smtp_user_id=printer_service.id, sender_id=printer.id, granted_by_admin_id=None
    )

    result = sender_login_map(db_session)
    assert result == {
        "noreply@example.com": ["inventree"],
        "printer@example.com": ["printer-service"],
    }


def test_sender_login_map_supports_multiple_users_per_sender(db_session: Session) -> None:
    account = _make_upstream(db_session)
    server = _make_sender(db_session, account, "server@example.com")
    monitoring = _make_user(db_session, "monitoring")
    web = _make_user(db_session, "webapp")

    grant_permission(db_session, local_smtp_user_id=monitoring.id, sender_id=server.id, granted_by_admin_id=None)
    grant_permission(db_session, local_smtp_user_id=web.id, sender_id=server.id, granted_by_admin_id=None)

    assert sender_login_map(db_session) == {"server@example.com": ["monitoring", "webapp"]}


def test_disabled_sender_excluded_even_if_granted(db_session: Session) -> None:
    account = _make_upstream(db_session)
    sender = _make_sender(db_session, account, "printer@example.com", enabled=False)
    user = _make_user(db_session, "printer-service")
    grant_permission(db_session, local_smtp_user_id=user.id, sender_id=sender.id, granted_by_admin_id=None)

    assert sender_login_map(db_session) == {}


def test_disabled_local_user_excluded_even_if_granted(db_session: Session) -> None:
    account = _make_upstream(db_session)
    sender = _make_sender(db_session, account, "printer@example.com")
    user = _make_user(db_session, "printer-service", enabled=False)
    grant_permission(db_session, local_smtp_user_id=user.id, sender_id=sender.id, granted_by_admin_id=None)

    assert sender_login_map(db_session) == {}


def test_revoke_removes_the_entry(db_session: Session) -> None:
    account = _make_upstream(db_session)
    sender = _make_sender(db_session, account, "printer@example.com")
    user = _make_user(db_session, "printer-service")
    grant_permission(db_session, local_smtp_user_id=user.id, sender_id=sender.id, granted_by_admin_id=None)
    assert sender_login_map(db_session) == {"printer@example.com": ["printer-service"]}

    revoke_permission(db_session, local_smtp_user_id=user.id, sender_id=sender.id)
    assert sender_login_map(db_session) == {}


def test_grant_is_idempotent(db_session: Session) -> None:
    account = _make_upstream(db_session)
    sender = _make_sender(db_session, account, "printer@example.com")
    user = _make_user(db_session, "printer-service")

    grant_permission(db_session, local_smtp_user_id=user.id, sender_id=sender.id, granted_by_admin_id=None)
    grant_permission(db_session, local_smtp_user_id=user.id, sender_id=sender.id, granted_by_admin_id=None)

    assert sender_login_map(db_session) == {"printer@example.com": ["printer-service"]}


def test_revoke_of_ungranted_permission_is_a_no_op(db_session: Session) -> None:
    account = _make_upstream(db_session)
    sender = _make_sender(db_session, account, "printer@example.com")
    user = _make_user(db_session, "printer-service")
    revoke_permission(db_session, local_smtp_user_id=user.id, sender_id=sender.id)  # must not raise
    assert sender_login_map(db_session) == {}


def test_enabled_senders_with_upstream_excludes_disabled_upstream(db_session: Session) -> None:
    healthy_account = _make_upstream(db_session)
    disabled_account = _make_upstream(db_session, enabled=False)
    good_sender = _make_sender(db_session, healthy_account, "noreply@example.com")
    _make_sender(db_session, disabled_account, "printer@example.com")

    result = enabled_senders_with_upstream(db_session)
    assert [s.id for s in result] == [good_sender.id]


def test_enabled_senders_with_upstream_excludes_disabled_sender(db_session: Session) -> None:
    account = _make_upstream(db_session)
    good_sender = _make_sender(db_session, account, "noreply@example.com")
    _make_sender(db_session, account, "printer@example.com", enabled=False)

    result = enabled_senders_with_upstream(db_session)
    assert [s.id for s in result] == [good_sender.id]
