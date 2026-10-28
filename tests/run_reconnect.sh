#!/bin/sh
# TASK 25 part B: does the link come back?
#
#  1) DROP  the link is dropped for 8 s in the middle of play with the test-only `netpause 8000` pipe
#           command on BOTH copies (no packet is sent or received, exactly like a dead link), then it is
#           back. Expected: both copies are in sync again within ~2 s, WITHOUT a level reload, and the
#           characters' positions converge.
#  2) RESTART  the guest's game is killed and started again at the main menu while the host keeps
#           playing. Expected: the guest is brought back into the host's game (the host's save, the same
#           level) exactly like a late join.
#
# Usage (from the worktree root, Git Bash):  sh tests/run_reconnect.sh <dll> [1|2|both]
# Prints every step verbatim, always stops the games it started, kills only what it started.
set -u

if [ $# -lt 1 ]; then
	echo "usage: sh tests/run_reconnect.sh <dll> [1|2|both]" >&2
	exit 2
fi
DLLARG=$1
shift
CASE=${1:-both}
case "$DLLARG" in
/*|[A-Za-z]:*) ;;
*) DLLARG=$(pwd)/$DLLARG ;;
esac
DLL=$(cygpath -w "$DLLARG") || exit 2
HERE=$(cd "$(dirname "$0")" && pwd)
export OBSCOOP_TEST_ROOT="${OBSCOOP_TEST_ROOT:-$(cd "$HERE/../.." && pwd)}"
export OBSCOOP_DLL="$DLL"
export OBSCOOP_HOST_DIR="${OBSCOOP_HOST_DIR:-$OBSCOOP_TEST_ROOT/obscure2-test}"
export OBSCOOP_GUEST_DIR="${OBSCOOP_GUEST_DIR:-$OBSCOOP_TEST_ROOT/obscure2-test2}"
PY="${PYTHON:-python}"
RC=0

count_image() {
	n=$(tasklist //FI "IMAGENAME eq $1" //FO CSV //NH 2>/dev/null | grep -c '^"')
	echo $((n + 0))
}

cleanup() {
	trap - EXIT INT TERM
	echo "== stopping the two games"
	timeout 30 "$PY" -I "$HERE/duo.py" stop 2>&1 | tail -3
	echo "remaining Obscure2.exe: $(count_image Obscure2.exe)"
}
trap cleanup EXIT INT TERM

if [ "$(count_image Obscure2.exe)" != 0 ]; then
	echo "REFUSING: an Obscure2.exe is already running that this script did not start" >&2
	tasklist //FI "IMAGENAME eq Obscure2.exe" //FO CSV //NH >&2
	exit 3
fi

echo "=== reconnect run ($CASE)  dll $DLL"
START=$(cd "$HERE" && "$PY" -I duo.py start | tail -1)
echo "pair: $START"
case "$START" in
*running*) ;;
*) echo "the pair did not start; stopping"; "$PY" -I "$HERE/duo.py" stop | tail -1; exit 2 ;;
esac
HP=$(cat "$HERE/duo_host.pid")
GP=$(cat "$HERE/duo_guest.pid")
echo "host pid $HP guest pid $GP"

echo "== both at the main menu; the host loads save 01 with the game's own LoadByName"
(cd "$HERE" && "$PY" -I start_menu_load.py | tail -6)

# Read both copies' world (level tag and every human's position) and wait until they agree.
wait_sync() {   # seconds label
	"$PY" -I - "$HP" "$GP" "$HERE" "$1" "$2" <<'PY'
import struct, sys, time
tests, secs, label = sys.argv[3], float(sys.argv[4]), sys.argv[5]
sys.path.insert(0, tests)
from peek import Proc
GAME = 0x6c3068
procs = [Proc(int(sys.argv[1])), Proc(int(sys.argv[2]))]

def tag4(v):
    if not v:
        return '-'
    b = struct.pack('<I', v)[::-1]
    return b.decode('latin1') if all(32 <= c < 127 for c in b) else '%08x' % v

def snap(p):
    g = p.u32(p.va(GAME))
    if not g:
        return (None, {})
    w = p.u32(g + 0x378) if g else 0
    if not w:
        return (None, {})
    lvl = tag4(p.u32(w + 4))
    mgr = p.u32(w + 0x175c)
    if not mgr:
        return (lvl, {})
    n, arr = p.u32(mgr + 4) or 0, p.u32(mgr + 0xc)
    out = {}
    for i in range(min(n, 8)):
        h = p.u32(arr + 4 * i) if arr else 0
        if not h:
            continue
        b = p.read(h + 0x23c, 12)
        if not b or len(b) < 12:
            continue
        out[tag4(p.u32(h + 0x14))] = struct.unpack('<3f', b)
    return (lvl, out)

def diff(a, b):
    common = set(a) & set(b)
    if not common:
        return None
    worst = 0.0
    for t in common:
        pa, pb = a[t], b[t]
        d = ((pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2) ** 0.5
        worst = max(worst, d)
    return worst

ok = 0
t0 = time.time()
while time.time() - t0 < secs:
    (lh, ah), (lg, ag) = snap(procs[0]), snap(procs[1])
    d = diff(ah, ag)
    good = lh and lh == lg and len(ah) >= 2 and len(ag) >= 2 and d is not None and d <= 3.0
    ok = ok + 1 if good else 0
    print('  %s t+%4.1f s level host %-4s guest %-4s chars %d/%d copy diff %s'
          % (label, time.time() - t0, lh, lg, len(ah), len(ag), '-' if d is None else '%.1f' % d))
    if ok >= 2:
        print('%s: IN SYNC after %.1f s (level %s, %d characters, worst copy difference %.1f units)'
              % (label, time.time() - t0, lh, len(ah), d))
        sys.exit(0)
    time.sleep(0.5)
print('%s: NOT IN SYNC after %.1f s' % (label, secs))
sys.exit(1)
PY
}

echo "== waiting for the loaded level to agree on both copies"
wait_sync 90 "before" || RC=1

if [ "$CASE" = 1 ] || [ "$CASE" = both ]; then
	echo
	echo "== CASE 1: drop the link for 8 s in the middle of play (netpause 8000 on both copies)"
	LEVELS_BEFORE=$(grep -c "guest: host LoadByName\|guest: host ChangeLevel" "$OBSCOOP_GUEST_DIR/obscoop.log" 2>/dev/null)
	echo "guest level/load requests before: ${LEVELS_BEFORE:-0}"
	"$PY" -I - "$HP" "$GP" "$HERE" <<'PY'
import sys, time
sys.path.insert(0, sys.argv[3])
from bot import Pipe
h, g = Pipe(int(sys.argv[1])), Pipe(int(sys.argv[2]))
print('  host : ' + h.cmd('netpause 8000'))
print('  guest: ' + g.cmd('netpause 8000'))
print('  host net: ' + h.cmd('net'))
print('  guest net: ' + g.cmd('net'))
time.sleep(10)
print('  host net after the drop: ' + h.cmd('net'))
print('  guest net after the drop: ' + g.cmd('net'))
PY
	echo "-- both copies, right after the link came back:"
	wait_sync 15 "resume" || RC=1
	LEVELS_AFTER=$(grep -c "guest: host LoadByName\|guest: host ChangeLevel" "$OBSCOOP_GUEST_DIR/obscoop.log" 2>/dev/null)
	echo "guest level/load requests after: ${LEVELS_AFTER:-0} (before ${LEVELS_BEFORE:-0})"
	if [ "${LEVELS_AFTER:-0}" != "${LEVELS_BEFORE:-0}" ]; then
		echo "CASE 1: FAIL -- the guest was told to load/change level after the reconnect"
		RC=1
	else
		echo "CASE 1: no level or load request reached the guest (no reload)"
	fi
	echo "-- reconnect lines:"
	grep -ah "guest joined again\|resuming without\|host welcomed us\|guest dropped\|host silent" \
		"$OBSCOOP_HOST_DIR/obscoop.log" "$OBSCOOP_GUEST_DIR/obscoop.log" 2>/dev/null | tail -8
fi

if [ "$CASE" = 2 ] || [ "$CASE" = both ]; then
	echo
	echo "== CASE 2: kill the guest and start it again at the main menu while the host keeps playing"
	GP=$(cat "$HERE/duo_guest.pid")
	echo "  killing guest pid $GP"
	taskkill //PID "$GP" //F >/dev/null 2>&1
	sleep 3
	echo "  Obscure2.exe now: $(count_image Obscure2.exe) (the host must still be there)"
	echo "  starting a new guest copy (duo.py start-guest)"
	(cd "$HERE" && "$PY" -I duo.py start-guest | tail -1)
	GP=$(cat "$HERE/duo_guest.pid")
	echo "  new guest pid $GP"
	echo "-- waiting for the guest to be brought back into the host's game"
	wait_sync 150 "late join" || RC=1
	echo "-- the guest's own log about the join:"
	grep -ah "host welcomed us\|host LoadByName\|host party applied\|host ChangeLevel\|real load" \
		"$OBSCOOP_GUEST_DIR/obscoop.log" 2>/dev/null | tail -6
	echo "-- the host's log about the join:"
	grep -h "guest joined\|resuming without\|save transfer starts\|guest dropped" \
		"$OBSCOOP_HOST_DIR/obscoop.log" 2>/dev/null | tail -6
fi

if [ "$RC" = 0 ]; then echo "=== reconnect run ($CASE): PASS"; else echo "=== reconnect run ($CASE): FAIL"; fi
exit $RC
