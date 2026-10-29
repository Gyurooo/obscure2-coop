"""TASK 34 item 1: crash soak - 30 location changes back and forth under the ~90 ms relay.

Each iteration makes the host load one of two test saves (the other one each time), which is a real world
rebuild and level change (LoadByName -> request state 3/4, the same path a door's ChangeLevel takes), waits
until BOTH copies are in the same level, then drives movement and an attack on both pads. Every fifth
iteration also runs the game's own door use on the host and on the guest (PKT_DOOR in both directions).

The pass conditions: every iteration reached a common level on both copies, both processes are alive at
the end, BOTH GAME THREADS ARE STILL RUNNING (the `frames` counter in `sync` rises - TASK 34's soak
passed while the guest's game thread was stopped), and neither log contains a crash report
("*** obscoop: FATAL EXCEPTION") or a stall report ("*** obscoop: GAME THREAD STALLED", TASK 35). The
runner then asks the guest to fault (pipe `crash`) and checks that the report is present and complete -
that is the proof that the crash handler works.

Usage: python -I soak34.py <host pid> <guest pid> [iterations]
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe
from peek import Proc
from tp_to_items import level, player_human, player_pos, tag, u32, world

GAME = 0x6c3068
SAVES = ('game0.sav', 'game3.sav')   # I100 and J002 (both test saves, both have doors)
WAIT_LEVEL = 30.0

host_pid, guest_pid = int(sys.argv[1]), int(sys.argv[2])
iters = int(sys.argv[3]) if len(sys.argv) > 3 else 30
H, G = Proc(host_pid), Proc(guest_pid)
HP, GP = Pipe(host_pid), Pipe(guest_pid)


def in_level(m):
    g = u32(m, m.va(GAME))
    if not g:
        return False
    w = u32(m, g + 0x378)
    return u32(m, g + 0x310) == 1 and u32(m, g + 0x320) == 0 and w and (u32(m, w + 4) or 0) != 0


def mode_of(m):
    g = u32(m, m.va(GAME))
    return (u32(m, g + 0x310), u32(m, g + 0x320)) if g else (None, None)


def wait_same(t=WAIT_LEVEL):
    t0 = time.time()
    while time.time() - t0 < t:
        if in_level(H) and in_level(G) and tag(level(H)) == tag(level(G)):
            return True, time.time() - t0
        time.sleep(0.3)
    return False, time.time() - t0


def settle(secs=1.0):
    time.sleep(secs)


def drive(seconds=0.6):
    HP.cmd('pad 0 0 0 26000')
    GP.cmd('pad 0 0 0 -26000')
    time.sleep(seconds)
    HP.cmd('pad 0 0')
    GP.cmd('pad 0 0')
    time.sleep(0.25)


def attack():
    HP.cmd('pad 0 0x100')
    time.sleep(0.45)
    HP.cmd('pad 0 0x300')
    time.sleep(0.2)
    HP.cmd('pad 0 0x100')
    time.sleep(0.35)
    HP.cmd('pad 0 0')


def use_door(pipe, pl, who):
    r = pipe.cmd('usedoor %d' % pl)
    print('     %s usedoor %d -> %s' % (who, pl, r))
    return r.startswith('ok')


def count_line(pipe, what):
    r = pipe.cmd('sync')
    for part in r.split('|'):
        if what in part:
            return part.strip()
    return ''


def frames(pipe):
    """The game-thread heartbeat from `sync` (sync.c:4921). -1 when the pipe does not say."""
    part = count_line(pipe, 'frames ')
    try:
        return int(part.split()[-1])
    except (IndexError, ValueError):
        return -1


# TASK 37: the race phases read the game logs the runner's env names (OBSCOOP_HOST_DIR / OBSCOOP_GUEST_DIR).
def log_path(role):
    d = os.environ.get('OBSCOOP_%s_DIR' % role.upper())
    return os.path.join(d, 'obscoop.log') if d else ''


def log_size(role):
    try:
        return os.path.getsize(log_path(role))
    except (OSError, TypeError):
        return 0


def wait_log(role, marker, since, timeout):
    """True as soon as the log holds `marker` after byte offset `since`."""
    p = log_path(role)
    if not p or not os.path.exists(p):
        return False
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with open(p, 'rb') as f:
                f.seek(since)
                if marker.encode() in f.read():
                    return True
        except OSError:
            pass
        time.sleep(0.1)
    return False


def threads_running(waited=2.0):
    """Both game threads must still run frames: sample, wait, sample again."""
    f0 = (frames(HP), frames(GP))
    time.sleep(waited)
    f1 = (frames(HP), frames(GP))
    running = (f1[0] > f0[0] >= 0) and (f1[1] > f0[1] >= 0)
    print('game threads: host frames %s -> %s, guest %s -> %s (%s)' % (
        f0[0], f1[0], f0[1], f1[1], 'both running' if running else 'STOPPED'))
    return running


ok_all = True
warm, el = wait_same(45)
print('start: both copies in one level after %.1fs (%s / %s)' % (el, tag(level(H)), tag(level(G))))
if not warm:
    print('soak FAIL: the two copies never reached a common level')
    sys.exit(1)

prev = tag(level(H))
for i in range(iters):
    sv = SAVES[i % len(SAVES)]
    before = tag(level(H))
    reply = HP.cmd('loadsave %s' % sv)
    # The load is a world rebuild: wait until the host is in a level again, the level actually changed (or
    # the load named the level we are in, then at least a full load cycle passed), and both copies agree.
    t0 = time.time()
    changed = False
    while time.time() - t0 < 45:
        lt = tag(level(H))
        if in_level(H) and lt and time.time() - t0 > 2.0 and (lt != before or time.time() - t0 > 20.0):
            changed = True
            break
        time.sleep(0.3)
    same, el = wait_same(30 if changed else 5)
    lv = '%s/%s' % (tag(level(H)), tag(level(G)))
    print('== %2d: host loads %-9s -> %s, level %s -> %s (%.1fs, %s) (mode %s / %s)' % (
        i + 1, sv, 'load done' if changed else 'NO change', before, lv, el,
        'one level' if same else 'NOT one level', mode_of(H), mode_of(G)))
    if not (changed and same):
        ok_all = False
        continue
    settle(1.5)
    drive()
    attack()
    if not threads_running(1.5):
        ok_all = False
        print('     soak stops here: a game thread is not running any more (the watchdog report is in the log)')
        break
    if (i + 1) % 5 == 0:
        use_door(HP, 0, 'host')
        time.sleep(0.6)
        use_door(GP, 1, 'guest')
        time.sleep(0.6)
        same2, el2 = wait_same(20)
        print('     after the door uses: %s (%.1fs) level %s/%s' % (
            'one level' if same2 else 'not one level', el2, tag(level(H)), tag(level(G))))
        if not same2:
            ok_all = False

# ---- TASK 37: deliberate race phases -------------------------------------------------------------
# The soak failure this task fixes was a door's ChangeLevel and a save load 0.7 s apart: the host
# announced both, its own game applied them in one order and the guest's in another, and the copies
# stayed split. These two phases reproduce that on purpose and require ONE level afterwards (the
# transition sequence + the guest's self-heal must end them together).
print('\n== race A: door use on the host, then a save load the moment the door asks for its level')
t_door = time.time()
if not use_door(HP, 0, 'host'):
    print('   race A: no door for the host in level %s: skipped' % tag(level(H)))
else:
    sz = log_size('host')
    got = wait_log('host', 'request ChangeLevel', sz, 25)
    print('   the door reached its ChangeLevel: %s' % ('yes' if got else 'NO'))
    if not got:
        ok_all = False
    sv = SAVES[iters % len(SAVES)]
    print('   issuing loadsave %s right now (%.1f s after the door use)' % (sv, time.time() - t_door))
    HP.cmd('loadsave %s' % sv)
    same, el = wait_same(35)
    print('   race A result: level %s/%s after %.1fs -> %s' % (
        tag(level(H)), tag(level(G)), el, 'one level' if same else 'NOT one level'))
    if not same:
        ok_all = False
    if not threads_running(1.5):
        ok_all = False

print('\n== race B: the same door used on the host and on the guest at the same moment')
use_door(HP, 0, 'host')
use_door(GP, 1, 'guest')
time.sleep(0.6)
same, el = wait_same(35)
print('   race B result: level %s/%s after %.1fs -> %s' % (
    tag(level(H)), tag(level(G)), el, 'one level' if same else 'NOT one level'))
if not same:
    ok_all = False
if not threads_running(1.5):
    ok_all = False

# The race phases leave a door animation / a level ask in flight; the checks that follow (run_soak runs
# check_doors right after this script) need a settled pair: one level and no change for 3 s.
print('\n== settling after the race phases (one level, no change for 3 s)')
t0 = time.time()
quiet_since, last = None, None
while time.time() - t0 < 40:
    ok = in_level(H) and in_level(G) and tag(level(H)) == tag(level(G))
    lv = tag(level(H))
    if ok and lv == last:
        if quiet_since is None:
            quiet_since = time.time()
        if time.time() - quiet_since >= 3.0:
            break
    else:
        quiet_since = None
    last = lv
    time.sleep(0.5)
print('   settled: level %s/%s, quiet for %.1f s (%s)' % (
    tag(level(H)), tag(level(G)), time.time() - (quiet_since if quiet_since else time.time()),
    'yes' if quiet_since else 'NO'))
if not quiet_since:
    ok_all = False

alive = True
for name, pid in (('host', host_pid), ('guest', guest_pid)):
    try:
        r = HP.cmd('ping') if name == 'host' else GP.cmd('ping')
    except OSError:
        r = ''
    print('%s pipe: %s' % (name, r or 'no reply'))
    if not r:
        alive = False

print('final levels: host %s guest %s' % (tag(level(H)), tag(level(G))))
if not threads_running(2.0):
    ok_all = False
print('door counters: host [%s] guest [%s]' % (count_line(HP, 'door sent'), count_line(GP, 'door sent')))
if alive and ok_all:
    print('soak OK (%d location changes, both copies alive)' % iters)
    sys.exit(0)
print('soak FAIL (%d iterations, alive %s)' % (iters, alive))
sys.exit(1)
