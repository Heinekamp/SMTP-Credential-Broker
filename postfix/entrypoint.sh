#!/bin/sh
set -e

# The control surface (security-model.md §6) is the only channel `app`
# ever uses to mutate sasldb2 or install generated config — it also now
# owns Postfix's entire process lifecycle (see control_surface.py's
# _apply_config): it starts Postfix for the first time once the first
# real config arrives, and stops+restarts it (never reloads — see that
# function's comment for why) on every later change. This script's only
# job is to keep the container alive for as long as the control surface
# is, so it simply becomes the container's PID 1.
exec python3 /control_surface.py
