import pytest
from sqlalchemy.orm import Session

from app.core import sasldb_reconcile
from app.core.postfix_control import PostfixControlError
from app.models.local_user import LocalSmtpUser


def _user(db: Session, username: str, *, enabled: bool = True) -> None:
    db.add(LocalSmtpUser(name=username, username=username, password_hash="x", enabled=enabled))
    db.commit()


def test_removes_sasldb_users_that_are_disabled_or_unknown(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    """Regression test for #185: a revoked credential restored from a stale
    volume copy must not keep working — the database decides who may
    authenticate."""
    _user(db_session, "wordpress")
    _user(db_session, "printer", enabled=False)
    deleted: list[str] = []
    monkeypatch.setattr(
        sasldb_reconcile.postfix_control, "sasl_list_users", lambda: ["wordpress", "printer", "deleted-long-ago"]
    )
    monkeypatch.setattr(sasldb_reconcile.postfix_control, "sasl_delete_user", deleted.append)

    removed = sasldb_reconcile.reconcile_sasldb(db_session)

    assert removed == ["printer", "deleted-long-ago"]
    assert deleted == ["printer", "deleted-long-ago"]


def test_never_raises_when_postfix_is_unreachable(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> None:
    def _unreachable():
        raise PostfixControlError("Could not reach the Postfix control surface")

    monkeypatch.setattr(sasldb_reconcile.postfix_control, "sasl_list_users", _unreachable)
    assert sasldb_reconcile.reconcile_sasldb(db_session) == []


def test_a_failed_delete_is_skipped_without_stopping_the_rest(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    deleted: list[str] = []

    def _delete(username: str) -> None:
        if username == "stuck":
            raise PostfixControlError("saslpasswd2 -d failed")
        deleted.append(username)

    monkeypatch.setattr(sasldb_reconcile.postfix_control, "sasl_list_users", lambda: ["stuck", "stale"])
    monkeypatch.setattr(sasldb_reconcile.postfix_control, "sasl_delete_user", _delete)

    assert sasldb_reconcile.reconcile_sasldb(db_session) == ["stale"]
    assert deleted == ["stale"]
