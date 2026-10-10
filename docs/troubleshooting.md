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

If you just changed `RELAY_SUBMISSION_HOST`, see the entry below.
Otherwise it's most often a permissions problem rather than a credential
one — a symptom is *every* local user failing, not just one. `smtpd` reads
`/etc/sasldb2` directly through Cyrus SASL's `sasldb` auxprop plugin (no
`saslauthd` is involved), as the `postfix` user, which is in the `sasl`
group. The file must stay `root:sasl`, mode `0660`; the entrypoint sets
that on every start, so a bind mount or custom volume over it is the
usual culprit. `docker compose exec postfix ls -l /etc/sasldb2` and
`docker compose exec postfix sasldblistusers2` show the file and the
users in it.

### Every local user fails SMTP AUTH after changing `RELAY_SUBMISSION_HOST`

The variable is also the Cyrus SASL realm (postfix-architecture.md §5),
and each local user's credential is stored under the realm in force when
it was issued. After a change, Postfix looks every user up under the new
realm and finds nothing, so all existing local users fail at once.
Neither restarting `postfix` nor regenerating the config re-issues
credentials. Make sure both containers picked up the new value
(`docker compose up -d` recreates them; the app regenerates and applies
the Postfix config on start), then **Regenerate** each local user's
password on the Local SMTP Users screen and update the services using
them. The Connection Details view shows the new host once `app` has been
recreated.

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

### Login (or first-run setup) succeeds but you're never logged in

The login screen says your browser didn't keep the session cookie. Older
builds just showed the login form again. The app sends `Secure`
(HTTPS-only) cookies by default, and a browser discards those on a
plain-HTTP page other than `localhost`. Either put the console behind an
HTTPS reverse proxy, or, on a trusted LAN, set `RELAY_COOKIE_SECURE=false`
in `.env` and run `docker compose up -d` (configuration.md). Before 0.3.5,
`docker-compose.yml` hard-coded this to `true`, so setting it in `.env`
had no effect. Put it in a `docker-compose.override.yml` under
`services.app.environment` instead.

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

### Relayed mail is missing from the Mail Log

The app reads Postfix's log into the Mail Log every minute (and whenever
the page loads), matched by queue ID, so a message can take up to a
minute to appear. If messages don't appear at all:

- `docker compose logs app | grep "mail log ingestion"` shows whether
  reading the log is failing; it's logged once when it starts failing and
  once when it recovers.
- **Before 0.3.6**, mail could go missing for good. The log was read only
  when someone opened the Mail Log page, and it lived inside the `postfix`
  container, so every deploy threw away anything not yet read (#228).
  Those entries can't be recovered; the mail itself was still delivered.

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
off removes it from `smtpd_sender_login_maps` once the configuration is
next applied, revoking use even if the grant still exists in the
database. A grant that was *just* added also needs that apply (next
entry).

### A newly added sender/permission doesn't seem to take effect

Changes to senders, permissions and upstream accounts reach Postfix only
when the configuration is **applied**, which is deliberately a manual
step (architecture.md §5). While the database and the live config differ,
every page shows a *Pending configuration changes* banner with an **Apply
now** button. Settings → System has the same Generate & Apply action and
the generation history, which shows whether a generation ran and passed
validation after your change. `relay generate-config` does the same from
the CLI. (Disabling, deleting or regenerating a *local user* is the
exception: that changes SMTP AUTH immediately.)

## Getting more detail

Every response carries an `X-Request-ID` header, and every log line
`app` emits during that request carries the same ID as structured JSON
(`docs/security-model.md` §8). When reporting a bug, capture that ID
alongside `docker compose logs app` output from around the same time —
it's the fastest way to isolate the exact request in a busy log.
