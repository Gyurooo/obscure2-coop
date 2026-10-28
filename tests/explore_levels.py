"""TASK 20 step 3: visit the levels the game's own doors point to, one after another, and scan each.

Every (tag, entry) below was read LIVE from a door entity in a save slot (`entity+0x118` = destination
tag, `entity+4` = the entry id the door hands to `FUN_004a1c00`, flag constant 1) and added to
`obscoop_levels.txt`, so the mod's `level` command accepts exactly the call the door makes.

For each jump this prints: whether a new world came up, the level tag, entity count, both characters'
positions, every live item (`+0x20 != 0`, `+0xa8 == 0`, gates 0), every enemy (`CCharacter*` life > 0),
every spawner, and the room verdict (`tp_to_items.room_verdict`) around the player.

If the game dies at a jump the tool says so and stops (the runner still stops the copy).

Usage: python -I explore_levels.py <pid> [tag:entry ...]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe
from peek import Proc
from tp_to_items import (entities, level, player_pos, room_verdict, scan_room, tag, u32, world, ITEM_TAGS, pos_of)

GAME = 0x6c3068
DEFAULT = [('J000', 314), ('J001', 317), ('J003', 157), ('H001', 130), ('H002', 131), ('H003', 134),
           ('I005', 155), ('I005', 157), ('I008', 161), ('I010', 160), ('I012', 304)]


def mode(m):
    g = u32(m, m.va(GAME))
    return u32(m, g + 0x310) if g else 0


def main():
    pid = int(sys.argv[1])
    jumps = DEFAULT
    if len(sys.argv) > 2:
        jumps = []
        for a in sys.argv[2:]:
            t, e = a.split(':')
            jumps.append((t, int(e)))
    m, pipe = Proc(pid), Pipe(pid)
    print('start: level %s world %#x mode %s player 1 %s'
          % (tag(level(m)), world(m) or 0, mode(m), player_pos(m, 0)))
    rows = []
    for (want, entry) in jumps:
        lv0, w0 = tag(level(m)), world(m)
        print('\n===== jump level %s %d 1   (from %s)' % (want, entry, lv0))
        print('   -> %s' % pipe.cmd('level %s %d 1' % (want, entry)))
        t0 = time.time()
        ok = False
        why = 'no new world'
        while time.time() - t0 < 45:
            try:
                w = world(m)
                if not w or mode(m) is None:
                    why = 'game gone'
                    break
                if mode(m) == 1 and tag(level(m)) != lv0 and len(entities(m)) > 0:
                    ok = True
                    break
            except Exception as e:
                why = str(e)
                break
            time.sleep(1.0)
        if not ok:
            print('   FAILED: %s (mode %s level %s world %#x)' % (why, mode(m), tag(level(m)), world(m) or 0))
            rows.append((want, entry, 'FAILED ' + why, 0, 0, 0, None))
            break
        time.sleep(7.0)
        lv = tag(level(m))
        p1 = player_pos(m, 0)
        placed = bool(p1) and max(abs(v) for v in p1) > 1.0
        ents = entities(m)
        n_items = sum(1 for e in ents if u32(m, e + 0x10) in ITEM_TAGS)
        print('   new world in %.1f s: level %s, %d entities, %d item-class, player 1 %s (%s), player 2 %s'
              % (time.time() - t0, lv, len(ents), n_items, p1, 'PLACED' if placed else 'NOT PLACED',
                 player_pos(m, 1)))
        target = p1 if p1 else (0.0, 0.0, 0.0)
        room = scan_room(m, target, 1.0e9, verbose=False)
        for r in room['near_items']:
            print('   LIVE ITEM %s id %s at (%.2f, %.2f, %.2f)' % (r['cls'], r['id'], *r['pos']))
        for r in room['dead_items']:
            print('   item (not live) %s id %s p20=%d collected=%d gates %s at (%.2f, %.2f, %.2f)'
                  % (r['cls'], r['id'], r['active'], r['collected'], r['gates'], *r['pos']))
        for r in room['enemies']:
            print('   ENEMY %s life %d at (%.2f, %.2f, %.2f) %.0f away' % (r['rtti'], r['life'], *r['pos'], r['d']))
        for r in room['spawners']:
            print('   SPAWNER %s at (%.2f, %.2f, %.2f)' % (r['rtti'], *r['pos']))
        okv, whyv = room_verdict(room)
        print('   VERDICT around the player: %s (%s)' % ('VISITABLE' if okv else 'NO', whyv))
        rows.append((want, entry, lv, len(ents), len(room['near_items']), len(room['enemies']), p1))
    print('\n===== TABLE (level tag, entry, landed level, entities, live items, enemies, player 1)')
    for r in rows:
        print('   %-4s entry %-5s -> %-4s  ents %-4d live %-2d enemies %-2d  p1 %s' % r)
    print('DONE')


if __name__ == '__main__':
    main()
