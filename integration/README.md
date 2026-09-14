# Integration test harness

Drives real SMTP sessions against a real Postfix instance (the actual
`postfix/Dockerfile` image, not a mock) and a controlled upstream SMTP
stand-in, per [docs/testing-strategy.md](../docs/testing-strategy.md) §2.
Every test here corresponds to one of spec §25's mandatory scenarios.

**Status: verified.** All 12 scenarios pass against a real Docker Desktop +
real Postfix 3.7 instance, twice in a row from a clean `down -v`/`up -d`
(not a fluke). Getting here surfaced and fixed several real bugs that no
amount of unit testing would have caught — see "What this caught" below.
If you change `postfix/`, `backend/app/templates/`, or
`backend/app/core/config_generator.py`/`postfix_control.py`/
`mail_log_parser.py`/`mail_log_ingest.py`, re-run this suite before
trusting the change.

## Running it

```bash
# From the repo root:
docker compose -f integration/docker-compose.test.yml up -d --build

pip install -r integration/requirements.txt
pytest integration/

docker compose -f integration/docker-compose.test.yml down -v
```

## What's running

- `app` — the real backend image, port 8000 exposed to the host.
- `postfix` — the real postfix image, submission (587) exposed on host port
  1587, plain smtp (25) on host port 1025 (used only by the open-relay test —
  it's expected to be unreachable; see below).
- `upstream-stub` — a throwaway SMTP server (`aiosmtpd`) standing in for an
  externally hosted provider, with an inspection HTTP API on port 2526 so
  the test suite (running on the host) can see what was actually delivered
  and to which authenticated identity, and can rotate its accepted
  password for the credential-rotation scenario.

All state is test-only and reset with `down -v` — the encryption key used
here is a fixed, published test value; never reuse it anywhere real.

## What this caught

Real, non-hypothetical bugs found only by running this against a live
Postfix instance (all fixed; kept here so the reasoning isn't lost):

- **`postfix reload` (SIGHUP) reproducibly killed the master process** on
  the second and later config change, regardless of whether Postfix ran as
  the container's PID 1 (`start-fg`) or as a normal detached daemon
  (`postfix start`). A cold `postfix stop && postfix start` on the exact
  same config never had the problem, so `control_surface.py`'s
  `_apply_config` uses that instead of reload — see its comment for the
  full story. Also serves as how Postfix gets started on the container's
  very first boot.
- **`postfix-lmdb` isn't in the base `postfix` Debian package** — `lmdb`-typed
  lookup tables need it installed separately, or `postmap` fails with
  "unsupported dictionary type: lmdb".
- **`maillog_file = /dev/stdout` needs a `postlog` service entry in
  master.cf** (Postfix 3.4+) — without it, `postfix start`'s own integrity
  check refuses to start at all.
- **Cyrus SASL had no auxprop config** (`/usr/lib/sasl2/smtpd.conf` didn't
  exist) and **the `postfix` user wasn't in the `sasl` group** that owns
  `/etc/sasldb2` — both silent until an actual `AUTH` attempt, both
  surfacing as a generic `454 4.7.0 Temporary authentication failure`.
- **A per-service `-o inet_interfaces=loopback-only` override in master.cf
  does not restrict that service's listener** — inet_interfaces is a
  master-level socket-bind setting, not one master re-reads per service.
  Binding an address to one service specifically means writing it directly
  in the service-name column (`127.0.0.1:smtp` instead of `smtp`).
- **`smtplib`'s low-level `.mail()`/`.rcpt()` don't raise on failure** —
  only `.sendmail()` does. Two tests were asserting `pytest.raises(...)`
  around calls that just return a `(code, message)` tuple, so a real,
  correct `553` rejection from Postfix was going unnoticed by the test
  itself. Fixed by asserting the returned code directly.
- **Pydantic's `EmailStr` rejects RFC 2606 reserved TLDs** (`.test`,
  `.invalid`, `.localhost`) outright — a fixture using `admin@...test`
  never got past request validation.
- **A `master.cf` service whose name differs from its daemon logs with a
  slash in the process tag** — `postfix/submission/smtpd[pid]`, not
  `postfix/smtpd[pid]` — since this relay's `submission` service runs the
  `smtpd` daemon. The mail-log parser's line regex didn't originally allow
  a `/` there, so it silently failed to match *every* line the submission
  service ever produces: every AUTH and every NOQUEUE reject, since
  submission is the only port real clients use. Two new mail-log
  ingestion tests caught this immediately (local user attribution and
  the rejection itself were both silently absent) — see
  postfix-architecture.md §9.
