# Getting Started

A full, step-by-step walkthrough for setting up SMTP Credential Broker
from nothing — no prior Docker, Linux sysadmin, or DNS experience
assumed. If you already know your way around Docker, the shorter
[installation.md](installation.md) covers the same ground faster.

## What you'll need

- **A server, VM, or NAS to run this on**, reachable from the internal
  network your other services (printers, apps, monitoring tools, etc.)
  live on. Anything from a Raspberry Pi upwards is enough — this stack
  is lightweight. This guide assumes Linux; Docker also runs on Windows
  and macOS if that's what you have.
- **Admin (root) access** to that machine, and comfort opening a
  terminal on it (directly, or over SSH).
- **At least one existing SMTP mailbox** from a provider you already
  have — a STRATO mailbox, a Gmail account with an
  [app password](https://support.google.com/accounts/answer/185833), or
  similar. This relay doesn't send mail on its own; it manages access to
  a real mailbox you already have.
- **A domain name, if you want a real (not self-signed) TLS
  certificate** — read [the next section](#do-you-need-a-real-tls-certificate)
  before deciding whether to skip this. Any domain works, from any
  registrar. Cloudflare-managed DNS makes issuance fully automated in
  [step 8](#8-setting-up-real-tls-with-lets-encrypt); any other DNS host
  still works too, just with one manual step instead.

## Do you need a real TLS certificate?

Decide this now — it affects a setting you'll choose early on, and
changing it later means redoing part of the config.

This relay ships with a self-signed placeholder certificate by default.
It works fine for quick testing with a lenient SMTP client, but **many
real applications refuse to connect to it at all** — mail plugins like
WP Mail SMTP, printers/scanners with "scan to email," and most anything
that validates certificates strictly will reject the connection outright
during STARTTLS, before your credentials are even checked. If that
describes the service you're planning to connect, a real certificate
isn't really optional for you — plan on doing step 8 below.

If you just want to try this out first, or you know the specific service
you're connecting tolerates a self-signed certificate, it's safe to skip
TLS for now and add it later.

**No domain name available at all, and a service that needs a real
certificate?** Step 8 has no path around that requirement — Let's
Encrypt only issues certificates for domain names, never for a bare IP
address. If that's your situation, it's worth stopping here rather than
finishing the rest of this install first: register a domain (even a
cheap one used for nothing else) before continuing, or reconsider
whether this project fits your setup.

## 1. What this project actually does

In one sentence: internal services (a printer's "scan to email"
feature, a monitoring stack, a self-hosted app) get their own private
login to send mail, instead of every one of them being handed your real
mailbox password. You'll set up one relay, connect it to your real
mailbox once, then create a separate, revocable credential for each
service that needs to send mail.

## 2. Installing Docker

Everything in this project runs inside Docker containers — you don't
need to install Python, Postfix, or anything else directly on your
server. Follow Docker's own official installation instructions for your
operating system:

- [Install Docker Engine (Linux)](https://docs.docker.com/engine/install/)
- [Docker Desktop (Windows/macOS)](https://docs.docker.com/desktop/)

Docker's instructions change over time, so this guide intentionally
doesn't duplicate them — follow the official page for your OS, then come
back here.

Once installed, verify you have the right version of Docker Compose:

```bash
docker compose version
```

This must print a version starting with `v2` (e.g. `Docker Compose
version v2.24.0`). This project uses the modern `docker compose`
subcommand (with a **space**), which comes bundled with current Docker
installs — not the old standalone `docker-compose` program (with a
**hyphen**), which is a different, older tool. If `docker compose`
(space) says "command not found" but `docker-compose` (hyphen) works,
your Docker install is outdated; reinstall Docker following the link
above rather than trying to use the hyphenated tool.

## 3. Getting the code

If you have `git` installed, this is the easiest path:

```bash
git clone https://github.com/Heinekamp/smtp-credential-broker.git
cd smtp-credential-broker
```

(`git` is a tool for downloading and tracking a project's source code —
`clone` just means "download a copy.")

**No `git`?** Download a ZIP instead: go to the project's
[Releases page](https://github.com/Heinekamp/smtp-credential-broker/releases),
pick the newest release (not "main" — see below), and download its
"Source code (zip)" link. Extract it on your server and `cd` into the
extracted folder.

Either way, **use the newest tagged release**, not the `main` branch.
Releases are tested checkpoints; `main` can be mid-change at any given
moment. If you used `git clone` above, switch to the latest release tag
with:

```bash
git checkout v0.3.2   # replace with whatever the current release tag is
```

## 4. Configuring your `.env` file

The project ships a template file listing every setting with an
explanation next to it. Copy it to a real config file — `.env` is the
one you'll actually edit, and it's deliberately excluded from git so
your secrets never get committed anywhere:

```bash
cp .env.example .env
```

First, generate an encryption key. It protects every mailbox password
you'll store in this app — nothing is stored in plain text:

```bash
docker compose run --rm app relay generate-encryption-key
```

This prints a random value. Copy it somewhere you can paste it from in a
moment.

> [!IMPORTANT]
> **Save this key somewhere else too** — a password manager, or written
> down and locked away. If it's ever lost, every stored mailbox password
> becomes permanently unreadable, with no way to recover it. This is the
> single most important thing to get right in this whole setup.

Now open `.env` in a text editor (`nano .env` is the easiest if you're
on the server directly over SSH) and make these two changes:

**Paste the encryption key** you just generated as
`RELAY_ENCRYPTION_KEY=<the value>`.

**Set `RELAY_SUBMISSION_HOST`**, replacing the placeholder value the
template ships with (`smtp-relay.internal`, which doesn't resolve to
anything). This is the name/address the relay calls itself internally,
and — importantly — it's also literally what the app's Connection
Details screen later tells your other services to connect *to* as
"Host" (step 7), so whatever you put here has to actually be reachable
from those services. Two options:

- **Simplest, no DNS needed**: set this to your relay server's own LAN
  IP address (e.g. `RELAY_SUBMISSION_HOST=192.168.1.50`). Every device
  on your network can already reach an IP address directly, no extra
  setup required. Good choice if you're skipping real TLS for now.
- **If you decided above that you need real TLS**: set this to the
  actual domain name you're planning to use for the certificate in
  step 8 (e.g. `RELAY_SUBMISSION_HOST=relay.example.com`). You'll still
  need to make that domain resolve to this server on your local
  network — step 8a walks through adding that DNS record, so it's fine
  to set this now and finish the DNS side when you get there. Deciding
  this now avoids changing it after the fact: changing
  `RELAY_SUBMISSION_HOST` later requires regenerating config and
  re-creating existing local users' credentials, since they're tied to
  this value at creation time.

Everything else in `.env` can stay at its default for a first install.
If port 8000 is already used by something else on your server, uncomment
and change the `APP_HOST_PORT` line — otherwise skip it.

## 5. Starting the stack

```bash
docker compose up -d --build
```

This builds and starts the two containers this project needs (the web
app and Postfix, the actual mail-sending engine). It'll take a minute or
two the first time. Check on it with:

```bash
docker compose ps
```

You're looking for both `app` and `postfix` to eventually show
`healthy`. If you'd rather wait for it than repeatedly check, use:

```bash
docker compose up --wait
```

which blocks until both are healthy (or reports a failure).

**Seeing a line like "attempt 1 failed, retrying" in the logs
(`docker compose logs app`) right after starting?** That's expected on
first boot, not an error — the app briefly retries connecting to Postfix
while both containers are still starting up. It resolves itself within a
few seconds.

## 6. First-run setup in the browser

Open `http://<your-server's-address>:8000/` in a browser (e.g.
`http://192.168.1.50:8000/` — use whatever address your server has on
your network). A brand-new install has no admin account yet, so you'll
land straight on **Create the first admin account**. Fill in an email
and a strong password. (This screen only ever appears once — after the
first admin exists, this same address takes you to the ordinary login
page instead.)

After logging in, you'll see a guided setup walking through the three
things every relay needs. Here's a concrete worked example — replace the
values with your own real mailbox details:

1. **Add an upstream account** — this is your real, existing mailbox.
   Give it a name (e.g. "STRATO main mailbox"), and enter the real
   SMTP host/port/username/password your provider gave you. This
   password is encrypted with the key you generated in step 4 and is
   never shown again in plain text once saved.
2. **Add a sender** — an email address allowed to send mail, tied to
   the upstream account you just added (e.g. `printer@example.com`,
   if that's an address your mailbox provider lets you send as).
3. **Create a local SMTP user** — this is the credential you'll hand to
   one internal service. Give it a descriptive name (e.g. "Office
   printer"), and grant it permission to use the sender address from
   step 2.

> [!IMPORTANT]
> The local SMTP user's password is shown to you **exactly once**,
> immediately after creation. Copy it into a text file right now — you're
> about to paste it into your printer/app/service's own SMTP settings in
> the next step. If you lose it, there's no way to view it again; you'd
> need to generate a new one.

## 7. Connecting your first internal service

Whatever service you're connecting (a printer's scan-to-email feature, a
self-hosted app, a monitoring tool) needs these SMTP settings, all shown
together in the Local SMTP Users screen's **Connection Details** view:

- **Host**: whatever you set `RELAY_SUBMISSION_HOST` to in step 4 — an
  IP address, or a domain name if you already set that up for TLS.
- **Port**: `587`.
- **Encryption**: STARTTLS (sometimes just labeled "TLS" — not
  "SSL/implicit TLS", which is a different thing and uses a different
  port).
- **Username / password**: the local SMTP user you just created, and
  the password you saved in step 6.

**If the service refuses to connect or complains about a certificate
error**, that's the self-signed placeholder certificate being rejected —
see [the note near the top](#do-you-need-a-real-tls-certificate) about
why this happens and whether you need step 8 to fix it. If a service
you're connecting doesn't validate certificates strictly, it may work
fine as-is.

## 8. Setting up real TLS with Let's Encrypt (optional)

This step replaces the default self-signed certificate with a real one
trusted by everything, issued via a DNS challenge (no inbound port 80/443
needed) and, on one of the two paths below, renewed automatically from
then on. It needs a domain name — any domain, from any registrar. Skip
this whole section if you decided above that you don't need it yet;
everything else in this guide works without it.

### 8a. Point your domain at the relay — on your own network only

Pick a domain (or a subdomain of one) you control, e.g.
`relay.example.com` — the same one you set `RELAY_SUBMISSION_HOST` to in
step 4, if you already made that decision there. You need to make this
domain resolve to your relay's address, but **only for devices on your
own network** — you do not want or need this relay reachable from the
public internet.

Do this in your router's or internal DNS server's own settings (the
exact menu name varies — look for "Local DNS", "DNS override", or
similar), adding an entry like:

```
relay.example.com  →  192.168.x.x   (your relay server's LAN address)
```

This matters because a client validates a certificate against the
hostname it *connects to* — not the relay's IP address. If a client
connects using the bare IP instead of this domain, it'll get a
certificate-hostname mismatch even once the real certificate is issued.
Point every service at the domain, not the IP, once this step is done.

**You do not need a public DNS record pointing this domain at your
relay.** The DNS record created in one of the two paths below exists
purely to prove domain ownership to Let's Encrypt — it's not what makes
the relay reachable.

### 8b. Choose how to prove domain ownership

The relay needs to prove to Let's Encrypt that you control the domain,
by creating a temporary DNS TXT record. Two ways to do that:

- **Path A: Cloudflare (automated)**: if your domain's DNS is managed
  through Cloudflare (a free account is enough), the relay can create
  and remove that TXT record for you automatically, and — the real
  advantage — renew the certificate on its own forever after. Use
  [8c](#8c-path-a-cloudflare-automated).
- **Path B: manual (any DNS host)**: works regardless of who your
  domain's DNS is hosted with. You'll copy one TXT record into your
  DNS host's own dashboard by hand each time. No account credentials
  needed, but it doesn't renew itself — you'll repeat this manually
  shortly before the certificate expires. Use
  [8d](#8d-path-b-manual-any-dns-host).

If you're not sure and already have a Cloudflare account, Path A is
less ongoing effort. Either way, skip to [8e](#8e-issue-the-certificate)
once you've finished your chosen path.

### 8c. Path A: Cloudflare (automated)

Create an API token that lets the relay create a short-lived DNS record
to prove it controls the domain — nothing else. In the Cloudflare
dashboard:

1. Log in, then click your profile icon (top right) → **My Profile**.
2. Go to the **API Tokens** tab.
3. Click **Create Token**.
4. Choose **Create Custom Token** (don't use one of the built-in
   templates).
5. Under **Permissions**, set: `Zone` / `DNS` / `Edit`.
6. Under **Zone Resources**, choose **Specific zone** and select the
   exact domain you're using (not "All zones") — this limits what the
   token can touch if it's ever leaked, to just this one domain.
7. Click **Continue to summary**, then **Create Token**.
8. Cloudflare shows the token value **exactly once**. Copy it now —
   just like the local SMTP user password in step 6, there's no way to
   view it again afterward, only to create a new one.

Keep this token; you'll paste it into the relay's UI in step 8e. (The
form there also has an optional "Cloudflare Zone ID" field — leave it
blank, it's auto-detected from the domain.)

### 8d. Path B: manual (any DNS host)

No account or credentials needed for this path — you'll add one DNS
record by hand, wherever your domain's DNS is actually managed (your
registrar's own dashboard, or wherever else it's hosted). You'll do this
from inside the relay's UI in step 8e below (it shows you the exact
record to add, generated at that point), so there's nothing to prepare
here beyond knowing how to log in to add a DNS record when the time
comes.

Keep in mind this path needs you to repeat the same manual step again
shortly before the certificate expires — it does not renew itself the
way Path A does.

### 8e. Issue the certificate

Back in the relay's web UI:

1. Go to **Settings → TLS Certificate**.
2. Turn on the **Enable Let's Encrypt** switch, then fill in the
   **Domain** field (from step 8a) and, for Path A, the
   **Cloudflare API Token** (from step 8c); for Path B, set
   **DNS Provider** to **Manual**.
3. Click **Save**. This matters: the buttons in the next step stay
   disabled until "Enable Let's Encrypt" is on and a domain is filled
   in, and both act on whatever was last saved — not on unsaved changes
   still sitting in the form.
4. **Path A**: click **Verify Cloudflare Access** first — a safe,
   read-only check that doesn't create any DNS record or use up a Let's
   Encrypt attempt, so it's worth confirming before the real thing. Once
   that succeeds, click **Issue / Renew Now**.
   **Path B**: click **Start DNS-01 Challenge**. It shows an
   `_acme-challenge` TXT record — add exactly that record at your DNS
   host, then come back and click **Verify & Continue**. Safe to retry
   if DNS hasn't propagated yet.
5. Either path makes a real, rate-limited request to Let's Encrypt once
   you confirm — avoid repeating it unnecessarily.
6. Once issued, reconnect the service from step 7 (or test with any SMTP
   client) using the domain name, not the IP address, and confirm the
   certificate error is gone.

**Path A** renews automatically in the background from here on —
nothing further to do unless Settings → TLS Certificate ever shows a
renewal failure. **Path B** does not auto-renew — repeat this step
again once the certificate is close to expiry (Settings → TLS
Certificate shows the expiry date).

## 9. Where to go from here

This guide covers a working first install. A few things worth doing
before you rely on this for anything important:

- **[Back up your data](backup-restore.md)** — especially the
  encryption key from step 4. Do this before you have real mail flowing
  through, not after something goes wrong.
- **[Full configuration reference](configuration.md)** — every setting
  this guide didn't cover (rate limits, session timeouts, alert email,
  and more).
- **[Upgrading](upgrading.md)** — how to move to a new release later.
- **[Troubleshooting](troubleshooting.md)** — common issues and fixes,
  if something isn't behaving as expected.
