import typer

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.admin import AdminUser

cli = typer.Typer(help="Managed SMTP Relay administrative CLI.")


@cli.command("create-admin")
def create_admin(
    email: str = typer.Option(..., prompt=True),
    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True),
) -> None:
    """Bootstrap the first admin account.

    There is no "Initial Setup" UI yet (a later stage), so this is the only
    way to create an admin account and manually exercise Login in this
    slice. It also seeds the `relay` CLI architecture.md §8 already commits
    to — later stages add `doctor`, `validate-config`, `generate-config`,
    `test-upstream`, and `queue` here rather than as one-off scripts.
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


if __name__ == "__main__":
    cli()
