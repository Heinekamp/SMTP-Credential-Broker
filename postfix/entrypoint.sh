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

# The control surface (security-model.md §6) is the only channel `app`
# ever uses to mutate sasldb2 or install generated config — it also now
# owns Postfix's entire process lifecycle (see control_surface.py's
# _apply_config): it starts Postfix for the first time once the first
# real config arrives, and stops+restarts it (never reloads — see that
# function's comment for why) on every later change. This script's only
# job is to keep the container alive for as long as the control surface
# is, so it simply becomes the container's PID 1.
exec python3 /control_surface.py
