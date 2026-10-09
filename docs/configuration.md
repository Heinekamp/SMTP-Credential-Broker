# Configuration

Every setting is an environment variable prefixed `RELAY_`, read once at
process startup (`backend/app/config.py`'s `Settings`, a `pydantic-settings`
model — unknown `RELAY_*` variables are silently ignored, not an error).
Set them in the `.env` file next to `docker-compose.yml` (see
[`.env.example`](../.env.example)) — the `app` container loads that whole
file — or through your orchestrator's own secret/config mechanism. The
handful of values `docker-compose.yml` sets under `environment:` win over
`.env`; of those, `RELAY_COOKIE_SECURE`, `RELAY_SUBMISSION_HOST`,
`RELAY_SUBMISSION_AUTH_RATE_LIMIT_PER_MINUTE` and the encryption key are
read from `.env` there too, and `RELAY_DATABASE_URL` and
`RELAY_POSTFIX_CONTROL_SOCKET` are fixed to the container paths.

## Application

| Variable | Default | Notes |
|---|---|---|
| `RELAY_DATABASE_URL` | `sqlite:///./data/app.db` | The production compose file sets this to `sqlite:////data/app.db` (the mounted `app_data` volume). Any SQLAlchemy-compatible URL works — pointing this at Postgres instead is a configuration change, not a code change (architecture.md §4). |
| `RELAY_COOKIE_SECURE` | `true` | Whether the session/CSRF cookies get the `Secure` flag (HTTPS-only). Keep `true` behind an HTTPS reverse proxy. Set `false` only when the console is reached as plain `http://` on a trusted network — browsers discard `Secure` cookies on plain-HTTP pages (except `localhost`), so login can't stick otherwise; the trade-off is that the session cookie then crosses the network unencrypted. |
| `RELAY_SESSION_TTL_SECONDS` | `43200` (12h) | How long an admin session stays valid after login before re-authentication is required. |
| `RELAY_SUBMISSION_HOST` | `smtp-relay.internal` | The relay's own identity: `myhostname` in the generated Postfix config, what local SMTP users are told to connect to (the Connection Details view), and the Cyrus SASL realm `saslpasswd2` stores credentials under. **Must be identical** on both the `app` and `postfix` services — the compose file already wires the same variable to both for this reason. Changing it once local users exist: run `docker compose up -d` (both containers pick up the new value, and the app regenerates and applies the Postfix config on start), then **Regenerate** every local user's password and update the services using them. Each credential is stored under the realm in force when it was issued, so every existing one stops authenticating; regenerating config alone does not re-issue them. |
| `RELAY_SUBMISSION_AUTH_RATE_LIMIT_PER_MINUTE` | `60` | Postfix's `smtpd_client_auth_rate_limit`: SMTP AUTH commands allowed per client IP per minute, against password guessing on the submission port. Every internal service behind the same NAT or Docker host counts as one client, so raise it if many services authenticate frequently from one address. `0` disables it. |
| `RELAY_IMAGE_TAG` (`.env`, used by `docker-compose.yml`) | `latest` | Which published image tag `docker compose pull` fetches for both services (a release version such as `0.3.4`, or `latest`). Ignored when building locally with `--build`, which tags the build with the same name. See upgrading.md. |
| `SUBMISSION_BIND_ADDRESS` (`.env`, used by `docker-compose.yml`) | `0.0.0.0` | Host address the submission port (587) is published on. The default is every interface; on a host with a public interface, set it to the LAN address internal services use. |
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
| `RELAY_POSTFIX_CONTROL_SOCKET` | `/shared-config/control.sock` | Where `app` expects to find the Postfix container's control-surface Unix socket (security-model.md §6). The production compose file's `control_socket` volume already wires this up correctly on both sides — only change this if you've changed that volume's mount point in `app`. |
| `RELAY_POSTFIX_CONTROL_TIMEOUT` | `15.0` | Seconds `app` waits for a control-surface response before treating it as unreachable (surfaced as a 503, e.g. on "Test Connection"). |
| `RELAY_POSTFIX_CONTROL_APPLY_TIMEOUT` | `75.0` | The same, for applying a generated configuration, which can legitimately take up to about a minute (Postfix is stopped and started, each step allowed 30 s). Raise it only if applies on a slow host are reported as "control surface unreachable" although Settings → System's generation history shows them succeeding. |

