# Troubleshooting

## Startup

### `app` never becomes healthy

Check `docker compose logs app`. The entrypoint runs migrations and an
initial config generation before serving; if `postfix`'s control socket
isn't listening yet, this is retried a few times with a logged warning —
that alone is not a fault. If it never recovers:

- Confirm `postfix` is actually healthy first (`docker compose ps`) —
  `app` depends on it functionally even though Compose's `depends_on`
  only waits for container start, not socket readiness.
- Confirm `RELAY_ENCRYPTION_KEY` (or `_FILE`) is set and valid — see
  "invalid encryption key" below.

### `postfix` never becomes healthy / crashes on start

Two real causes have shown up during development, both from incomplete
base-image assumptions rather than this project's own config:

- **`postfix-lmdb` missing**: some Debian-slim base images don't ship the
  LMDB backend Postfix's map lookups need out of the box; the container
  build must install it explicitly. If you've forked `postfix/Dockerfile`
  and this regresses, look for a "table type not supported" error in the
  Postfix logs — it's this, not a config bug.
- **`postlog` missing / `postfix status` failing oddly**: seen when a
  base image trims non-essential Postfix binaries; needed for the
  healthcheck (`postfix status`) and for logging to work at all.

If neither applies and startup just crashes with a `main.cf` parse error
immediately after a config change, that's `relay generate-config` having
pushed something `postconf` itself would have rejected — check
`config_generations.validation_detail` via the Settings screen, since
validation is supposed to catch this before it's ever applied
(architecture.md §5); a crash despite that means a mismatch between what
`postconf -n` validates and what Postfix accepts at actual startup, worth
reporting as a bug in this project rather than working around.

### SASL authentication fails for every local user, even correct ones

Most often a Cyrus SASL `auxprop`/socket permission issue rather than a
credential issue — a symptom is *every* local user failing, not just one.
Check that the `postfix` container's `saslauthd`/`sasldb2` file
permissions weren't altered by a bind-mount override, and that the SASL
group the Postfix `smtpd` process runs under still has read access to
`sasldb2` after any custom volume changes.

### A local user's connection settings show the wrong host after changing `RELAY_SUBMISSION_HOST`

`inet_interfaces` and the SASL realm are derived from this variable at
config-generation time — changing it in `.env` and restarting `postfix`
alone does not retroactively re-issue existing credentials under the new
realm. Run `relay generate-config` (or trigger "Generate & Apply" from
Settings) after changing it, and expect existing local users' stored
credentials to need regeneration too, since `saslpasswd2` ties them to
the realm at creation time.

## Encryption

### "Encryption key not configured" / 503 on account creation, TOTP enroll, etc.

Neither `RELAY_ENCRYPTION_KEY` nor `RELAY_ENCRYPTION_KEY_FILE` resolved
to a valid 32-byte base64 key at startup. Generate one:
`docker compose run --rm app relay generate-encryption-key`, set it, and
restart `app`.

### "Invalid encryption key" / decryption failures after a restore

