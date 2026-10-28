"""TASK 19: the door / save point eligibility checks want the character to FACE them.

OBSERVED in the decompile (addresses are the vtable slots read live in run_i1):

* CToeDoor   vtable 0x656254, slot +0x34 = `FUN_0042a480` (decompile 24473-24500):
      entity+0xb8 == 0, entity+0x24 != 0, distance <= **80.0**, and
      dot(character+0x248..0x250, entity+0x13c..0x144) >= 0.5
* CToeSavePoint vtable 0x65ca24, slot +0x34 = `FUN_0046e6c0` (decompile 64851-64885):
      entity+0x24 != 0, entity+0xb8 == 0, entity+0x150 != 0, type == 1, entity+0x14 == 0,
      |entity z - character z| <= 200, entity+0x15c == 0 or FUN_00484e70(char) != 0,
      2-D distance <= entity+0xa0 (200), and dot(normalize(char -> entity), character+0x248..0x250) > 0.5

`FUN_00401f30` is the dot product, `FUN_00401ef0` the normaliser (`FUN_00401fa0` = sqrt). 0.5 is
cos(60 deg), so both want the character's forward vector within ~60 deg of the target.

This probe stands next to the target, prints every one of those fields, then sweeps the eight stick
directions and prints, for each, the distance, the two dot products and whether the game reacted
(level / world change or a big move). It writes nothing: the mod's safe `tp` and the virtual pad only.

Usage: python -I probe_face.py <pid> [door|save|both]
"""
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe
from peek import Proc
from tp_to_items import (dist2d, dist3, entities, f32, level, player_human, player_pos, rtti, scan_room,
                         tag, u32, world)

GAME = 0x6c3068
DOORS = ('CToeDoor', 'CToeDoubleDoor', 'CToeSpecialDoor', 'CToeInternalDoor', 'CToeFlapDoor')
SAVES = ('CToeSavePoint', 'CToeSimpleSavePoint')
WHAT = sys.argv[2] if len(sys.argv) > 2 else 'both'
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


def entity_dir(e):
    return (f32(m, e + 0x13c), f32(m, e + 0x140), f32(m, e + 0x144))


def sample(e, p):
    """Every field both checks read, computed the way the game computes it."""
    c = player_pos(m, 0)
    to = (p[0] - c[0], p[1] - c[1], p[2] - c[2])
    u = unit(to)
    f = fwd()
    d2 = dist2d(c, p)
    d3 = dist3(c, p)
    return dict(pos=c, fwd=f, fwd_len=math.sqrt(sum(v * v for v in f)), d2=d2, d3=d3,
                dot_to=dot(u, f), dot_dir=dot(f, entity_dir(e)),
                radial=u, ent_dir=entity_dir(e))


def show(label, e, p):
    s = sample(e, p)
    print('   %-10s dist2d %6.1f dist3d %6.1f | fwd (%.3f, %.3f, %.3f) |len| %.3f | '
          'dot(char->target, fwd) %+.3f  dot(fwd, ent+0x13c) %+.3f'
          % (label, s['d2'], s['d3'], s['fwd'][0], s['fwd'][1], s['fwd'][2], s['fwd_len'],
             s['dot_to'], s['dot_dir']))
    print('              char %s | entity +0x24 %#x +0xb8 %#x +0x150 %#x +0x14 %d +0x15c %#x | ent dir (%.3f, %.3f, %.3f)'
          % (tuple(round(v, 1) for v in s['pos']), u32(m, e + 0x24), u32(m, e + 0xb8), u32(m, e + 0x150),
             u32(m, e + 0x14), u32(m, e + 0x15c), s['ent_dir'][0], s['ent_dir'][1], s['ent_dir'][2]))
    return s


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


def sweep(e, p, label):
    old = (level(m), world(m), player_pos(m, 0))
    for name, lx, ly in STICK:
        pipe.cmd('pad 0 0 %d %d' % (lx, ly))
        time.sleep(0.55)
        pipe.cmd('pad 0 0')
        time.sleep(0.35)
        lv, w, q = level(m), world(m), player_pos(m, 0)
        if lv != old[0] or w != old[1]:
            print('   *** %s: TRANSITION on stick %s -> level %s world %#x' % (label, name, tag(lv), w or 0))
            return 'transition'
        moved = dist2d(q, old[2]) if q and old[2] else 0.0
        show('%s move %.0f' % (name, moved), e, p)
        old = (lv, w, q)
    return None


print('probe_face: pid %d, what %s' % (pid, WHAT))
print('level %s mode %s world %#x' % (tag(level(m)), mode(), world(m) or 0))
doors, saves = targets(DOORS), targets(SAVES)
for d, e, n, p in doors[:4]:
    print('  door %-16s id %s at (%.1f, %.1f, %.1f) %.0f away' % (n, tag(u32(m, e + 4)), p[0], p[1], p[2], d))
for d, e, n, p in saves[:4]:
    print('  save %-16s id %s at (%.1f, %.1f, %.1f) %.0f away' % (n, tag(u32(m, e + 4)), p[0], p[1], p[2], d))
if doors:
    show('at start', doors[0][1], doors[0][3])

jobs = []
if WHAT in ('door', 'both') and doors:
    jobs.append(('door', doors[0]))
if WHAT in ('save', 'both') and saves:
    jobs.append(('save', saves[0]))
for label, (d, e, name, p) in jobs:
    print('\n== %s: %s id %s at (%.1f, %.1f, %.1f), %.0f away' % (label, name, tag(u32(m, e + 4)), p[0], p[1], p[2], d))
    p1 = player_pos(m, 0)
    room = scan_room(m, p1, 400.0, verbose=False)
    if room['enemies']:
        print('   REFUSED: the start room has %d live enemy(ies); no teleport' % len(room['enemies']))
        continue
    dx, dy = p[0] - p1[0], p[1] - p1[1]
    n = (dx * dx + dy * dy) ** 0.5 or 1.0
    gx, gy = p[0] - dx / n * 60.0, p[1] - dy / n * 60.0    # 60 units: inside the door's 80-unit check
    print('   tp -> %s' % pipe.cmd('tp 0 %.3f %.3f %.3f' % (gx, gy, p1[2])))
    time.sleep(0.8)
    show('after tp', e, p)
    r = sweep(e, p, label)
    print('   sweep result for the %s: %s' % (label, r))
    if not r:
        # try again from a point on the other side of the target
        print('   retrying from the opposite side')
        ox, oy = p[0] + dx / n * 60.0, p[1] + dy / n * 60.0
        print('   tp -> %s' % pipe.cmd('tp 0 %.3f %.3f %.3f' % (ox, oy, p1[2])))
        time.sleep(0.8)
        show('after tp2', e, p)
        print('   sweep result (other side): %s' % sweep(e, p, label))
print('\nend: level %s mode %s pos %s' % (tag(level(m)), mode(), player_pos(m, 0)))
