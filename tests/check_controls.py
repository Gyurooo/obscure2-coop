"""TASK 34 item 4: each player's own pad drives their own character (host = player 1, guest = player 2).

The owner's playtest had the guest's controller driving the HOST's character until they swapped
controllers in the game's menu. The pad -> player mapping is the game's input map (o2.ipt): player 1's
action block must be on device 3 (gamepad 1 = XInput user 0) and player 2's on device 4 (gamepad 2 =
user 1). The mod corrects the map in memory when the game reads it, so this check drives each pad on its
own PC and reads where each character moved on both copies:

  * host pad forward  -> the character player 1 drives moves on BOTH copies, player 2 stays put;
  * guest pad forward -> the character player 2 drives moves on BOTH copies, player 1 stays put.

It also prints the controller wiring (which character each input controller record drives, and which
controller each human answers) and the mod's own `input map:` lines from both logs.

Usage: python -I check_controls.py <host pid> <guest pid>
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe
from peek import Proc
from tp_to_items import level, open_spot, player_human, player_pos, tag, u32, world

GAME = 0x6c3068
MOVE_MIN = 20.0
STILL_MAX = 6.0
STICK_MS = 1300

host_pid, guest_pid = int(sys.argv[1]), int(sys.argv[2])
H, G = Proc(host_pid), Proc(guest_pid)
HP, GP = Pipe(host_pid), Pipe(guest_pid)

ROOT = os.environ.get('OBSCOOP_TEST_ROOT') or os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DIRS = (os.environ.get('OBSCOOP_HOST_DIR') or os.path.join(ROOT, 'obscure2-test'),
        os.environ.get('OBSCOOP_GUEST_DIR') or os.path.join(ROOT, 'obscure2-test2'))


def in_level(m):
    g = u32(m, m.va(GAME))
    if not g:
        return False
    w = u32(m, g + 0x378)
    return u32(m, g + 0x310) == 1 and u32(m, g + 0x320) == 0 and w and (u32(m, w + 4) or 0) != 0


def normal(m):
    """In a level AND in normal play. The game only runs its pad/movement scan in world state 1 with no
    requested scene (FINDINGS_36 §2/§6); right after a load the level' own script often opens a scripted
    event (state 7 / world+0x12c != 0) for a few seconds, during which a held stick moves nobody. TASK 37:
    wait for normal play instead of failing a pad that is wired correctly."""
    g = u32(m, m.va(GAME))
    if not g:
        return False
    w = u32(m, g + 0x378)
    if not w or u32(m, g + 0x310) != 1 or u32(m, g + 0x320) != 0 or (u32(m, w + 4) or 0) == 0:
        return False
    return u32(m, w + 0x11c) == 1 and u32(m, w + 0x12c) == 0


def wait_normal(t=25.0):
    t0 = time.time()
    while time.time() - t0 < t:
        if normal(H) and normal(G) and tag(level(H)) == tag(level(G)):
            return time.time() - t0
        time.sleep(0.3)
    return None


def wiring(m):
    w = world(m)
    ctl = u32(m, w + 0x1748) if w else 0
    mgr = u32(m, w + 0x175c) if w else 0
    n, arr = (u32(m, mgr + 4) or 0, u32(m, mgr + 0xc)) if mgr else (0, 0)
    out = []
    for i in range(2):
        c = ctl + 0x764 * i if ctl else 0
        h = u32(m, c + 4) if c else 0
        out.append((tag(u32(m, h + 0x14)) if h else '-', c, u32(m, c + 0xc) if c else 0))
    hum = []
    for i in range(min(n, 8)):
        h = u32(m, arr + 4 * i) if arr else 0
        if not h:
            continue
        c = u32(m, h + 8)
        which = '-'
        for k in range(2):
            if c == out[k][1]:
                which = 'ctl%d' % k
        hum.append('%s->%s' % (tag(u32(m, h + 0x14)), which))
    return out, ' '.join(hum)


def positions(m):
    return {0: player_pos(m, 0), 1: player_pos(m, 1)}


def move(pipe, user, pl, secs, ly=30000):
    # TASK 47: start on the character's open spot (tests/tp_to_items.py open_spot, the owner's teleport
    # rule). A character the previous phase left against a wall does not move for its pad at all
    # (FINDINGS_47: 0.0 units forward, 242.2 backwards at the same spot), which would read as a wiring bug.
    # `ly` is signed: the second attempt walks the other way when the way forward is walled (run 47 proof 2
    # read 0.8 units twice for the guest at (-520.8, -79.0)).
    spot = SPOT.get(pl)
    if spot:
        try:
            r = pipe.cmd('tp %d %.2f %.2f %.2f' % (pl, spot[0], spot[1], spot[2]))
            if not r.startswith('ok'):
                print('   could not stand on the open spot (%s), the phase starts where it is' % r)
        except OSError as e:
            print('   open spot teleport: %s' % e)
    pipe.cmd('pad %d 0 0 %d' % (user, ly))
    time.sleep(secs / 2.0)
    # what each side sees while the stick is held: the pad this PC reads, and what the other copy feeds
    for name, p, u in (('host', HP, 0), ('guest', GP, 1)):
        try:
            print('   mid-hold %s xread %d: %s' % (name, u, p.cmd('xread %d' % u)))
        except OSError as e:
            print('   mid-hold %s xread: %s' % (name, e))
    for name, p in (('host', HP), ('guest', GP)):
        try:
            print('   mid-hold %s padshow: %s' % (name, p.cmd('padshow')))
        except OSError as e:
            print('   mid-hold %s padshow: %s' % (name, e))
    time.sleep(secs / 2.0)
    pipe.cmd('pad %d 0' % user)
    time.sleep(0.4)


def dist(a, b):
    if not a or not b:
        return 0.0
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def log_maps():
    for d in DIRS:
        p = os.path.join(d, 'obscoop.log')
        try:
            lines = open(p, encoding='latin1', errors='replace').read().splitlines()
        except OSError:
            print('   no log at %s' % p)
            continue
        im = [l for l in lines if 'input map:' in l]
        print('   %s: %d input-map line(s)' % (os.path.basename(d), len(im)))
        for l in im[-3:]:
            print('     ' + l.strip())


t0 = time.time()
while time.time() - t0 < 40 and not (in_level(H) and in_level(G)):
    time.sleep(0.5)
if not (in_level(H) and in_level(G)):
    print('NOT IN A LEVEL on both copies: check skipped')
    sys.exit(1)
wh, humh = wiring(H)
wg, humg = wiring(G)
print('wiring host : ctl0->%s ctl1->%s || %s' % (wh[0][0], wh[1][0], humh))
print('wiring guest: ctl0->%s ctl1->%s || %s' % (wg[0][0], wg[1][0], humg))
for name, pipe in (('host', HP), ('guest', GP)):
    try:
        print('%s stats: %s' % (name, pipe.cmd('stats')))
        print('%s pads : %s' % (name, pipe.cmd('padshow')))
    except OSError as e:
        print('%s pipe: %s' % (name, e))
print('the mod\'s input-map correction:')
log_maps()
if wh[0][0] == wh[1][0] or wg[0][0] == wg[1][0]:
    print('controls FAIL: both input controllers drive the same character')
    sys.exit(1)

ok = []
SPOT = {}
for by, pl, m, pipe in (('host', 0, H, HP), ('guest', 1, G, GP)):
    try:
        spot, why = open_spot(m, pipe, pl)
        SPOT[pl] = spot
        print('open spot of %s player %d: (%.1f, %.1f, %.1f) - %s'
              % (by, pl + 1, spot[0], spot[1], spot[2], why))
    except OSError as e:
        print('open spot of %s player %d: %s (the phases start where the character is)' % (by, pl + 1, e))
for by, pl in (('host', 0), ('guest', 1)):
    pipe = HP if by == 'host' else GP
    other = 1 - pl
    # Each copy's own controller is virtual pad 0 (LOCAL_PAD), whatever player it drives: on the host it
    # is served as XInput user 0 (player 1), on the guest as user 1 (player 2).
    print('== %s own pad (vpad 0) forward %.1f s (drives player %d = %s)' % (by, STICK_MS / 1000.0, pl + 1, wh[pl][0]))
    good = False
    for attempt in (1, 2):
        t = None if attempt == 1 else wait_normal(25)
        if attempt == 2:
            print('   the world was not in normal play (or nothing moved): waited %s s, driving the other '
                  'way (the forward direction from the open spot is walled)' % (
                      ('%.1f' % t) if t is not None else 'NO'))
        b0, b1 = positions(H), positions(G)
        move(pipe, 0, pl, STICK_MS / 1000.0, 30000 if attempt == 1 else -30000)
        a0, a1 = positions(H), positions(G)
        dh = [dist(b0[i], a0[i]) for i in (0, 1)]
        dg = [dist(b1[i], a1[i]) for i in (0, 1)]
        print('   host copy moved: player 1 %.1f, player 2 %.1f units | guest copy: player 1 %.1f, player 2 %.1f units'
              % (dh[0], dh[1], dg[0], dg[1]))
        good = dh[pl] >= MOVE_MIN and dg[pl] >= MOVE_MIN and dh[other] < STILL_MAX and dg[other] < STILL_MAX
        print('   %s: %s (own character moved on both copies, the other did not)' % (by, 'PASS' if good else 'FAIL'))
        if good:
            break
        if attempt == 1 and wait_normal(25) is not None:
            continue
        break
    ok.append(good)
    time.sleep(0.6)
if all(ok):
    print('controls OK (each pad drives its own character on both copies)')
    sys.exit(0)
print('controls FAIL (%s)' % ', '.join('PASS' if x else 'FAIL' for x in ok))
sys.exit(1)
