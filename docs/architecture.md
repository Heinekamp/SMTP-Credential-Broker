# Architecture

## 1. Purpose and scope

SMTP Credential Broker is a self-hosted management plane around Postfix. It
lets a small number of externally-hosted SMTP mailboxes (e.g. STRATO accounts)
be shared by many internal services, without ever handing those services the
upstream credentials.

```text
Internal services ──▶ SMTP Credential Broker ──▶ External SMTP provider(s)
                       (Web UI, API, Postfix)
```

This document covers the system as a whole: components, data flow, technology
choices, and the configuration-generation pipeline. Postfix-specific detail
lives in [postfix-architecture.md](postfix-architecture.md); the threat model
and secret handling live in [security-model.md](security-model.md).

## 2. Non-goals

The application does **not** reimplement any part of SMTP. It does not speak
SMTP to inbound clients or outbound servers itself, does not queue or retry
mail, and does not do TLS negotiation. All of that is Postfix's job. The
application's job is to **decide what Postfix's configuration should say**,
write it out, validate it, and apply it.

## 3. Component overview

```text
┌─────────────────────────────────────────────────────────────────┐
│                        "app" container                          │
│                                                                   │
│  ┌───────────────┐   ┌───────────────┐   ┌────────────────────┐ │
│  │   React SPA   │   │   FastAPI     │   │  Config generator  │ │
│  │ (served as    │──▶│   REST API    │──▶│  (Jinja2 templates │ │
│  │  static files)│   │               │   │   + map builders)  │ │
│  └───────────────┘   └───────┬───────┘   └──────────┬─────────┘ │
│                               │                       │           │
│                        ┌──────▼──────┐                │           │
│                        │   SQLite    │                │           │
│                        │  (SQLAlchemy│                │           │
│                        │  + Alembic) │                │           │
│                        └─────────────┘                │           │
└────────────────────────────────────────────────────────┼─────────┘
                                                           │ shared volume
                                                           │ (config + maps)
┌──────────────────────────────────────────────────────────▼─────────┐
│                       "postfix" container                          │
│                                                                     │
│  main.cf / master.cf   sasl_passwd.db   sender_login.db   sasldb2  │
│         │                    │                │              │     │
│         ▼                    ▼                ▼              ▼     │
│                        postfix (smtpd, smtp, cleanup, qmgr, ...)    │
└──────────────────────────────────────────────────────┬─────────────┘
                                                          │
                                                          ▼
                                                 External SMTP provider(s)
```

The app never talks SMTP to Postfix or to upstream providers for the purpose
of sending mail. The one exception is the explicit **"Test connection"**
feature (§15 of the brief), which opens a short-lived TCP/TLS/SMTP session
directly from the app to the upstream host to verify DNS/TCP/TLS/AUTH — this
is diagnostic, not part of the mail path, and is clearly labeled as such in
the UI.

## 4. Technology stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.12 + FastAPI | Async-capable, strong typing via Pydantic, mature ecosystem for everything else this app needs (SQLAlchemy, Alembic, Jinja2, cryptography, pyotp). Confirmed with the user as the preferred stack. |
| ORM / migrations | SQLAlchemy 2.x + Alembic | Versioned schema migrations are a hard requirement (spec §31); Alembic is the standard tool and works identically against SQLite and Postgres. |
| Database | SQLite (WAL mode) by default | Confirmed with the user. Single file, trivial backup (copy the file), sufficient for the expected scale (a handful of upstream accounts, tens of local users/senders, moderate log volume). Models are kept dialect-neutral (no SQLite-only types, explicit migrations) so Postgres is a configuration change (`DATABASE_URL`), not a rewrite, if a deployment outgrows it. |
| Config templating | Jinja2 | Already a FastAPI/Python-ecosystem dependency in spirit; well suited to generating `main.cf`, `master.cf`, and lookup-table source files from typed data. |
| Frontend | React + TypeScript + Vite, TanStack Query | Claude Design's output in this environment is React/Tailwind-based (Phase 4). Using the same stack means design artifacts become real components with minimal translation, rather than being redrawn in a different framework. |
| SMTP engine | Postfix (Debian stable package) | Mandated by the brief. Not patched or forked — only configured. |
| Local SMTP AUTH | Cyrus SASL, `sasldb2` | See §5.2 below and [security-model.md](security-model.md) §4. |
| Secrets encryption | AES-256-GCM via `cryptography` (Python) | Authenticated encryption, no custom crypto. See [security-model.md](security-model.md) §1-3. |
| Admin auth | argon2id, server-side sessions, CSRF token, optional TOTP | Independent of all SMTP credentials (spec §21). |
| Containerization | Docker Compose | Required deployment target (spec §22). |

### Why not Dovecot for SASL?

