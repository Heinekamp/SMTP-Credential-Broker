# Claude Design Prompt — Managed SMTP Relay Admin UI

This is the complete brief to hand to Claude Design for Phase 4 of this
project. It describes the product, its users, its workflows, and the screens
needed, and states explicit constraints on tone and visual approach. It
deliberately does not specify colors, typography, or branding — see
"Visual identity" below.

---

## What this application is

A self-hosted web administration console for a Postfix-based SMTP relay. It
lets an infrastructure operator centralize several externally-hosted SMTP
mailboxes (e.g. multiple accounts at a hosting provider) and hand out
scoped, per-service credentials to internal applications/devices, so those
services never see the real upstream provider passwords. The operator
manages upstream accounts, defines "senders" (email addresses) tied to those
accounts, creates local SMTP credentials for each internal service, and
grants each local credential permission to send as specific senders. Postfix
itself — not this application — handles actual SMTP traffic; the UI is a
management plane over it, plus visibility into its logs and queue.

## Who uses it

A single technically proficient administrator (a homelab or small-business
infrastructure engineer), managing infrastructure that other people don't
directly touch. This is not a multi-tenant SaaS product and not aimed at
non-technical users — but it should still be genuinely pleasant and fast to
use for the person who lives in it daily. Assume the user is comfortable with
concepts like SMTP, TLS, DNS, and reading a table of technical status
information, but has no patience for a UI that's slow, cute, or hides
information behind excessive clicks.

## Primary workflows (design for these end to end)

