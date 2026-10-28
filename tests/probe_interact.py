"""TASK 19: what stops a door / save point from being used after a save load?

FINDINGS_18 s5 measured `character+0x73c` (the interaction scan's *collect* target) at a door and a save
point and found it 0 - but the scan in FUN_004cf940 (decompile 128214-128245) writes +0x73c only for an
entity whose vtable+0x20 ("collectable") is non-zero. Doors and save points are used through
vtable+0x70 instead, so +0x73c staying 0 at a door says nothing. This probe therefore

  * dumps the state the scan depends on: the controller (world+0x1748 + 0x764*pl) fields
    +0x04 (character) / +0x14 / +0x50 / +0xa4 (the `in_ECX[0x29]` gate of the scan) / +0x758
    (the `in_ECX[0x1d6]` early return), the character fields (+0x2dc anim, +0x320 life, +0x278,
    +0x2bc the object whose vtable+0xa8 gates the scan, +0x73c, +0x880/+0x884), and the *addresses*
    of the character's and the door's vtable slots so they can be looked up in
    Obscure2.exe.functions.tsv;
  * teleports next to the nearest eligible door (same room: the start room is scanned first and the
    probe refuses if it has a live enemy) and presses A, then watches mode/level/world/position for a
    transition;
  * then does the same at the nearest CToeSavePoint, where a successful use opens the save menu.

Usage: python -I probe_interact.py <pid> [door|save|both]
No memory is written: the only changes are the mod's own safe `tp` and the virtual pad.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe, press
from peek import Proc
from tp_to_items import (dist2d, entities, f32, level, player_human, player_pos, rtti, scan_room, tag, u32,
                         world)

GAME = 0x6c3068
DOORS = ('CToeDoor', 'CToeDoubleDoor', 'CToeSpecialDoor', 'CToeInternalDoor', 'CToeFlapDoor')
SAVES = ('CToeSavePoint', 'CToeSimpleSavePoint')
WHAT = sys.argv[2] if len(sys.argv) > 2 else 'both'

pid = int(sys.argv[1])
m, pipe = Proc(pid), Pipe(pid)


def mode():
    g = u32(m, m.va(GAME))
    return u32(m, g + 0x310) if g else 0


def vt_dump(label, vt, slots):
    print('  %s vtable %#x: %s' % (label, vt, ' '.join('+%#04x->%#010x' % (s, u32(m, vt + s)) for s in slots)))


def dump(label):
    w = world(m)
    ctl = u32(m, w + 0x1748) if w else 0
    print('\n-- %s: level %s mode %s world %#x ctl %#x' % (label, tag(level(m)), mode(), w or 0, ctl))
    for pl in (0, 1):
        base = ctl + 0x764 * pl if ctl else 0
        h = u32(m, base + 4) if base else 0
        if not h:
            print('   player %d: no character (%#x)' % (pl, base))
            continue
        vt = u32(m, h)
        print('   player %d char %#x tag %s vt %#x' % (pl, h, tag(u32(m, h + 0x14)), vt))
        print('     char: anim+0x2dc %d life+0x320 %.1f +0x278 %#x +0x2bc %#x +0x73c %#x +0x880 %#x +0x884 %#x'
              % (u32(m, h + 0x2dc), f32(m, h + 0x320), u32(m, h + 0x278), u32(m, h + 0x2bc),
                 u32(m, h + 0x73c), u32(m, h + 0x880), u32(m, h + 0x884)))
        if pl == 0:
            vt_dump('char', vt, (0x1c, 0x20, 0x34, 0x44, 0x48, 0x70, 0x90, 0xa8, 0xb8))
        ctlv = u32(m, base + 0x2bc) if base else 0
        print('     ctl +0x04 %#x +0x14 %d +0x50 %#x +0xa4 %d +0x758 %d' %
              (u32(m, base + 4), u32(m, base + 0x14), u32(m, base + 0x50),
               u32(m, base + 0xa4), u32(m, base + 0x758)))
        if pl == 0 and ctlv:
            print('     ctl +0x2bc -> %#x' % ctlv)


def targets(names):
    p1 = player_pos(m, 0)
    out = []
    for e in entities(m):
        name = rtti(m, e)
        if name in names:
            p = (f32(m, e + 0x6c), f32(m, e + 0x70), f32(m, e + 0x74))
            out.append((dist2d(p, p1), e, name, p))
    out.sort()
    return [(d, e, n, p, d) for d, e, n, p in out]


def show_entity(e, name):
    print('   %-18s id %s at (%.1f, %.1f, %.1f): p20 %d coll %d gates (%d, %d, %d) radius %s'
          % (name, tag(u32(m, e + 4)), f32(m, e + 0x6c), f32(m, e + 0x70), f32(m, e + 0x74),
             u32(m, e + 0x20), u32(m, e + 0xa8), u32(m, e + 0xc0), u32(m, e + 0xac), u32(m, e + 0xb0),
             f32(m, e + 0xa0)))
    vt = u32(m, e)
    vt_dump('  its', vt, (0x1c, 0x20, 0x34, 0x38, 0x70))


def go_and_use(rec, label, buttons=('A',), tries=3, wait=6.0):
    d, e, name, p, _ = rec
    show_entity(e, name)
    p1 = player_pos(m, 0)
    room = scan_room(m, p1, 400.0, verbose=False)
    print('   start room before the tp: live items %d near, enemies %d, spawners %d'
          % (len(room['near_items']), len(room['enemies']), len(room['spawners'])))
    if room['enemies']:
        print('   REFUSED: the start room has a live enemy; not teleporting (%s)' % label)
        return None
    dx, dy = p[0] - p1[0], p[1] - p1[1]
    n = (dx * dx + dy * dy) ** 0.5 or 1.0
    gx, gy = p[0] - dx / n * 70.0, p[1] - dy / n * 70.0
    r = pipe.cmd('tp 0 %.3f %.3f %.3f' % (gx, gy, p1[2]))
    print('   tp -> %s' % r)
    time.sleep(0.8)
    q = player_pos(m, 0)
    print('   now at (%.2f, %.2f, %.2f), %.1f from the %s' % (q[0], q[1], q[2], dist2d(q, p), name))
    dump('next to the %s' % name)
    old = (level(m), world(m), q)
    for i in range(tries):
        for b in buttons:
            print('   press %s (%d/%d)' % (b, i + 1, tries))
            press(pipe, 0, b, 0.45)
            t0 = time.time()
            while time.time() - t0 < wait:
                lv, w2, q2 = level(m), world(m), player_pos(m, 0)
                if lv != old[0] or w2 != old[1]:
                    print('   *** TRANSITION after %s: level %s world %#x' % (b, tag(lv), w2 or 0))
                    return 'transition'
                if q2 and old[2] and dist2d(q2, old[2]) > 300.0:
                    print('   *** MOVED %.0f units after %s (level %s)' % (dist2d(q2, old[2]), b, tag(lv)))
                    return 'moved'
                time.sleep(0.25)
            print('   nothing: level %s mode %s pos (%.1f, %.1f, %.1f) +0x73c %#x'
                  % (tag(level(m)), mode(), *player_pos(m, 0), u32(m, player_human(m, 0) + 0x73c)))
            old = (level(m), world(m), player_pos(m, 0))
    return None


print('probe_interact: pid %d, what %s' % (pid, WHAT))
dump('at the start')
doors, saves = targets(DOORS), targets(SAVES)
print('\n%d door(s), %d save point(s) in this level' % (len(doors), len(saves)))
for d, e, n, p, _ in doors:
    print('  door %-16s id %s at (%.1f, %.1f, %.1f) %.0f away' % (n, tag(u32(m, e + 4)), p[0], p[1], p[2], d))
for d, e, n, p, _ in saves:
    print('  save %-16s id %s at (%.1f, %.1f, %.1f) %.0f away' % (n, tag(u32(m, e + 4)), p[0], p[1], p[2], d))

res = {}
if WHAT in ('door', 'both') and doors:
    print('\n== door test')
    res['door'] = go_and_use(doors[0], 'door')
if WHAT in ('save', 'both') and saves:
    print('\n== save point test')
    res['save'] = go_and_use(saves[0], 'save point', buttons=('A',))
dump('at the end')
print('\nresult: %s' % res)
