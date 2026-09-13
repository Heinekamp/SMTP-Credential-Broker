# Testing Strategy

Per the project brief, integration tests against a **real Postfix instance**
are a mandatory requirement, not an optional nice-to-have. Unit test coverage
is important but secondary to those scenarios actually passing.

## 1. Unit tests (pytest, no Postfix required)

Run against the FastAPI app and its service layer directly, with SQLite
in-memory/temp-file databases.

| Area | What's verified |
|---|---|
| Permission evaluation | Given a set of `user_sender_permissions` rows, the correct `smtpd_sender_login_maps` content is produced; disabled users/senders are excluded; a user with no permissions produces no entries. |
| Sender → upstream mapping | Each enabled sender resolves to exactly one upstream account's relayhost/credentials entry; a sender pointing at a disabled upstream account is flagged as an invariant violation rather than silently rendering broken config. |
| Config generation | Deterministic output for a given DB state (same input → byte-identical rendered files, so `checksum` in `config_generations` is meaningful); templates escape values that could otherwise break map-file syntax (spec §22 / security-model.md §7). |
| Config validation | A deliberately broken template/DB state (e.g. a sender with no upstream) is rejected before ever reaching the "atomic install" step; a valid one passes. |
| Encryption/decryption | AES-256-GCM round-trip for upstream passwords; tampering with ciphertext is detected (GCM auth tag failure) rather than silently producing garbage plaintext; wrong key fails cleanly. |
| Authentication | Argon2id hashing/verification for admin passwords; session token issuance/expiry/revocation; CSRF token validation; login rate limiting logic (attempt counting, lockout window, reset on success). |
| Database migrations | Every Alembic migration applies cleanly to a fresh DB and round-trips (upgrade → downgrade → upgrade) without data loss on a seeded test DB. |
| API authorization | Every admin-only endpoint rejects unauthenticated/unauthorized requests; upstream password fields are absent from every response schema (a schema-level assertion, not just a behavioral one — see database-schema.md §3). |

## 2. Integration tests (real Postfix, via Docker Compose test harness)

A dedicated `docker-compose.test.yml` brings up `app` + `postfix` (SQLite,
ephemeral) plus a throwaway upstream SMTP stand-in (a local test SMTP server
the test suite controls, so tests don't depend on real internet mailboxes)
and drives real SMTP sessions with `aiosmtplib`/`smtplib` from the test
runner. These are the scenarios from spec §25, verified literally:

### Authentication
- Valid local SMTP user credentials → `AUTH` succeeds.
- Invalid credentials (wrong password, unknown username, disabled user) →
  `AUTH` fails with a rejection, no message accepted.

### Sender authorization
- `printer-service` authenticates, `MAIL FROM:<printer@example.com>` →
  accepted.
- `printer-service` authenticates, `MAIL FROM:<noreply@example.com>` →
  rejected (asserts the exact `reject_sender_login_mismatch` failure, not
  just "some 5xx").

### Upstream selection
- A message sent as `printer@example.com` is delivered to the test stand-in
  configured as "STRATO printer," authenticated with that account's
  credentials — verified by asserting which stand-in received it and which
  credentials it saw.
- A message sent as `noreply@example.com` is delivered to the "STRATO
  noreply" stand-in with *its* distinct credentials.

### Upstream authentication failure
- Upstream account's stored password is deliberately wrong → delivery to
  that account fails, `mail_log` records a `deferred`/`bounced` status with a
  non-empty `error`, and the test asserts the error text does **not** contain
  the configured password (security-model.md §8).

### TLS
- Upstream stand-in requires STARTTLS → delivery succeeds only when Postfix
  negotiates TLS; a plaintext-only stand-in (STARTTLS unavailable) is used to
  confirm the client's TLS policy behaves as configured (encrypt-preferred vs
  encrypt-required, per whatever `smtp_tls_security_level` is set to for that
  test case).

### Open relay prevention
- An SMTP session with **no** `AUTH` attempts to relay to an external
  recipient → rejected at `RCPT TO` (asserts `smtpd_relay_restrictions`
  behavior, not just "connection refused").
- The same unauthenticated session attempting `MAIL FROM` using one of the
  configured sender addresses → also rejected (covers
  `reject_unauthenticated_sender_login_mismatch` independently of the relay
  restriction, since both close the same door for different reasons).

### Configuration updates
- Start with `printer-service → printer@example.com`.
- Send successfully as `printer@example.com`.
- Change the permission (via the app's service layer, not a raw DB edit) to
  `printer-service → alerts@example.com`.
- Trigger the same config-generation pipeline the app uses in production.
- Assert: sending as `printer@example.com` now **fails**, sending as
  `alerts@example.com` now **succeeds** — and assert this happened without a
  `postfix reload` (map-only change, per postfix-architecture.md §7), by
  checking the harness never issued one and the transition still took effect.

### Credential rotation
- Rotate an upstream account's password through the app.
- Assert: the *old* upstream password stand-in credential no longer works
  (test stand-in configured to reject it), the *new* one does, and — the
  point of the whole product — the local SMTP user's credentials are
  byte-for-byte unchanged and still authenticate exactly as before.

## 3. What the integration harness deliberately does not do

It does not send real mail to real internet providers. The upstream side is
always a controlled test SMTP server so tests are deterministic, fast, and
don't leak credentials or spam real mailboxes. A separate, manual "smoke
test" procedure (documented in installation.md, produced in a later phase)
covers verifying real-provider connectivity via the app's own "Test
connection" feature after a real deployment.

## 4. CI

Unit tests run on every push (fast, no Docker required beyond what the app
itself needs). Integration tests run the Compose-based harness in CI as well
— they're mandatory gates for anything touching the config generator, the
Postfix templates, or the permission model, not an optional/manual step.

## 5. Coverage philosophy

Per the brief: these scenario-based integration tests are the actual
definition of "done" for the security-critical paths. A high line-coverage
percentage on the web CRUD layer is a secondary, nice-to-have signal — it is
not a substitute for the §25 scenarios all passing against real Postfix.
