#!/bin/sh
# CASE 1 (TASK 14, host first): the HOST copy starts and loads its save on its own, its world is up and
# settled, and only THEN the guest copy starts at the main menu and connects. The guest must receive the
# save file through the transfer and build the same world from it (party, inventory, hands, entities,
# level), and movement must work afterwards.
#
# Usage: sh tests/run_late_join.sh <dll> [check_script.py ...]
#   OBSCOOP_LATE_SAVE=<file>   the save the host loads (default game0.sav = slot 01, level I100)
#   OBSCOOP_LATE_SETTLE=<s>    how long the host is left in game alone before the guest starts (default 10)
# Prints each check's output verbatim and always stops the games it started.
DLLARG=$1
shift
# duo.py needs an absolute path: it copies the DLL into the test folder from its own working directory.
case "$DLLARG" in
/*|[A-Za-z]:*) ;;
*) DLLARG=$(pwd)/$DLLARG ;;
esac
DLL=$(cygpath -w "$DLLARG")
export OBSCOOP_TEST_ROOT="${OBSCOOP_TEST_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}" OBSCOOP_DLL="$DLL"
PY="${PYTHON:-python}"
SAVE="${OBSCOOP_LATE_SAVE:-game0.sav}"
SETTLE="${OBSCOOP_LATE_SETTLE:-10}"
cd "$(dirname "$0")" || exit 2
START=$($PY -I duo.py start-host | tail -1)
echo "$START"
case "$START" in
*pid*) ;;
*) echo "the host did not start; not running the checks"; $PY -I duo.py stop | tail -1; exit 2 ;;
esac
echo "== CASE 1: the host alone loads $SAVE and settles, then the guest starts and must follow"
$PY -I start_late_join.py "$SAVE" "$SETTLE" 120
sleep 5
RC=0
for c in "$@"; do
	echo "== $c"
	$PY -I "$c" "$(cat duo_host.pid)" "$(cat duo_guest.pid)" || RC=1
done
echo "== shot_pair.py (both windows, after the checks)"
$PY -I shot_pair.py "$(cat duo_host.pid)" "$(cat duo_guest.pid)"
$PY -I duo.py stop | tail -2
exit $RC