## Sending rate limits

Not to be confused with the admin-login "Rate limiting" section above —
this is about SMTP sending volume, covered in full in
[postfix-architecture.md](postfix-architecture.md) §10 and
[security-model.md](security-model.md) §10.

| Variable | Default | Notes |
|---|---|---|
| `RELAY_POLICY_SERVICE_ALLOWED_CLIENT` | `postfix` | The only host (besides loopback) the rate-limit policy service answers. It's resolved per connection, so container IP changes don't matter. The listener trusts the `sasl_username` it's sent, so nothing else on a shared Docker network may talk to it. Change it only if the Postfix service has a different name in your compose setup. |
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
submission port (generated for each deployment at first start) — good
enough for local testing, but most real SMTP clients (e.g. PHPMailer-based
plugins like WP Mail SMTP) reject it during STARTTLS with something like
"unknown ca" and drop the connection before AUTH, so the mail never even
reaches the queue.

Settings → TLS Certificate lets an admin provision a real, auto-renewing
Let's Encrypt certificate instead, via a DNS-01 challenge — no inbound
port 80/443 needed, so this works for a relay that's only reachable on a
LAN. Two DNS providers are supported:

- **Cloudflare** — fully automated. Configure a domain, a Cloudflare API
  token scoped to `Zone:DNS:Edit` on that domain's zone, and enable it.
  "Verify Cloudflare Access" is a read-only precheck (no DNS record is
  created, no Let's Encrypt attempt spent) worth running before
  "Issue / Renew Now", which makes a real, rate-limited request against
  Let's Encrypt's production API.
- **Manual** — for any other DNS host. No credentials are needed;
  "Start DNS-01 Challenge" shows the `_acme-challenge` TXT record to add
  yourself, wherever the domain is actually hosted. Once it's added,
  "Verify & Continue" checks it and finishes issuance — safe to retry as
  many times as needed while DNS propagates. Because it needs a human in
  the loop, a domain on the manual provider does not auto-renew in the
  background; renew it the same way once it's close to expiry.

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
> DNS server. The public DNS zone used for the DNS-01 challenge above
> doesn't need, and normally shouldn't have, an A record for this domain
> at all — it exists purely to prove domain ownership to Let's Encrypt,
> not to make the relay reachable from the internet.
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
| `RELAY_UPSTREAM_TLS_CA_FILE` | *(system trust store)* | CA bundle that upstream providers' certificates are verified against, by both Postfix (`smtp_tls_CAfile`) and the app's own upstream connections (Test Connection, scheduled tests, alert email). Set it only for an upstream behind a private CA, and mount the file at the same path in **both** the `app` and `postfix` containers. To skip verification for one provider instead, use the upstream account's **Skip certificate verification** option. |
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

`RELAY_SCHEDULER_ENABLED` (default `true`) exists so the test suite can
switch off everything the app runs in the background. Never turn it off in
a real deployment: it doesn't only stop the scheduled jobs above (plus
retention cleanup, certificate renewal and rate-limit abuse detection), it
also stops the local-user rate-limit policy listener. Postfix then lets
all mail through unmetered (`smtpd_policy_service_default_action =
DUNNO`), so per-user rate limits silently stop being enforced. It also
skips the startup re-sync of the TLS certificate and of `sasldb2`.

## What's *not* here

Upstream SMTP account credentials, local SMTP user credentials, senders,
and permissions are **all managed through the web UI and API**, backed by
the database — never through environment variables or `docker-compose.yml`
(spec §23). If you find yourself wanting to put a provider password in an
env var, that's the wrong layer; use the Upstream Accounts screen instead.