1. **First-time setup**: fresh install → create the first admin account →
   land on a mostly-empty dashboard → guided next steps ("Add an upstream
   account," "Add a sender," "Create a local SMTP user").
2. **Add an upstream SMTP account**: name, host, port, TLS mode, username,
   password → Test Connection (shows DNS/TCP/TLS/AUTH sub-steps and their
   individual pass/fail) → Save.
3. **Add a sender**: address + which upstream account it uses → save; the
   form should make the upstream credential choice unambiguous (which
   provider/mailbox this address will actually send through).
4. **Create a local SMTP user**: name + auto-generated username → Generate
   Password → the generated password is shown exactly once, with an
   unmistakable "copy this now, it cannot be shown again" affordance → Save.
5. **Grant permissions**: from a local user, check which senders they may
   use; from a sender, see which local users may use it (both directions
   need to be a first-class view, not one bolted onto the other — spec
   requirement).
6. **Configure the actual internal service** (outside this UI, but the UI
   should make the handoff easy): the user copies host/port/username/
   password/from-address for pasting into some other application's SMTP
   settings — consider a "connection details" summary view/copy-block for
   this purpose.
7. **Day-to-day monitoring**: check the dashboard for relay/Postfix health,
   glance at recent mail log entries and queue depth, investigate a specific
   failed delivery by filtering the mail log.
8. **Incident response**: a delivery is failing — operator needs to quickly
   determine whether it's an auth problem, a permission problem, or an
   upstream provider problem, and the mail log / error text needs to make
   that distinction obvious without needing to SSH into the box.

## Information architecture / navigation

Primary navigation (persistent, e.g. a left sidebar — but defer to the
existing design system's own navigation pattern rather than reinventing one):

- **Dashboard**
- **Upstream Accounts**
- **Senders**
- **Local SMTP Users**
- (Permissions are reached *from* Senders and Local SMTP Users, not a
  separate top-level nav item — it's a relationship you view from either
  side, not a third entity)
- **Mail Log**
- **Queue**
- **Settings** (includes admin accounts, TOTP, encryption key status,
  Postfix connection/health details)

Login and Initial Setup are unauthenticated, full-screen flows outside the
main nav shell.

## Terminology (use exactly these terms throughout — do not invent synonyms)

- **Upstream account** — an externally-hosted SMTP account/mailbox.
- **Sender** — an email address this relay is authorized to send as, tied to
  exactly one upstream account.
- **Local SMTP user** — a credential issued to an internal service to
  authenticate to this relay.
- **Permission** / **Allowed senders** — the grant connecting a local SMTP
  user to the senders it may use.
- **Relay** — the whole system's mail-sending role; never call it a "mail
  server" in user-facing copy (it deliberately doesn't host mailboxes or
  accept inbound mail).
- **Queue** — Postfix's own delivery queue, shown, not reimplemented.

## Required screens / states

### Dashboard
Operational information only, no decorative metrics (explicit constraint):
relay/Postfix health status, counts of upstream accounts / local users /
senders (as plain counts, not oversized "hero" cards), queue depth, recent
delivery failures (short list, links into Mail Log filtered accordingly),
recent deliveries, per-upstream-account connection health (last test
result/time). Needs a clear, low-drama visual distinction between "healthy,"
"degraded" (e.g. one upstream account failing), and "down."

### Upstream Accounts
- List view: name, host, TLS mode, enabled/disabled, last test result + time,
  row actions (edit, test connection, disable, delete).
- Add/Edit form: name, host, port, TLS mode (STARTTLS/implicit), username,
  password field that is **write-only** — editing an existing account must
  never populate the password field with anything (not even masked dots
  standing in for a real value it then re-sends); make "leave blank to keep
  the current password" explicit and unambiguous in the UI, not just a
  tooltip.
- Test Connection: a distinct action (a button, not something that happens
  automatically or silently on save) with a result view showing each
  sub-check (DNS, TCP, TLS, greeting, AUTH) and where in that chain it failed
  if it did. Must not silently double as "send a test email" — that's a
  separate, explicitly-labeled action if offered at all.
- Delete: confirmation dialog that names what depends on this account (which
  senders reference it) so the operator understands the blast radius before
  confirming.

### Senders
- List view: address, upstream account (name, clickable through to it),
  enabled/disabled, count of allowed local users (clickable through to the
  permission view for that sender).
- Add/Edit form: address, upstream account picker that shows enough of that
  account's identity (name + host) that the choice is unambiguous, not just
  an opaque ID or bare name.
- Permission view (from a sender): "Allowed local users" — a checklist or
  equivalent, same interaction pattern as the reverse view below, so a user
  who's learned one direction already knows the other.

### Local SMTP Users
- List view: name, username, enabled/disabled, password last changed,
  allowed-senders count.
- Add form: name → username auto-suggested from it (editable) → "Generate
  Password" action.
- **Password reveal state**: appears once, immediately after generation or
  regeneration, in a state visually distinct from normal UI chrome (this is
  the single most security-sensitive moment in the product — the design
  should make "this will not be shown again, store it now" impossible to
  miss, without resorting to alarmist styling). A copy-to-clipboard control
  is expected here.
- Regenerate Password: a distinct, confirmable action (this invalidates the
  existing credential — the service using it will break until reconfigured,
  and the UI should say so plainly before the operator confirms).
- Permission view (from a user): "Allowed senders" checklist, per spec's own
  example:
  ```
  User: InvenTree
  Allowed senders:
  [x] noreply@example.com
  [ ] printer@example.com
  [ ] server@example.com
  ```
- A "Connection details" view/panel summarizing host/port/username/
  from-address for copy-paste into the service being configured (password
  intentionally excluded here once it's no longer in its one-time reveal
  state — this view must not become a second place the secret is
  retrievable).

### Mail Log
- Table: timestamp, local user, envelope sender, recipients, upstream
  account, status (queued/sent/deferred/bounced/rejected), queue ID, error.
- Filters: date range, sender, recipient, local user, status — combinable,
  not one-at-a-time.
- Status needs clear, non-emoji visual encoding (spec explicitly rules out
  emoji status indicators) — text + a restrained shape/icon from the
  existing design system's own iconography, not a bespoke one.
- Row detail (expand or drill-in): full error text, useful for the "is this
  an auth problem or a permission problem or an upstream problem" incident
  workflow above.
- Explicitly no message body/subject content anywhere in this screen — only
  envelope-level metadata exists to show.

### Queue
- Table: queue ID, sender, recipients, age, status.
- Row actions where Postfix allows it: retry, delete — each with
  confirmation appropriate to its reversibility (delete is destructive and
  needs a clear confirmation; retry is low-risk and can be lighter-weight).

### Settings
- Admin accounts: list, add, TOTP enrollment/removal, password change.
- Encryption key status: whether one is configured, without ever displaying
  it (not even partially) — a health-style indicator, not a secret viewer.
- Postfix/system status: version, config validation status, last
  generation's result, links into recent `config_generations` history for
  troubleshooting.

### Login
Plain, fast, unauthenticated. Email + password, optional TOTP step,
rate-limit feedback if applicable (a clear but non-alarming "too many
attempts, try again in N minutes" — never reveal whether the email or the
password was the wrong part).

### Initial Setup
First-run only: create the first admin account, then hand off into the
Dashboard's guided-empty-state described above. Should not look like a
separate "wizard product" bolted onto the real UI — same visual language
throughout.

### Confirmation dialogs
Needed for: delete (upstream account, sender, local user), regenerate
password, disable (lighter-weight than delete, but still confirmed since it
has immediate operational effect), rotate encryption key (Settings). Each
should state the concrete consequence in plain language ("services using
this credential will stop being able to send until reconfigured"), not a
generic "are you sure?".

### Error states
- Form validation errors inline, field-level, specific (not a generic toast
  for a field-level problem).
- System-level errors (e.g. config generation failed validation) surfaced
  prominently with the actual validation detail available (collapsed by
  default is fine, but accessible in one click) — this is a technical
  audience that wants the real error, not a sanitized one.
- Network/API failure state distinct from "you have no data yet" (see empty
  states) and from "this legitimately failed" (see above).

### Empty states
Every list (Upstream Accounts, Senders, Local SMTP Users, Mail Log, Queue)
needs a real empty state, not a blank table: what this section is for, and a
direct call to action to create the first one (or, for Mail Log/Queue, an
explanation that there's simply nothing to show yet, since those aren't
user-created).

### Loading states
Skeleton/placeholder states for tables and the dashboard's status widgets;
avoid a full-page spinner for anything that isn't a full page navigation.

## Security-sensitive UI elements (design these with particular care)

- The one-time password reveal (Local SMTP Users) — see above.
- The write-only upstream password field — see above.
- Delete/disable/regenerate confirmations that state real consequences.
- Encryption key status indicator that never leaks the key.
- Rate-limit/lockout messaging on Login that doesn't help an attacker
  distinguish valid usernames from invalid ones.

## What should be emphasized vs. secondary

**Emphasize**: current health/status (dashboard and per-item status
indicators), the permission relationship (it's the core value proposition of
the product and should never feel buried in a secondary tab), clear
distinction between "local" and "upstream" concepts everywhere they appear
together (e.g. on the Senders list, the upstream account should never be
visually confusable with the sender address itself).

**Keep secondary**: historical/audit detail (available, not front-and-center),
Settings/admin-account management (necessary but not a place operators live
day to day), decorative or celebratory success states (a save confirms
quietly; this is infrastructure tooling, not a consumer app).

## Design constraints

- No emoji-based status indicators.
- No gratuitous animation, gradients, giant dashboard "hero" cards, excessive
  rounded containers, illustrations, or marketing-style UI. This is an
  infrastructure administration tool and should look and feel like one —
  dense, precise, calm.
- Tables and forms need to be genuinely excellent: this product is mostly
  tables and forms, and their quality is most of the product's perceived
  quality.
- Keyboard accessible throughout (tab order, focus states, dialogs
  trap/return focus correctly, tables/lists operable without a mouse).
- Responsive down to tablet width; the primary target is desktop (this is an
  admin console an operator sits at a real screen for), but it must remain
  usable on a tablet for quick checks.
- Dark mode, if the existing design system supports it.
- Accessible color contrast and non-color-only status encoding (status must
  be legible to a colorblind user via shape/text, not color alone) —
  important given "clear status" is one of this product's core jobs.

## Visual identity

Do not invent a new visual identity for this product. **Inspect and follow
the existing corporate design identity already available in the design
environment.** This SMTP relay should feel like a natural part of that
existing product family — same component library, same spacing/typography
system, same interaction patterns — applied to the screens and workflows
described above, not a fresh brand exercise.

## Deliverable expectations

Produce implementation-ready design artifacts (real components/screens at
the fidelity needed to build from, not a mood board): the full screen list
above, including their error/empty/loading states, using the existing
design system's actual components wherever they already cover a need (form
fields, buttons, tables, dialogs, toasts) and only introducing new patterns
for something genuinely specific to this product (e.g. the permission
checklist view, the one-time password reveal, the multi-step Test Connection
result).
