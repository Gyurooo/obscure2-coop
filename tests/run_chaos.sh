#!/bin/sh
# Live chaos test: host + guest copies through two relays that lag, jitter and lose packets.
#
# Usage (from the repo/worktree root, Git Bash):
#   sh tests/run_chaos.sh <dll> [lag_ms jitter_ms loss_pct] [--save-xfer]
# Example:
#   sh tests/run_chaos.sh chk.dll 60 20 5 --save-xfer
#
# Env: OBSCOOP_TEST_ROOT (folder holding obscure2-test and obscure2-test2, default <tests>/../..),
#      PYTHON (default python), OBSCOOP_RELAY (default <root>/obscure2-coop-repo/build/obscoop-relay.exe),
#      OBSCOOP_HOST_DIR / OBSCOOP_GUEST_DIR (as in duo.py).
#
# --save-xfer: first backs the guest's Save/game*.sav up to the guest's Save.chaos.bak (only if that
# folder does not exist yet) and deletes them, so the host has to transfer all ten saves; check_savexfer.py
# is added to the checks.
#
# OBSCOOP_FLOW=menu: the TASK 12 flow instead of the new-game-first one — both copies stay at the main
# menu, the host loads save 01 with the game's own LoadByName (start_menu_load.py).
#
# Starts only its own relays and games, kills only those, and every wait has a timeout. Prints each
# check's output verbatim.

set -u

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=${OBSCOOP_TEST_ROOT:-$(cd "$HERE/../.." && pwd)}
PY=${PYTHON:-python}
RELAY=${OBSCOOP_RELAY:-$ROOT/obscure2-coop-repo/build/obscoop-relay.exe}
export OBSCOOP_TEST_ROOT="$ROOT"
export OBSCOOP_HOST_DIR="${OBSCOOP_HOST_DIR:-$ROOT/obscure2-test}"
export OBSCOOP_GUEST_DIR="${OBSCOOP_GUEST_DIR:-$ROOT/obscure2-test2}"

