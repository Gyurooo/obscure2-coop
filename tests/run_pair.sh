#!/bin/sh
# One-command live test: start the host+guest copies on a DLL, put both in save 01 (I100), run checks, stop.
# Usage (from the repo/worktree root, Git Bash):  sh tests/run_pair.sh <dll> [check_script.py ...]
# Example: sh tests/run_pair.sh /c/Users/gyuro/AppData/Local/Temp/b3.dll check_party.py check_items.py
# Never leaves a game running: the stop step always runs. Prints each check's output verbatim.
DLL=$(cygpath -w "$1"); shift
export OBSCOOP_TEST_ROOT=/c/Users/gyuro/coop-anything-obscure/local OBSCOOP_DLL="$DLL"
PY=/c/Users/gyuro/AppData/Local/Python/bin/python
cd "$(dirname "$0")" || exit 2
$PY -I duo.py start | tail -1
$PY -I duo_start_game.py | tail -1 | cut -c1-100
$PY -I start_save.py "$(cat duo_host.pid)" | tail -1
sleep 15
RC=0
for c in "$@"; do
  echo "== $c"
  $PY -I "$c" "$(cat duo_host.pid)" "$(cat duo_guest.pid)" || RC=1
done
$PY -I duo.py stop | tail -2
exit $RC
