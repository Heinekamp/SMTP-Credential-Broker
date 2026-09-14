# Database Schema

Default engine: SQLite (WAL mode). Schema is kept dialect-neutral (standard
types, no SQLite-only features, all constraints expressed in a way SQLAlchemy
can compile to Postgres too) so `DATABASE_URL` can point at Postgres instead
without a schema rewrite. All tables use an integer surrogate primary key
(`id`) and standard `created_at`/`updated_at` timestamps unless noted.

Migrations are managed with Alembic; every schema change ships as a
migration, never a manual `ALTER`.

## Entity-relationship overview

```text
admin_users ──1:N── admin_sessions

upstream_accounts ──1:N── senders

senders ──N:M (via user_sender_permissions)── local_smtp_users

local_smtp_users ──1:N── mail_log (as sender-of-record)
senders ──1:N── mail_log
upstream_accounts ──1:N── mail_log

admin_users ──1:N── audit_log

config_generations (standalone, references nothing — see §8)
```

## 1. `admin_users`

Web administration accounts. Entirely separate from SMTP credentials.

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `email` | text, unique, not null | login identifier |
| `password_hash` | text, not null | Argon2id |
| `totp_secret_encrypted` | text, nullable | encrypted the same way as upstream passwords (security-model.md §5); null = TOTP disabled |
| `is_active` | boolean, not null, default true | disabling an admin without deleting their audit history |
| `created_at` | timestamp, not null | |
| `last_login_at` | timestamp, nullable | |

## 2. `admin_sessions`

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `admin_user_id` | FK → `admin_users.id`, not null | |
| `token_hash` | text, unique, not null | SHA-256 of the session token; the raw token only ever exists in the cookie |
| `created_at` | timestamp, not null | |
| `expires_at` | timestamp, not null | |
| `revoked_at` | timestamp, nullable | explicit logout / admin-forced revocation |
| `ip_address` | text, nullable | audit metadata |
| `user_agent` | text, nullable | audit metadata |

## 3. `upstream_accounts`

One row per externally-hosted SMTP account (a STRATO mailbox, etc.).

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `name` | text, not null | admin-facing label, e.g. "STRATO noreply" |
| `host` | text, not null | e.g. `smtp.strato.de` |
| `port` | integer, not null | e.g. `587` |
| `tls_mode` | enum: `starttls`, `implicit` | `implicit` = wrapper-mode TLS (typically port 465) |
| `username` | text, not null | upstream SMTP AUTH username, usually the mailbox address |
| `encrypted_password` | blob, not null | AES-256-GCM ciphertext + nonce (security-model.md §2) |
| `enabled` | boolean, not null, default true | disabled accounts are excluded from config generation entirely |
| `last_test_at` | timestamp, nullable | last "Test connection" run |
| `last_test_result` | enum: `unknown`, `success`, `failure`, nullable | |
| `last_test_error` | text, nullable | human-readable diagnostic only — never contains the password |
| `created_at` / `updated_at` | timestamp | |

`encrypted_password` is **never** included in any API response schema, at
any endpoint, under any admin role — enforced by never defining a Pydantic
field for it on output models, not by a runtime redaction step (removing a
class of bug rather than trying to catch it every time).

## 4. `senders`

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `address` | text, unique, not null | e.g. `noreply@example.com` |
| `upstream_account_id` | FK → `upstream_accounts.id`, not null | **one sender → one upstream account** (see architecture.md §9 for why this default was chosen) |
| `enabled` | boolean, not null, default true | disabled senders are dropped from `smtpd_sender_login_maps` and `sender_dependent_relayhost_maps` on next generation, immediately revoking their use |
| `description` | text, nullable | free-form admin note |
| `created_at` / `updated_at` | timestamp | |

## 5. `local_smtp_users`

Credentials issued to internal services (InvenTree, monitoring, printers...).

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `name` | text, not null | admin-facing label, e.g. "InvenTree" |
| `username` | text, unique, not null | the SASL/AUTH username, e.g. `inventree` |
| `password_hash` | text, not null | Argon2id — **bookkeeping only**; the authoritative check happens in Cyrus SASL's `sasldb2` (security-model.md §4). Kept so the UI can show "password last changed" without ever re-reading the real secret. |
| `enabled` | boolean, not null, default true | disabling removes the user from `sasldb2` on next generation, immediately revoking SMTP AUTH, without deleting history/permissions |
| `created_at` | timestamp, not null | |
| `password_last_rotated_at` | timestamp, nullable | |

## 6. `user_sender_permissions`

