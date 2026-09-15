# Installation

Requires Docker and Docker Compose (v2, the `docker compose` subcommand —
not the standalone `docker-compose` v1 binary). No other host dependencies;
Postfix, Python, and the SPA all run inside the two containers this stack
builds.

## 1. Clone and configure

```bash
git clone https://github.com/Heinekamp/SMTP-Manager.git
cd SMTP-Manager
cp .env.example .env
```

Generate an encryption key — this protects every upstream account
password at rest (security-model.md §2) and **cannot be recovered if
lost**, so back it up somewhere durable immediately, separately from the
database (see [backup-restore.md](backup-restore.md)):

```bash
docker compose run --rm app relay generate-encryption-key
```

Paste the printed value into `.env` as `RELAY_ENCRYPTION_KEY`. Set
`RELAY_SUBMISSION_HOST` in the same file to whatever hostname your
internal services will actually use to reach this relay (it doesn't need
to be publicly resolvable — it's the identity Postfix presents on its own
submission port, and the Cyrus SASL realm local credentials are issued
under). See [configuration.md](configuration.md) for every other setting.

## 2. Build and start

```bash
docker compose up -d --build
docker compose ps
```

Both `app` and `postfix` should settle into `healthy` within about a
minute (`docker compose up --wait` will block until they do, if you'd
rather script this than poll `ps`). The `app` container's entrypoint runs
database migrations, generates and applies an initial (empty) Postfix
config automatically, and only then starts serving — this is
best-effort and retried a few times if the `postfix` container's control
surface isn't listening yet (Compose's `depends_on` only waits for the
container to *start*, not for the socket inside it), so a transient
"attempt N failed, retrying" line in `docker compose logs app` on first
boot is expected, not a fault.

## 3. First-run setup

Open `http://<host>:8000/` in a browser. A fresh install has no admin
account yet, so you'll land on **Create the first admin account**
automatically. This is the only time this screen is reachable — once one
admin exists, the same URL redirects to the ordinary login screen instead
(there is deliberately no way to re-trigger first-run setup as a second
account-creation path).

After creating the account you land directly in the dashboard's
guided-empty state, which walks through the three things every relay
needs before it can send anything:

1. **Add an upstream account** — the externally-hosted mailbox
   (e.g. a STRATO account) this relay will actually send through.
2. **Add a sender** — an address allowed to send, tied to that upstream
   account.
3. **Create a local SMTP user** — the credential an internal service
   (a printer, InvenTree, a monitoring stack, ...) authenticates with,
   granted permission to use one or more senders.

Each local SMTP user's password is shown exactly once, at creation time
— copy it into the consuming service's configuration immediately; it is
never retrievable again (security-model.md §5), only regenerable.

## 4. Point a service at it

Any service that speaks SMTP with `AUTH` + `STARTTLS` can use this relay.
The Local SMTP Users screen's **Connection Details** view has the exact
host/port/username to give it; the password is whatever was shown at
creation/regeneration time. The relay's own TLS certificate is a
self-signed placeholder baked into the `postfix` image by default — most
real clients (e.g. PHPMailer-based mailers) reject this during STARTTLS.
See [configuration.md](configuration.md#tls-certificates) for provisioning
a real, auto-renewing certificate from Settings → TLS Certificate, or
mounting one manually.

## Exposed ports

| Port | Service | Purpose |
|---|---|---|
| 8000 | `app` | Web UI + API (put a reverse proxy with real TLS in front of this for anything beyond a trusted internal network — the app itself serves plain HTTP) |
| 587 | `postfix` | SMTP submission — what internal services connect to. `AUTH` is mandatory; there is no way to relay without it (postfix-architecture.md §6-8) |

Postfix's plain SMTP port (25) is intentionally not exposed at all — it's
bound loopback-only inside the container and used for nothing (this relay
never accepts inbound mail).
