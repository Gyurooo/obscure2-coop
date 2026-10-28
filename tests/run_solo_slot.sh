#!/bin/sh
# TASK 17: ONE host copy, load a save slot with the game's own menu-load path, wait until the level has
# placed the characters, then run the given checks against that single copy. Always stops the copy.
#
# Usage: sh tests/run_solo_slot.sh <dll> <slot 0..9> <check_script.py|-pass-> [more checks...]
#   e.g. sh tests/run_solo_slot.sh chk17.dll 6 check_tp.py
#        sh tests/run_solo_slot.sh chk17.dll 9 play_forward.py
DLLARG=$1
SLOT=$2
shift 2
if [ $# -eq 0 ]; then
	echo "usage: sh tests/run_solo_slot.sh <dll> <slot 0..9> <check_script.py|-pass-> [...]"
	exit 2
fi
case "$DLLARG" in
/*|[A-Za-z]:*) ;;
*) DLLARG=$(pwd)/$DLLARG ;;
esac
DLL=$(cygpath -w "$DLLARG")
export OBSCOOP_TEST_ROOT="${OBSCOOP_TEST_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}" OBSCOOP_DLL="$DLL"
export SAVE_SLOT="$SLOT"
PY="${PYTHON:-python}"
cd "$(dirname "$0")" || exit 2
START=$($PY -I duo.py start-host | tail -1)
echo "$START"
case "$START" in
*pid*) ;;
*) echo "the host did not start"; exit 2 ;;
esac
$PY -I -u load_slot.py "$(cat duo_host.pid)" "$SLOT"
LOADRC=$?
RC=$LOADRC
if [ "$LOADRC" -ne 0 ]; then
	echo "the slot did not load (rc $LOADRC); not running the checks"
else
	for c in "$@"; do
		[ "$c" = "-pass-" ] && continue
		echo "== $c"
		$PY -I -u "$c" "$(cat duo_host.pid)" || RC=1
	done
fi
$PY -I duo.py stop | tail -2
exit $RC
