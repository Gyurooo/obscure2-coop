#!/bin/sh
# TASK 34 crash soak + the three new checks, over the lossy relay (~90 ms round trip like the owner's
# Steam link). What it does, in order:
#   1. two relays (lag 45 ms + jitter 10 ms + 1 % loss per direction, ~90 ms RTT) and the pair on loopback;
#   2. the host loads save 01 (I100) with the game's own menu path, the guest follows;
#   3. check_attack_anim.py  - the aim stance + attack animation on both copies, both players;
#   4. check_controls.py     - each pad drives its own character on both copies;
#   5. soak34.py            - 30 location changes back and forth + movement + attacks + door uses;
#   6. check_doors.py --reset game3.sav - the door image and the transition in both directions;
#   7. liveness and the logs: no crash report; then the guest is asked to fault (pipe `crash`) and the
#      report must be complete (code, eip as module+offset, registers, stack, log tail).
#
# Usage: sh tests/run_soak.sh <dll>
# Env: OBSCOOP_TEST_ROOT (folder holding obscure2-test and obscure2-test2), PYTHON, OBSCOOP_RELAY,
#      OBSCOOP_HOST_DIR / OBSCOOP_GUEST_DIR (as in duo.py), OBSCOOP_SOAK_ITERS (default 30).
# Starts only its own relays and games, kills only those, and every wait has a timeout.
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=${OBSCOOP_TEST_ROOT:-$(cd "$HERE/../.." && pwd)}
PY=${PYTHON:-python}
RELAY=${OBSCOOP_RELAY:-$ROOT/obscure2-coop-repo/build/obscoop-relay.exe}
export OBSCOOP_TEST_ROOT="$ROOT"
export OBSCOOP_HOST_DIR="${OBSCOOP_HOST_DIR:-$ROOT/obscure2-test}"
export OBSCOOP_GUEST_DIR="${OBSCOOP_GUEST_DIR:-$ROOT/obscure2-test2}"
ITERS=${OBSCOOP_SOAK_ITERS:-30}

if [ $# -lt 1 ]; then
	echo "usage: sh tests/run_soak.sh <dll>" >&2
	exit 2
fi
DLL=$(cygpath -w "$1") || exit 2
export OBSCOOP_DLL="$DLL"
RUNDIR=${TMPDIR:-/tmp}/obscoop-soak-$$
mkdir -p "$RUNDIR" || exit 2
RUNDIR_WIN=$(cygpath -w "$RUNDIR")
STARTED=0
RC=0

proc_image() {
	tasklist //FI "PID eq $1" //FO CSV //NH 2>/dev/null | sed -n '1s/^"\([^"]*\)".*/\1/p'
}
count_image() {
	n=$(tasklist //FI "IMAGENAME eq $1" //FO CSV //NH 2>/dev/null | grep -c '^"')
	echo $((n + 0))
}
kill_own() {
	[ -f "$1" ] || return 0
	pid=$(cat "$1" 2>/dev/null)
	case "$pid" in ''|*[!0-9]*) return 0 ;; esac
	if [ "$(proc_image "$pid")" = "$2" ]; then
		taskkill //PID "$pid" //F >/dev/null 2>&1
		echo "stopped $2 pid $pid"
	fi
}
cleanup() {
	trap - EXIT INT TERM
	if [ "$STARTED" = 1 ]; then
		echo "== stopping the two games"
		timeout 30 "$PY" -I "$HERE/duo.py" stop 2>&1 | tail -3
		STARTED=0
	fi
	kill_own "$RUNDIR/host/relay.pid" obscoop-relay.exe
	kill_own "$RUNDIR/guest/relay.pid" obscoop-relay.exe
	echo "remaining Obscure2.exe: $(count_image Obscure2.exe), obscoop-relay.exe: $(count_image obscoop-relay.exe)"
}
start_relay() {
	mkdir -p "$RUNDIR/$1"
	"$PY" -I - "$RELAY" "$RUNDIR_WIN/$1" "$1" "$LAG" "$JIT" "$LOSS" "$PROFILE" <<'PY' > "$RUNDIR/$1/start.txt" 2>&1
import os, subprocess, sys
exe, cwd, role, lag, jit, loss, profile = sys.argv[1:8]
args = [exe, role, '27961' if role == 'host' else '27962',
        '--udp-link', 'listen:28000' if role == 'host' else '28000',
        '--lag', lag, '--jitter', jit, '--loss', loss]
if profile:
    args += ['--profile', profile]
out = open(os.path.join(cwd, 'relay.out'), 'wb')
p = subprocess.Popen(args, cwd=cwd, stdout=out, stderr=subprocess.STDOUT,
                     creationflags=0x00000008 | 0x00000200)
open(os.path.join(cwd, 'relay.pid'), 'w').write(str(p.pid))
print('relay %s pid %d: %s' % (role, p.pid, ' '.join(args)))
PY
	cat "$RUNDIR/$1/start.txt"
}
wait_relay() {
	i=0
	while [ $i -lt 40 ]; do
		if grep -q "udp link:" "$RUNDIR/$1/relay.out" 2>/dev/null; then
			sed -n '1p' "$RUNDIR/$1/relay.out"
			return 0
		fi
		i=$((i + 1))
		sleep 0.25
	done
	echo "relay $1 did not come up:" >&2
	cat "$RUNDIR/$1/relay.out" 2>/dev/null >&2
	return 1
}

PROFILE=${OBSCOOP_LINK:-}
case "$PROFILE" in
''|steam) ;;
*) echo "unknown OBSCOOP_LINK '$PROFILE' (only: steam)" >&2; exit 2 ;;
esac
LAG=45 JIT=10 LOSS=1
[ "$PROFILE" = steam ] && LAG=0 JIT=0   # the profile brings its own delay, jitter, bursts and blackouts
OB=$(count_image Obscure2.exe)
RL=$(count_image obscoop-relay.exe)
if [ "$OB" != 0 ] || [ "$RL" != 0 ]; then
	echo "REFUSING: $OB Obscure2.exe and $RL obscoop-relay.exe already run; I did not start them." >&2
	exit 3
