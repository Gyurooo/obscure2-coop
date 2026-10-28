#!/bin/sh
# TASK 20: start ONE copy (the host test copy), load save slots with the game's own menu-load path and
# read every transition destination the level's own entities carry. Always stops the copy.
# Usage: sh tests/run_scan_transitions.sh <dll> [slot[,slot...]]   (default: all ten slots)
DLLARG=$1
SLOTS=${2:-0,1,2,3,4,5,6,7,8,9}
case "$DLLARG" in
/*|[A-Za-z]:*) ;;
*) DLLARG=$(pwd)/$DLLARG ;;
esac
DLL=$(cygpath -w "$DLLARG")
export OBSCOOP_TEST_ROOT="${OBSCOOP_TEST_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}" OBSCOOP_DLL="$DLL"
PY="${PYTHON:-python}"
cd "$(dirname "$0")" || exit 2
START=$($PY -I duo.py start-host | tail -1)
echo "$START"
case "$START" in
*pid*) ;;
*) echo "the host did not start"; exit 2 ;;
esac
$PY -I -u scan_transitions.py "$(cat duo_host.pid)" "$SLOTS"
RC=$?
$PY -I duo.py stop | tail -2
exit $RC
