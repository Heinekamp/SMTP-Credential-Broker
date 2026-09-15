# Known limitations

Findings from internal review passes that were judged **accepted risk or
informational** rather than actionable bugs — deliberately not filed as
GitHub issues, but kept here so they aren't rediscovered from scratch later.
If the app's usage pattern changes (more admins, higher threat model, larger
scale), re-read this list before assuming these are still fine to leave as-is.

## Flat, single-role admin authorization model

`admin_users` has no `role` column; every admin is equally privileged. Any
authenticated admin can create additional admin accounts (`admins.py`), and
by extension every other route in the app is reachable by every admin
equally — there is no super-admin/operator/viewer distinction.

This matches the security model's documented single-trusted-operator
assumption, so it isn't a vulnerability under that assumption. It becomes a
real gap the moment this app is run with multiple admins who shouldn't fully
trust each other (e.g. an on-call/ops person who only needs Dashboard/Mail
Log/Queue visibility during an incident, but today would need a fully
privileged account to get it).

**Revisit when:** a second admin with a different trust level is actually
needed. See the open question in [architecture.md](architecture.md) §10.
A read-only viewer role would touch authorization checks across every
mutating route — not a localized change — so it deserves its own scoping
pass rather than being bolted on quickly.

## Login/TOTP rate-limit lockout caps at a fixed 15 minutes

`backend/app/config.py` defines escalating lockout thresholds —
`(5 failures, 60s)`, `(10, 300s)`, `(15, 900s)` — and
`backend/app/core/rate_limit.py` applies the highest threshold met. Beyond 15
cumulative failures, the lockout window never grows past 15 minutes; it
doesn't escalate further, and there's no eventual hard lockout, alerting, or
CAPTCHA-style backoff growth.

This still throttles a TOTP brute force to roughly 4 attempts/hour
indefinitely, against a 6-digit code with `valid_window=1` (~333k valid
values) — slow enough to be low risk today, not urgent to change.

**Revisit when:** exposing the admin login to an untrusted network directly
(vs. behind a VPN/reverse-proxy-with-its-own-auth, the assumed common case),
or if login attempt volume in the audit log ever suggests real brute-force
attempts are happening.
