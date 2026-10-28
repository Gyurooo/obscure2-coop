"""TASK 19: does the door / save point interaction work in ANY save-loaded level?

One host copy, all ten save slots, in one game launch. For each slot:

  * `loadsave gameN.sav` (the mod's replay of the menu's Load) and wait until the level has placed the
    characters;
  * print every door and save point with the fields their own eligibility check reads:
    `+0x24` (must be non-zero), `+0xb8` (must be 0), `+0x14`, `+0x150`, the door's interaction anchor
    `+0x10c..+0x114` (what `FUN_0042a480` measures the 80-unit distance to) and its direction
    `+0x13c..+0x144` (the facing dot product);
  * put the character 40 units from that anchor **facing it exactly** (`tp` takes `dx dy`) and press A.
    The observable is the entity's own "user" field **+0xc4**, which the door's use `FUN_0042c2b0`
    (decompile 25527) and the save point's use `FUN_0046e830` (64928) write with the character pointer.
    A door use need not change the level, so level/world/position watching (what probe_face.py,
    probe_use.py and play_forward.try_door did) cannot see it;
  * if the first side does not work, try the opposite side of the same anchor.

Usage: python -I probe_slots19.py <pid> [first slot] [last slot]
Writes nothing but the mod's safe `tp` and the virtual pad.
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

pid = int(sys.argv[1])
FIRST = int(sys.argv[2]) if len(sys.argv) > 2 else 0
LAST = int(sys.argv[3]) if len(sys.argv) > 3 else 9
m, pipe = Proc(pid), Pipe(pid)


def mode():
    g = u32(m, m.va(GAME))
    return u32(m, g + 0x310) if g else 0


def fwd(pl=0):
    h = player_human(m, pl)
    return (f32(m, h + 0x248), f32(m, h + 0x24c), f32(m, h + 0x250)) if h else (0.0, 0.0, 0.0)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def unit(a):
    n = math.sqrt(sum(v * v for v in a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def wait_placed(limit=30.0):
    t0 = time.time()
    while time.time() - t0 < limit:
        p = player_pos(m, 0)
        if mode() == 1 and p and all(abs(v) < 50000 for v in p) and max(abs(v) for v in p) > 1.0:
            time.sleep(2.0)
            return True
        time.sleep(1.0)
    return False


def load(slot, limit=60.0):
    lv0, w0 = tag(level(m)), world(m)
    print('\n---- slot %d: loadsave game%d.sav -> %s' % (slot + 1, slot, pipe.cmd('loadsave game%d.sav' % slot)))
    t0 = time.time()
    while time.time() - t0 < limit:
        if mode() == 1 and world(m) and len(entities(m)) > 0 and (tag(level(m)) != lv0 or world(m) != w0):
            break
        time.sleep(1.0)
    return wait_placed()


def records(names):
    p1 = player_pos(m, 0)
    out = []
    for e in entities(m):
        name = rtti(m, e)
        if name in names:
            p = (f32(m, e + 0x6c), f32(m, e + 0x70), f32(m, e + 0x74))
            out.append((dist2d(p, p1), e, name, p))
    out.sort()
    return out


def place_and_use(e, a, label, stand=40.0, flip=False):
    """Stand `stand` units from `a` on the side the character is already on, facing `a` exactly
    (`tp 0 x y z dx dy` writes character+0x248/+0x24c), then press A once and read entity+0xc4."""
    c = player_pos(m, 0)
    vx, vy = c[0] - a[0], c[1] - a[1]
    n = (vx * vx + vy * vy) ** 0.5 or 1.0
    if flip:
        vx, vy = -vx, -vy
    gx, gy = a[0] + vx / n * stand, a[1] + vy / n * stand
    dx, dy = (a[0] - gx) / stand, (a[1] - gy) / stand
    r = pipe.cmd('tp 0 %.3f %.3f %.3f %.4f %.4f' % (gx, gy, a[2] + 0.4, dx, dy))
    if not r.startswith('ok'):
        r = pipe.cmd('tp 0 %.3f %.3f %.4f %.4f' % (gx, gy, dx, dy))
    time.sleep(0.8)
    c = player_pos(m, 0)
    u = unit((a[0] - c[0], a[1] - c[1], a[2] - c[2]))
    f = fwd()
    h = player_human(m, 0)
    print('   %s: tp %s -> pos (%.1f, %.1f, %.1f), %.1f from the anchor, dot(char->anchor, fwd) %+.3f'
          % (label, 'ok' if r.startswith('ok') else r, c[0], c[1], c[2], dist2d(c, a), dot(u, f)))
    for btn in ('A', 'A'):
        press(pipe, 0, btn, 0.45)
        time.sleep(0.7)
        user = u32(m, e + 0xc4)
        if user and user == h:
            print('   *** %s USED (entity+0xc4 = the character %#x)' % (label.upper(), user))
            return 'USED'
    print('   %s not used: +0xc4 %#x (character %#x) +0x154 %d'
          % (label, u32(m, e + 0xc4), h or 0, u32(m, e + 0x154)))
    return 'no'


def use_test(rec, label, anchor_off, dir_off):
    d, e, name, p = rec
    a = (f32(m, e + anchor_off), f32(m, e + anchor_off + 4), f32(m, e + anchor_off + 8))
    if max(abs(v) for v in a) < 0.01:
        a = p
    ed = (f32(m, e + dir_off), f32(m, e + dir_off + 4), f32(m, e + dir_off + 8))
    print('   %s %s id %s pos (%.1f, %.1f, %.1f) anchor (%.1f, %.1f, %.1f) +0x24 %#x +0xb8 %#x +0x14 %d +0x150 %#x dir (%.2f, %.2f, %.2f)'
          % (label, name, tag(u32(m, e + 4)), p[0], p[1], p[2], a[0], a[1], a[2],
             u32(m, e + 0x24), u32(m, e + 0xb8), u32(m, e + 0x14), u32(m, e + 0x150), ed[0], ed[1], ed[2]))
    r = place_and_use(e, a, label + ' side 1')
    if r == 'USED':
        return r
    return place_and_use(e, a, label + ' side 2', flip=True)


print('probe_slots19: pid %d, slots %d..%d' % (pid, FIRST + 1, LAST + 1))
print('start: mode %s level %s world %#x' % (mode(), tag(level(m)), world(m) or 0))
rows = []
for slot in range(FIRST, LAST + 1):
    if slot == FIRST and world(m) and mode() == 1 and len(entities(m)) > 0:
        print('\n---- slot %d: already loaded by the runner (level %s)' % (slot + 1, tag(level(m))))
        ok = wait_placed()
    else:
        ok = load(slot)
    if not ok:
        print('   slot %d did not get ready' % (slot + 1))
        rows.append((slot + 1, '?', 'not ready', '', '-'))
        continue
    lv = tag(level(m))
    doors, saves = records(DOORS), records(SAVES)
    room = scan_room(m, player_pos(m, 0), 400.0, verbose=False)
    print('   level %s: %d entities, %d doors, %d save points | near the player: live items %d, enemies %d, spawners %d'
          % (lv, len(entities(m)), len(doors), len(saves), len(room['near_items']), len(room['enemies']),
             len(room['spawners'])))
    for r in room['near_items']:
        print('     LIVE ITEM %s id %s at (%.1f, %.1f, %.1f) %.0f away' % (r['cls'], r['id'], *r['pos'], r['d2']))
    for r in room['enemies']:
        print('     ENEMY %s life %d at (%.1f, %.1f, %.1f) %.0f away' % (r['rtti'], r['life'], *r['pos'], r['d']))
    dres = sres = '-'
    if room['enemies']:
        print('   live enemy within 400 units of the player: no teleport in this level')
    else:
        if doors:
            print('   -- door test')
            dres = use_test(doors[0], 'door', 0x10c, 0x13c)
        if saves:
            print('   -- save point test')
            sres = use_test(saves[0], 'save', 0x6c, 0x13c)
    rows.append((slot + 1, lv, dres, sres, '%d/%d/%d' % (len(room['near_items']), len(room['enemies']),
                                                         len(room['spawners']))))

print('\n== summary (slot, level, door, save point, live items/enemies/spawners near the player)')
for r in rows:
    print('   %2d  %-4s  door %-9s  save %-9s  %s' % r)
