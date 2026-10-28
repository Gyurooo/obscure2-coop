"""TASK 19: the door interaction in the PAIR flow, plus a side-by-side state dump of both copies.

The question this answers: the game's interaction scan `FUN_004cf940` (0x4cf940) selects a door through
its vtable+0x34 and then uses it with vtable+0x70; that scan is gated by
    controller+0xa4 in {0,1} AND character->vtable+0x90(2) != 0
(`FUN_004dca40`), plus a per-entity score from the door's own `FUN_0042a480` (distance <= 80 and
dot(character+0x248.., door+0x13c..) >= 0.5). Solo slot 01 runs showed every one of those door/entity
conditions satisfied while A did nothing, so this check dumps the character and controller state on
BOTH copies of a working pair flow (where the mod's own pickup check does collect a world item) and
runs the same face-and-press-A sweep on the host's player 1.

Usage: python -I check_door_pair.py <host pid> <guest pid>
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
STICK = (('up', 0, 30000), ('up-right', 21000, 21000), ('right', 30000, 0), ('down-right', 21000, -21000),
         ('down', 0, -30000), ('down-left', -21000, -21000), ('left', -30000, 0), ('up-left', -21000, 21000))

hp, gp = int(sys.argv[1]), int(sys.argv[2])
H, G = Proc(hp), Proc(gp)
hpipe, gpipe = Pipe(hp), Pipe(gp)


def mode(m):
    g = u32(m, m.va(GAME))
    return u32(m, g + 0x310) if g else 0


def dump(m, who):
    w = world(m)
    ctl = u32(m, w + 0x1748) if w else 0
    print('  [%s] level %s mode %s world %#x ctl %#x' % (who, tag(level(m)), mode(m), w or 0, ctl))
    for pl in (0, 1):
        base = ctl + 0x764 * pl if ctl else 0
        h = u32(m, base + 4) if base else 0
        if not h:
            print('    player %d: no character' % pl)
            continue
        vt = u32(m, h)
        print('    player %d char %#x tag %s vt %#x anim %d life %.1f +0x73c %#x +0x2bc %#x'
              % (pl, h, tag(u32(m, h + 0x14)), vt, u32(m, h + 0x2dc), f32(m, h + 0x320),
                 u32(m, h + 0x73c), u32(m, h + 0x2bc)))
        print('      dwords 0x220..0x2e0: %s' % ' '.join('%#x' % u32(m, h + o) for o in range(0x220, 0x2e4, 4)))
        print('      dwords 0x860..0x890: %s' % ' '.join('%#x' % u32(m, h + o) for o in range(0x860, 0x894, 4)))
        print('      ctl  0x00..0x60: %s' % ' '.join('%#x' % u32(m, base + o) for o in range(0x0, 0x64, 4)))
        print('      ctl  0x90..0xc0 + 0x2b0..0x2d0 + 0x750..0x764: %s | %s | %s'
              % (' '.join('%#x' % u32(m, base + o) for o in range(0x90, 0xc4, 4)),
                 ' '.join('%#x' % u32(m, base + o) for o in range(0x2b0, 0x2d4, 4)),
                 ' '.join('%#x' % u32(m, base + o) for o in range(0x750, 0x768, 4))))
        print('      char 0x248..0x250 (forward): %.3f %.3f %.3f' % (f32(m, h + 0x248), f32(m, h + 0x24c), f32(m, h + 0x250)))


def fwd(m):
    h = player_human(m, 0)
    return (f32(m, h + 0x248), f32(m, h + 0x24c), f32(m, h + 0x250)) if h else (0.0, 0.0, 0.0)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def unit(a):
    n = math.sqrt(sum(v * v for v in a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


print('check_door_pair: host %d guest %d' % (hp, gp))
for _ in range(60):
    if world(H) and world(G):
        break
    time.sleep(1.0)
print('\n== state of both copies in the pair flow (the flow where the mod\'s pickup check collects an item)')
dump(H, 'host')
dump(G, 'guest')

# --- the door, on the host's player 1 -------------------------------------------------------------
doors = []
p1 = player_pos(H, 0)
for e in entities(H):
    if rtti(H, e) in DOORS:
        p = (f32(H, e + 0x6c), f32(H, e + 0x70), f32(H, e + 0x74))
        doors.append((dist2d(p, p1), e, rtti(H, e), p))
doors.sort()
print('\n== %d door(s) in %s; nearest at %s' % (len(doors), tag(level(H)), doors[0][3] if doors else '-'))
res = None
if doors:
    d, e, name, p = doors[0]
    room = scan_room(H, p1, 400.0, verbose=False)
    print('   start room: live items %d, enemies %d, spawners %d'
          % (len(room['near_items']), len(room['enemies']), len(room['spawners'])))
    if room['enemies']:
        print('   REFUSED: live enemy in the start room, no teleport')
    else:
        print('   door %s id %s at (%.1f, %.1f, %.1f): +0x24 %#x +0xb8 %#x +0x10c..0x114 (%.1f, %.1f, %.1f) +0x13c..0x144 (%.3f, %.3f, %.3f)'
              % (name, tag(u32(H, e + 4)), p[0], p[1], p[2], u32(H, e + 0x24), u32(H, e + 0xb8),
                 f32(H, e + 0x10c), f32(H, e + 0x110), f32(H, e + 0x114),
                 f32(H, e + 0x13c), f32(H, e + 0x140), f32(H, e + 0x144)))
        c = player_pos(H, 0)
        fromx, fromy = c[0] - p[0], c[1] - p[1]
        n = (fromx * fromx + fromy * fromy) ** 0.5 or 1.0
        gx, gy = p[0] + fromx / n * 55.0, p[1] + fromy / n * 55.0
        print('   tp -> %s' % hpipe.cmd('tp 0 %.3f %.3f %.3f' % (gx, gy, p[2] - 0.5)))
        time.sleep(0.8)
        for sname, lx, ly in STICK:
            hpipe.cmd('pad 0 0 %d %d' % (lx, ly))
            time.sleep(0.35)
            hpipe.cmd('pad 0 0')
            time.sleep(0.15)
            c = player_pos(H, 0)
            u = unit((p[0] - c[0], p[1] - c[1], p[2] - c[2]))
            f = fwd(H)
            ed = (f32(H, e + 0x13c), f32(H, e + 0x140), f32(H, e + 0x144))
            print('   %-10s d2 %6.1f d3 %6.1f dot(char->door, fwd) %+.3f dot(fwd, doordir) %+.3f pos (%s)'
                  % (sname, dist2d(c, p), dist3(c, p), dot(u, f), dot(f, ed), ', '.join('%.1f' % v for v in c)))
            lv0, w0 = level(H), world(H)
            press(hpipe, 0, 'A', 0.45)
            t0 = time.time()
            while time.time() - t0 < 2.0:
                if level(H) != lv0 or world(H) != w0:
                    print('   *** TRANSITION on stick %s -> level %s world %#x' % (sname, tag(level(H)), world(H) or 0))
                    res = 'transition'
                    break
                time.sleep(0.2)
            if res:
                break
        print('   door result: %s' % res)

print('\n== guest after the host\'s door sweep')
dump(G, 'guest')
print('\nRESULT door-in-pair-flow: %s' % res)
