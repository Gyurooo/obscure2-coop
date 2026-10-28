#!/bin/sh
# TASK 20: ONE host copy, load a save slot, survey the given door destinations (survey_levels.py).
# Always stops the copy.
# Usage: sh tests/run_survey.sh <dll> <slot 0..9> [tag:entry ...]
DLLARG=$1
SLOT=$2
shift 2
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
	echo "the slot did not load (rc $LOADRC); not surveying"
else
	$PY -I -u survey_levels.py "$PID" "$@"
	RC=$?
fi
$PY -I duo.py stop | tail -2
exit $RC
