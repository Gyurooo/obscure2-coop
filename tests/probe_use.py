"""TASK 19: use a door / save point the way a player does - while FACING it.

run_f1 (probe_face.py, I100) showed every field the door's own check `FUN_0042a480` reads is fine at
60 units (entity+0x24 = 1, entity+0xb8 = 0, distance 60 <= 80) and that the two dot products the check
uses go from +0.974 / +0.998 (facing the door) to negative values when the character is turned away.
run_i1 pressed A at 70 units with dot(char->door, forward) = +0.316 - i.e. not facing it.

This probe therefore, for every one of the eight stick directions: teleports back to 60 units in front
of the target, holds that stick briefly (`--turn`, default 0.35 s: long enough to turn the character,
short enough to stay inside the door's 80-unit check), reads the two dot products, presses A for 0.4 s
and watches mode / level / world / position for the game's own reaction.

Usage: python -I probe_use.py <pid> [door|save|both] [turn seconds]
"""
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe, press
from peek import Proc
from tp_to_items import (dist2d, dist3, entities, f32, level, player_human, player_pos, rtti, scan_room,
                         tag, u32, world)

GAME = 0x6c3068
DOORS = ('CToeDoor', 'CToeDoubleDoor', 'CToeSpecialDoor', 'CToeInternalDoor', 'CToeFlapDoor')
SAVES = ('CToeSavePoint', 'CToeSimpleSavePoint')
WHAT = sys.argv[2] if len(sys.argv) > 2 else 'both'
TURN = float(sys.argv[3]) if len(sys.argv) > 3 else 0.35
DIST = 55.0
STICK = (('up', 0, 30000), ('up-right', 21000, 21000), ('right', 30000, 0), ('down-right', 21000, -21000),
         ('down', 0, -30000), ('down-left', -21000, -21000), ('left', -30000, 0), ('up-left', -21000, 21000))

pid = int(sys.argv[1])
m, pipe = Proc(pid), Pipe(pid)


def mode():
    g = u32(m, m.va(GAME))
    return u32(m, g + 0x310) if g else 0


def fwd():
    h = player_human(m, 0)
    return (f32(m, h + 0x248), f32(m, h + 0x24c), f32(m, h + 0x250)) if h else (0.0, 0.0, 0.0)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def unit(a):
    n = math.sqrt(sum(v * v for v in a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def dumps(e, p, label):
    c = player_pos(m, 0)
    f = fwd()
    u = unit((p[0] - c[0], p[1] - c[1], p[2] - c[2]))
    ed = (f32(m, e + 0x13c), f32(m, e + 0x140), f32(m, e + 0x144))
    print('   %-9s d2 %6.1f d3 %6.1f dot(char->t, fwd) %+.3f dot(fwd, entdir) %+.3f | char %s'
          % (label, dist2d(c, p), dist3(c, p), dot(u, f), dot(f, ed), tuple(round(v, 1) for v in c)))
    return dot(u, f), dot(f, ed)


def targets(names):
    p1 = player_pos(m, 0)
    out = []
    for e in entities(m):
        name = rtti(m, e)
        if name in names:
            p = (f32(m, e + 0x6c), f32(m, e + 0x70), f32(m, e + 0x74))
            out.append((dist2d(p, p1), e, name, p))
    out.sort()
    return out


def attempt(e, p, side, label):
    """tp back to DIST in front of the target (front = the side the character came from, or the other),
    turn with each stick, read the dots, press A, watch for a reaction."""
    c = player_pos(m, 0)
    if side == 0:
        fromx, fromy = c[0] - p[0], c[1] - p[1]
    else:
        fromx, fromy = p[0] - c[0], p[1] - c[1]
    n = (fromx * fromx + fromy * fromy) ** 0.5 or 1.0
    gx, gy = p[0] + fromx / n * DIST, p[1] + fromy / n * DIST
    print('   tp -> %s' % pipe.cmd('tp 0 %.3f %.3f %.3f' % (gx, gy, p[2] - 0.5)))
    time.sleep(0.7)
    for name, lx, ly in STICK:
        pipe.cmd('pad 0 0 %d %d' % (lx, ly))
        time.sleep(TURN)
        pipe.cmd('pad 0 0')
        time.sleep(0.15)
        d1, d2 = dumps(e, p, name)
        lv0, w0, q0 = level(m), world(m), player_pos(m, 0)
        press(pipe, 0, 'A', 0.45)
        t0 = time.time()
        while time.time() - t0 < 2.5:
            lv, w = level(m), world(m)
            if lv != lv0 or w != w0:
                print('   *** %s: TRANSITION after A on stick %s (dots %+.3f/%+.3f) -> level %s world %#x'
                      % (label, name, d1, d2, tag(lv), w or 0))
                return 'transition'
            if mode() != 1:
                print('   *** %s: MODE %s after A on stick %s (dots %+.3f/%+.3f)' % (label, mode(), name, d1, d2))
                return 'mode %s' % mode()
            time.sleep(0.25)
        q = player_pos(m, 0)
        if q and dist2d(q, p) > 400.0:
            print('   *** %s: teleported/moved %.0f away after A on stick %s' % (label, dist2d(q, p), name))
            return 'moved'
    return None


print('probe_use: pid %d, what %s, turn %.2f s, stand %.0f units off' % (pid, WHAT, TURN, DIST))
print('level %s mode %s world %#x' % (tag(level(m)), mode(), world(m) or 0))
doors, saves = targets(DOORS), targets(SAVES)
jobs = []
if WHAT in ('door', 'both') and doors:
    jobs.append(('door', doors[0]))
if WHAT in ('save', 'both') and saves:
    jobs.append(('save', saves[0]))
for label, (d, e, name, p) in jobs:
    print('\n== %s: %s id %s at (%.1f, %.1f, %.1f), %.0f away' % (label, name, tag(u32(m, e + 4)), p[0], p[1], p[2], d))
    print('   entity +0x24 %#x +0xb8 %#x +0x14 %d +0x150 %#x +0x15c %#x +0xa0 %s'
          % (u32(m, e + 0x24), u32(m, e + 0xb8), u32(m, e + 0x14), u32(m, e + 0x150),
             u32(m, e + 0x15c), f32(m, e + 0xa0)))
    room = scan_room(m, player_pos(m, 0), 400.0, verbose=False)
    if room['enemies']:
        print('   REFUSED: %d live enemy(ies) in the start room; no teleport' % len(room['enemies']))
        continue
    r = attempt(e, p, 0, label)
    if not r:
        print('   -- nothing from side 0; trying the other side of the %s' % label)
        r = attempt(e, p, 1, label)
    print('   result for the %s: %s' % (label, r))
print('\nend: level %s mode %s pos %s' % (tag(level(m)), mode(), player_pos(m, 0)))
