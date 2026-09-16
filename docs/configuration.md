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

## Sending rate limits

Not to be confused with the admin-login "Rate limiting" section above —
this is about SMTP sending volume, covered in full in
[postfix-architecture.md](postfix-architecture.md) §10 and
[security-model.md](security-model.md) §10.

| Variable | Default | Notes |
|---|---|---|
| `RELAY_POLICY_SERVICE_PORT` | `10030` | The internal-only TCP port `app` listens on for Postfix's policy-delegation protocol, enforcing each local user's rate limit. Reached via `inet:app:{port}` over the Compose network — never published to the host, and there's normally no reason to change it. |

The limits themselves — per local user and per upstream account — are
**not** environment variables; they're set per-entity from the Local SMTP
Users and Upstream Accounts screens (blank/unset = unlimited, today's
behavior). A local user over their limit gets a temporary rejection at
send time; an upstream account over its limit is never rejected — its
excess mail is simply paced out more slowly, still sitting safely in
Postfix's own queue in the meantime.

## TLS certificates

The relay ships with a self-signed placeholder certificate on the
submission port (baked into the `postfix` image at build time) — good
enough for local testing, but most real SMTP clients (e.g. PHPMailer-based
plugins like WP Mail SMTP) reject it during STARTTLS with something like
"unknown ca" and drop the connection before AUTH, so the mail never even
reaches the queue.

Settings → TLS Certificate lets an admin provision a real, auto-renewing
Let's Encrypt certificate instead, via a DNS-01 challenge — no inbound
port 80/443 needed, so this works for a relay that's only reachable on a
LAN. Cloudflare is the only supported DNS provider today; configure a
domain, a Cloudflare API token scoped to `Zone:DNS:Edit` on that domain's
zone, and enable it. "Verify Cloudflare Access" is a read-only precheck
(no DNS record is created, no Let's Encrypt attempt spent) worth running
before "Issue / Renew Now", which makes a real, rate-limited request
against Let's Encrypt's production API.

**The domain you configure here is independent of `RELAY_SUBMISSION_HOST`
above.** This domain only needs to match what a connecting client
validates the certificate's hostname against — it has no relationship to
Postfix's `myhostname`, EHLO greeting, or SASL realm. You do not need (and
generally should not) set them to the same value unless that's also
genuinely the hostname clients connect to.

> [!IMPORTANT]
> A client validates the certificate against whatever hostname it
> connects *to* — never the relay's IP address, and never anything Postfix
> itself claims to be. If this relay only lives on your LAN, that domain
> needs a **local** DNS answer pointing it at the relay's LAN IP address —
> a "Local DNS Record" (the exact name varies by vendor) in your router or
> DNS server. The public Cloudflare zone used for the DNS-01 challenge
> above doesn't need, and normally shouldn't have, an A record for this
> domain at all — it exists purely to prove domain ownership to Let's
> Encrypt, not to make the relay reachable from the internet.
>
> Skip this and every client that connects using the relay's bare IP
> address (rather than the domain) will fail with a certificate/hostname
> mismatch and refuse to send — even though the certificate itself is
> perfectly valid. Point the client at the domain, and make sure that
> domain actually resolves to the relay for whichever network it's on.

Once issued, the certificate and its private key are stored encrypted in
the database — the source of truth an app-startup check and the daily
renewal check reconcile the Postfix container's live files against, so a
lost `postfix_tls` volume or a recreated `postfix` container self-heals
without re-issuing. Renewal happens automatically once a certificate is
within 30 days of expiry; failures are visible in the same Settings tab.

A real cert/key pair can still be mounted directly over
`/etc/postfix/tls/relay.crt`/`relay.key` instead (e.g. from another CA) —
this feature is purely an additional, automated path, not a requirement.

| Variable | Default | Notes |
|---|---|---|
| `RELAY_ACME_DIRECTORY_URL` | Let's Encrypt production | Deliberately an environment variable, not a Settings toggle — a UI switch would risk a production relay being silently left pinned to Let's Encrypt's **staging** directory (whose certificates nothing trusts). Override only for manual verification against staging. |

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
