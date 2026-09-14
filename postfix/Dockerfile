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
RUN echo "postfix postfix/main_mailer_type select No configuration" | debconf-set-selections \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        postfix \
        libsasl2-modules \
        sasl2-bin \
        python3 \
        openssl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Placeholder self-signed cert so smtpd_tls_cert_file/smtpd_tls_key_file
# (postfix-architecture.md §2) resolve to *something* on first boot —
# `smtpd_tls_security_level = encrypt` doesn't verify the client's view of
# this cert, so a self-signed one doesn't break anything, but it is NOT a
# substitute for a real certificate in production. Mount a real
# cert/key over these two paths (e.g. from Let's Encrypt) for anything
# beyond local testing.
RUN mkdir -p /etc/postfix/tls \
    && openssl req -x509 -newkey rsa:2048 -keyout /etc/postfix/tls/relay.key -out /etc/postfix/tls/relay.crt \
        -days 3650 -nodes -subj "/CN=smtp-relay.internal"

COPY control_surface.py /control_surface.py
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Shared volume: map source files (sender_login, sender_relayhost,
# sasl_passwd) and the control socket live here — writable by this
# container (the control surface writes them), read-only from `app`'s side
# in docker-compose.yml, since `app` only ever talks to the socket, never
# the files directly.
VOLUME ["/etc/postfix/relay"]

ENTRYPOINT ["/entrypoint.sh"]
