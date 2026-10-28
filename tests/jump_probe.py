"""TASK 20 step 3: trigger ONE level transition with the mod's `level` pipe command and scan the level
the game puts us in.

The command replays exactly the call the game's own door makes (`FUN_0042aa70`, decompile 24666-24710:
`FUN_004a1c00(entity+0x118, entity+4, 1)`) and only accepts a (tag, entry, flag) triple listed in
`obscoop_levels.txt` next to the DLL - i.e. one the game itself produced.

For the new world it prints:
  * the level tag, the entity count, both characters' positions and whether they were placed,
  * every item-class entity with the live test (`+0x20 != 0`, `+0xa8 == 0`, gates 0) and its distance,
  * every enemy (`CCharacter*` with life > 0) and every `CToeRespawn*` spawner in the level,
  * the level's doors with their own destination (`+0x118`, entry `+4`) so a chain can be followed.

Read-only apart from the requested transition.
Usage: python -I jump_probe.py <pid> <TAG> <entry> <flag> [wait seconds]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe
from peek import Proc
from tp_to_items import (entities, f32, level, player_pos, pos_of, rtti, scan_room, tag, u32, world)

GAME = 0x6c3068


def mode(pid_proc):
    g = u32(pid_proc, pid_proc.va(GAME))
    return u32(pid_proc, g + 0x310) if g else 0


def main():
    pid = int(sys.argv[1])
    want = sys.argv[2]
    entry = int(sys.argv[3])
    flag = int(sys.argv[4])
    limit = float(sys.argv[5]) if len(sys.argv) > 5 else 90.0
    m, pipe = Proc(pid), Pipe(pid)
    lv0, w0 = tag(level(m)), world(m)
    print('before: mode %s level %s world %#x entities %d player 1 %s'
          % (mode(m), lv0, w0 or 0, len(entities(m)), player_pos(m, 0)))
    print('level %s %d %d -> %s' % (want, entry, flag, pipe.cmd('level %s %d %d' % (want, entry, flag))))
    t0 = time.time()
    ok = False
    while time.time() - t0 < limit:
        try:
            if mode(m) == 1 and world(m) and tag(level(m)) != lv0 and len(entities(m)) > 0:
                ok = True
                break
        except Exception:
            pass
        time.sleep(1.0)
    if not ok:
        print('NO new world after %.1f s: mode %s level %s world %#x'
              % (time.time() - t0, mode(m), tag(level(m)), world(m) or 0))
        sys.exit(1)
    print('new world after %.1f s: level %s world %#x entities %d'
          % (time.time() - t0, tag(level(m)), world(m) or 0, len(entities(m))))
    time.sleep(8.0)   # let the level build its entities and place the characters
    p1 = player_pos(m, 0)
    print('player 1 %s  player 2 %s  mode %s' % (p1, player_pos(m, 1), mode(m)))
    if not p1:
        print('no character after the transition')
        sys.exit(1)
    room = scan_room(m, p1, 1.0e9, verbose=True)   # whole level, radius huge
    print('\n-- level rows')
    for e in entities(m):
        name = rtti(m, e)
        cls = tag(u32(m, e + 0x10))
        p = pos_of(m, e)
        print('   %-24s cls %-4s id %-5s +0x24 %d +0xb8 %d pos (%.1f, %.1f, %.1f) %s'
              % (name, cls, tag(u32(m, e + 4)), u32(m, e + 0x24), u32(m, e + 0xb8), p[0], p[1], p[2],
                 ('-> ' + tag(u32(m, e + 0x118)) + ' entry %d flag 1' % u32(m, e + 4))
                 if u32(m, e + 0x118) and rtti(m, e).startswith('CToe') and
                 (rtti(m, e) in ('CToeDoor', 'CToeDoubleDoor', 'CToeSpecialDoor', 'CToeInternalDoor'))
                 else ''))
    print('\nSUMMARY level %s entities %d live-items %d near-items %d enemies %d spawners %d'
          % (room['level'], room['entities'], room['live_total'], len(room['near_items']),
             len(room['enemies']), len(room['spawners'])))
    sys.exit(0 if (room['live_total'] and not room['enemies']) else 3)


if __name__ == '__main__':
    main()
