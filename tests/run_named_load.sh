#!/bin/sh
# CASE 2 (TASK 14): the file the host's load names must reach the guest before the guest loads.
# Stand-in on the test copies: o2.sav (what the main menu's own Load Game is hard-wired to) is put on the
# HOST only; the guest has neither copy. Both copies start at the main menu and connect, the join transfer
# finishes, the guest's own copy of the slot the host will load is deleted, and then the host loads a save
# through the game's own menu (see tests/case2.py for the exact steps and which route worked). The guest
# must receive that file through the transfer and build its world from it.
#
# Usage: sh tests/run_named_load.sh <dll> [check_script.py ...]
#   OBSCOOP_CASE2_SAVE=<file>  the slot the host loads (default game1.sav, level I015)
DLLARG=$1
shift
case "$DLLARG" in
/*|[A-Za-z]:*) ;;
*) DLLARG=$(pwd)/$DLLARG ;;
esac
DLL=$(cygpath -w "$DLLARG")
export OBSCOOP_TEST_ROOT="${OBSCOOP_TEST_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}" OBSCOOP_DLL="$DLL"
PY="${PYTHON:-python}"
cd "$(dirname "$0")" || exit 2
$PY -I o2_file.py prepare
START=$($PY -I duo.py start | tail -1)
echo "$START"
case "$START" in
*running*) ;;
*) echo "the pair did not start; not running the checks"; $PY -I duo.py stop | tail -1; exit 2 ;;
esac
echo "== CASE 2: the host loads the file the guest has just lost; the guest must receive it and follow"
$PY -I case2.py "${OBSCOOP_CASE2_SAVE:-game1.sav}" 120
RC=$?
sleep 10
for c in "$@"; do
	echo "== $c"
	$PY -I "$c" "$(cat duo_host.pid)" "$(cat duo_guest.pid)" || RC=1
done
echo "== o2_file.py check (what the two copies have now)"
$PY -I o2_file.py check
echo "== shot_pair.py"
$PY -I shot_pair.py "$(cat duo_host.pid)" "$(cat duo_guest.pid)"
$PY -I duo.py stop | tail -2
exit $RC
