# Security Model

This document covers secret handling, encryption, authentication, and the
explicit threat-model boundaries of the system. It complements
[postfix-architecture.md](postfix-architecture.md) (which covers how Postfix
itself enforces the sender-authorization invariant) with everything above and
around Postfix: the web application, its database, and its secrets.

## 1. What's a secret, and where it lives

| Secret | At rest | In transit | Ever shown in UI/API/logs? |
|---|---|---|---|
| Upstream SMTP account password | AES-256-GCM ciphertext in `upstream_accounts.encrypted_password` | TLS (admin UI ↔ browser); decrypted only in-process when writing `sasl_passwd` | **Never**, after initial entry. Not returned by any API response, not rendered in any form (edit forms show a "leave blank to keep current password" affordance). |
| Upstream SMTP password (materialized) | Plaintext inside `/etc/postfix/relay/sasl_passwd(.lmdb)` — required by Postfix's own SASL client, see §3 | Written to a root-owned, `0600` file inside the `postfix` container's private volume | Never logged; excluded from any config export/diagnostic bundle the UI can produce |
| Local SMTP user password | Argon2id hash stored for the web UI's own bookkeeping (so "has this been changed" can be shown without storing the secret twice); authoritative check happens in `sasldb2` | Shown **once**, at creation/regeneration time, over TLS | Never stored or shown in plaintext after that one-time display |
| `sasldb2` entries | Berkeley DB, effectively plaintext-equivalent (see §4) | Root-owned, `0640`, `postfix`-group-readable file inside the `postfix` container | Never exposed via API; not readable by the `app` container after write |
| Admin web session token | SHA-256 hash of the token stored server-side; the token itself only exists in the HttpOnly cookie | TLS | Never logged |
| `ENCRYPTION_KEY` | Never stored in the database. Supplied via environment variable or Docker secret at container start. | N/A (injected at deploy time) | Never logged, never exposed via API, redacted from any dumped environment in diagnostics |

## 2. Upstream password encryption

- **Algorithm**: AES-256-GCM (authenticated encryption — tampering with
  ciphertext is detected, not just confidentiality-protected).
- **Key**: a single 256-bit key supplied externally via `ENCRYPTION_KEY`
  (base64-encoded in the environment) or a Docker secret file
  (`ENCRYPTION_KEY_FILE`, preferred for production since it avoids the
  key appearing in `docker inspect` output for env-var-based secrets). The
  key is never written to the database, never logged, and never derived from
  anything stored in the database — losing the database without the key
  yields ciphertext with no usable path back to plaintext, by design.
- **Nonce**: a fresh random 96-bit nonce per encryption, stored alongside the
  ciphertext (standard GCM practice — nonces are never reused with the same
  key).
- **Key rotation**: rotating `ENCRYPTION_KEY` requires re-encrypting every
  `upstream_accounts.encrypted_password` row. The CLI provides
  `relay rotate-encryption-key --old-key-file ... --new-key-file ...`, which
  decrypts every row with the old key and re-encrypts with the new one inside
  a single DB transaction, aborting (and leaving the database untouched) if
  any row fails to decrypt. This is the *only* supported way to rotate the
  key; there is no "partial" state where some rows use the old key and some
  the new one.
- **Key loss**: if `ENCRYPTION_KEY` is lost with no backup, every upstream
  account's password becomes **permanently unrecoverable**. The application
  cannot fall back to anything — this is intentional (a recoverable key
  defeats the purpose of encrypting it at all). Recovery path: mark each
  upstream account's password as unknown in the UI, re-enter it from the
  provider's own credential (the provider still has it; only this relay's
  copy is lost), save, and the relay resumes normal operation. Local SMTP
  users and their permissions are **unaffected** by encryption-key loss —
  they're independent secrets stored separately (see §4) — so this is an
  outage of upstream delivery, not of local SMTP AUTH.
- **Backup implication**: the encryption key **must** be backed up
  separately from the database (see [backup-restore.md](backup-restore.md),
  produced in a later phase). A database backup without the matching key is
  equivalent to a backup with all upstream passwords deleted.

## 3. Why upstream passwords must exist in plaintext somewhere

Postfix's SMTP client performs the actual SASL AUTH exchange with the
upstream provider itself — the application does not, and must not,
reimplement SMTP client authentication. Postfix's `smtp_sasl_password_maps`
mechanism requires its lookup table to contain the credential in a form
Postfix can present in an `AUTH PLAIN`/`AUTH LOGIN` exchange, i.e.
effectively plaintext (Postfix does not support looking up
already-hashed/already-encrypted values there — the receiving server expects
to be able to verify the actual secret). This is not a shortcut taken by this
project; it's how Postfix's SASL client has always worked, and is the
reason spec §9 explicitly anticipated this: *"If Postfix inherently requires
a plaintext password in a local lookup map, design the filesystem
permissions and container boundaries accordingly and document the resulting
threat model."*

