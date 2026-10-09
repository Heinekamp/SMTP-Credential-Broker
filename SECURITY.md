# Security Policy

## Supported versions

SMTP Credential Broker is pre-1.0. Security fixes go into the **latest
release** only. If you're on an older version, upgrade first (see
[docs/upgrading.md](docs/upgrading.md)).

## Reporting a vulnerability

**Please don't report security issues in public GitHub issues, discussions
or pull requests.**

Report them privately through GitHub's private vulnerability reporting:
open the repository's **Security** tab and click **Report a
vulnerability**, or go straight to
<https://github.com/Heinekamp/SMTP-Credential-Broker/security/advisories/new>.

Where you can, include:

- the affected version (or commit) and how it is deployed
- what an attacker could do, and what access they need to start with
- steps to reproduce, or a proof of concept

This is a solo-maintained project, so responses are best-effort. Once a
report is confirmed, the fix ships in a new release and is published as a
GitHub security advisory. Reporters are credited unless they'd rather not
be.

## Scope

The system's secret handling, trust boundaries and stated threat model are
documented in [docs/security-model.md](docs/security-model.md). Reports are
especially welcome for:

- any way an internal service's local credential can send as a sender it
  isn't authorized for, or reach a real upstream password
- authentication, session, CSRF or TOTP bypasses in the admin UI/API
- abuse of the Postfix control surface or of generated Postfix config
- exposure of stored secrets (upstream passwords, TOTP secrets, API
  tokens, TLS keys, `RELAY_ENCRYPTION_KEY`)

Problems caused only by a deployment choice the docs already warn against,
such as exposing the admin UI beyond a trusted network without a TLS
reverse proxy, or setting `RELAY_COOKIE_SECURE=false` in production, are
out of scope.