fi
if [ ! -f "$RELAY" ]; then echo "no relay at $RELAY" >&2; exit 2; fi
if [ ! -f "$DLL" ]; then echo "no dll at $DLL" >&2; exit 2; fi

trap cleanup EXIT INT TERM
echo "=== soak run (${PROFILE:+profile $PROFILE, }lag $LAG jitter $JIT loss $LOSS, $ITERS iterations)  run dir $RUNDIR"
echo "transport pump: $([ "${OBSCOOP_TRANSPORT_FRAME:-0}" = 1 ] && echo frame || echo thread)"
echo "root $ROOT"
echo "relay $RELAY"
echo "dll $DLL"

start_relay host || exit 4
start_relay guest || exit 4
wait_relay host || exit 4
wait_relay guest || exit 4
sleep 1

STARTED=1
echo "== start the pair (guest UDP 27962)"
timeout 60 "$PY" -I "$HERE/duo.py" start -- OBSCOOP_UDP=27962 > "$RUNDIR/start.out" 2>&1
tail -2 "$RUNDIR/start.out"
HP=$(cat "$HERE/duo_host.pid" 2>/dev/null)
GP=$(cat "$HERE/duo_guest.pid" 2>/dev/null)
if [ -z "$HP" ] || [ -z "$GP" ] || [ "$(proc_image "$HP")" != Obscure2.exe ] || [ "$(proc_image "$GP")" != Obscure2.exe ]; then
	echo "both game copies are not running (host '$HP' guest '$GP'); stopping"
	cleanup
	exit 5
fi
echo "host pid $HP, guest pid $GP"

echo "== both at the main menu; the host loads save 01 with the game's own menu path (the guest follows)"
timeout 300 "$PY" -I "$HERE/start_menu_load.py" > "$RUNDIR/load.out" 2>&1
tail -25 "$RUNDIR/load.out"
sleep 10

run_check() {   # label timeout script args...
	lbl=$1; t=$2; shift 2
	echo "== $lbl (timeout ${t}s)"
	timeout "$t" "$@" > "$RUNDIR/last.out" 2>&1
	rc=$?
	cat "$RUNDIR/last.out"
	[ $rc -ne 0 ] && { echo "-- $lbl: exit $rc"; RC=1; }
	return 0
}

