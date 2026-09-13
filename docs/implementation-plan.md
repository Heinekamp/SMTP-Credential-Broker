# Implementation Plan

This is the build order for Phase 6, after architecture review (this
document's own checkpoint) and the Claude Design review (Phase 3) are both
complete. It is intentionally sequenced so that every stage has something
testable at the end of it, rather than a single big-bang integration at the
finish.

## Stage 0 — Project scaffolding

- Python project layout (`app/`, `tests/`), FastAPI app skeleton, SQLAlchemy
  engine/session setup against SQLite, Alembic initialized with an empty
  baseline migration.
- React + Vite + TypeScript scaffolding, served as static files by FastAPI in
  production, proxied in dev.
- Docker Compose skeleton: `app` + `postfix` containers, shared volume wired
  up, no functionality yet beyond "both containers start and can see the
  shared volume."
- CI pipeline running lint + unit test scaffolding (empty test suite is fine
  at this stage — the point is the pipeline exists before code does).

## Stage 1 — Core data model

- SQLAlchemy models for every table in
  [database-schema.md](database-schema.md); first real Alembic migration.
- Admin auth: `admin_users`, password hashing, session issuance/validation,
  CSRF, login rate limiting. A minimal login screen (can predate the full
  Claude Design UI with a plain form) so every subsequent stage can be built
  behind auth from day one instead of retrofitting it.
- Unit tests for all of the above (testing-strategy.md §1).

## Stage 2 — Upstream accounts + encryption

- `upstream_accounts` CRUD API + encryption/decryption service
  (security-model.md §2).
- "Test connection" feature: DNS → TCP → TLS → SMTP greeting → AUTH, no mail
  sent.
- CLI: `relay test-upstream <id>`.
- Unit tests for encryption round-trip and the test-connection logic
  (mockable transport layer so this doesn't require network access in CI).

## Stage 3 — Senders, local users, permissions

- `senders`, `local_smtp_users`, `user_sender_permissions` CRUD APIs.
- Local user password generation (secure random, shown once) and the
  `saslpasswd2` integration (postfix-architecture.md §5) via the control
  surface (security-model.md §6).
- Unit tests for permission evaluation logic.

## Stage 4 — Config generator + Postfix container

- The generator pipeline end to end (architecture.md §5): Jinja2 templates
  for `main.cf`/`master.cf`/map sources, `postconf`/`postmap` validation,
  atomic install, reload-vs-no-reload decision.
- Build the real `postfix` container image (Debian + `postfix` +
  `libsasl2-modules` + `sasldb2` support) and the in-container control
  surface listener.
- `config_generations` audit trail wired up.
- CLI: `relay validate-config`, `relay generate-config`.
- **This stage is where the integration test harness
  (testing-strategy.md §2) starts running for real** — it's the first point
  a real Postfix instance exists to test against. All of spec §25's
  scenarios should be automated here, not deferred to the end.

## Stage 5 — Mail logs + queue

- Postfix log ingestion into `mail_log` (tail + parse, matched by queue ID).
- Queue read/retry/delete via `postqueue`/`postsuper`, exposed through the
  control surface, not a second queue implementation.
- CLI: `relay queue`.

## Stage 6 — Health checks + `relay doctor`

- The real health-check logic from architecture.md §7 (DB reachable, Postfix
  running, last generation valid, maps present and current).
- CLI: `relay doctor`.

## Stage 7 — Frontend build-out

- Wire the React SPA to every API surface built in Stages 1-6, following
  whatever screens/components come out of the Claude Design phase (Phase 4).
  This stage is sequenced last on purpose: the backend and Postfix behavior
  are the part with actual security consequences and are validated by
  integration tests independent of any UI; the UI is how a human drives
  already-correct behavior.
- Dashboard, upstream accounts, senders, local users, permissions (both
  directions — spec §18), mail logs with filtering, queue view, settings,
  initial setup wizard, login/2FA.

## Stage 8 — Hardening pass

- TOTP (if not already folded into Stage 1).
- Rate limiting tuning, structured logging review (confirm nothing on the
  "never logged" list in security-model.md §8 has leaked anywhere).
- `relay rotate-encryption-key` CLI command and its own test coverage.
- Full spec §25 integration suite re-run as a gate.

## Stage 9 — Documentation + release (Phase 8)

- `installation.md`, `configuration.md`, `backup-restore.md` (written and
  *tested* against a real restore, per spec §30), `troubleshooting.md`,
  `upgrading.md` — these were explicitly scoped out of Phase 1 (they describe
  a running system that doesn't exist until now).
- `.env.example`, final Compose file review, tagged release.

## Sequencing rationale

Backend/Postfix correctness (Stages 0-6) is fully integration-tested before
the frontend (Stage 7) is built against it, so the UI is never used as the
only way to discover that a permission model or config-generation edge case
is wrong. This mirrors the brief's own instruction that the backend/security
architecture is authoritative and the UI is built to match it, not the other
way around.
