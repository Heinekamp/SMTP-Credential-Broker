# Backup and Restore

Two things must be backed up, separately, for a restore to work at all:

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

This procedure has been tested end-to-end against a real simulated
disaster (deleting the `app_data` volume outright and restoring from a
backup taken minutes earlier), including verifying that restored data
matches byte-for-byte and that the backed-up key correctly decrypts the
restored secrets.

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
2. Restore the database file into the (still-existing, or recreated)
   `app_data` volume:
   ```bash
   docker compose up -d app_data_placeholder 2>/dev/null || true
   docker run --rm -v smtp-manager_app_data:/data -v "$(pwd)/backups":/backups \
     alpine cp /backups/app-20260101-020000.db /data/app.db
   ```
   (Adjust the volume name to match `docker volume ls` on your host —
   Compose prefixes it with the project/directory name.) If `app.db-wal`
   or `app.db-shm` files exist alongside the live database at backup
   time, they are not part of this backup and don't need to be restored
   — the online backup API already folds any in-flight WAL content into
   the single `backup.db` file it produces.
3. Confirm `RELAY_ENCRYPTION_KEY` (or `RELAY_ENCRYPTION_KEY_FILE`) is set
   to the key that was current when this backup was taken — restoring the
   database with the wrong key doesn't fail loudly at startup; it fails
   the first time something tries to decrypt a secret (surfaced as a 503
   with "invalid encryption key" — see
   [troubleshooting.md](troubleshooting.md)).
4. Start the stack back up:
   ```bash
   docker compose up -d
   ```
   Give it a few seconds — the entrypoint runs `alembic upgrade head`
   and regenerates the Postfix config on boot, so an immediate
   connection attempt can see a brief empty reply before it's ready
   (`docker compose logs -f app` to watch it settle).
5. Verify: log in, confirm the upstream accounts/senders/local users you
   expect are present, and use an existing local SMTP user's credentials
   to send a real test message end-to-end. A successful send is the only
   real proof the restored encryption key actually matches the restored
   ciphertext — the UI alone won't tell you a decrypt is silently
   failing until something tries to use the secret.

## What's not covered by this procedure

- **Postfix's mail queue** (in-flight messages not yet delivered) is not
  backed up by this procedure — it lives in the `postfix` container's
  own filesystem, not a named volume, and is expected to drain on its
  own before any planned maintenance. If you stop the stack with mail
  still queued, it resumes delivery attempts from where it left off once
  `postfix` starts back up (Postfix's queue is durable across container
  restarts as long as its filesystem layer isn't discarded).
- **`mail_log` history** is part of the database backup above like any
  other table — no separate step needed.
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
