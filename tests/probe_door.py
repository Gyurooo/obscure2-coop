"""TASK 18: is the game's own interaction scan running in a save-loaded world?

The character-side interaction target is `character+0x73c`: the entity the game's scan
(FUN_0044d6a0 / FUN_00450770, which require +0x20 != 0, +0xa8 == 0, gates +0xc0/+0xac/+0xb0 == 0 and a
distance <= the entity's +0xa0) has selected for the player. A door that is eligible by those fields but
never appears there would mean the scan itself does not run in these worlds.

This probe teleports (the mod's SAFE tp) next to the nearest door, then samples +0x73c every 40 ms while
pressing A, then presses A, X, B and Y once each and reports what happened (position, +0x73c, level tag).
No item is involved, so the item/enemy gate of tp_to_items does not apply.

Usage: python -I probe_door.py <pid>
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe, press
from peek import Proc
from tp_to_items import dist2d, entities, f32, level, player_human, player_pos, rtti, tag, u32, world

DOORS = ('CToeDoor', 'CToeDoubleDoor', 'CToeSpecialDoor', 'CToeInternalDoor', 'CToeFlapDoor')
TARGETS = ('CToeSavePoint', 'CToeSimpleSavePoint') if os.environ.get('PROBE_TARGET') == 'save' else DOORS

pid = int(sys.argv[1])
m, pipe = Proc(pid), Pipe(pid)


def target():
    h = player_human(m, 0)
    return u32(m, h + 0x73c) if h else 0


def show(label):
    h, p, t = player_human(m, 0), player_pos(m, 0), target()
    print('  %-22s level %s pos (%.2f, %.2f, %.2f) anim %s target +0x73c %#x %s'
          % (label, tag(level(m)), p[0], p[1], p[2], u32(m, h + 0x2dc), t, rtti(m, t) if t else ''))


p1 = player_pos(m, 0)
doors = []
for e in entities(m):
    name = rtti(m, e)
    if name in TARGETS:
        p = (f32(m, e + 0x6c), f32(m, e + 0x70), f32(m, e + 0x74))
        doors.append((dist2d(p, p1), e, name, p))
doors.sort()
print('level %s, %d entities, %d doors' % (tag(level(m)), len(entities(m)), len(doors)))
for d, e, name, p in doors:
    print('  door %-16s id %s at (%.1f, %.1f, %.1f), %.0f away: p20 %d coll %d gates (%d, %d, %d) radius %s'
          % (name, tag(u32(m, e + 4)), p[0], p[1], p[2], d, u32(m, e + 0x20), u32(m, e + 0xa8),
             u32(m, e + 0xc0), u32(m, e + 0xac), u32(m, e + 0xb0), f32(m, e + 0xa0)))
if not doors:
    sys.exit('no door in this level')
d, e, name, p = doors[0]
show('before the tp')
# stand 70 units in front of the door, on the line from the character
dx, dy = p[0] - p1[0], p[1] - p1[1]
n = (dx * dx + dy * dy) ** 0.5 or 1.0
gx, gy = p[0] - dx / n * 70.0, p[1] - dy / n * 70.0
r = pipe.cmd('tp 0 %.3f %.3f %.3f' % (gx, gy, p1[2]))
print('  tp -> %s' % r)
time.sleep(0.6)
show('next to the door')
print('  distance to the door: %.1f' % dist2d(player_pos(m, 0), p))

# A save point opens a menu, and a second A there could write a save: one press and a B to close.
buttons = ('A',) if os.environ.get('PROBE_TARGET') == 'save' else ('A', 'A', 'X', 'B', 'Y')
for btn in buttons:
    tgt_before = target()
    pipe.cmd('pad 0 0x%x' % {'A': 0x1000, 'X': 0x4000, 'B': 0x2000, 'Y': 0x8000}[btn])
    seen = []
    t0 = time.time()
    while time.time() - t0 < 0.6:
        t = target()
        if t and (not seen or seen[-1] != t):
            seen.append(t)
        time.sleep(0.04)
    pipe.cmd('pad 0 0')
    time.sleep(0.8)
    print('  pressed %s: +0x73c before %#x, seen during the press %s (%s), after %#x, pos (%.1f, %.1f, %.1f)'
          % (btn, tgt_before, [hex(t) for t in seen], [rtti(m, t) for t in seen], target(), *player_pos(m, 0)))
if os.environ.get('PROBE_TARGET') == 'save':
    g = u32(m, m.va(0x6c3068))
    print('  mode before closing with B: %s (1 = in game)' % (u32(m, g + 0x310) if g else None))
    press(pipe, 0, 'B', 0.3)
    time.sleep(1.2)
    print('  mode after B: %s' % (u32(m, g + 0x310) if g else None))
show('end')
