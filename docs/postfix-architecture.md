# Postfix Architecture

This document is the one a future maintainer should read to understand the
Postfix side of the relay **without** re-deriving it from first principles.
It shows the actual configuration the application generates, explains every
non-obvious directive, and walks through the authentication, authorization,
upstream-selection, and TLS flows end to end.

All secrets shown below are fake/redacted placeholders.

## 0. The four identities

Before anything else, four distinct things must never be conflated — the rest
of this document only makes sense if they're kept separate:

| # | Identity | Where it comes from | Verified by |
|---|---|---|---|
| 1 | **SMTP AUTH identity** | `AUTH PLAIN/LOGIN` credentials the connecting client presents | Cyrus SASL / `sasldb2` |
| 2 | **Envelope sender** (`MAIL FROM:`) | The address the client declares it's sending as | `smtpd_sender_login_maps` + `reject_sender_login_mismatch`, checked against identity #1 |
| 3 | **`From:` message header** | Whatever the client puts in the message body | **Nothing.** Never used for any authorization decision. |
| 4 | **Upstream SMTP identity** | The credentials Postfix's own `smtp` client presents to the provider | `sender_dependent_relayhost_maps` + `smtp_sasl_password_maps`, selected by identity #2, completely independent of identity #1 |

A local user authenticates as #1, is authorized to use a specific #2, and
Postfix separately authenticates as #4 to deliver — the local user never
sees, needs, or can retrieve #4.

## 1. Worked example

Three upstream mailboxes at two different providers, four senders, three
local applications:

```text
Upstream accounts
------------------
"STRATO printer"        smtp.strato.de:587    STARTTLS   printer@example.com
"STRATO noreply"        smtp.strato.de:587    STARTTLS   noreply@example.com
"Example Hosting alerts" smtp.example-hosting.net:587  STARTTLS  server@example.com

Senders                          Upstream account
--------------------------------------------------
printer@example.com       →      STRATO printer
noreply@example.com       →      STRATO noreply
server@example.com        →      Example Hosting alerts
alerts@example.com        →      Example Hosting alerts   (alias mailbox,
                                                             same provider
                                                             credentials as
                                                             server@)

Local SMTP users     Allowed senders
--------------------------------------------------
printer-service   →  printer@example.com
inventree         →  noreply@example.com
monitoring        →  server@example.com, alerts@example.com
```

This shows the generic model in action (two different providers, one
provider hosting two mailboxes/senders that share credentials) — nothing here
is STRATO-specific in the generated configuration.

## 2. Generated `main.cf` (relay-relevant subset)

```ini
# ── Identity / posture ──────────────────────────────────────────────
myhostname = relay.internal.example.net
mydomain = internal.example.net
myorigin = $mydomain
inet_interfaces = all
inet_protocols = ipv4
mynetworks = 127.0.0.0/8
# This relay never accepts mail *for* any domain (no inbound delivery),
# and mynetworks is loopback-only on purpose: no client, however local,
# is trusted to relay without SMTP AUTH. See "Why no permit_mynetworks"
# in §6.
mydestination =
relay_domains =
local_transport = error:local mail delivery is disabled on this relay

# ── Client-facing (smtpd) TLS ───────────────────────────────────────
smtpd_tls_cert_file = /etc/postfix/tls/relay.crt
smtpd_tls_key_file = /etc/postfix/tls/relay.key
smtpd_tls_security_level = encrypt
smtpd_tls_auth_only = yes
smtpd_tls_protocols = !SSLv2, !SSLv3, !TLSv1, !TLSv1.1
smtpd_tls_mandatory_ciphers = high

# ── Client-facing (smtpd) SASL ──────────────────────────────────────
smtpd_sasl_type = cyrus
smtpd_sasl_path = smtpd
smtpd_sasl_auth_enable = yes
smtpd_sasl_security_options = noanonymous
smtpd_sasl_local_domain =
broken_sasl_auth_clients = yes

# ── Sender authorization (the core invariant) ───────────────────────
smtpd_sender_login_maps = lmdb:/etc/postfix/relay/sender_login
smtpd_sender_restrictions =
    reject_sender_login_mismatch
smtpd_relay_restrictions =
    permit_sasl_authenticated
    reject
smtpd_recipient_restrictions =
    permit_sasl_authenticated
    reject_unauth_destination
smtpd_helo_required = yes

# ── Upstream (smtp client) TLS ──────────────────────────────────────
smtp_tls_security_level = encrypt
smtp_tls_CAfile = /etc/ssl/certs/ca-certificates.crt
smtp_tls_loglevel = 1

# ── Upstream selection / sender-dependent authentication ────────────
smtp_sender_dependent_authentication = yes
sender_dependent_relayhost_maps = lmdb:/etc/postfix/relay/sender_relayhost
smtp_sasl_auth_enable = yes
smtp_sasl_password_maps = lmdb:/etc/postfix/relay/sasl_passwd
smtp_sasl_security_options = noanonymous
relayhost =
```

