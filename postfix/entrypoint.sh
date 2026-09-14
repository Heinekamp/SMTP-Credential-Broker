#!/bin/sh
set -e

# The control surface (security-model.md §6) is the only way `app` ever
# mutates sasldb2 or installs generated config — started in the
# background, alongside Postfix itself as the container's foreground
# process.
python3 /control_surface.py &

exec postfix start-fg