Many mail-management stacks (Mailu, Modoboa, iRedMail) run Dovecot purely as a
SASL backend for Postfix, even without offering IMAP. That's a defensible
choice for those projects because they also need Dovecot for mailbox access.
This relay never stores or serves mailboxes — it only needs "is this
username/password pair one of our local SMTP users." Cyrus SASL's `sasldb2`
backend answers exactly that question, is maintained as part of the Postfix
Docker base image's SASL library, and avoids adding a fourth long-running
process/container purely for authentication. The tradeoff — `sasldb2` needs a
plaintext-equivalent secret store, shelled into via `saslpasswd2` — is
accepted and documented as a threat-model boundary in
[security-model.md](security-model.md) §4, per the brief's explicit
fallback clause (spec §9). If future requirements need SQL-backed or
LDAP-backed SASL, Dovecot remains a documented, swappable alternative — see
[security-model.md](security-model.md) §4 for the tradeoff table.

## 5. Configuration-generation pipeline

The single most important architectural rule in this system: **the
application never hand-edits Postfix configuration.** Every change to
upstream accounts, senders, local users, or permissions flows through one
deterministic pipeline.

```text
Database state (SQLAlchemy models)
        │
        ▼
Config generator (Python + Jinja2)
   - renders main.cf / master.cf from templates + DB-derived context
   - renders map *source* files (sender_login, sender_relayhost,
     sasl_passwd) from DB rows
        │
        ▼
Write to a temp path inside the shared volume
        │
        ▼
Validate
   - `postconf -c <tmpdir>` syntax-checks main.cf/master.cf
   - `postmap -q` / `postmap` dry-run style check on each map source
   - internal invariant checks (e.g. every sender referenced by a
     permission actually exists and is enabled)
        │
        ├── validation FAILS ──▶ abort, keep previous config active,
        │                        surface the error in the UI + audit log
        ▼
Validation PASSES
        │
        ▼
Atomic install
   - `postmap` writes each `.db` next to its source, then renames
     into place (postmap itself is already atomic — see
     postfix-architecture.md §7)
   - main.cf/master.cf are written to a temp file in the same
     directory and rename(2)'d over the live file (atomic on the
     shared volume's filesystem)
        │
        ▼
Apply
   - map-only changes (sender/permission/upstream edits that don't
     touch main.cf/master.cf structure): NO reload/restart needed —
     Postfix detects the changed table file automatically (see
     postfix-architecture.md §7)
   - main.cf/master.cf changes (rare — e.g. changing which upstream
     accounts exist enough to add/remove a distinct TLS policy):
     `postfix stop` + `postfix start` — see postfix-architecture.md §7
     for why this is a full restart rather than `postfix reload`
     (SIGHUP), despite reload being the theoretically lighter-weight
     option: it reproducibly crashed the master process in real testing
     against a real Postfix instance, in this project's target
     deployment environment, while a cold restart with the identical
     config never did. The in-flight queue is preserved either way
     (it's on-disk, not in master's memory); a restart only means a
     brief window (observed: under a second) where the submission port
     isn't accepting new connections.
        │
        ▼
config_generations row recorded: checksum, validation result,
whether applied — every generation is auditable and the previous
generation is retained on disk for rollback
```

This gives the "previous valid configuration remains active if the new one
fails validation" guarantee required by spec §10 for free: nothing is
overwritten until validation has already succeeded.

## 6. Docker topology

```text
docker compose
│
├── app        FastAPI + built React SPA, owns the SQLite DB,
│              writes generated config into a shared volume,
│              exposes the admin web UI (and a small internal API
│              the "postfix" container never needs to call — the
│              relationship is one-directional: app writes, postfix
│              reads).
│
├── postfix    Custom minimal image (Debian + postfix package +
│              libsasl2-modules), mounts the shared config volume
│              read-only where possible, exposes 587 (submission)
│              to internal networks only.
│
└── postgres   OPTIONAL. Only present if DATABASE_URL is pointed at
               Postgres instead of the default SQLite file. Not part
               of the default compose file.
```

No separate queue-viewer, log-shipper, or SASL container. `postqueue`,
`mailq`, and `postsuper` are invoked by `app` (via a small privileged helper
inside the shared volume boundary — see
[security-model.md](security-model.md) §6) rather than built as a second
queue implementation.

## 7. Health checks

Per spec §28, the health endpoint must reflect actual capability, not just
process liveness. `GET /api/health` (`app/core/health.py`) runs four checks:

- **Database reachable** — a real `SELECT 1`, not just "process is up."
- **Postfix reachable and running** — via a `status` op on the control
  surface (security-model.md §6), which wraps `postfix status`. A
  successful RPC round-trip already proves the control surface itself is
  reachable; "running" is the separate question of whether Postfix's
  master process has actually started.
- **Last config generation attempt's validation result** (`pass`/`fail`/
  `none`) — `config_generations`' own audit trail (§5), read back rather
  than re-derived.