### Explanation of the non-obvious ones

- **`mydestination =` / `relay_domains =` / `local_transport = error:...`** —
  this relay is submission-only. It must never accept mail addressed *to* any
  domain it thinks it owns, and must never attempt local delivery. Leaving
  these at their package defaults (which typically list `$myhostname`) would
  make Postfix try to deliver certain messages locally instead of relaying
  them.
- **`mynetworks = 127.0.0.0/8`** — deliberately loopback-only. See §6 for why
  no internal subnet is ever added here for relay purposes.
- **`smtpd_tls_auth_only = yes`** — refuses `AUTH` before `STARTTLS`, so
  credentials are never sent in the clear even if a misconfigured client
  offers to.
- **`smtpd_sasl_type = cyrus` / `smtpd_sasl_path = smtpd`** — tells Postfix's
  `smtpd` process to authenticate via the Cyrus SASL library using the
  `smtpd` service name, which the Cyrus SASL config
  (`/usr/lib/sasl2/smtpd.conf`) points at the `sasldb` auxprop plugin — i.e.
  at `/etc/sasldb2`. This is the local SMTP AUTH identity check (#1).
- **`broken_sasl_auth_clients = yes`** — accepts the old
  (pre-RFC-4954-draft-final) `AUTH=` syntax some embedded devices (printers,
  NAS firmware, older appliances) still send. Harmless to enable broadly;
  without it, some real hardware in this project's target audience simply
  cannot authenticate at all.
- **`smtpd_sender_login_maps`** — the map from envelope-sender address to the
  local SMTP username(s) allowed to use it. This is *not* an authentication
  mechanism; it's the authorization table `reject_sender_login_mismatch`
  consults.
- **`smtpd_sender_restrictions = reject_sender_login_mismatch`** — evaluated
  at `MAIL FROM` time. `reject_sender_login_mismatch` is shorthand for both
  `reject_authenticated_sender_login_mismatch` (an authenticated client using
  a sender address it doesn't own) and
  `reject_unauthenticated_sender_login_mismatch` (an unauthenticated client
  trying to use *any* address that has an owner in the map at all). This is
  the line that enforces the invariant in §5.
- **`smtpd_relay_restrictions = permit_sasl_authenticated, reject`** —
  evaluated at `RCPT TO` time, and deliberately kept separate from
  `smtpd_recipient_restrictions` (current Postfix practice since 2.10, rather
  than the older pattern of overloading `smtpd_recipient_restrictions` with
  both relay control and spam control — mixing them risks a permissive
  anti-spam rule accidentally becoming a permissive relay rule). No
  `permit_mynetworks` here: only a SASL-authenticated session may relay,
  full stop. This is what makes open relaying impossible regardless of
  source IP — see §7.
- **`smtpd_recipient_restrictions = permit_sasl_authenticated,
  reject_unauth_destination`** — the (now purely anti-abuse, not
  relay-authorization) recipient-side check. `reject_unauth_destination` is
  effectively redundant with `smtpd_relay_restrictions` today but is kept as
  defense in depth and because it's still the parameter most anti-spam
  add-ons expect to extend.
- **`smtp_sender_dependent_authentication = yes`** — tells the Postfix SMTP
  *client* (the outbound side, delivering to upstream) to look up SASL
  credentials by the message's envelope sender *before* falling back to
  looking them up by destination host. This is what makes "credentials
  depend on which mailbox is sending" possible at all.
- **`sender_dependent_relayhost_maps`** — per-sender override of `relayhost`.
  Without a sender-specific entry, Postfix would fall back to the global
  `relayhost` (intentionally left empty here — every sender in this system
  must have an explicit entry, so a sender with no map entry fails loudly
  instead of leaking through a default host).
- **`smtp_sasl_password_maps`** — the credentials the outbound `smtp` client
  presents, looked up first by sender (because of
  `smtp_sender_dependent_authentication`), format `key  username:password`.

## 3. Generated `master.cf` (submission service)

```text
submission inet n       -       n       -       -       smtpd
  -o syslog_name=postfix/submission
  -o smtpd_tls_security_level=encrypt
  -o smtpd_tls_auth_only=yes
  -o smtpd_sasl_auth_enable=yes
  -o smtpd_sender_restrictions=reject_sender_login_mismatch
  -o smtpd_relay_restrictions=permit_sasl_authenticated,reject
  -o smtpd_recipient_restrictions=permit_sasl_authenticated,reject_unauth_destination
  -o milter_macro_daemon_name=ORIGINATING
```

Only the submission service (port 587) is exposed to internal networks. The
plain port-25 `smtpd` service is left bound to loopback only (its default
`main.cf`-level restrictions apply, but nothing internal is expected to ever
reach it) — this relay's job is *submission*, not accepting arbitrary
port-25 SMTP.

## 4. Generated lookup maps (source files, before `postmap`)

`/etc/postfix/relay/sender_login`:

```text
printer@example.com    printer-service
noreply@example.com    inventree
server@example.com     monitoring
alerts@example.com     monitoring
```

`/etc/postfix/relay/sender_relayhost`:

```text
printer@example.com    [smtp.strato.de]:587
noreply@example.com    [smtp.strato.de]:587
server@example.com     [smtp.example-hosting.net]:587
alerts@example.com     [smtp.example-hosting.net]:587
```

`/etc/postfix/relay/sasl_passwd`:

```text
printer@example.com    printer@example.com:REDACTED-UPSTREAM-PASSWORD-1
noreply@example.com    noreply@example.com:REDACTED-UPSTREAM-PASSWORD-2
server@example.com     server@example.com:REDACTED-UPSTREAM-PASSWORD-3
alerts@example.com     server@example.com:REDACTED-UPSTREAM-PASSWORD-3
```

Note `alerts@example.com` authenticates upstream *as* `server@example.com` —
they're the same real mailbox at the provider, just two envelope-sender
addresses the local `monitoring` user is allowed to use. This is the generic
model's answer to "an address is really just an alias of a mailbox I already
pay for."

Each source file is converted with `postmap lmdb:/etc/postfix/relay/<name>`
into `<name>.lmdb`, which is what the running `main.cf` directives actually
reference (`lmdb:/etc/postfix/relay/<name>`, no `.lmdb` suffix needed —
Postfix appends it). `lmdb` is used instead of the older `hash`/`cdb` types
because it tolerates concurrent readers without the reader needing to reopen
the file on every lookup, which matters once the relay handles more than a
handful of senders.

## 5. Local SMTP AUTH (`sasldb2`)

Local SMTP users are **not** stored in a Postfix map at all — Cyrus SASL's
`sasldb` auxprop plugin owns `/etc/sasldb2`, a Berkeley DB file that only
`saslpasswd2` (or the SASL library itself) can write to safely. The
application shells out to it whenever a local user is created, has its
password regenerated, or is deleted:

```bash
# create / update (password piped on stdin, never passed as an argv,
# never logged)
printf '%s' "$GENERATED_PASSWORD" | saslpasswd2 -c -p -u relay.internal.example.net printer-service

# delete
saslpasswd2 -d -u relay.internal.example.net printer-service
```

The `-u` realm (`relay.internal.example.net`, i.e. `$myhostname`) must match
what `smtpd_sasl_local_domain` resolves to (empty ⇒ `$myhostname`) — this is
called out because it's the single most common cause of "valid-looking
credentials that Postfix rejects anyway" in Cyrus SASL setups, and is worth a
maintainer knowing on day one rather than rediscovering via trial and error.

`/etc/sasldb2` is owned by root, mode `0640`, group-readable only by the
`postfix`/`sasl` group inside the `postfix` container — see
[security-model.md](security-model.md) §4 for the full threat-model
discussion of this being the one place a plaintext-equivalent secret must
exist outside the encrypted database.

## 6. Why no `permit_mynetworks` in relay restrictions

It's tempting to trust "internal" IP ranges (the Docker network, the LAN) and
let them relay without authentication, the way many quick Postfix tutorials
do. This system deliberately does not, for one reason: the entire point of
the product is **per-service sender permission**, and an IP-based trust rule
has no concept of "which service." Any device on the trusted subnet would be
able to send as *any* sender, defeating the reason this project exists. So
every client — including other containers on the same Docker network —
authenticates with its own local SMTP user and is bound by that user's
`smtpd_sender_login_maps` entry.

## 7. How configuration changes are applied

| Change | What's regenerated | Apply step |
|---|---|---|
| Add/edit/disable a sender's permissions | `sender_login` source + `.lmdb` | **None.** Postfix's `smtpd(8)` processes re-read a lookup table automatically once its file's mtime/inode changes; no `reload` or restart needed. |
| Add/edit an upstream account or change which upstream a sender uses | `sender_relayhost` + `sasl_passwd` sources + `.lmdb`s | **None**, same reason. |
| Rotate an upstream account's password | `sasl_passwd` source + `.lmdb` only | **None.** `sender_login` and `sender_relayhost` are untouched — this is why credential rotation never affects local users' credentials (spec §25's rotation test). |
| Add/remove a local SMTP user | `sasldb2` entry (via `saslpasswd2`) + `sender_login` (if permissions changed too) | **None** for `sasldb2` — the SASL library reads it per-authentication-attempt, not cached at process start. |
| Change `myhostname`, add a new TLS certificate, or any other `main.cf`/`master.cf`-level change | Full `main.cf`/`master.cf` render | `postfix reload` (never a hard restart — reload keeps the queue and in-flight connections intact; `postfix.org`'s own guidance is that config file edits only need `reload`, and even that isn't required for pure lookup-table changes). |

Every regeneration — whether or not it results in an `apply` step — is
validated first (`postconf -c <tmp>`; `postmap` against each source file) and
recorded in `config_generations` (see
[database-schema.md](database-schema.md)) with its checksum and validation
result, so "what config was active when" is always answerable.

## 8. Open-relay prevention, summarized

An unauthenticated client cannot relay because:

1. It never passes `smtpd_relay_restrictions` — there is no
   `permit_mynetworks`, and `permit_sasl_authenticated` requires a completed
   `AUTH` exchange.
2. Even if it tries a `MAIL FROM` using an address that happens to be one of
   our senders, `reject_unauthenticated_sender_login_mismatch` (part of
   `reject_sender_login_mismatch`) rejects it during the `MAIL FROM` stage,
   before relay is even considered.
3. `mynetworks` is loopback-only, so there is no IP range from which either
   restriction is bypassed.

An authenticated client cannot relay as a sender it doesn't own because
`reject_authenticated_sender_login_mismatch` (the other half of
`reject_sender_login_mismatch`) checks the authenticated SASL username
against `smtpd_sender_login_maps` for the declared `MAIL FROM` address on
every message, regardless of what the client's SMTP library or the operator
typed into a device's web form.
