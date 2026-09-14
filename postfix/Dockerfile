# syntax=docker/dockerfile:1

# Stage 0 stub: proves the container starts and can see the shared config
# volume. Real generated main.cf/master.cf, sasldb2 wiring, and the
# in-container control-surface listener (security-model.md §6) land in
# Stage 4 — see docs/implementation-plan.md.
FROM debian:bookworm-slim

# Preseed debconf so `apt-get install postfix` doesn't block on the
# interactive "General type of mail configuration" prompt — "No
# configuration" leaves main.cf at its package default, which this stub
# intentionally does not touch yet.
RUN echo "postfix postfix/main_mailer_type select No configuration" | debconf-set-selections \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        postfix \
        libsasl2-modules \
        sasl2-bin \
    && rm -rf /var/lib/apt/lists/*

# Shared volume the "app" container writes generated config/maps into
# (architecture.md §6: app writes, postfix reads). Read-only from this
# container's side in docker-compose.yml.
VOLUME ["/etc/postfix/relay"]

CMD ["postfix", "start-fg"]
