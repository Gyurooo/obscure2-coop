#!/bin/sh
# Bot checks on the two loopback copies; run after the pair is in the saved level.
set -e
HOST=$(cat duo_host.pid)
GUEST=$(cat duo_guest.pid)
python -I check_save.py "$HOST" "$GUEST"
python -I check_items.py "$HOST" "$GUEST"
python -I check_health.py "$HOST" "$GUEST"
python -I check_death.py "$HOST" "$GUEST"
