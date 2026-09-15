import base64
import os
from pathlib import Path

import typer

from app.core.audit import record_audit
from app.core.config_generator import generate_and_apply
from app.core.encryption import (
    DecryptionFailed,
    EncryptionKeyNotConfigured,
    decrypt_secret,
    decrypt_with_key,
    encrypt_with_key,
    parse_key_file,
)
from app.core.health import run_health_check
from app.core.postfix_control import PostfixControlError, queue_list
from app.core.security import hash_password
from app.core.sessions import revoke_all_sessions_for_admin
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


@cli.command("reset-admin-password")
def reset_admin_password(
    email: str = typer.Argument(..., help="Email of the admin to reset"),
    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True),
) -> None:
    """Break-glass recovery for a forgotten admin password — with no web
    UI path to reset another admin's credentials (by design: no admin can
    reset another admin's password from the API either) and no
    "unlock"/self-service reset flow, this was previously only possible
    by hand-editing the database. Revokes every one of that admin's
    active sessions, same as a self-service password change (a stolen
    session is exactly the kind of thing a forgotten-password recovery
    should not leave usable)."""
    db = SessionLocal()
    try:
        admin = db.query(AdminUser).filter(AdminUser.email == email).one_or_none()
        if admin is None:
            typer.echo(f"No admin with email {email!r}.", err=True)
            raise typer.Exit(code=1)
        admin.password_hash = hash_password(password)
        revoke_all_sessions_for_admin(db, admin.id)
        record_audit(
            db, admin_user_id=None, action="admin.reset_password", target_type="admin_user", target_id=admin.id
        )
        db.commit()
        typer.echo(f"Password reset for {email}.")
    finally:
        db.close()


@cli.command("disable-totp")
def disable_totp(email: str = typer.Argument(..., help="Email of the admin to disable TOTP for")) -> None:
    """Break-glass recovery for a lost authenticator device — the API
    only ever exposes /me/totp/remove (self-service, requires already
    being logged in), so a locked-out admin with no other admin account
    had no way back in short of hand-editing the database. Revokes every
    active session, same rationale as reset-admin-password."""
    db = SessionLocal()
    try:
        admin = db.query(AdminUser).filter(AdminUser.email == email).one_or_none()
        if admin is None:
            typer.echo(f"No admin with email {email!r}.", err=True)
            raise typer.Exit(code=1)
        if admin.totp_secret_encrypted is None:
            typer.echo(f"{email} does not have TOTP enabled.")
            return
        admin.totp_secret_encrypted = None
        revoke_all_sessions_for_admin(db, admin.id)
        record_audit(db, admin_user_id=None, action="admin.totp_remove", target_type="admin_user", target_id=admin.id)
        db.commit()
        typer.echo(f"TOTP disabled for {email}.")
    finally:
        db.close()


@cli.command("generate-encryption-key")
def generate_encryption_key() -> None:
    """Prints a fresh base64-encoded 32-byte key suitable for
    RELAY_ENCRYPTION_KEY. Generated, not derived from anything — there is
    no way to recover it later if it's lost (security-model.md §2), so
    store it somewhere durable immediately."""
    typer.echo(base64.b64encode(os.urandom(32)).decode())


