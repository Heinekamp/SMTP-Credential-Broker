# Upgrading

## Before you upgrade

Take a database backup first (see [backup-restore.md](backup-restore.md))
— schema migrations run automatically on startup (below), and while every
migration in this project is expected to be forward-only and safe, a
backup taken immediately before is the cheap insurance against the
unexpected. There is no supported downgrade path once a migration has
run against your database.

## Procedure

```bash
git pull
docker compose pull    # if pulling published images rather than building locally
docker compose up -d --build
```

That's the whole procedure for a normal release. The `app` container's
entrypoint runs `alembic upgrade head` on every start, before serving any
traffic, so schema migrations are applied automatically — there is no
separate manual migration step. It also regenerates and re-applies the
Postfix config on start, so a Postfix-side config format change ships the
same way.

Watch it come up the same way you would on first install:

```bash
docker compose ps
docker compose logs -f app
```

Both containers should reach `healthy` within about a minute; a longer
first-boot delay than usual can mean a migration is doing real work
against a larger database than a fresh install would have.

## What to check after upgrading

- Log in and confirm the dashboard loads and shows the expected upstream
  accounts/senders/local users — this alone confirms migrations applied
  cleanly and the encryption key still decrypts existing secrets.
- Send one real test message through an existing local user's
  credentials — the one check that actually exercises the Postfix-facing
  path end-to-end, not just the web UI.
- Check the release notes (or `git log` between the two versions, if
  there isn't yet a formal changelog) for anything the release calls out
  as needing a manual step — a genuinely breaking change would be called
  out explicitly there rather than silently handled, since this project's
  default posture is that upgrades should not require operator
  intervention beyond this procedure.

## Rolling back

If a new version misbehaves, restore the pre-upgrade database backup
into a checkout of the previous version's code and start that instead —
there is no automatic downgrade migration. This is the reason the backup
in "Before you upgrade" above isn't optional: it's the only rollback path
that exists.
