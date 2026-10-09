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

from app.cli import cli, encrypted_columns
from app.core.encryption import decrypt_with_key, encrypt_with_key
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.admin import AdminUser
from app.models.enums import TlsMode
from app.models.sender import Sender
from app.models.settings import RelaySettings
from app.models.tls import TlsCertificateState, TlsPendingManualChallenge
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
        # senders.upstream_account_id has no ON DELETE action, so any
        # sender left behind by another shared-engine test file (e.g.
        # test_alert_email.py) must be cleared first, or deleting
        # upstream_accounts below hits a FOREIGN KEY constraint failure.
        db.query(Sender).delete()
        db.query(UpstreamAccount).delete()
        db.query(AdminUser).delete()
        db.query(RelaySettings).delete()
        db.query(TlsCertificateState).delete()
        db.query(TlsPendingManualChallenge).delete()
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
    assert "upstream_accounts.encrypted_password: 1" in result.output

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
    assert "admin_users.totp_secret_encrypted: 1" in result.output

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


def test_every_encrypted_column_is_known() -> None:
    """Pins the set rotate-encryption-key discovers (#179). Rotation itself
    finds encrypted columns from the metadata, so a new one is rotated
    automatically — this only makes adding one a deliberate, visible change
    (and a reminder to cover it in the test below)."""
    assert sorted(f"{t.name}.{c.name}" for t, c in encrypted_columns()) == [
        "admin_users.totp_secret_encrypted",
        "relay_settings.tls_cloudflare_api_token_encrypted",
        "tls_certificate_state.acme_account_key_encrypted",
        "tls_certificate_state.encrypted_key_pem",
        "tls_pending_manual_challenge.encrypted_account_key_pem",
        "tls_pending_manual_challenge.encrypted_cert_key_pem",
        "upstream_accounts.encrypted_password",
    ]


def test_rotates_the_cloudflare_token_and_tls_keys(tmp_path) -> None:
    """Regression test for #179: these five were left under the old key, so
    certificate renewal failed for good after any rotation."""
    import datetime

    db = SessionLocal()
    db.add(RelaySettings(id=1, tls_cloudflare_api_token_encrypted=_encrypt_under("cf-token", OLD_KEY)))
    db.add(
        TlsCertificateState(
            id=1,
            encrypted_key_pem=_encrypt_under("cert-key", OLD_KEY),
            acme_account_key_encrypted=_encrypt_under("acme-key", OLD_KEY),
        )
    )
    db.add(
        TlsPendingManualChallenge(
            id=1,
            domain="relay.example.com",
            record_name="_acme-challenge.relay.example.com",
            record_value="v",
            order_json="{}",
            encrypted_cert_key_pem=_encrypt_under("pending-cert-key", OLD_KEY),
            encrypted_account_key_pem=_encrypt_under("pending-account-key", OLD_KEY),
            account_uri="https://acme.example/acct/1",
            directory_url="https://acme.example/directory",
            expires_at=datetime.datetime(2030, 1, 1),
        )
    )
    db.commit()
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
    assert "Rotated 5 stored secret(s)" in result.output

    new_key = base64.b64decode(NEW_KEY)
    db = SessionLocal()
    settings_row = db.get(RelaySettings, 1)
    cert_state = db.get(TlsCertificateState, 1)
    pending = db.get(TlsPendingManualChallenge, 1)
    assert decrypt_with_key(settings_row.tls_cloudflare_api_token_encrypted, new_key) == "cf-token"
    assert decrypt_with_key(cert_state.encrypted_key_pem, new_key) == "cert-key"
    assert decrypt_with_key(cert_state.acme_account_key_encrypted, new_key) == "acme-key"
    assert decrypt_with_key(pending.encrypted_cert_key_pem, new_key) == "pending-cert-key"
    assert decrypt_with_key(pending.encrypted_account_key_pem, new_key) == "pending-account-key"
    db.close()