if [ $# -lt 1 ]; then
	echo "usage: sh tests/run_chaos.sh <dll> [lag_ms jitter_ms loss_pct] [--save-xfer]" >&2
	exit 2
fi
DLL=$(cygpath -w "$1") || exit 2
shift
export OBSCOOP_DLL="$DLL"
LAG=0 JIT=0 LOSS=0 XFER=0
if [ $# -ge 1 ] && [ "$1" != "--save-xfer" ]; then
	LAG=$1; shift
	[ $# -ge 1 ] && [ "$1" != "--save-xfer" ] && { JIT=$1; shift; }
	[ $# -ge 1 ] && [ "$1" != "--save-xfer" ] && { LOSS=$1; shift; }
fi
while [ $# -gt 0 ]; do
	case "$1" in
	--save-xfer) XFER=1 ;;
	*) echo "unknown argument: $1" >&2; exit 2 ;;
	esac
	shift
done
TAG="lag${LAG}-jit${JIT}-loss${LOSS}"
RUNDIR=${TMPDIR:-/tmp}/obscoop-chaos-$$
mkdir -p "$RUNDIR" || exit 2
RUNDIR_WIN=$(cygpath -w "$RUNDIR")
STARTED=0
RC=0

proc_image() {   # pid -> image name (empty if no such process)
	tasklist //FI "PID eq $1" //FO CSV //NH 2>/dev/null | sed -n '1s/^"\([^"]*\)".*/\1/p'
}
count_image() {
	n=$(tasklist //FI "IMAGENAME eq $1" //FO CSV //NH 2>/dev/null | grep -c '^"')
	echo $((n + 0))
}
kill_own() {   # pidfile image
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

start_relay() {   # role exe rundirwin lag jit loss
	mkdir -p "$RUNDIR/$1"
	"$PY" -I - "$RELAY" "$RUNDIR_WIN/$1" "$1" "$LAG" "$JIT" "$LOSS" <<'PY' > "$RUNDIR/$1/start.txt" 2>&1
import os, subprocess, sys
exe, cwd, role, lag, jit, loss = sys.argv[1:7]
args = [exe, role, '27961' if role == 'host' else '27962',
        '--udp-link', 'listen:28000' if role == 'host' else '28000',
        '--lag', lag, '--jitter', jit, '--loss', loss]
out = open(os.path.join(cwd, 'relay.out'), 'wb')
p = subprocess.Popen(args, cwd=cwd, stdout=out, stderr=subprocess.STDOUT,
                     creationflags=0x00000008 | 0x00000200)
open(os.path.join(cwd, 'relay.pid'), 'w').write(str(p.pid))
print('relay %s pid %d: %s' % (role, p.pid, ' '.join(args)))
PY
	cat "$RUNDIR/$1/start.txt"
}

wait_relay() {   # role what -> waits up to 10 s for the log line
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

run_logged() {   # timeout-seconds label command...
	t=$1; lbl=$2; shift 2
	echo "== $lbl (timeout ${t}s)"
	timeout "$t" "$@" > "$RUNDIR/last.out" 2>&1
	rc=$?
	cat "$RUNDIR/last.out"
	if [ $rc -ne 0 ]; then echo "-- $lbl: exit $rc"; fi
	return $rc
}

echo "=== chaos run $TAG (save-xfer $XFER)  run dir $RUNDIR"
echo "root $ROOT"
echo "relay $RELAY"
echo "dll $DLL"

# ---- preflight: nothing may be running that this script did not start ---------------------------------
OB=$(count_image Obscure2.exe)
RL=$(count_image obscoop-relay.exe)
if [ "$OB" != 0 ] || [ "$RL" != 0 ]; then
	echo "REFUSING: $OB Obscure2.exe and $RL obscoop-relay.exe already run; I did not start them." >&2
	tasklist //FI "IMAGENAME eq Obscure2.exe" //FO CSV //NH >&2
	tasklist //FI "IMAGENAME eq obscoop-relay.exe" //FO CSV //NH >&2
	exit 3
fi
if [ ! -f "$RELAY" ]; then echo "no relay at $RELAY" >&2; exit 2; fi
if [ ! -f "$DLL" ]; then echo "no dll at $DLL" >&2; exit 2; fi

trap cleanup EXIT INT TERM

# ---- save-transfer case: the guest starts without saves ------------------------------------------------
if [ "$XFER" = 1 ]; then
	GS="$OBSCOOP_GUEST_DIR/Save"
	BAK="$OBSCOOP_GUEST_DIR/Save.chaos.bak"
	mkdir -p "$GS" "$BAK"
	n=$(ls "$GS"/game*.sav 2>/dev/null | wc -l)
	if [ "$n" -gt 0 ] && [ -z "$(ls "$BAK"/game*.sav 2>/dev/null)" ]; then
		cp "$GS"/game*.sav "$BAK"/ && echo "save-xfer: kept $n original guest save(s) in $BAK"
	fi
	rm -f "$GS"/game*.sav
	echo "save-xfer: removed $n guest save(s) from $GS; host has $(ls "$OBSCOOP_HOST_DIR/Save"/game*.sav 2>/dev/null | wc -l)"
fi

# ---- relays ---------------------------------------------------------------------------------------------
start_relay host || { echo "relay start failed"; exit 4; }
start_relay guest || { echo "relay start failed"; exit 4; }
wait_relay host || { echo "host relay not up"; exit 4; }
wait_relay guest || { echo "guest relay not up"; exit 4; }
sleep 1
for r in host guest; do
	if [ "$(proc_image "$(cat "$RUNDIR/$r/relay.pid")")" != obscoop-relay.exe ]; then
		echo "relay $r died:"; cat "$RUNDIR/$r/relay.out"; exit 4
	fi
done

# ---- games through the relays ---------------------------------------------------------------------------
STARTED=1
if ! run_logged 60 "start the pair (guest UDP 27962)" "$PY" -I "$HERE/duo.py" start -- OBSCOOP_UDP=27962; then
	echo "pair did not start"; RC=1
fi
HP=""; GP=""
if [ -f "$HERE/duo_host.pid" ]; then HP=$(cat "$HERE/duo_host.pid"); fi
if [ -f "$HERE/duo_guest.pid" ]; then GP=$(cat "$HERE/duo_guest.pid"); fi
if [ -z "$HP" ] || [ -z "$GP" ] || [ "$(proc_image "$HP")" != Obscure2.exe ] || [ "$(proc_image "$GP")" != Obscure2.exe ]; then
	echo "both game copies are not running (host '$HP' guest '$GP'); stopping"; cleanup; exit 5
fi
echo "host pid $HP, guest pid $GP"

if [ "${OBSCOOP_FLOW:-newgame}" = menu ]; then
	if ! run_logged 300 "both at the main menu, the host loads save 01" "$PY" -I "$HERE/start_menu_load.py"; then
		echo "start_menu_load did not finish"; RC=1
	fi
else
	if ! run_logged 210 "both into a 2P new game" "$PY" -I "$HERE/duo_start_game.py"; then
		echo "duo_start_game did not finish"; RC=1
	fi
	if ! run_logged 180 "host loads save 01" "$PY" -I "$HERE/start_save.py" "$HP"; then
		echo "start_save did not finish"; RC=1
	fi
fi

# ---- convergence: bounded poll, memory only --------------------------------------------------------------
echo "== waiting up to 60 s for convergence"
timeout 90 "$PY" -I - "$HP" "$GP" "$HERE" <<'PY' > "$RUNDIR/converge.out" 2>&1
import struct, sys, time
sys.path.insert(0, sys.argv[3])
from peek import Proc
hp, gp = int(sys.argv[1]), int(sys.argv[2])
mh, mg = Proc(hp), Proc(gp)

def tag(v):
    return struct.pack('<I', v or 0).decode('latin1')[::-1]

def humans(m):
    try:
        g = m.u32(m.va(0x6c3068))
        w = m.u32(g + 0x378) if g else 0
        mgr = m.u32(w + 0x175c) if w else 0
        if not mgr:
            return []
        n, arr = m.u32(mgr + 4) or 0, m.u32(mgr + 0xc)
        out = []
        for i in range(min(n, 8)):
            hp = m.u32(arr + 4 * i) if arr else 0
            if not hp:
                continue
            slots = []
            for s in range(4):
                wp = m.u32(hp + 0x704 + 4 * s)
                slots.append(tag(m.u32(wp + 0x10)) if wp else '-')
            out.append(dict(tag=tag(m.u32(hp + 0x14)), slots=slots, cur=m.u32(hp + 0x714)))
        return out
    except Exception:
        return []

def hands_differ(hh, hg):
    byg = {x['tag']: x for x in hg}
    for x in hh:
        y = byg.get(x['tag'])
        if y and (x['slots'] != y['slots'] or x['cur'] != y['cur']):
            return '%s host %s/%s guest %s/%s' % (x['tag'], x['slots'], x['cur'], y['slots'], y['cur'])
    return ''

def snap(m):
    try:
        g = m.u32(m.va(0x6c3068))
        if not g:
            return None
        mode, state = m.u32(g + 0x310), m.u32(g + 0x320)
        w = m.u32(g + 0x378) if g else 0
        if mode != 1 or state != 0 or not w:
            return dict(level=None, inv=None, party=None, mode=mode, state=state, hands=[])
        lvl = tag(m.u32(w + 4))
        invs = m.u32(w + 0x1790)
        inv = m.u32(invs + 4) if invs else None
        mgr = m.u32(w + 0x175c)
        arr = m.u32(mgr + 0xc) if mgr else 0
        party = None
        if arr:
            n = m.u32(mgr + 4)
            if n is not None and n <= 8:
                party = sorted(tag(m.u32(m.u32(arr + 4 * i) + 0x14)) for i in range(n))
        return dict(level=lvl, inv=inv, party=party, mode=mode, state=state, hands=humans(m))
    except Exception:
        return None

def line(s):
    if not s:
        return '?'
    return 'level %s inv %s party %s (mode %s state %s) hands %s' % (
        s['level'], s['inv'], s['party'], s['mode'], s['state'],
        [(x['tag'], x['slots'], x['cur']) for x in s['hands']])

def converged(a, b):
    if not (a and b and a['level'] and b['level'] and a['level'] == b['level'] and a['inv'] is not None
            and a['inv'] == b['inv'] and a['party'] is not None and a['party'] == b['party']):
        return False
    # the hands count too: the host's weapons exist, and every character on both copies has the same slots
    if any(any(s != '-' for s in x['slots']) for x in a['hands']):
        if not a['hands'] or not b['hands']:
            return False
        return not hands_differ(a['hands'], b['hands']) and not hands_differ(b['hands'], a['hands'])
    return True

t0 = time.time()
last = None
while time.time() - t0 < 60:
    a, b = snap(mh), snap(mg)
    last = (a, b)
    if converged(a, b):
        break
    time.sleep(0.6)
el = time.time() - t0
a, b = last if last else (None, None)
print('host : %s' % line(a))
print('guest: %s' % line(b))
if converged(a, b):
    print('CONVERGED after %.1f s (level %s, inventory %s, party %s)' % (el, a['level'], a['inv'], a['party']))
    sys.exit(0)
print('NOT CONVERGED after %.1f s' % el)
if not a or not a['level']:
    print('  host is not in a level')
if not b or not b['level']:
    print('  guest is not in a level')
if a and b and a['level'] and b['level'] and a['level'] != b['level']:
    print('  levels differ: host %s guest %s' % (a['level'], b['level']))
if a and b and a['inv'] != b['inv']:
    print('  inventory counts differ: host %s guest %s' % (a['inv'], b['inv']))
if a and b and a['party'] != b['party']:
    print('  parties differ: host %s guest %s' % (a['party'], b['party']))
if a and b and a['hands'] and b['hands']:
    d = hands_differ(a['hands'], b['hands']) or hands_differ(b['hands'], a['hands'])
    if d:
        print('  hands differ: %s' % d)
sys.exit(1)
PY
cat "$RUNDIR/converge.out"
grep -q '^CONVERGED' "$RUNDIR/converge.out" || RC=1

# ---- checks ----------------------------------------------------------------------------------------------
for c in check_save.py check_party.py check_hands.py check_items.py; do
	echo "== $c"
	timeout 60 "$PY" -I "$HERE/$c" "$HP" "$GP" || RC=1
done
if [ "$XFER" = 1 ]; then
	echo "== check_savexfer.py"
	timeout 60 "$PY" -I "$HERE/check_savexfer.py" || RC=1
fi

# ---- what the logs say about convergence ----------------------------------------------------------------
echo "== log timing (host vs guest, same PC clock)"
timeout 60 "$PY" -I - "$OBSCOOP_HOST_DIR" "$OBSCOOP_GUEST_DIR" <<'PY'
import os, re, sys, time
host_dir, guest_dir = sys.argv[1], sys.argv[2]

def read(name):
    try:
        return open(os.path.join(name, 'obscoop.log'), encoding='latin1', errors='replace').read().splitlines()
    except OSError:
        return []

def stamp(l):
    m = re.match(r'(\d\d):(\d\d):(\d\d)\.(\d\d\d)', l)
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000.0

def epoch(l):
    m = re.match(r'(\d\d):(\d\d):(\d\d)\.(\d\d\d)', l)
    if not m:
        return None
    lt = time.localtime()
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, int(m.group(1)), int(m.group(2)), int(m.group(3)), 0, 0, -1)) + int(m.group(4)) / 1000.0

host = read(host_dir)
guest = read(guest_dir)
hp = re.compile(r'request (ChangeLevel|LoadProgress|LoadByName)|host: level is now')
gp = re.compile(r'guest: host (ChangeLevel|LoadProgress|LoadByName|party stored|party applied)')
hl = [l for l in host if hp.search(l)]
gl = [l for l in guest if gp.search(l)]
print('-- host log (%d matching lines):' % len(hl))
for l in hl[-6:]:
    print('  ' + l)
# anchor on the save load (the last "level is now" line), not on the earlier new-game lines
anchor_line = None
for l in host:
    if 'host: level is now' in l:
        anchor_line = l
if anchor_line is None:
    for l in hl:
        if 'request ChangeLevel' in l or 'request LoadByName' in l:
            anchor_line = l
anchor = stamp(anchor_line) if anchor_line else None
lvl = ''
m = re.search(r'level is now (\w{4})', anchor_line or '')
if m:
    lvl = m.group(1)
print('-- anchor (host): %s' % (anchor_line or 'none'))
after = [l for l in gl if stamp(l) is not None and anchor is not None and stamp(l) >= anchor - 1.0]
print('-- guest log after the anchor (%d lines, %d parenthesised):' % (len(after), len(gl)))
for l in after[:6]:
    print('  ' + l)
print('-- guest timeline:')


def first_after(pat):
    for l in after:
        if pat in l:
            return l
    return None


t_lev = first_after('guest: host ChangeLevel')
t_store = first_after('guest: host party stored')
t_apply = first_after('guest: host party applied')
if t_lev and lvl and lvl not in t_lev:
    t_lev = next((l for l in after if 'guest: host ChangeLevel' in l and lvl in l), t_lev)
if t_store and lvl:
    t_store = next((l for l in after if 'party stored' in l and lvl in l), t_store)
if t_apply and lvl:
    t_apply = next((l for l in after if 'party applied' in l and lvl in l), t_apply)
if anchor is not None:
    for name, l in (('level request reaches the guest', t_lev), ('host party stored on the guest', t_store),
                    ('host party applied at the level change', t_apply)):
        print('  %-38s %s' % (name, 'no such line' if l is None else '%+.2f s  %s' % (stamp(l) - anchor, l)))
else:
    print('  no host level line in the log')
# guest save files: presence and how long after the load the last one was written
t0 = epoch(hl[0]) if hl else None
print('-- guest Save/game*.sav:')
newest = None
for i in range(10):
    p = os.path.join(guest_dir, 'Save', 'game%d.sav' % i)
    try:
        st = os.stat(p)
    except OSError:
        print('  game%d.sav MISSING' % i)
        continue
    newest = st.st_mtime if newest is None else max(newest, st.st_mtime)
    print('  game%d.sav %6d bytes written %s' % (i, st.st_size, time.strftime('%H:%M:%S', time.localtime(st.st_mtime))))
if newest is not None and t0 is not None:
    print('  last guest save write: %+.1f s after the host load line' % (newest - t0))
hlast = os.path.join(host_dir, 'Save', 'game9.sav')
try:
    print('  host game9.sav written %s' % time.strftime('%H:%M:%S', time.localtime(os.stat(hlast).st_mtime)))
except OSError:
    print('  host game9.sav MISSING')
PY

# ---- relay health and tails -------------------------------------------------------------------------------
for r in host guest; do
	pid=$(cat "$RUNDIR/$r/relay.pid" 2>/dev/null)
	echo "-- relay $r pid ${pid:-?} image $(proc_image "${pid:-0}")"
	sed -n '1,3p' "$RUNDIR/$r/relay.out"
	tail -3 "$RUNDIR/$r/relay.out"
done

# ---- always stop ---------------------------------------------------------------------------------------------
cleanup
if [ "$RC" = 0 ]; then echo "=== chaos run $TAG: PASS"; else echo "=== chaos run $TAG: FAIL"; fi
exit $RC