The many-to-many grant. This table's contents, filtered to enabled users and
enabled senders, is exactly what gets rendered into
`smtpd_sender_login_maps`.

| Column | Type | Notes |
|---|---|---|
| `local_smtp_user_id` | FK → `local_smtp_users.id`, part of composite PK | |
| `sender_id` | FK → `senders.id`, part of composite PK | |
| `granted_at` | timestamp, not null | |
| `granted_by_admin_id` | FK → `admin_users.id`, nullable | audit trail |

## 7. `mail_log`

Populated by tailing/parsing Postfix's own logs (matched by queue ID), not by
the application intercepting mail. **No message bodies or subject lines are
ever stored** (spec §19).

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `queue_id` | text, not null, indexed | Postfix's queue ID, the join key back to `postqueue`/`postsuper` output |
| `timestamp` | timestamp, not null | |
| `local_smtp_user_id` | FK → `local_smtp_users.id`, nullable | nullable because a log row must still be storable if the user was later deleted |
| `envelope_sender` | text, not null | |
| `recipients` | text (JSON array), not null | envelope recipients only |
| `upstream_account_id` | FK → `upstream_accounts.id`, nullable | nullable for the same reason as `local_smtp_user_id` |
| `status` | enum: `queued`, `sent`, `deferred`, `bounced`, `rejected` | |
| `error` | text, nullable | Postfix's own diagnostic text, credential-free by construction (security-model.md §8) |
| `created_at` | timestamp, not null | |

Indexed on `(timestamp)`, `(envelope_sender)`, `(local_smtp_user_id)`,
`(status)` to support the filtering required by spec §19.

### 7a. `mail_log_ingest_state`

Added in Stage 5, alongside the ingestion pipeline that populates
`mail_log` itself (postfix-architecture.md §9) — not part of this
document's original table list, since log ingestion didn't exist yet when
this document was first written. Purely operational state, not
admin-facing or audit-relevant data.

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | Always `1` — a singleton row. |
| `byte_offset` | integer, not null | How far into the postfix container's maillog ingestion has read; lets an app restart resume instead of re-parsing the whole file or skipping whatever was written meanwhile. |
| `updated_at` | timestamp, not null | |

## 8. `config_generations`

One row per attempted configuration generation (not just successful ones —
failures are exactly what an admin needs visibility into).

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `generated_at` | timestamp, not null | |
| `triggered_by_admin_id` | FK → `admin_users.id`, nullable | null for system/CLI-triggered generations |
| `checksum` | text, not null | hash of the rendered `main.cf`/`master.cf` output, for "did anything actually change" checks (drives `reload_triggered`) |
| `maps_checksum` | text, not null | hash of the rendered map sources, tracked separately since map-only changes deliberately don't affect `checksum` — added in Stage 6 for health-check drift detection (architecture.md §7) |
| `validation_result` | enum: `pass`, `fail` | |
| `validation_detail` | text, nullable | `postconf`/`postmap` error output on failure |
| `applied` | boolean, not null, default false | true only once the atomic install step (architecture.md §5) completed |
| `reload_triggered` | boolean, not null, default false | distinguishes "map-only, no reload needed" from "main.cf/master.cf changed, reload issued" |

## 9. `audit_log`

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `timestamp` | timestamp, not null | |
| `admin_user_id` | FK → `admin_users.id`, nullable | null for system actions |
| `action` | text, not null | e.g. `upstream_account.create`, `sender.disable`, `permission.grant` |
| `target_type` / `target_id` | text / integer | polymorphic reference to the affected row |
| `detail` | text (JSON), nullable | structured, non-secret context (never includes password fields, by the same "no field defined for it" rule as §3) |
| `ip_address` | text, nullable | |

## Notes on the one-sender-to-one-upstream default

`senders.upstream_account_id` is a plain not-null foreign key rather than a
join table. This matches the real-world model this project targets (one
externally hosted mailbox, one set of credentials, one or more envelope
addresses that legitimately send as that mailbox — see the `alerts@` /
`server@` example in postfix-architecture.md §1) and keeps
`sender_dependent_relayhost_maps` a simple one-line-per-sender lookup. If a
future requirement needs upstream failover per sender (e.g. try provider A,
fall back to provider B), that's a schema migration (`senders` ↔
`upstream_accounts` becomes many-to-many with an ordering column) and a
Postfix-side redesign (Postfix's sender-dependent maps don't natively express
failover the way this would need); it is out of scope unless explicitly
requested, per architecture.md §10's open question.
