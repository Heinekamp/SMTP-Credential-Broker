#!/bin/sh
set -e

# main.cf's maillog_file now points at a real file (docs/postfix-architecture.md
# §2) instead of /dev/stdout directly, so the control surface can tail it
# for mail_log ingestion (§9). Mirror it to this container's own stdout in
# the background purely so `docker compose logs postfix` keeps working as
# a live operator view — nothing else depends on this process.
mkdir -p /var/log/postfix
touch /var/log/postfix/maillog
tail -F /var/log/postfix/maillog &

# Restore local SMTP user credentials from the volume-backed copy
# (docker-compose.yml's `sasldb` volume, SASLDB_DIR) into /etc/sasldb2 —
# the path Cyrus SASL's sasldb auxprop plugin actually reads at AUTH
# time, hardcoded and not redirectable at runtime (see postfix/Dockerfile's
# comment for the two approaches that don't work and why). No-op on a
# genuinely fresh deployment, where SASLDB_DIR doesn't have a synced copy
# yet — /etc/sasldb2 stays the empty placeholder sasl2-bin's own postinst
# already created. control_surface.py copies the live file back out to
# SASLDB_DIR after every create/delete (issue #118).
if [ -f "$SASLDB_DIR/sasldb2" ]; then
    cp "$SASLDB_DIR/sasldb2" /etc/sasldb2
    chown root:sasl /etc/sasldb2
    chmod 660 /etc/sasldb2
fi

# The control surface (security-model.md §6) is the only channel `app`
# ever uses to mutate sasldb2 or install generated config — it also now
# owns Postfix's entire process lifecycle (see control_surface.py's
# _apply_config): it starts Postfix for the first time once the first
# real config arrives, and stops+restarts it (never reloads — see that
# function's comment for why) on every later change. This script's only
# job is to keep the container alive for as long as the control surface
# is, so it simply becomes the container's PID 1.
exec python3 /control_surface.py
