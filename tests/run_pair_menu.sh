#!/bin/sh
# New real flow (TASK 12): both copies start and stay at the main menu; the GUEST is not touched at all.
# The HOST loads save 01 through the game's own menu-load path (`loadsave game0.sav`: the save manager's
# open + LoadByName, exactly what the pause menu does), then the guest must bring itself into the same
# level from the transferred save file. Prints each check's output verbatim and always stops the games.
#
# Usage: sh tests/run_pair_menu.sh <dll> [check_script.py ...]
#        sh tests/run_pair_menu.sh --host-newgame <dll> [check_script.py ...]
#          baseline: the old flow's host action (new 2P game, then pause -> Load save 01) with the guest
#          left at the main menu; used to show what the guest does today.
#
# check_movement.py is special-cased: the runner runs its phase E (movement right after the load) as soon
# as the load script returns, then the usual A-D phases with the other checks. Any other check runs only
# after the 20 s settle.
DLLARG=$1
if [ "$DLLARG" = "--host-newgame" ]; then
	MODE=host-newgame
	shift
	DLLARG=$1
fi
# duo.py needs an absolute path: it copies the DLL into the test folder from its own working directory.
case "$DLLARG" in
/*|[A-Za-z]:*) ;;
*) DLLARG=$(pwd)/$DLLARG ;;
esac
DLL=$(cygpath -w "$DLLARG"); shift
export OBSCOOP_TEST_ROOT="${OBSCOOP_TEST_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}" OBSCOOP_DLL="$DLL"
PY="${PYTHON:-python}"
cd "$(dirname "$0")" || exit 2
START=$($PY -I duo.py start | tail -1)
echo "$START"
case "$START" in
*running*) ;;
*) echo "the pair did not start; not running the checks"; $PY -I duo.py stop | tail -1; exit 2 ;;
esac
if [ "${MODE:-}" = host-newgame ]; then
	echo "== host: new 2P game, then pause menu -> Load save 01 (guest stays at the main menu)"
	$PY -I start_save.py "$(cat duo_host.pid)" | tail -3
else
	echo "== both at the main menu; the host loads save 01 with the game's own LoadByName"
	$PY -I start_menu_load.py | tail -40
fi
RC=0
EARLY=""
for c in "$@"; do
	[ "$c" = check_movement.py ] && EARLY=1
done
if [ -n "$EARLY" ]; then
	echo "== check_movement.py --early (phase E: movement right after the load)"
	$PY -I check_movement.py "$(cat duo_host.pid)" "$(cat duo_guest.pid)" --early || RC=1
fi
sleep 20
for c in "$@"; do
	echo "== $c"
	if [ "$c" = check_movement.py ]; then
		$PY -I "$c" "$(cat duo_host.pid)" "$(cat duo_guest.pid)" --phases A,B,C,D || RC=1
	else
		$PY -I "$c" "$(cat duo_host.pid)" "$(cat duo_guest.pid)" || RC=1
	fi
done
$PY -I duo.py stop | tail -2
exit $RC