**The resulting threat model:**

- The plaintext materialization exists in exactly one place:
  `/etc/postfix/relay/sasl_passwd(.lmdb)`, inside the `postfix` container's
  filesystem, not the `app` container's.
- It is written with `0600` permissions, owned by root (the user Postfix
  itself runs its privileged pickup as before dropping privileges — this
  matches Postfix's own documented expectation for `smtp_sasl_password_maps`
  files).
- It never leaves that container: it is not on a volume shared with `app`
  read-write; `app` only ever writes it (through the shared config volume,
  §6) and never reads it back.
- Compromise of the encrypted database alone (e.g. an exfiltrated SQLite
  file, without `ENCRYPTION_KEY`) does **not** expose upstream passwords.
- Compromise of the `postfix` container's filesystem **does** expose
  whichever upstream passwords are currently in use — this is an accepted,
  documented residual risk, not a gap the application is pretending doesn't
  exist. It is the same residual risk present in *any* Postfix relay that
  authenticates outbound, including a hand-configured one; this project adds
  encryption-at-rest in the database and tight file permissions on top of
  that baseline, it does not (and cannot) eliminate it.

## 4. Local SMTP AUTH: `sasldb2` and its own threat-model boundary

The same category of tradeoff applies, independently, to local SMTP user
credentials: Cyrus SASL's `sasldb` auxprop backend must be able to verify a
`PLAIN`/`LOGIN` credential, which for a Berkeley DB-backed store means the
stored form is effectively plaintext-equivalent (SASL mechanisms like
`CRAM-MD5`/`DIGEST-MD5` would let it store a non-reversible verifier instead,
but this project intentionally only offers `PLAIN`/`LOGIN` over mandatory
TLS — see [postfix-architecture.md](postfix-architecture.md) §2 — because
that's what real-world client devices, like printer firmware, actually
support).

| Aspect | Detail |
|---|---|
| Where | `/etc/sasldb2`, inside the `postfix` container only |
| Permissions | root-owned, `0640`, readable only by the SASL library's runtime group |
| Written by | `saslpasswd2`, invoked by the application, password piped via stdin (never an argv, never logged; process argv is visible to other processes on the host via `/proc`, stdin is not) |
| Exposure if `postfix` container is compromised | All local SMTP users' passwords, for that relay instance only. Upstream provider credentials are a separate store (§3) and are not additionally exposed by this. |
| Exposure if `app`/database is compromised without the encryption key | **None** — local user passwords are never derived from or storable via `ENCRYPTION_KEY`; the app only ever writes to `sasldb2`, it doesn't read from it, and the DB only holds an Argon2id hash used for the web UI's own "was this ever set" bookkeeping. |
| Considered alternative | Dovecot SASL with a pluggable SQL/passdb backend, which *can* use a proper password hash. Rejected for v1 to avoid a fourth long-running container purely for authentication (see [architecture.md](architecture.md) §4); documented here as the natural next step if this tradeoff becomes unacceptable for a given deployment. |

## 5. Admin web authentication

Deliberately **independent** of every SMTP credential in the system — an
admin account compromise and an SMTP credential compromise are different
incidents with different blast radii, and the code must never let them be
confused.

- **Password hashing**: Argon2id (via `argon2-cffi`), tuned parameters
  reviewed periodically as hardware changes; never a fast hash (bcrypt is an
  acceptable fallback, MD5/SHA1/plain-SHA256 are not used anywhere in this
  system).
