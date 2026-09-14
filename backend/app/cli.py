import base64
import os

import typer

from app.core.encryption import DecryptionFailed, EncryptionKeyNotConfigured, decrypt_secret
from app.core.security import hash_password
from app.core.test_connection import test_upstream_connection
from app.db.session import SessionLocal
from app.models.admin import AdminUser
from app.models.upstream import UpstreamAccount

cli = typer.Typer(help="Managed SMTP Relay administrative CLI.")


@cli.command("create-admin")
def create_admin(
    email: str = typer.Option(..., prompt=True),
    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True),
) -> None:
    """Bootstrap the first admin account.

    There is no "Initial Setup" UI yet (a later stage), so this is the only
    way to create an admin account and manually exercise Login in this
    slice.
    """
    db = SessionLocal()
    try:
        if db.query(AdminUser).filter(AdminUser.email == email).one_or_none() is not None:
            typer.echo(f"An admin with email {email!r} already exists.", err=True)
            raise typer.Exit(code=1)
        admin = AdminUser(email=email, password_hash=hash_password(password))
        db.add(admin)
        db.commit()
        typer.echo(f"Created admin account: {email}")
    finally:
        db.close()


@cli.command("generate-encryption-key")
def generate_encryption_key() -> None:
    """Prints a fresh base64-encoded 32-byte key suitable for
    RELAY_ENCRYPTION_KEY. Generated, not derived from anything — there is
    no way to recover it later if it's lost (security-model.md §2), so
    store it somewhere durable immediately."""
    typer.echo(base64.b64encode(os.urandom(32)).decode())


@cli.command("test-upstream")
def test_upstream(account_id: int = typer.Argument(..., help="Upstream account ID")) -> None:
    """Runs the same DNS/TCP/TLS/greeting/AUTH diagnostic as the UI's "Test
    Connection" button, from the command line — keeps the relay
    manageable if the web UI is unavailable (spec §27)."""
    db = SessionLocal()
    try:
        account = db.get(UpstreamAccount, account_id)
        if account is None:
            typer.echo(f"No upstream account with id {account_id}.", err=True)
            raise typer.Exit(code=1)
        try:
            password = decrypt_secret(account.encrypted_password)
        except (EncryptionKeyNotConfigured, DecryptionFailed) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc

        result = test_upstream_connection(
            host=account.host,
            port=account.port,
            tls_mode=account.tls_mode,
            username=account.username,
            password=password,
        )
        for step in result.steps:
            typer.echo(f"[{'PASS' if step.passed else 'FAIL'}] {step.name}: {step.detail}")
        if not result.success:
            raise typer.Exit(code=1)
    finally:
        db.close()


if __name__ == "__main__":
    cli()
