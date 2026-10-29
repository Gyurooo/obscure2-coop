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
#
# TASK 41 link options (env):
#   OBSCOOP_LINK=steam   run the pair through the two test relays with the relay's steam-like profile
#                        (OBSCOOP_RELAY, default <root>/obscure2-coop-repo/build/obscoop-relay.exe):
#                        ~75 ms RTT, -40..+40 ms jitter, 150 ms spikes, 16-33 ms bursts, 300-800 ms
#                        blackouts - the shape the owner's Steam playtest had. Unset = plain loopback, as before.
#   OBSCOOP_TRANSPORT_FRAME=1  inherited by both game copies: the OLD per-frame transport pump (test only),
#                        so the same link measures the old path against the new transport thread.
#   OBSCOOP_RELAY        the relay exe to start for OBSCOOP_LINK=steam.
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
# The save slot both copies load (and that check_pickup.py reports): OBSCOOP_SLOT=0..9, default 01.
export SAVE_SLOT="${SAVE_SLOT:-${OBSCOOP_SLOT:-0}}"
PY="${PYTHON:-python}"
HERE=$(cd "$(dirname "$0")" && pwd)
LINK=${OBSCOOP_LINK:-}
case "$LINK" in
''|steam) ;;
*) echo "unknown OBSCOOP_LINK '$LINK' (only: steam)" >&2; exit 2 ;;
esac
RELAY=${OBSCOOP_RELAY:-$OBSCOOP_TEST_ROOT/obscure2-coop-repo/build/obscoop-relay.exe}
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
	if [ -n "$RUNDIR" ]; then
		kill_own "$RUNDIR/host/relay.pid" obscoop-relay.exe
		kill_own "$RUNDIR/guest/relay.pid" obscoop-relay.exe
	fi
	echo "remaining Obscure2.exe: $(count_image Obscure2.exe), obscoop-relay.exe: $(count_image obscoop-relay.exe)"
}
start_relay() {
	mkdir -p "$RUNDIR/$1"
	"$PY" -I - "$RELAY" "$RUNDIR_WIN/$1" "$1" <<'PY' > "$RUNDIR/$1/start.txt" 2>&1
import os, subprocess, sys
exe, cwd, role = sys.argv[1:4]
args = [exe, role, '27961' if role == 'host' else '27962',
        '--udp-link', 'listen:28000' if role == 'host' else '28000', '--profile', 'steam']
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
			sed -n '1,2p' "$RUNDIR/$1/relay.out"
			return 0
		fi
		i=$((i + 1))
		sleep 0.25
	done
	echo "relay $1 did not come up:" >&2
	cat "$RUNDIR/$1/relay.out" 2>/dev/null >&2
	return 1
}

cd "$HERE" || exit 2
echo "=== run_pair_menu: dll $DLL  link ${LINK:-plain loopback}  pump $([ "${OBSCOOP_TRANSPORT_FRAME:-0}" = 1 ] && echo frame || echo thread)"
if [ -n "$LINK" ]; then
	OB=$(count_image Obscure2.exe)
	RL=$(count_image obscoop-relay.exe)
	if [ "$OB" != 0 ] || [ "$RL" != 0 ]; then
		echo "REFUSING: $OB Obscure2.exe and $RL obscoop-relay.exe already run; I did not start them." >&2
		exit 3
	fi
	if [ ! -f "$RELAY" ]; then
		echo "no relay at $RELAY (set OBSCOOP_RELAY)" >&2
		exit 2
	fi
	RUNDIR=${TMPDIR:-/tmp}/obscoop-menu-$$
	mkdir -p "$RUNDIR" || exit 2
	RUNDIR_WIN=$(cygpath -w "$RUNDIR")
	echo "relay $RELAY"
fi
trap cleanup EXIT INT TERM
if [ -n "$LINK" ]; then
	start_relay host || exit 4
	start_relay guest || exit 4
	wait_relay host || exit 4
	wait_relay guest || exit 4
	sleep 1
	START=$($PY -I duo.py start -- OBSCOOP_UDP=27962 | tail -1)
else
	START=$($PY -I duo.py start | tail -1)
fi
echo "$START"
case "$START" in
*running*) STARTED=1 ;;
*) echo "the pair did not start; not running the checks"; $PY -I duo.py stop | tail -1; exit 2 ;;
esac
if [ "${MODE:-}" = host-newgame ]; then
	echo "== host: new 2P game, then pause menu -> Load save 01 (guest stays at the main menu)"
	$PY -I start_save.py "$(cat duo_host.pid)" | tail -3
else
	echo "== both at the main menu; the host loads save 01 with the game's own LoadByName"
	$PY -I start_menu_load.py | tail -40
fi
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
if [ -n "$LINK" ]; then
	for g in host guest; do
		echo "-- $g relay: counters"
		grep -ah "link profile steam\|link: blackout\|link: 1 ms" "$RUNDIR/$g/relay.out" 2>/dev/null | tail -6
	done
fi
cleanup
exit $RC
