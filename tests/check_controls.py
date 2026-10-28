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
from tp_to_items import level, player_human, player_pos, tag, u32, world

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


def move(pipe, user, secs):
    pipe.cmd('pad %d 0 0 30000' % user)
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
for by, pl in (('host', 0), ('guest', 1)):
    pipe = HP if by == 'host' else GP
    other = 1 - pl
    # Each copy's own controller is virtual pad 0 (LOCAL_PAD), whatever player it drives: on the host it
    # is served as XInput user 0 (player 1), on the guest as user 1 (player 2).
    print('== %s own pad (vpad 0) forward %.1f s (drives player %d = %s)' % (by, STICK_MS / 1000.0, pl + 1, wh[pl][0]))
    b0, b1 = positions(H), positions(G)
    move(pipe, 0, STICK_MS / 1000.0)
    a0, a1 = positions(H), positions(G)
    dh = [dist(b0[i], a0[i]) for i in (0, 1)]
    dg = [dist(b1[i], a1[i]) for i in (0, 1)]
    print('   host copy moved: player 1 %.1f, player 2 %.1f units | guest copy: player 1 %.1f, player 2 %.1f units'
          % (dh[0], dh[1], dg[0], dg[1]))
    good = dh[pl] >= MOVE_MIN and dg[pl] >= MOVE_MIN and dh[other] < STILL_MAX and dg[other] < STILL_MAX
    print('   %s: %s (own character moved on both copies, the other did not)' % (by, 'PASS' if good else 'FAIL'))
    ok.append(good)
    time.sleep(0.6)
if all(ok):
    print('controls OK (each pad drives its own character on both copies)')
    sys.exit(0)
print('controls FAIL (%s)' % ', '.join('PASS' if x else 'FAIL' for x in ok))
sys.exit(1)