run_check "check_attack_anim.py" 180 "$PY" -I "$HERE/check_attack_anim.py" "$HP" "$GP"
run_check "check_controls.py" 180 "$PY" -I "$HERE/check_controls.py" "$HP" "$GP"
run_check "check_visible.py (the peer character is drawn)" 150 "$PY" -I "$HERE/check_visible.py" "$HP" "$GP"
run_check "check_fight_pair.py (players attack each other)" 240 "$PY" -I "$HERE/check_fight_pair.py" "$HP" "$GP"
run_check "soak34.py ($ITERS location changes)" 1500 "$PY" -I "$HERE/soak34.py" "$HP" "$GP" "$ITERS"
run_check "check_doors.py --reset game3.sav" 300 "$PY" -I "$HERE/check_doors.py" "$HP" "$GP" --reset game3.sav

echo "== liveness and crash reports"
for g in host guest; do
	d=$([ "$g" = host ] && echo "$OBSCOOP_HOST_DIR" || echo "$OBSCOOP_GUEST_DIR")
	alive=$(tasklist //FI "PID eq $([ "$g" = host ] && echo "$HP" || echo "$GP")" //FO CSV //NH 2>/dev/null | grep -c '^"')
	fatal=$(grep -ac "FATAL EXCEPTION" "$d/obscoop.log" 2>/dev/null)
	fatal=$(echo ${fatal:-0} | tr -d '[:space:]')
	unhandled=$(grep -ac "on the unhandled" "$d/obscoop.log" 2>/dev/null)
	unhandled=$(echo ${unhandled:-0} | tr -d '[:space:]')
	stalls=$(grep -ac "GAME THREAD STALLED" "$d/obscoop.log" 2>/dev/null)
	stalls=$(echo ${stalls:-0} | tr -d '[:space:]')
	echo "  $g: alive $alive, FATAL EXCEPTION lines ${fatal:-0} (unhandled ${unhandled:-0}), game-thread stall reports ${stalls:-0}"
	if [ "$alive" = 0 ]; then echo "-- $g died during the soak"; RC=1; fi
	if [ "${unhandled:-0}" != 0 ]; then echo "-- $g logged an unhandled crash:"; grep -a -A8 "FATAL EXCEPTION" "$d/obscoop.log" | head -20; RC=1; fi
	if [ "${stalls:-0}" != 0 ]; then
		echo "-- $g stopped running frames (TASK 35 watchdog); the reports:"
		grep -a -A18 "GAME THREAD STALLED" "$d/obscoop.log" | head -40
		RC=1
	fi
done

echo "== crash handler proof: the guest is asked to fault (pipe crash)"
timeout 40 "$PY" -I - "$GP" "$HERE" <<'PY' > "$RUNDIR/crash.out" 2>&1
import os, sys, time
sys.path.insert(0, sys.argv[2])
try:
    from bot import Pipe
    p = Pipe(int(sys.argv[1]))
    print(p.cmd('crash'))
except Exception as e:
    print('pipe gone as expected:', e)
time.sleep(3)
print('guest still running:',
      os.popen('tasklist /FI "PID eq %s" /FO CSV /NH' % sys.argv[1]).read().strip()[:80])
PY
cat "$RUNDIR/crash.out"
GD=$OBSCOOP_GUEST_DIR
sleep 2
echo "== the guest's crash report"
for pat in "FATAL EXCEPTION" "fault at" "eip " "eax " "stack (" "last sync/net log lines" "end of the crash report"; do
	n=$(grep -c "$pat" "$GD/obscoop.log" 2>/dev/null)
	n=$(echo ${n:-0} | tr -d '[:space:]')
	echo "  $pat: ${n:-0} line(s)"
	[ "${n:-0}" = 0 ] && RC=1
done
grep -A16 "FATAL EXCEPTION" "$GD/obscoop.log" 2>/dev/null | tail -20

cleanup
if [ "$RC" = 0 ]; then echo "=== soak run: PASS"; else echo "=== soak run: FAIL"; fi
exit $RC
