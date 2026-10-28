"""TASK 19: is the door being USED at all? Direct observable = the entity's own "user" field.

`FUN_0042c2b0` (the door's vtable+0x70 = "use", decompile 25494-25563) starts with
`FUN_00402840(character)` and `in_ECX[0x31] = param_1`, i.e. **door+0xc4 = the character**. So after a
successful use door+0xc4 is a character pointer, and the door also stores that character's position at
+0x150..0x164. A door use does NOT have to change the level (it may just swing open), so watching the
level tag / world / position - what probe_use.py, probe_face.py and play_forward.try_door did - can
miss it completely.

The save point's use `FUN_0046e830` (decompile 64890-64934) likewise sets
`*(int *)(*(int *)(entity+0xc4) + 700) = entity` and `entity+0x154 = 1`.

This probe stands next to a door, prints `+0xc4` / `+0x154`, sweeps the eight stick directions (turn),
presses A while facing, and prints the same fields again after each press. It also reports the distance
to the door's real interaction anchor **+0x10c/+0x110/+0x114** (the point `FUN_0042a480` measures to, not
+0x6c), and the two dot products.

Usage: python -I probe_door2.py <pid> [door|save|both]
Writes nothing: only the mod's safe `tp` and the virtual pad.
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


def anchor(e):
    return (f32(m, e + 0x10c), f32(m, e + 0x110), f32(m, e + 0x114))


def state(e):
    return 'user+0xc4 %#x +0x154 %d +0x150 %#x +0x14 %d +0x24 %#x +0xb8 %#x' % (
        u32(m, e + 0xc4), u32(m, e + 0x154), u32(m, e + 0x150), u32(m, e + 0x14), u32(m, e + 0x24),
        u32(m, e + 0xb8))


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


def test(rec, label, stand=40.0):
    d, e, name, p = rec
    a = anchor(e)
    print('\n== %s: %s id %s at (%.1f, %.1f, %.1f), anchor +0x10c (%.1f, %.1f, %.1f)'
          % (label, name, tag(u32(m, e + 4)), p[0], p[1], p[2], a[0], a[1], a[2]))
    print('   before: %s' % state(e))
    c = player_pos(m, 0)
    fromx, fromy = c[0] - a[0], c[1] - a[1]
    n = (fromx * fromx + fromy * fromy) ** 0.5 or 1.0
    gx, gy = a[0] + fromx / n * stand, a[1] + fromy / n * stand
    print('   tp -> %s' % pipe.cmd('tp 0 %.3f %.3f %.3f' % (gx, gy, a[2] - 0.3)))
    time.sleep(0.8)
    print('   after tp: %s' % state(e))
    ed = (f32(m, e + 0x13c), f32(m, e + 0x140), f32(m, e + 0x144))
    for sname, lx, ly in STICK:
        pipe.cmd('pad 0 0 %d %d' % (lx, ly))
        time.sleep(0.35)
        pipe.cmd('pad 0 0')
        time.sleep(0.15)
        c = player_pos(m, 0)
        u = unit((a[0] - c[0], a[1] - c[1], a[2] - c[2]))
        f = fwd()
        print('   %-10s dist-to-anchor 2d %6.1f 3d %6.1f dot(char->anchor, fwd) %+.3f dot(fwd, entdir) %+.3f'
              % (sname, dist2d(c, a), dist3(c, a), dot(u, f), dot(f, ed)))
        lv0, w0 = level(m), world(m)
        press(pipe, 0, 'A', 0.45)
        time.sleep(0.6)
        print('      after A: %s pos %s level %s mode %s'
              % (state(e), tuple(round(v, 1) for v in player_pos(m, 0)), tag(level(m)), mode()))
        if u32(m, e + 0xc4) or u32(m, e + 0x154):
            print('   *** the %s recorded a user (see +0xc4/+0x154 above)' % label)
            return 'used'
        if level(m) != lv0 or world(m) != w0:
            print('   *** TRANSITION -> level %s world %#x' % (tag(level(m)), world(m) or 0))
            return 'transition'
    return None


print('probe_door2: pid %d, what %s' % (pid, WHAT))
print('level %s mode %s world %#x' % (tag(level(m)), mode(), world(m) or 0))
doors, saves = targets(DOORS), targets(SAVES)
for d, e, n, p in doors[:4]:
    print('  door %-16s id %s at (%.1f, %.1f, %.1f) %.0f away, anchor (%.1f, %.1f, %.1f)'
          % (n, tag(u32(m, e + 4)), p[0], p[1], p[2], d, *anchor(e)))
for d, e, n, p in saves[:4]:
    print('  save %-16s id %s at (%.1f, %.1f, %.1f) %.0f away, anchor (%.1f, %.1f, %.1f)'
          % (n, tag(u32(m, e + 4)), p[0], p[1], p[2], d, *anchor(e)))

res = {}
if WHAT in ('door', 'both') and doors:
    room = scan_room(m, player_pos(m, 0), 400.0, verbose=False)
    if room['enemies']:
        print('REFUSED: live enemy in the start room')
    else:
        res['door'] = test(doors[0], 'door')
if WHAT in ('save', 'both') and saves:
    room = scan_room(m, player_pos(m, 0), 400.0, verbose=False)
    if room['enemies']:
        print('REFUSED: live enemy in the start room')
    else:
        res['save'] = test(saves[0], 'save point')
print('\nresult: %s' % res)
