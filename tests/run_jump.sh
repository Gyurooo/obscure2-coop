#!/bin/sh
# TASK 20 step 3: ONE host copy, load a save slot with the game's own menu-load path, then make ONE
# level transition with the mod's `level` command and scan the new level. Always stops the copy.
# Usage: sh tests/run_jump.sh <dll> <slot 0..9> <TAG> <entry> <flag>
DLLARG=$1
SLOT=$2
WANT=$3
ENTRY=$4
FLAG=$5
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
PID=$(cat duo_host.pid)
$PY -I -u load_slot.py "$PID" "$SLOT"
LOADRC=$?
RC=$LOADRC
if [ "$LOADRC" -ne 0 ]; then
	echo "the slot did not load (rc $LOADRC); not jumping"
else
	$PY -I -u jump_probe.py "$PID" "$WANT" "$ENTRY" "$FLAG"
	RC=$?
fi
$PY -I duo.py stop | tail -2
exit $RC
