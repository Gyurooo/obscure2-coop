"""TASK 20: survey the remaining door destinations for a level that has BOTH a live collectable and a
save point (and no enemy near it), so the pickup can be saved with the game's own save point.

Every target is a live door destination read in `scan_transitions.py`; the mod's `level` command
replays the exact call the door makes. For each level it prints: entities, live items, enemies,
spawners, save points with the fields their own check reads (`+0x24`, `+0xb8`, `+0x150`, `+0x14`,
position), doors with their own destination, and the distance from each save point to the nearest
live item and nearest enemy.

Usage: python -I survey_levels.py <pid> [TAG:entry ...]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe
from peek import Proc
from tp_to_items import (ITEM_TAGS, dist3, entities, f32, level, player_pos, pos_of, rtti, tag, u32, world)

GAME = 0x6c3068
DEFAULT = [('J000', 314), ('I008', 161), ('I010', 160), ('I012', 304), ('I010', 300)]
SAVES = ('CToeSavePoint', 'CToeSimpleSavePoint')
DOORS = ('CToeDoor', 'CToeDoubleDoor', 'CToeSpecialDoor', 'CToeInternalDoor', 'CToeFlapDoor')


def mode(m):
    g = u32(m, m.va(GAME))
    return u32(m, g + 0x310) if g else 0


def survey(m, pipe, want, entry):
    print('\n===== level %s %d 1' % (want, entry))
    print('   -> %s' % pipe.cmd('level %s %d 1' % (want, entry)))
    lv0 = tag(level(m))
    t0 = time.time()
    while time.time() - t0 < 45:
        try:
            w = world(m)
            if not w or mode(m) is None:
                print('   game gone')
                return None
            if mode(m) == 1 and tag(level(m)) == want and len(entities(m)) > 0:
                break
        except Exception:
            pass
        time.sleep(1.0)
    else:
        print('   level did not come up (still %s)' % tag(level(m)))
        return None
    time.sleep(7.0)
    lv = tag(level(m))
    p1 = player_pos(m, 0)
    ents = entities(m)
    items, enemies, spawners, saves, doors = [], [], [], [], []
    for e in ents:
        name = rtti(m, e)
        clsint = u32(m, e + 0x10)
        p = pos_of(m, e)
        if clsint in ITEM_TAGS and u32(m, e + 0xa8) == 0 and u32(m, e + 0x20) != 0:
            items.append((e, tag(clsint), p))
        if name.startswith('CCharacter') and u32(m, e + 0x320):
            enemies.append((e, name, p))
        if name.startswith('CToeRespawn'):
            spawners.append((e, name, p))
        if name in SAVES:
            saves.append((e, name, p, u32(m, e + 0x24), u32(m, e + 0xb8), u32(m, e + 0x150), u32(m, e + 0x14)))
        if name in DOORS:
            doors.append((e, name, tag(u32(m, e + 4)), p, tag(u32(m, e + 0x118))))
    print('   level %s: %d entities, player 1 %s, live items %d, enemies %d, spawners %d, save points %d'
          % (lv, len(ents), p1, len(items), len(enemies), len(spawners), len(saves)))
    for e, cls, p in items:
        print('     LIVE %s at (%.1f, %.1f, %.1f)' % (cls, *p))
    for e, name, p in enemies:
        print('     ENEMY %s at (%.1f, %.1f, %.1f)' % (name, *p))
    for e, name, p in spawners:
        print('     SPAWNER %s at (%.1f, %.1f, %.1f)' % (name, *p))
    for e, name, p, g24, gb8, g150, g14 in saves:
        di = min([dist3(p, ip) for _, _, ip in items], default=None)
        de = min([dist3(p, ep) for _, _, ep in enemies], default=None)
        print('     SAVE POINT %s id %s at (%.1f, %.1f, %.1f) +0x24 %d +0xb8 %d +0x150 %d +0x14 %d | '
              'nearest live item %s, nearest enemy %s'
              % (name, tag(u32(m, e + 4)), p[0], p[1], p[2], g24, gb8, g150, g14,
                 ('%.0f' % di) if di is not None else '-', ('%.0f' % de) if de is not None else '-'))
    for e, name, idt, p, tgt in doors:
        print('     DOOR %s id %s at (%.1f, %.1f, %.1f) -> %s' % (name, idt, *p, tgt))
    return dict(level=lv, items=len(items), enemies=len(enemies), spawners=len(spawners), saves=len(saves))


def main():
    pid = int(sys.argv[1])
    targets = DEFAULT
    if len(sys.argv) > 2:
        targets = []
        for a in sys.argv[2:]:
            t, e = a.split(':')
            targets.append((t, int(e)))
    m, pipe = Proc(pid), Pipe(pid)
    print('start: level %s player 1 %s' % (tag(level(m)), player_pos(m, 0)))
    rows = []
    for want, entry in targets:
        r = survey(m, pipe, want, entry)
        if r is None:
            break
        rows.append((want, entry, r))
    print('\n===== TABLE')
    for want, entry, r in rows:
        print('   %-4s entry %-5d -> %-4s items %-2d enemies %-2d spawners %-2d save-points %d'
              % (want, entry, r['level'], r['items'], r['enemies'], r['spawners'], r['saves']))
    print('DONE')


if __name__ == '__main__':
    main()
