"""`relay reset-admin-password` and `relay disable-totp` (break-glass
recovery for a forgotten password / lost authenticator when there's no
other admin account to recover through). Same shared-global-engine
pattern as test_rotate_encryption_key.py — these CLI commands use
app.db.session.SessionLocal directly, not the per-test db_session
fixture's isolated engine.
"""

import datetime

import pytest
from typer.testing import CliRunner

from app.cli import cli
from app.core.clock import utcnow
from app.core.encryption import encrypt_secret
from app.core.security import hash_password, verify_password
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.admin import AdminSession, AdminUser
from app.models.audit import AuditLog
from app.models.sender import Sender
from app.models.upstream import UpstreamAccount

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_shared_db() -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        db.query(AuditLog).delete()
        db.query(AdminSession).delete()
        db.query(Sender).delete()
        db.query(UpstreamAccount).delete()
        db.query(AdminUser).delete()
        db.commit()
    finally:
        db.close()


def _create_admin(**overrides) -> int:
    db = SessionLocal()
    defaults = dict(email="locked-out@example.com", password_hash=hash_password("old-password"))
    defaults.update(overrides)
    admin = AdminUser(**defaults)
    db.add(admin)
    db.commit()
    admin_id = admin.id
    db.close()
    return admin_id


def _add_session(admin_id: int) -> None:
    db = SessionLocal()
    db.add(
        AdminSession(
            admin_user_id=admin_id,
            token_hash="a" * 64,
            expires_at=utcnow() + datetime.timedelta(hours=1),
        )
    )
    db.commit()
    db.close()


def test_reset_admin_password_updates_the_hash(tmp_path) -> None:
    admin_id = _create_admin()

    result = runner.invoke(
        cli, ["reset-admin-password", "locked-out@example.com"], input="New-Sup3rSecret!\nNew-Sup3rSecret!\n"
    )
    assert result.exit_code == 0, result.output
    assert "Password reset" in result.output

    db = SessionLocal()
    row = db.get(AdminUser, admin_id)
    assert verify_password(row.password_hash, "New-Sup3rSecret!") is True
    db.close()


def test_reset_admin_password_revokes_existing_sessions(tmp_path) -> None:
    admin_id = _create_admin()
    _add_session(admin_id)

    runner.invoke(cli, ["reset-admin-password", "locked-out@example.com"], input="New-Sup3rSecret!\nNew-Sup3rSecret!\n")

    db = SessionLocal()
    session = db.query(AdminSession).filter_by(admin_user_id=admin_id).one()
    assert session.revoked_at is not None
    db.close()


def test_reset_admin_password_records_an_audit_row_with_no_acting_admin(tmp_path) -> None:
    admin_id = _create_admin()

    runner.invoke(cli, ["reset-admin-password", "locked-out@example.com"], input="New-Sup3rSecret!\nNew-Sup3rSecret!\n")

    db = SessionLocal()
    entry = db.query(AuditLog).filter_by(action="admin.reset_password").one()
    assert entry.admin_user_id is None
    assert entry.target_id == admin_id
    db.close()


def test_reset_admin_password_unknown_email_fails_cleanly(tmp_path) -> None:
    result = runner.invoke(
        cli, ["reset-admin-password", "nobody@example.com"], input="New-Sup3rSecret!\nNew-Sup3rSecret!\n"
    )
    assert result.exit_code == 1
    assert "no admin" in result.output.lower()


def test_disable_totp_clears_the_secret(tmp_path) -> None:
    admin_id = _create_admin(totp_secret_encrypted=encrypt_secret("JBSWY3DPEHPK3PXP"))

    result = runner.invoke(cli, ["disable-totp", "locked-out@example.com"])
    assert result.exit_code == 0, result.output
    assert "TOTP disabled" in result.output

    db = SessionLocal()
    row = db.get(AdminUser, admin_id)
    assert row.totp_secret_encrypted is None
    db.close()


def test_disable_totp_revokes_existing_sessions(tmp_path) -> None:
    admin_id = _create_admin(totp_secret_encrypted=encrypt_secret("JBSWY3DPEHPK3PXP"))
    _add_session(admin_id)

    runner.invoke(cli, ["disable-totp", "locked-out@example.com"])

    db = SessionLocal()
    session = db.query(AdminSession).filter_by(admin_user_id=admin_id).one()
    assert session.revoked_at is not None
    db.close()


def test_disable_totp_when_already_disabled_is_a_no_op(tmp_path) -> None:
    _create_admin(totp_secret_encrypted=None)

    result = runner.invoke(cli, ["disable-totp", "locked-out@example.com"])
    assert result.exit_code == 0
    assert "does not have TOTP enabled" in result.output


def test_disable_totp_unknown_email_fails_cleanly(tmp_path) -> None:
    result = runner.invoke(cli, ["disable-totp", "nobody@example.com"])
    assert result.exit_code == 1
    assert "no admin" in result.output.lower()
