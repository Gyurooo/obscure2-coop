#!/bin/sh
# CASE 3 (TASK 14): a second load in one session. Both copies get into a level the normal way (host loads
# save 01 from the main menu, guest follows), then the HOST loads a save again from the pause menu and the
# guest must follow into the rebuilt world with matching party/inventory/hands/entities.
#
# Usage: sh tests/run_second_load.sh <dll> [check_script.py ...]
#   OBSCOOP_SECOND_SAVE=<file>  what the pause menu load should name (the host reloads slot 01 by default)
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
START=$($PY -I duo.py start | tail -1)
echo "$START"
case "$START" in
*running*) ;;
*) echo "the pair did not start; not running the checks"; $PY -I duo.py stop | tail -1; exit 2 ;;
esac
echo "== first load, the usual way: the host loads save 01 from the main menu, the guest follows"
$PY -I start_menu_load.py | tail -25
sleep 20
echo "== CASE 3: a second load in the same session"
$PY -I case3.py "${OBSCOOP_SECOND_SAVE:-game0.sav}" || RC=1
sleep 10
RC=${RC:-0}
for c in "$@"; do
	echo "== $c"
	$PY -I "$c" "$(cat duo_host.pid)" "$(cat duo_guest.pid)" || RC=1
done
$PY -I duo.py stop | tail -2
exit $RC