@cli.command("rotate-encryption-key")
def rotate_encryption_key(
    old_key_file: Path = typer.Option(..., exists=True, help="Path to the current base64-encoded 32-byte key"),
    new_key_file: Path = typer.Option(..., exists=True, help="Path to the new base64-encoded 32-byte key"),
) -> None:
    """Re-encrypts every stored secret (upstream account passwords, admin
    TOTP secrets) from the old key to the new one, in a single transaction
    (security-model.md §2). Nothing is committed until every row has been
    successfully decrypted with the old key and re-encrypted with the new
    one — any failure aborts the whole operation and leaves the database
    exactly as it was; there is no partial-rotation state."""
    old_key = parse_key_file(old_key_file)
    new_key = parse_key_file(new_key_file)

    db = SessionLocal()
    try:
        accounts = db.query(UpstreamAccount).all()
        admins_with_totp = db.query(AdminUser).filter(AdminUser.totp_secret_encrypted.is_not(None)).all()

        try:
            for account in accounts:
                plaintext = decrypt_with_key(account.encrypted_password, old_key)
                account.encrypted_password = encrypt_with_key(plaintext, new_key)
            for admin in admins_with_totp:
                plaintext = decrypt_with_key(admin.totp_secret_encrypted, old_key)
                admin.totp_secret_encrypted = encrypt_with_key(plaintext, new_key)
        except DecryptionFailed as exc:
            db.rollback()
            typer.echo(f"Rotation aborted, database left unchanged: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        db.commit()
        typer.echo(
            f"Rotated {len(accounts)} upstream account credential(s) and "
            f"{len(admins_with_totp)} TOTP secret(s)."
        )
    finally:
        db.close()


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


@cli.command("validate-config")
def validate_config() -> None:
    """Renders the desired Postfix config from current DB state without
    installing anything — a pure dry run, safe to run anytime (spec §27)."""
    db = SessionLocal()
    try:
        outcome = generate_and_apply(db, triggered_by_admin_id=None, dry_run=True)
        typer.echo(outcome.validation_detail)
        for warning in outcome.warnings:
            typer.echo(f"WARNING: {warning}")
    finally:
        db.close()


@cli.command("generate-config")
def generate_config() -> None:
    """Runs the full architecture.md §5 pipeline: render, validate,
    atomically install, and reload only if main.cf/master.cf changed.
    This is the same operation the Settings UI's "regenerate" action (and
    every senders/local-users/permissions mutation, in later stages) would
    trigger, exposed here so the relay is manageable without the web UI."""
    db = SessionLocal()
    try:
        try:
            outcome = generate_and_apply(db, triggered_by_admin_id=None)
        except PostfixControlError as exc:
            typer.echo(f"Could not reach the Postfix control surface: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        typer.echo(f"Generation #{outcome.generation_id}: {'PASS' if outcome.success else 'FAIL'}")
        if outcome.validation_detail:
            typer.echo(outcome.validation_detail)
        for warning in outcome.warnings:
            typer.echo(f"WARNING: {warning}")
        typer.echo(f"Reloaded: {outcome.reloaded}")
        if not outcome.success:
            raise typer.Exit(code=1)
    finally:
        db.close()


@cli.command("queue")
def queue_cmd() -> None:
    """Lists the live Postfix queue (wraps `postqueue -j` via the control
    surface) — architecture.md §8, keeps the queue manageable without the
    web UI."""
    try:
        entries = queue_list()
    except PostfixControlError as exc:
        typer.echo(f"Could not reach the Postfix control surface: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not entries:
        typer.echo("Queue is empty.")
        return
    for entry in entries:
        typer.echo(f"{entry['queue_id']}  {entry.get('queue_name', ''):10s}  {entry.get('sender', '')}")
        for rcpt in entry.get("recipients", []):
            reason = f" ({rcpt['delay_reason']})" if rcpt.get("delay_reason") else ""
            typer.echo(f"    -> {rcpt.get('address', '')}{reason}")


@cli.command("doctor")
def doctor() -> None:
    """Runs the same real capability checks as GET /api/health
    (architecture.md §7), human-readable — keeps the relay diagnosable
    without the web UI (spec §27). Exits non-zero if anything is actually
    unhealthy (a never-configured, fresh install is reported but doesn't
    fail this command — see core/health.py)."""
    db = SessionLocal()
    try:
        report = run_health_check(db)

        def _line(label: str, ok: bool, detail: str = "") -> None:
            marker = "PASS" if ok else "FAIL"
            suffix = f": {detail}" if detail else ""
            typer.echo(f"[{marker}] {label}{suffix}")

        _line("Database reachable", report.database.ok, report.database.detail)
        _line("Postfix control surface reachable", report.postfix_reachable.ok, report.postfix_reachable.detail)
        _line("Postfix running", report.postfix_running.ok, report.postfix_running.detail)
        _line(
            "Last config generation attempt",
            report.last_generation_result != "fail",
            f"result: {report.last_generation_result}",
        )
        _line("Config in sync with database", report.config_in_sync.ok, report.config_in_sync.detail)

        typer.echo(f"Overall: {report.status}")
        if report.status != "ok":
            raise typer.Exit(code=1)
    finally:
        db.close()


if __name__ == "__main__":
    cli()
