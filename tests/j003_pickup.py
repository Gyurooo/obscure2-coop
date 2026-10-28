"""TASK 20: jump to the level with live items and no enemies (J003), inspect it, and pick an item up
in the game's own flow (safe teleport through the item/enemy gate, then the pad's A press).

Level selection (OBSERVED, run_e1.log): the door destination `J003 157 1` (read live from the J005
double door, `entity+0x118` = J003, entry = `entity+4` = 157, flag 1) loads J003 with the character
PLACED, **2 live collectable items and no enemy and no spawner in the whole level**.

Steps per live item, nearest first:
  * `tp_to_items.gate_teleport` - the owner's rule: scan the target room, refuse unless >= 1 live item
    and no enemy, then the mod's SAFE tp and a 3 s stand-still proof;
  * read the item's own gate fields and `character+0x73c`, press A (the game's own interaction scan
    then collect + animation), and watch `item+0xa8` (collected) and `item+0xc4` (user character);
  * print the inventory count (world+0x1790, count +4) before and after.

Usage: python -I j003_pickup.py <pid>
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe, press
from peek import Proc
from tp_to_items import (ITEM_TAGS, dist3, entities, f32, gate_teleport, level, player_human, player_pos,
                         pos_of, room_verdict, rtti, scan_room, tag, u32, world)

GAME = 0x6c3068
WANT = ('J003', 157)


def mode(m):
    g = u32(m, m.va(GAME))
    return u32(m, g + 0x310) if g else 0


def inv_count(m):
    w = world(m)
    inv = u32(m, w + 0x1790) if w else 0
    return (u32(m, inv + 4), inv) if inv else (None, 0)


def wait_world(m, lv0, limit=45.0):
    t0 = time.time()
    while time.time() - t0 < limit:
        try:
            if mode(m) == 1 and world(m) and tag(level(m)) != lv0 and len(entities(m)) > 0:
                time.sleep(7.0)
                return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


def main():
    pid = int(sys.argv[1])
    m, pipe = Proc(pid), Pipe(pid)
    print('start: level %s mode %s player 1 %s' % (tag(level(m)), mode(m), player_pos(m, 0)))
    print('\n== jump %s %d 1 -> %s' % (WANT[0], WANT[1], pipe.cmd('level %s %d 1' % WANT)))
    if not wait_world(m, tag(level(m))):
        print('the level did not come up')
        sys.exit(1)
    lv = tag(level(m))
    p1 = player_pos(m, 0)
    print('level %s, %d entities, player 1 %s' % (lv, len(entities(m)), p1))
    if lv != 'J003':
        print('landed in %s, not J003' % lv)
        sys.exit(1)

    print('\n== level entities')
    live = []
    for e in entities(m):
        name = rtti(m, e)
        clsint = u32(m, e + 0x10)
        cls = tag(clsint)
        p = pos_of(m, e)
        print('   %-24s cls %-4s id %s %10d pos (%9.2f, %9.2f, %8.2f) +0x20 %d +0x24 %d +0xa8 %d +0xa0 %.1f'
              % (name, cls, tag(u32(m, e + 4)), u32(m, e + 4), p[0], p[1], p[2],
                 u32(m, e + 0x20), u32(m, e + 0x24), u32(m, e + 0xa8), f32(m, e + 0xa0)))
        if clsint in ITEM_TAGS and u32(m, e + 0xa8) == 0 and u32(m, e + 0x20) != 0:
            live.append((dist3(p, p1), e, cls, p))
    live.sort()
    print('\nlive items: %d -> %s' % (len(live), ', '.join('%s %.0f away' % (c, d) for d, e, c, p in live)))
    if not live:
        print('no live item in this level')
        sys.exit(3)

    inv0, invobj = inv_count(m)
    print('inventory before: count %s (world+0x1790 = %#x)' % (inv0, invobj))

    for (d, e, cls, p) in live:
        print('\n== item %s at (%.2f, %.2f, %.2f), %.0f from the player' % (cls, p[0], p[1], p[2], d))
        room = scan_room(m, p, 400.0, verbose=True)
        allowed, why = room_verdict(room)
        print('   gate: %s (%s)' % ('ALLOW' if allowed else 'REFUSE', why))
        if not allowed:
            continue
        res = gate_teleport(pid, 0, p[0], p[1], p[2], radius=400.0, verbose=True, pipe=pipe, m=m)
        if not res['ok']:
            print('   safe tp with z refused (%s); retry without z' % res['why'])
            res = gate_teleport(pid, 0, p[0], p[1], None, radius=400.0, verbose=True, pipe=pipe, m=m)
        if not res['ok']:
            print('   could not stand at the item: %s' % res['why'])
            continue
        c = player_pos(m, 0)
        h = player_human(m, 0)
        print('   player 1 at %s, %.1f from the item; char %#x; +0x73c %#x'
              % (c, dist3(c, p), h or 0, u32(m, h + 0x73c) if h else 0))
        for attempt in (1, 2, 3):
            press(pipe, 0, 'A', 0.45)
            time.sleep(1.2)
            coll, user = u32(m, e + 0xa8), u32(m, e + 0xc4)
            print('   A press %d: item +0xa8 %d +0xc4 %#x (char %#x) +0x20 %d'
                  % (attempt, coll, user, h or 0, u32(m, e + 0x20)))
            if coll:
                break
        if u32(m, e + 0xa8):
            inv1, _ = inv_count(m)
            print('   *** PICKED UP %s: inventory %s -> %s' % (cls, inv0, inv1))
            print('DONE picked up %s in %s with the real flow' % (cls, lv))
            sys.exit(0)
        print('   not collected after 3 A presses')
    print('\nno item was collected')
    sys.exit(2)


if __name__ == '__main__':
    main()
