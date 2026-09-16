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

local_smtp_users ──1:N── local_user_rate_limit_counters
local_smtp_users ──1:1── local_user_burst_buckets

admin_users ──1:N── audit_log

config_generations (standalone, references nothing — see §8)

senders ──0:1── relay_settings (as the notification sender)
background_job_state (standalone, references nothing — see §11)
```

## 1. `admin_users`

Web administration accounts. Entirely separate from SMTP credentials.

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `email` | text, unique, not null | login identifier |
| `password_hash` | text, not null | Argon2id |
| `totp_secret_encrypted` | blob, nullable | encrypted the same way as upstream passwords (security-model.md §5); null = TOTP disabled |
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
| `rate_limit_per_hour` | integer, nullable | `null` = unlimited (default). Paces outbound delivery via a synthetic per-account Postfix transport rather than rejecting anything — postfix-architecture.md §10. |
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
| `rate_limit_per_hour` | integer, nullable | `null` = unlimited (default). Enforced by the rate-limit policy service (postfix-architecture.md §10, security-model.md §10) against §12's counter table, keyed on this user's `username` as the authenticated SASL identity. |
| `rate_limit_burst` | integer, nullable | `null` = no burst protection (default). Only accepted, and only enforced, alongside `rate_limit_per_hour` — its refill rate is always derived from that field (postfix-architecture.md §10's burst-protection subsection). Backed by §13's token-bucket table. |
| `rate_limit_defer_streak_started_at` | timestamp, nullable | `null` = not currently in an unbroken streak of rejections. Set on any defer, cleared on any permit or on being re-enabled — backs the always-visible `rate_limit_abuse` alert and the opt-in auto-disable tick (postfix-architecture.md §10's abuse-detection subsection). |

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

## 10. `relay_settings`

Singleton row (id fixed at 1) — every admin-editable, DB-backed setting for
scheduled connection testing and alerting. Unlike this project's other
tunables (`app/config.py`, env-var-only by design), these need to be
editable from the UI without a restart, and the notification sender
references a live `senders` row, which an env var can't express.

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | Always `1` — a singleton row. |
| `connection_test_interval_minutes` | integer, nullable | `NULL` = disabled/manual-only (the default on a fresh install, so upgrading an existing instance never silently starts periodic AUTH attempts against a real upstream provider without opt-in). |
| `update_check_enabled` | boolean, not null, default false | Whether the background update-checker makes any outbound calls at all — off by default. |
| `notify_recipients` | JSON array of strings, not null | Alert email recipient addresses. |
| `notify_sender_id` | FK → `senders.id`, nullable, `ON DELETE SET NULL` | Which configured sender alert emails are sent from. |
| `notify_on_health_degraded` / `notify_on_upstream_test_failure` / `notify_on_app_update_available` / `notify_on_postfix_update_available` | boolean, not null, default true | Per-alert-kind email toggles — four fixed, known-in-advance kinds, so booleans on one row rather than a child table. |
| `notify_on_rate_limit_abuse` | boolean, not null, default **false** | Same shape as the four above, but default off — a new automated-behavior category should not silently start emailing on upgrade the way the older baseline-monitoring kinds already did (postfix-architecture.md §10). |
| `rate_limit_abuse_auto_disable_enabled` | boolean, not null, default false | Opt-in escalation: `core/rate_limit_abuse.py`'s tick disables a still-enabled flagged user outright, independent of the email toggle above. |
| `rate_limit_abuse_threshold_minutes` | integer, not null, default 10 | How long a local user's unbroken defer streak must run before it's surfaced at all — always consulted for the notification-bell alert, regardless of the two toggles above. |
| `updated_at` | timestamp, not null | |

## 11. `background_job_state`

Singleton row (id fixed at 1), system-only — never admin-edited, purely
operational state for the background scheduler, matching
`mail_log_ingest_state`'s existing pattern.

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | Always `1` — a singleton row. |
| `connection_test_last_run_at` / `update_check_last_run_at` | timestamp, nullable | When each periodic job last actually ran (not every poll tick — only ticks that did real work). |
| `latest_app_version` / `latest_postfix_version` | text, nullable | Cached result of the last successful update check. |
| `latest_app_version_checked_at` / `latest_postfix_version_checked_at` | timestamp, nullable | |
| `app_update_last_emailed_version` / `postfix_update_last_emailed_version` | text, nullable | Edge-trigger state — an update email fires once per newly-seen version, not on every poll. |
| `app_update_acknowledged_version` / `postfix_update_acknowledged_version` | text, nullable | An admin-acknowledged *version*, not a plain dismissed flag — a newer release automatically reactivates the alert. |
| `health_degraded_active` / `upstream_test_failure_active` / `rate_limit_abuse_active` | boolean, not null, default false | Last-seen state per alert kind, so email only fires on a resolved→active transition. `rate_limit_abuse_active` is bundled across every currently-flagged user into one gauge, exactly like `upstream_test_failure_active` already bundles multiple failing accounts. |
| `rate_limit_cleanup_last_run_at` | timestamp, nullable | Last time §12's stale counter rows were swept up (postfix-architecture.md §10). |
| `updated_at` | timestamp, not null | |

## 12. `local_user_rate_limit_counters`

Backs the local-user rate-limit policy service's accept/defer decision
(postfix-architecture.md §10, security-model.md §10) — the upstream-account
side needs no equivalent table, since its pacing is native Postfix
transport behavior with no counting of its own.

| Column | Type | Notes |
|---|---|---|
| `id` | integer PK | |
| `local_smtp_user_id` | FK → `local_smtp_users.id`, not null, `ON DELETE CASCADE` | |
| `window_start` | timestamp, not null | The current hour, truncated to `:00` — a fixed window, not a sliding one. Unique together with `local_smtp_user_id`. |
| `count` | integer, not null, default 0 | Messages permitted in this window so far. A rejected (over-limit) attempt does **not** increment this — retrying a legitimate send must never make things worse. |

A window rolling over needs no explicit reset: the next hour's
`window_start` simply has no row yet, so a fresh lookup starts at zero.
Rows more than a few hours stale are inert (nothing ever reads them again)
and are swept up by a daily background tick purely for table hygiene, not
correctness.

## 13. `local_user_burst_buckets`

Backs the burst-protection token bucket (postfix-architecture.md §10's
burst-protection subsection) — independent of, and checked in addition
to, §12's hourly counter. Unlike that table, this one never grows: it's
a single row per user, continuously refilled and spent in place, so
`local_smtp_user_id` is the primary key itself rather than a surrogate
`id` with a unique constraint, and there's no cleanup tick for it — the
row simply disappears via the same cascade delete as everything else
keyed off a local user.

| Column | Type | Notes |
|---|---|---|
| `local_smtp_user_id` | FK → `local_smtp_users.id`, PK, `ON DELETE CASCADE` | |
| `tokens` | float, not null | Available tokens right now, as of `last_refill_at` — capped at `rate_limit_burst`, decremented by 1 on every permitted message. |
| `last_refill_at` | timestamp, not null | The clock reference the next refill computation measures elapsed time from. Updated on **every** check, including a deferred one — a rejected message must not lose refill progress any more than it should get to spend a token it never used. |

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
