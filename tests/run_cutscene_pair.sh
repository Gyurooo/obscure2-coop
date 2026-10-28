#!/bin/sh
# TASK 30 live test: both copies start a 2-player new game and the level's intro cutscene plays on both;
# check_cutscene.py then skips it on ONE copy and asserts the other copy leaves it too (the mod forwards
# the skip) and that both end in normal play in the same level with the same party. Always stops the games.
#
# Usage: sh tests/run_cutscene_pair.sh <xinput1_3.dll> [--skip-by host|guest]
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
echo "== both copies: 2-player new game, intro NOT skipped"
$PY -I start_newgame.py 120 | tail -6
echo "== screenshots of both copies during the cutscene (tests/shots/cut30, gitignored)"
$PY -I shot_pair.py "$(cat duo_host.pid)" "$(cat duo_guest.pid)" "$(pwd)/shots/cut30" | tail -10
echo "== check_cutscene.py $*"
RC=0
$PY -I check_cutscene.py "$(cat duo_host.pid)" "$(cat duo_guest.pid)" "$@" || RC=1
$PY -I duo.py stop | tail -2
exit $RC
