# syntax=docker/dockerfile:1

# Debian + Postfix + Cyrus SASL (sasldb2 backend) + a bare python3 for the
# control surface (security-model.md §6) — no virtualenv needed, the
# script is stdlib-only.
FROM debian:bookworm-slim

# Preseed debconf so `apt-get install postfix` doesn't block on the
# interactive "General type of mail configuration" prompt. "No
# configuration" leaves main.cf/master.cf at the package's own defaults on
# first boot; the control surface's apply_config overwrites them with the
# real generated config the first time `relay generate-config` runs
# (postfix-architecture.md §7 — this is the same "app writes, postfix
# applies" pipeline, not a one-time image-build step).
# `lmdb`-backed lookup tables (postfix-architecture.md §4) need the
# separate postfix-lmdb package — Debian splits every non-default map
# backend out of the base `postfix` package. Discovered via a real
# `postmap` failure ("unsupported dictionary type: lmdb") on first boot.
RUN echo "postfix postfix/main_mailer_type select No configuration" | debconf-set-selections \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        postfix \
        postfix-lmdb \
        libsasl2-modules \
        sasl2-bin \
        python3 \
        openssl \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

# The placeholder self-signed cert that smtpd_tls_cert_file/key_file
# (postfix-architecture.md §2) resolve to until a real one is installed is
# generated per deployment, at first start, by entrypoint.sh — never here.
# A key generated at build time would ship inside the published image and
# be shared by every deployment using the placeholder (#173).
RUN mkdir -p /etc/postfix/tls

# Two real, silent SASL AUTH failures found by testing against a live
# Postfix instance, neither of which produces an error until an actual
# AUTH attempt (both surfaced as a generic "454 4.7.0 Temporary
# authentication failure"):
#   1. Cyrus SASL's smtpd service has no config telling it which auxprop
#      plugin to use, so it never actually consults sasldb2 at all.
#   2. `saslpasswd2` (sasl2-bin's default) creates /etc/sasldb2 as
#      root:sasl, mode 660 — but smtpd runs as user/group `postfix`, which
#      isn't a member of `sasl`, so it can't read the file it needs to
#      authenticate against.
#
# The config lives in /etc/postfix/sasl, which main.cf names explicitly
# (cyrus_sasl_config_path). It used to be written to /usr/lib/sasl2, a
# path this Debian build never reads, so `mech_list` was ignored and smtpd
# offered every installed mechanism (SCRAM-*, DIGEST-MD5, CRAM-MD5, NTLM)
# instead of only PLAIN and LOGIN (#230).
RUN mkdir -p /etc/postfix/sasl \
    && printf 'pwcheck_method: auxprop\nauxprop_plugin: sasldb\nmech_list: PLAIN LOGIN\n' > /etc/postfix/sasl/smtpd.conf \
    && adduser postfix sasl

# /etc/sasldb2 lived only in the container's own writable layer, with
# nothing persisting it: every deploy's `docker compose down` + `up`
# (`down` *removes* the container, not just stops it) silently wiped
# every local SMTP user's credentials, with no way to recover them — the
# app's own database only ever stores a one-way hash for its own
# bookkeeping (security-model.md §4), never the credential itself. Found
# in production (issue #118) after two deploys quietly broke every local
# user's login.
#
# Two tempting fixes were tried and confirmed NOT to work against a real
# build, in case a future maintainer is tempted to retry either:
#   - A named volume can't target /etc/sasldb2 directly: Docker volumes
#     mount *directories*, not individual files — mounting one onto a
#     single file path fails outright at container start ("not a
#     directory... mount a directory onto a file?").
#   - Redirecting Cyrus SASL's own `sasldb_path` config option to a
#     different, volume-backed directory doesn't work either: the
#     `sasldb` auxprop plugin's *live* AUTH lookup silently ignores
#     `sasldb_path` in /usr/lib/sasl2/smtpd.conf and always reads the
#     compiled-in default path, even though saslpasswd2/sasldblistusers2's
#     own `-f` flag *does* happily redirect — so writes would land in the
#     new location while the live AUTH check kept reading the old (now
#     permanently empty) one. A symlink at /etc/sasldb2 pointing into a
#     volume-backed directory doesn't work either, for a different
#     reason: saslpasswd2 creates its db file via an atomic rename, which
#     replaces whatever sits at /etc/sasldb2 — including a symlink — with
#     a brand new regular file, destroying the symlink on the very first
#     write.
#
# So instead of redirecting Postfix at all, /etc/sasldb2 stays exactly
# where the sasldb plugin expects it, and SASLDB_DIR (below,
# docker-compose.yml) holds a synced copy instead: entrypoint.sh copies
# it IN at container start (if one exists from a previous session),
# control_surface.py copies the live file back OUT after every
# create/delete. Postfix never needs to know any of this is happening.
ENV SASLDB_DIR=/var/lib/postfix-sasldb
RUN mkdir -p "$SASLDB_DIR" && chgrp sasl "$SASLDB_DIR" && chmod 770 "$SASLDB_DIR"

COPY control_surface.py /control_surface.py
COPY entrypoint.sh /entrypoint.sh
COPY postfix-running /usr/local/bin/postfix-running
RUN chmod +x /entrypoint.sh /usr/local/bin/postfix-running

# Generated lookup maps (sender_login, sender_relayhost, sasl_passwd, ...)
# live here. Private to this container: the control socket that `app`
# talks to is on its own volume (/run/relay-control, docker-compose.yml),
# so `app` can't read sasl_passwd's plaintext upstream passwords (#159).
VOLUME ["/etc/postfix/relay"]

# tini as PID 1 (#197): it reaps the Postfix daemons that every
# `postfix stop`/`start` cycle re-parents to PID 1, and forwards
# `docker stop`'s SIGTERM to the control surface, which then stops Postfix
# cleanly. With the control surface itself as PID 1, unhandled signals were
# ignored by the kernel — every stop waited 10s and ended in SIGKILL.
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