- **Config in sync with the database** — whether re-rendering the current
  DB state right now (with no side effects, no control-surface call)
  produces the same checksums as the last successfully applied generation.
  Two checksums are compared, not one: `config_generations.checksum`
  (main.cf/master.cf only) and a second `maps_checksum` (the three lookup
  tables), since map-only changes — the common case, e.g. adding a sender —
  deliberately don't change the first checksum at all (§5's "no
  reload needed" design). Comparing only the first would silently miss
  exactly the drift this check exists to catch.

A relay that has never had a config successfully applied yet (a fresh
install, before the first sender exists) reports "Postfix running" and
"config in sync" as false but is still overall `"ok"` — that's a normal
starting state, not a fault, and `postfix start` genuinely hasn't run yet
in that state (nothing else starts it; see postfix-architecture.md §7). Any
of these checks failing *after* a successful generation has happened is
what actually degrades overall status. The endpoint always returns HTTP
200 regardless — the body's `status` field, not the status code, carries
health, so a plain `curl --fail` liveness probe (this project's own
`compose-smoke` CI job) doesn't need special-casing while a real dashboard
can still inspect per-check detail. `relay doctor` runs the identical
check battery, human-readable, and exits non-zero when actually unhealthy.

## 7a. Background scheduler

`app/core/scheduler.py` is a stdlib-`asyncio`-only periodic-task runner
(no new dependency), started from `main.py`'s FastAPI `lifespan` and gated
on `RELAY_SCHEDULER_ENABLED` (default true; tests set this false so a
`TestClient`'s lifespan never spins up real background tasks against a
schema-less database). It polls every 60 seconds; each individual job's
`tick()` function decides for itself, via `relay_settings`/
`background_job_state` (database-schema.md §10-11), whether enough
wall-clock time has actually elapsed to do real work — this lets an
admin-edited interval take effect within one poll window, no restart
needed. One bad tick is caught and logged, never crashes the loop.

The first job wired in is scheduled upstream connection testing
(`app/core/scheduled_tests.py`): re-runs the same diagnostic as the manual
"Test Connection" button against every enabled upstream account, on an
admin-configurable interval that defaults to `NULL` (disabled/manual-only)
so upgrading an existing instance never silently starts periodic AUTH
attempts against a real provider without opt-in.

## 8. CLI

A `relay` CLI (a Typer app reusing the same service layer as the API) ships
in the `app` image so the system stays manageable if the web UI is down:

```text
relay create-admin              # bootstraps an admin without the web UI
relay generate-encryption-key   # prints a fresh base64 32-byte key
relay rotate-encryption-key     # re-encrypts every stored secret under a new key
relay doctor                    # runs the health checks above, human-readable
relay validate-config           # runs the generator in dry-run mode
relay generate-config           # forces a regeneration + apply
relay test-upstream ID          # runs the same test-connection logic as the UI
relay queue                     # lists the Postfix queue (wraps postqueue -j)
```

## 9. Major decisions and tradeoffs

| Decision | Alternative considered | Why this one |
|---|---|---|
| SQLite default | Postgres default | Homelab/small-business scale (spec explicitly allows SQLite); simpler backup story; Postgres remains a documented upgrade. |
| Cyrus SASL / sasldb2 | Dovecot SASL | Avoids a fourth container for pure auth; accepted the plaintext-equivalent-secret tradeoff and documented it. |
| One sender → one upstream account | Many-to-many senders↔upstream | Spec's stated default assumption; matches the real-world model (one mailbox, one set of credentials) and keeps `sender_dependent_relayhost_maps` a simple 1:1 lookup. Revisit only if a real use case needs upstream failover per sender. |
| Postfix restart (stop+start) on main.cf/master.cf change, not reload | `postfix reload` (SIGHUP) | Reload is the theoretically lighter-weight option and was the original design, but reproducibly crashed the master process in real integration testing (see integration/README.md) — a cold restart with the identical config never did. Map-only changes (the common case) still need neither. |
| React + Vite SPA served by FastAPI | Server-rendered templates | Needed for Claude Design compatibility (Phase 4) and for a genuinely interactive admin UI (live status, permission matrices, log filtering). |

## 10. Open questions for review

- Confirm the one-sender-to-one-upstream-account default is acceptable long
  term, or whether upstream failover per sender should be designed in now
  (schema change is small now, larger later).
- Confirm SQLite is acceptable as the shipped default even though the user
  may eventually run this alongside other services that already use Postgres.
- Confirm Cyrus SASL/sasldb2 is acceptable given the plaintext-equivalent
  secret tradeoff (see [security-model.md](security-model.md) §4) versus
  adding Dovecot as a fourth container.
- Confirm the flat, single-role admin model (any authenticated admin can
  create other admins and reach every route) is acceptable, or whether a
  read-only "viewer" role is worth the cross-cutting authorization change it
  would require. See [known-limitations.md](known-limitations.md) for detail.
