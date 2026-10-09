# Upgrading

## Before you upgrade

Take a database backup first (see [backup-restore.md](backup-restore.md))
— schema migrations run automatically on startup (below), and while every
migration in this project is expected to be forward-only and safe, a
backup taken immediately before is the cheap insurance against the
unexpected. There is no supported downgrade path once a migration has
run against your database.

## Procedure

Read the release notes of every version between yours and the new one
first. Anything that needs a manual step is called out under
**Upgrading** there.

### A `git clone` install

Getting Started has you check out a release tag, which leaves the clone
on a detached `HEAD`, so `git pull` has nothing to pull into. Fetch the
new tags and check out the release you're upgrading to instead:

```bash
git fetch --tags
git checkout vX.Y.Z    # the release you're upgrading to
docker compose up -d --build
```

`.env`, `docker-compose.override.yml` and anything else you added (an
encryption-key file, `backups/`) aren't tracked by git, so a checkout
leaves them alone.

### A ZIP install

Download the new release's "Source code (zip)" from the
[Releases page](https://github.com/Heinekamp/smtp-credential-broker/releases)
and extract it next to the current folder. **The new code has to end up
in a folder with the same name as the old one.** Compose names its
volumes after the folder (`<folder>_app_data`, `<folder>_sasldb`, ...),
so starting the new version from a differently named folder would quietly
start over with an empty database and no local SMTP credentials. Assuming
the current install is in `smtp-credential-broker` and the new release
was extracted to `smtp-credential-broker-new`:

```bash
cd smtp-credential-broker
cp .env ../smtp-credential-broker-new/
cp docker-compose.override.yml ../smtp-credential-broker-new/ 2>/dev/null   # if you have one
# ...and any other files you added: an encryption-key file, backups/
docker compose down
cd ..
mv smtp-credential-broker smtp-credential-broker-old   # keep it: it's your rollback
mv smtp-credential-broker-new smtp-credential-broker
cd smtp-credential-broker
docker compose up -d --build
```

### Published images

`docker compose up -d --build` builds both images from the checked-out
source. Each release is also published as images
(`ghcr.io/heinekamp/smtp-credential-broker/app` and `.../postfix`, tagged
with the release's version and `latest`; `RELAY_IMAGE_TAG` in `.env`
picks the tag), so `docker compose pull` followed by `docker compose up
-d` is an alternative to building. If `pull` reports `unauthorized`, the
packages aren't public: log in first with `docker login ghcr.io` and a
GitHub personal access token with `read:packages` scope, or just build.

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
- Double-check the **Upgrading** section of each release's notes for
  anything to do after the upgrade — a genuinely breaking change is
  called out explicitly there rather than silently handled, since this
  project's default posture is that upgrades should not require operator
  intervention beyond this procedure.

## Rolling back

If a new version misbehaves, restore the pre-upgrade database backup
into a checkout of the previous version's code (`git checkout` its tag,
or move the kept `-old` folder back into place) and start that instead —
there is no automatic downgrade migration. This is the reason the backup
in "Before you upgrade" above isn't optional: it's the only rollback path
that exists.
