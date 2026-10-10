# Backup and Restore

Three things must be backed up for a restore to work completely:

1. **The database** (`app_data` volume — `app.db` and its WAL/SHM
   siblings under SQLite's default settings).
2. **The encryption key** (`RELAY_ENCRYPTION_KEY` / the file behind
   `RELAY_ENCRYPTION_KEY_FILE`). A database backup without it is useless
   — every upstream account password and every admin's TOTP secret is
   ciphertext that only that key can open (security-model.md §2), and
   there is no recovery path if it's lost. Keep it somewhere durable and
   separate from the database backup itself (a password manager, a
   sealed secret store, printed and locked in a drawer — anywhere that
   doesn't get deleted in the same incident that takes out the database).
3. **The local SMTP credentials** (`sasldb` volume — `sasldb2`). The
   database only keeps a one-way hash of each local user's password; the
   credential Postfix actually checks at `AUTH` time lives only here
   (postfix-architecture.md §5). It can't be rebuilt from the database.
   Without it, every local user has to get a new password
   (**Regenerate** on the Local SMTP Users screen) and every service
   using one has to be reconfigured with it.

The database part of this procedure has been tested end-to-end against a
real simulated disaster (deleting the `app_data` volume outright and
restoring from a backup taken minutes earlier), including verifying that
restored data matches byte-for-byte and that the backed-up key correctly
decrypts the restored secrets.

## Backing up

Don't just copy `app.db` off the filesystem — under WAL mode a plain file
copy can catch the database mid-write and produce a corrupt or
inconsistent backup. Use SQLite's own online backup API instead, which is
safe to run against a live database with no downtime:

```bash
docker compose exec app python3 -c "
import sqlite3
src = sqlite3.connect('/data/app.db')
dst = sqlite3.connect('/data/backup.db')
src.backup(dst)
src.close()
dst.close()
"
docker compose cp app:/data/backup.db ./backups/app-$(date +%Y%m%d-%H%M%S).db
docker compose exec app rm /data/backup.db
```

Then the local SMTP credentials, at the same time so the two match:

```bash
docker compose cp postfix:/var/lib/postfix-sasldb/sasldb2 ./backups/sasldb2-$(date +%Y%m%d-%H%M%S)
docker compose exec postfix sasldblistusers2 -f /var/lib/postfix-sasldb/sasldb2   # lists every local user
```

That file is only rewritten when a local user is created, deleted,
disabled, re-enabled or gets a new password, so a plain copy is safe as
long as nobody is doing one of those at that moment.

Run this on whatever schedule matches your actual tolerance for lost
data (cron, a systemd timer, your orchestrator's own backup hooks — this
project doesn't prescribe one). Confirm at the same time that your
`RELAY_ENCRYPTION_KEY` (or the file it points at) is still backed up and
still matches what's running — if it was ever rotated
(`relay rotate-encryption-key`), the backed-up key must be the *current*
one, not a stale copy from before the rotation.

## Restoring

1. Stop the stack so nothing writes to the database during restore:
   ```bash
   docker compose down
   ```
2. Restore the database file into the `app_data` volume. `docker compose
   run` mounts the service's own volumes (creating them if they're gone),
   so there's no volume name to look up:
   ```bash
   docker compose run --rm --no-deps -v "$(pwd)/backups:/backups" --entrypoint sh app \
     -c 'rm -f /data/app.db-wal /data/app.db-shm && cp /backups/app-20260101-020000.db /data/app.db'
   ```
   The `rm` matters when restoring over a database that still exists:
   leftover `app.db-wal`/`app.db-shm` files from the old database must
   not be replayed onto the restored one. The backup itself is a single
   file — the online backup API already folds any in-flight WAL content
   into it.
3. Restore the local SMTP credentials into the `sasldb` volume, from the
   copy taken alongside that database backup:
   ```bash
   docker compose run --rm --no-deps -v "$(pwd)/backups:/backups" --entrypoint cp postfix \
     /backups/sasldb2-20260101-020000 /var/lib/postfix-sasldb/sasldb2
   ```
   `postfix` installs it as its live credential store on its next start.
   If the copy is newer or older than the database backup, the two are
   reconciled at startup only in one direction: any credential with no
   enabled local user in the database behind it is removed, but a local
   user whose credential is missing stays unable to log in until you
   **Regenerate** its password.
4. Confirm `RELAY_ENCRYPTION_KEY` (or `RELAY_ENCRYPTION_KEY_FILE`) is set
   to the key that was current when this backup was taken — restoring the
   database with the wrong key doesn't fail loudly at startup; it fails
   the first time something tries to decrypt a secret (surfaced as a 503
   with "invalid encryption key" — see
   [troubleshooting.md](troubleshooting.md)).
5. Start the stack back up:
   ```bash
   docker compose up -d
   ```
   Give it a few seconds — the entrypoint runs `alembic upgrade head`
   and regenerates the Postfix config on boot, so an immediate
   connection attempt can see a brief empty reply before it's ready
   (`docker compose logs -f app` to watch it settle).
6. Verify: log in, confirm the upstream accounts/senders/local users you
   expect are present, and use an existing local SMTP user's credentials
   to send a real test message end-to-end. A successful send is the only
   real proof that both the encryption key matches the restored
   ciphertext and the restored `sasldb2` holds that user's credential —
   the UI alone shows neither.

## What's not covered by this procedure

- **Postfix's mail queue** (in-flight messages not yet delivered) is not
  backed up by this procedure — there's no explicit backup step for it —
  but it *is* persisted, in the `postfix_queue` volume, so it survives a
  deploy the same way the database does. If you stop the stack with mail
  still queued (deferred, or simply paced by a rate-limited upstream
  account — postfix-architecture.md §10), it resumes exactly where it
  left off once `postfix` starts back up, including across a full
  `docker compose down` + `up` that recreates the container, not just a
  plain restart of the same one (issue #121 — before this volume
  existed, only a plain restart was actually durable; a real deploy's
  container recreation silently discarded whatever was still queued).
- **`mail_log` history** is part of the database backup above like any
  other table — no separate step needed. Postfix's raw log, which the app
  reads into it every minute, is on its own `postfix_log` volume, so a
  deploy doesn't lose lines that haven't been read yet. It's not worth
  backing up: anything already ingested is in the database.
- **TLS certificates** in the `postfix_tls` volume: if you've provisioned
  a Let's Encrypt certificate from Settings → TLS Certificate (see
  [configuration.md](configuration.md#tls-certificates)), the certificate
  and its private key are also stored encrypted in the database — the
  volume itself no longer needs a separate backup, since an app-startup
  check re-populates it from the database automatically if it's ever lost
  or the `postfix` container is recreated. If you've instead mounted a
  real certificate from another CA directly, back that up separately, the
  same as before this feature existed. A fresh deployment on neither path
  just regenerates the self-signed placeholder automatically, so that
  default case is still not part of the disaster-recovery-critical set
  the way the database and encryption key are.
