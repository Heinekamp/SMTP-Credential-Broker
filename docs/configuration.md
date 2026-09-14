# Configuration

Every setting is an environment variable prefixed `RELAY_`, read once at
process startup (`backend/app/config.py`'s `Settings`, a `pydantic-settings`
model — unknown `RELAY_*` variables are silently ignored, not an error).
Set them via `docker-compose.yml`'s `environment:` block, an `.env` file
next to it (see [`.env.example`](../.env.example)), or your orchestrator's
own secret/config mechanism.

## Application

| Variable | Default | Notes |
|---|---|---|
| `RELAY_DATABASE_URL` | `sqlite:///./data/app.db` | The production compose file sets this to `sqlite:////data/app.db` (the mounted `app_data` volume). Any SQLAlchemy-compatible URL works — pointing this at Postgres instead is a configuration change, not a code change (architecture.md §4). |
| `RELAY_COOKIE_SECURE` | `true` | Whether the session/CSRF cookies get the `Secure` flag (HTTPS-only). Only set to `false` for local HTTP development — never in a real deployment, since a stolen session token becomes replayable over plain HTTP otherwise. |
| `RELAY_SESSION_TTL_SECONDS` | `43200` (12h) | How long an admin session stays valid after login before re-authentication is required. |
| `RELAY_SUBMISSION_HOST` | `smtp-relay.internal` | The relay's own identity: `myhostname` in the generated Postfix config, what local SMTP users are told to connect to (the Connection Details view), and the Cyrus SASL realm `saslpasswd2` stores credentials under. **Must be identical** on both the `app` and `postfix` services — the compose file already wires the same variable to both for this reason. Changing it after local users already exist requires regenerating config (`relay generate-config`) so `saslpasswd2` re-issues credentials under the new realm. |
| `RELAY_SUBMISSION_PORT` | `587` | What the Connection Details view tells local users to configure. Only meaningful if you've also changed the exposed port in `docker-compose.yml`'s `postfix.ports` — this setting doesn't itself change what Postfix listens on. |

## Secrets

| Variable | Default | Notes |
|---|---|---|
| `RELAY_ENCRYPTION_KEY` | *(none — required)* | Base64-encoded, decoding to exactly 32 bytes. Encrypts every upstream account password and every admin's TOTP secret at rest (security-model.md §2). Generate one with `docker compose run --rm app relay generate-encryption-key`. **There is no recovery if this is lost** — back it up separately from the database (see [backup-restore.md](backup-restore.md)). |
| `RELAY_ENCRYPTION_KEY_FILE` | *(none)* | Path to a file containing the same base64 key, for Docker/Kubernetes secret mounts. Takes precedence over `RELAY_ENCRYPTION_KEY` when both are set — a mounted file doesn't appear in `docker inspect` the way an env var does. Prefer this over the plain env var in production. |

Exactly one of these two must resolve to a valid key before the app can
create an upstream account, enroll TOTP, or decrypt an existing one — see
[troubleshooting.md](troubleshooting.md) for what it looks like when
neither is set.

## Rate limiting

| Variable | Default | Notes |
|---|---|---|
| `RELAY_RATE_LIMIT_THRESHOLDS` | `[[5,60],[10,300],[15,900]]` | `(failure_count, lockout_seconds)` pairs — the highest threshold met wins. Applies to both wrong-password and wrong-TOTP-code attempts, counted per admin account and per source IP independently (security-model.md §5). Pydantic parses this from a JSON array in the environment, e.g. `RELAY_RATE_LIMIT_THRESHOLDS='[[5,60],[10,300],[15,900]]'`. |
| `RELAY_RATE_LIMIT_WINDOW_SECONDS` | `3600` | How far back failed attempts are counted for the per-IP counter. |

These are deliberately not exposed in the Settings UI — changing them is
rare enough that an environment variable + container restart is the
right level of friction.

## Postfix control surface

| Variable | Default | Notes |
|---|---|---|
| `RELAY_POSTFIX_CONTROL_SOCKET` | `/shared-config/control.sock` | Where `app` expects to find the Postfix container's control-surface Unix socket (security-model.md §6). The production compose file's `relay_config` volume already wires this up correctly on both sides — only change this if you've renamed that volume's mount point. |
| `RELAY_POSTFIX_CONTROL_TIMEOUT` | `15.0` | Seconds `app` waits for a control-surface response before treating it as unreachable (surfaced as a 503, e.g. on "Test Connection" or config generation). |

## Scheduled testing, update checks, and alert email

Unlike everything else in this document, these are **not** environment
variables — they're admin-editable from Settings → Notifications, backed
by the database (`relay_settings`, database-schema.md §10), so they can be
changed without a container restart:

- The upstream connection-test interval (off by default).
- Whether the background update-checker makes any outbound calls at all
  (GitHub for this app's own version, postfix.org for Postfix's — off by
  default; see security-model.md §8 for why this is opt-in).
- Alert email: recipients, which configured sender to send from, and
  which alert kinds (relay degraded, an upstream account failing its
  test, an available update) trigger an email.

A new `RELAY_SCHEDULER_ENABLED` (default `true`) setting exists purely so
the test suite can disable the background scheduler entirely — there's no
reason to change it in a real deployment.

## What's *not* here

Upstream SMTP account credentials, local SMTP user credentials, senders,
and permissions are **all managed through the web UI and API**, backed by
the database — never through environment variables or `docker-compose.yml`
(spec §23). If you find yourself wanting to put a provider password in an
env var, that's the wrong layer; use the Upstream Accounts screen instead.
