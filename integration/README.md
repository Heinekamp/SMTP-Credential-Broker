# Integration test harness

Drives real SMTP sessions against a real Postfix instance (the actual
`postfix/Dockerfile` image, not a mock) and a controlled upstream SMTP
stand-in, per [docs/testing-strategy.md](../docs/testing-strategy.md) §2.
Every test here corresponds to one of spec §25's mandatory scenarios.

**Status: written, not yet run.** This was built in an environment without
Docker available, so it has not been executed against a real Postfix
instance. Run it (and fix whatever the first run inevitably finds) before
treating Stage 4 as done — see `docs/implementation-plan.md`.

## Running it

```bash
# From the repo root:
docker compose -f integration/docker-compose.test.yml up -d --build

pip install -r integration/requirements.txt
pytest integration/

docker compose -f integration/docker-compose.test.yml down -v
```

## What's running

- `app` — the real backend image, submission-agnostic port 8000 exposed to the host.
- `postfix` — the real postfix image, submission (587) exposed on host port
  1587, plain smtp (25) on host port 1025 (used only by the open-relay test).
- `upstream-stub` — a throwaway SMTP server (`aiosmtpd`) standing in for an
  externally hosted provider, with an inspection HTTP API on port 2526 so
  the test suite (running on the host) can see what was actually delivered
  and to which authenticated identity, and can rotate its accepted
  password for the credential-rotation scenario.

All state is test-only and reset with `down -v` — the encryption key used
here is a fixed, published test value; never reuse it anywhere real.

## Known gaps to check on first run

- `test_sender_matching_permission_is_accepted_and_mismatch_is_rejected`
  and the reassignment test detect a `reject_sender_login_mismatch`
  rejection via `smtplib`'s exception types, but exactly which exception
  `smtplib` raises for a mid-transaction rejection can depend on timing
  (some servers reject at `MAIL FROM`, Postfix's `smtpd_sender_restrictions`
  placement here rejects at that point) — if the first run shows a
  different exception type or a non-raising 5xx code returned from
  `rcpt()`, tighten the assertion rather than loosening it away.
- The relay's self-signed TLS cert (generated at image build time) is
  trusted here via `ssl.CERT_NONE` on the test client only — this is
  correct for the test harness and must never be copied into anything
  that talks to a real deployment.
- `docker-compose.test.yml`'s `RELAY_SUBMISSION_HOST` must stay identical
  between the `app` and `postfix` services (it's also the SASL realm) —
  if you change one, change both.