- **Sessions**: server-side session records (`admin_sessions`), referenced by
  an opaque random token in an `HttpOnly`, `Secure`, `SameSite=Strict`
  cookie. The database stores only a SHA-256 hash of the token (so a DB leak
  alone doesn't yield usable session tokens), plus expiry and
  creation metadata (IP/user-agent, for the audit trail — not for
  fingerprinting).
- **CSRF**: double-submit token pattern (a second, non-HttpOnly cookie whose
  value the SPA must echo back in a custom request header on every
  state-changing request) — appropriate given the API is same-site, cookie
  authenticated, and consumed by our own SPA rather than third parties.
- **Rate limiting**: login attempts are rate-limited per source IP and per
  account (exponential backoff), with attempts and lockouts recorded in
  `audit_log`.
- **TOTP (optional)**: `pyotp`-based TOTP, off by default, enabled per-admin.
  Secrets stored encrypted the same way upstream passwords are (§2) — a TOTP
  secret is exactly as sensitive as a password and gets the same treatment,
  not a weaker one.
- **Logout**: invalidates the server-side session record immediately (not
  just cookie deletion, which wouldn't stop a stolen token from being reused).

## 6. Privileged operations from `app`

`app` needs to trigger a small number of privileged actions inside the
`postfix` container's boundary: writing generated config/maps, running
`postmap`, running `saslpasswd2`, checking whether Postfix's master
process is actually running (`postfix status`, for the health check —
architecture.md §7), reading new maillog lines for mail_log ingestion
(postfix-architecture.md §9), and (for the queue UI) running
`postqueue`/`postsuper`. Rather than giving `app` a shell into the `postfix`
container, these are exposed as a minimal, purpose-built control surface
(a small Unix-socket RPC listener inside the `postfix` container, started by
its entrypoint, accepting only a fixed, parameterized set of operations — no
arbitrary command execution) reachable only over a socket on the shared
volume, not over the network. This keeps the blast radius of an `app`
compromise limited to "can regenerate config and query/manage the queue," not
"has a general-purpose shell in the container that holds live upstream
credentials."

## 7. Input validation

All admin-facing API input is validated with Pydantic models at the API
boundary (addresses are checked as syntactically valid email addresses,
hostnames/ports for upstream accounts are validated before being allowed
into a config generation, etc.). Generated Postfix map values are always
built from validated, escaped fields — user-supplied strings are never
concatenated directly into a lookup-table line without checking for the
field separators (whitespace/tab) that would let one field inject a second
bogus entry.

## 8. Logging

- Application logs are structured (JSON) — `app/core/logging_config.py`'s
  `JsonFormatter`, configured once at app startup — and every admin action
  writes one `audit_log` row (`app/core/audit.py`'s `record_audit`, wired
  into every mutating route: upstream accounts, senders, local users,
  permissions, admin accounts, config generation) plus one correlated log
  line carrying the same request ID (`app/core/request_context.py`, set by
  a middleware in `app/main.py` and echoed back as an `X-Request-ID`
  response header). The structured log line deliberately omits
  `audit_log.detail` even though the DB row includes it — the DB is
  already the access-controlled place for that context; keeping it out of
  the log stream too is defense in depth, not a missing feature.
- **Never logged, anywhere, at any log level**: SMTP passwords (local or
  upstream), `ENCRYPTION_KEY`, session tokens, TOTP secrets, or raw
  Authorization/cookie headers. `record_audit`'s `detail` parameter is
  documented as plain/already-safe-to-log values only (IDs, names,
  booleans, addresses) — enforced by convention and by
  `test_audit_log.py::test_audit_log_never_contains_a_raw_password`, not a
  runtime redaction step.
- Postfix's own logs (which the mail-log ingester parses for
  [database-schema.md](database-schema.md)'s `mail_log` table) never contain
  credentials either — Postfix does not log SASL passwords, only the
  authenticated username, by design.
- **Outbound network calls this app makes on its own** (not triggered by
  an admin action) are all opt-in, off by default, and narrowly scoped:
  the background update-checker (`app/core/update_check.py`) only ever
  calls GitHub's public releases API and postfix.org's download page, and
  only when an admin has explicitly enabled update checking
  (`relay_settings.update_check_enabled`) — a self-hosted relay may run in
  a locked-down or air-gapped environment, so this must never happen
  silently. Alert email (`app/core/mailer.py`) connects directly to a
  configured sender's own upstream provider — no new outbound destination
  beyond what the admin has already configured as an upstream account.

## 9. Summary threat model statement

| Threat | Mitigated by |
|---|---|
| Anonymous internet host relays mail through the system | No `permit_mynetworks` in relay restrictions; SASL auth mandatory (postfix-architecture.md §6-8) |
| Authenticated local user sends as an address they're not permitted | `smtpd_sender_login_maps` + `reject_sender_login_mismatch`, enforced by Postfix itself, not just the web app |
| Stolen database file (no `ENCRYPTION_KEY`) | Upstream passwords remain encrypted and unusable; local SMTP passwords aren't stored in the DB at all beyond a hash |
| Stolen `ENCRYPTION_KEY` alone (no DB) | Useless without the ciphertext |
| Compromised `postfix` container | Exposes currently-active upstream and local credentials for *this* relay instance — an accepted residual risk inherent to Postfix's own credential-lookup design, not a gap unique to this project (§3, §4) |
| Compromised `app` container | Can view/change relay configuration and trigger config regeneration via the control surface (§6), but cannot read `sasldb2` or the materialized `sasl_passwd` file back out, and cannot obtain plaintext upstream passwords without also holding `ENCRYPTION_KEY` |
| Stolen admin session token | Session is server-side revocable; token itself is hashed at rest; `Secure`/`HttpOnly`/`SameSite` cookie flags limit exfiltration paths |
| Brute-forced admin login | Rate limiting + lockout + optional TOTP |
