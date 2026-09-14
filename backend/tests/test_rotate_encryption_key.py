"""`relay rotate-encryption-key` (security-model.md §2). Exercised via
Typer's CliRunner against the app's real `app.db.session.SessionLocal` —
the same one the CLI command itself uses — rather than the `db_session`
fixture's isolated temp-file engine, since CLI commands never go through
FastAPI's dependency-injected `get_db`. SQLAlchemy keeps one shared
connection alive for a `sqlite:///:memory:` URL within a single thread
(`SingletonThreadPool`), so this file's own fixture creates the schema
once and clears the relevant tables before each test to avoid leaking
rows between tests in this file.
"""

import base64

import pytest
from typer.testing import CliRunner

from app.cli import cli
from app.core.encryption import decrypt_with_key, encrypt_with_key
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.admin import AdminUser
from app.models.enums import TlsMode
from app.models.upstream import UpstreamAccount

runner = CliRunner()

OLD_KEY = base64.b64encode(b"1" * 32).decode()
NEW_KEY = base64.b64encode(b"2" * 32).decode()
WRONG_KEY = base64.b64encode(b"9" * 32).decode()


@pytest.fixture(autouse=True)
def _clean_shared_db() -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        db.query(UpstreamAccount).delete()
        db.query(AdminUser).delete()
        db.commit()
    finally:
        db.close()


def _key_file(tmp_path, name: str, key_b64: str) -> str:
    path = tmp_path / name
    path.write_text(key_b64)
    return str(path)


def _encrypt_under(plaintext: str, key_b64: str) -> bytes:
    return encrypt_with_key(plaintext, base64.b64decode(key_b64))


def test_rotates_upstream_account_passwords(tmp_path) -> None:
    db = SessionLocal()
    account = UpstreamAccount(
        name="STRATO",
        host="smtp.strato.de",
        port=587,
        tls_mode=TlsMode.starttls,
        username="a@example.com",
        encrypted_password=_encrypt_under("upstream-secret", OLD_KEY),
        enabled=True,
    )
    db.add(account)
    db.commit()
    account_id = account.id
    db.close()

    result = runner.invoke(
        cli,
        [
            "rotate-encryption-key",
            "--old-key-file",
            _key_file(tmp_path, "old.key", OLD_KEY),
            "--new-key-file",
            _key_file(tmp_path, "new.key", NEW_KEY),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "1 upstream account credential" in result.output

    db = SessionLocal()
    rotated = db.get(UpstreamAccount, account_id)
    assert decrypt_with_key(rotated.encrypted_password, base64.b64decode(NEW_KEY)) == "upstream-secret"
    db.close()


def test_rotates_admin_totp_secrets(tmp_path) -> None:
    db = SessionLocal()
    admin = AdminUser(
        email="admin@example.com",
        password_hash="irrelevant",
        totp_secret_encrypted=_encrypt_under("JBSWY3DPEHPK3PXP", OLD_KEY),
    )
    db.add(admin)
    db.commit()
    admin_id = admin.id
    db.close()

    result = runner.invoke(
        cli,
        [
            "rotate-encryption-key",
            "--old-key-file",
            _key_file(tmp_path, "old.key", OLD_KEY),
            "--new-key-file",
            _key_file(tmp_path, "new.key", NEW_KEY),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "1 TOTP secret" in result.output

    db = SessionLocal()
    rotated = db.get(AdminUser, admin_id)
    assert decrypt_with_key(rotated.totp_secret_encrypted, base64.b64decode(NEW_KEY)) == "JBSWY3DPEHPK3PXP"
    db.close()


def test_wrong_old_key_aborts_and_leaves_database_untouched(tmp_path) -> None:
    db = SessionLocal()
    account = UpstreamAccount(
        name="STRATO",
        host="smtp.strato.de",
        port=587,
        tls_mode=TlsMode.starttls,
        username="a@example.com",
        encrypted_password=_encrypt_under("upstream-secret", OLD_KEY),
        enabled=True,
    )
    db.add(account)
    db.commit()
    account_id = account.id
    original_ciphertext = account.encrypted_password
    db.close()

    result = runner.invoke(
        cli,
        [
            "rotate-encryption-key",
            "--old-key-file",
            _key_file(tmp_path, "old.key", WRONG_KEY),  # not the key this row was encrypted with
            "--new-key-file",
            _key_file(tmp_path, "new.key", NEW_KEY),
        ],
    )
    assert result.exit_code == 1
    assert "aborted" in result.output.lower()

    # Nothing changed — the row is still decryptable with the *original*
    # key, exactly as if the command had never run.
    db = SessionLocal()
    untouched = db.get(UpstreamAccount, account_id)
    assert untouched.encrypted_password == original_ciphertext
    assert decrypt_with_key(untouched.encrypted_password, base64.b64decode(OLD_KEY)) == "upstream-secret"
    db.close()


def test_one_bad_row_aborts_the_whole_batch_including_good_rows(tmp_path) -> None:
    """The "single transaction" guarantee only means something if a
    failure partway through a multi-row rotation doesn't leave the
    earlier rows already rotated."""
    db = SessionLocal()
    good = UpstreamAccount(
        name="Good",
        host="smtp.example.com",
        port=587,
        tls_mode=TlsMode.starttls,
        username="good@example.com",
        encrypted_password=_encrypt_under("good-secret", OLD_KEY),
        enabled=True,
    )
    bad = UpstreamAccount(
        name="Bad",
        host="smtp.example.com",
        port=587,
        tls_mode=TlsMode.starttls,
        username="bad@example.com",
        encrypted_password=_encrypt_under("bad-secret", WRONG_KEY),  # encrypted under a DIFFERENT key
        enabled=True,
    )
    db.add_all([good, bad])
    db.commit()
    good_id, bad_id = good.id, bad.id
    good_ciphertext = good.encrypted_password
    db.close()

    result = runner.invoke(
        cli,
        [
            "rotate-encryption-key",
            "--old-key-file",
            _key_file(tmp_path, "old.key", OLD_KEY),
            "--new-key-file",
            _key_file(tmp_path, "new.key", NEW_KEY),
        ],
    )
    assert result.exit_code == 1

    db = SessionLocal()
    assert db.get(UpstreamAccount, good_id).encrypted_password == good_ciphertext
    assert db.get(UpstreamAccount, bad_id) is not None
    db.close()


def test_malformed_key_file_fails_cleanly(tmp_path) -> None:
    bad_key_path = tmp_path / "bad.key"
    bad_key_path.write_text("not-valid-base64!!!")

    result = runner.invoke(
        cli,
        [
            "rotate-encryption-key",
            "--old-key-file",
            str(bad_key_path),
            "--new-key-file",
            _key_file(tmp_path, "new.key", NEW_KEY),
        ],
    )
    assert result.exit_code != 0