The database was restored with a different key than the one it was
encrypted under — see [backup-restore.md](backup-restore.md)'s reminder
to keep the key backup in sync with the database backup, and check
whether `relay rotate-encryption-key` was run after this particular
backup was taken (the key it needs is whatever was *current* at backup
time, not necessarily what's live now).

### `relay rotate-encryption-key` aborts partway through

By design — the command decrypts every row with the old key before
re-encrypting anything, and rolls back the entire operation if even one
row fails, rather than leaving some rows on the old key and some on the
new one. An abort means `--old-key-file` doesn't actually match what the
data was encrypted under; double-check you're not passing the *new* key
as old, or a key from before a previous rotation.

## Web UI / login

### Logging back in after logging out sometimes shows the login form still, despite a valid session

A real bug found and fixed during Stage 8 testing: React Query's
`invalidateQueries` only marks a query stale — it does not force a
refetch for a query with no currently-mounted observer, which is exactly
the situation right after login before navigation completes. Fixed by
switching to `refetchQueries` in both `Login.tsx` and `Setup.tsx`,
released in the same version as TOTP support. If you're running an older
build and see this, upgrading resolves it — there's no workaround at the
config level.

### TOTP login says "Invalid credentials" for a wrong code instead of a clearer message

Also fixed in the same pass: a wrong TOTP code now reports "Invalid
authentication code" distinctly from a wrong password. Older builds show
the generic message for both; the underlying rate-limiting and rejection
behavior was always correct, only the message was misleading.

### Repeated login attempts start returning a lockout even with the correct password/code

Working as designed (security-model.md §5) — both wrong-password and
wrong-TOTP-code attempts count toward the same per-account and per-IP
rate limiter (`RELAY_RATE_LIMIT_THRESHOLDS`). Wait out the window, or
adjust the threshold if it's genuinely too aggressive for your environment
(see [configuration.md](configuration.md)) — there is no admin-facing
"unlock" action by design, since that would itself be a brute-force
bypass vector.

### Locked out? (forgotten password or lost authenticator device)

No admin can reset another admin's password or TOTP from the web UI or
API — by design, the same way there's no admin-facing rate-limit
"unlock" above. If the admin who forgot their password or lost their
authenticator is the only admin (or every other admin account is also
unreachable), recover from the command line instead:

```bash
docker compose exec app relay reset-admin-password admin@example.com
docker compose exec app relay disable-totp admin@example.com
```

`reset-admin-password` prompts for (and confirms) a new password;
`disable-totp` removes the TOTP secret so the next login only needs the
password. Both revoke every one of that admin's currently active
sessions immediately — the same thing a self-service password change
does (security-model.md's stolen-session-token row) — and both are
recorded in the audit log with no acting admin (`admin_user_id` null),
the same convention used for scheduler-triggered rows.

## Mail Log

### A message shows in the Postfix queue but never appears in the Mail Log screen

The log ingestion pipeline tails and parses Postfix's own log file,
matched by queue ID; it's a distinct pipeline from delivery itself and
can lag briefly under load. If a specific message *never* appears despite
enough time passing, check `mail_log_ingest_state.byte_offset` isn't
stuck — a Postfix log rotation that isn't coordinated with this table's
offset tracking is the one scenario known to cause a permanent gap rather
than a transient lag; restarting `app` alone doesn't fix this, since the
offset is persisted in the database, not in memory.

### Mail Log timestamps look shifted from what Postfix's own logs show

Confirmed historical bug (Stage 5): an earlier version of the log parser
mishandled UTC conversion. If you see a consistent, fixed-size offset
(e.g. always off by your server's UTC offset) on a build older than the
fix, upgrade rather than trying to correct for it manually.

## Sending mail

### A local user gets "Sender address rejected" despite the sender existing

Check that the specific local user has been *granted* that sender — a
sender existing in the system does not by itself authorize any local
user to send as it; the grant in the Senders screen's permissions view is
a separate step (security-model.md §4). Also check the sender's
`enabled` flag and that its upstream account is `enabled` — either being
off removes it from `smtpd_sender_login_maps` on the next config
generation, immediately revoking use even if the grant still exists in
the database.

### A newly added sender/permission doesn't seem to take effect

Config is applied atomically on generation, not instantly on every
database write (architecture.md §5) — check the Settings screen's config
generation history for whether a generation actually ran and succeeded
after your change. Most UI actions that need this trigger it
automatically; if you scripted a change directly against the API in an
unusual way, confirm you didn't bypass the route that does so.

## Getting more detail

Every response carries an `X-Request-ID` header, and every log line
`app` emits during that request carries the same ID as structured JSON
(`docs/security-model.md` §8). When reporting a bug, capture that ID
alongside `docker compose logs app` output from around the same time —
it's the fastest way to isolate the exact request in a busy log.
