"""TASK 17 Part B, live: show that the item/enemy gate really decides before a teleport.

The gate itself is `tests/tp_to_items.py` (scan_room + room_verdict + gate_teleport). This check runs it
on four places in the loaded slot and prints each verdict, so the log shows the rule working in both
directions:

  1. the player's start          - whatever the room really has
  2. the nearest item entity     - as the save left it (in every slot: inactive, +0x20 == 0) -> SKIP
  3. the same item, forced live  - `wr item+0x20 = 1`, the same test-only write TASK 15/16 used, so there
                                   IS a live collectable; the gate must ALLOW unless an enemy is near
  4. a point 3000 units away     - no item there -> SKIP

Case 3 is the only memory write, it is printed, and it exists so the gate can be shown allowing a
teleport as well as refusing one. Nothing is written when --no-force is given.

Usage: python -I check_gate.py <pid> [--radius N] [--no-force]
Exit 0 when every verdict matches what the rule says it must be.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe
from peek import Proc
from tp_to_items import (ITEM_TAGS, dist2d, dist3, entities, level, player_pos, room_verdict,
                         scan_room, tag, u32, pos_of)

RADIUS = 400.0
FORCE = True
rest = sys.argv[2:]
i = 0
while i < len(rest):
    if rest[i] == '--radius' and i + 1 < len(rest):
        RADIUS = float(rest[i + 1])
        i += 2
    elif rest[i] == '--no-force':
        FORCE = False
        i += 1
    else:
        print('unknown option %s' % rest[i])
        sys.exit(1)

pid = int(sys.argv[1])
m, pipe = Proc(pid), Pipe(pid)
p1 = player_pos(m, 0)
print('gate check, level %s, player 1 at (%.1f, %.1f, %.1f)' % (tag(level(m)), p1[0], p1[1], p1[2]))

items = []
for e in entities(m):
    if u32(m, e + 0x10) in ITEM_TAGS:
        items.append(e)
print('item entities in this level: %d' % len(items))
for e in items:
    print('   %s id %s at (%.2f, %.2f, %.2f) +0x20=%d +0xa8=%d @%x'
          % (tag(u32(m, e + 0x10)), tag(u32(m, e + 4)), pos_of(m, e)[0], pos_of(m, e)[1], pos_of(m, e)[2],
             u32(m, e + 0x20), u32(m, e + 0xa8), e))

results = []


def show(name, target, expect, do_tp=False, informational=False):
    print('\n=== case: %s (expect %s)' % (name, expect))
    room = scan_room(m, target, RADIUS)
    allowed, why = room_verdict(room)
    verdict = 'ALLOW' if allowed else 'SKIP'
    print('   gate verdict: %s -- %s' % (verdict, why))
    ok = (verdict == expect)
    if do_tp and allowed:
        from tp_to_items import gate_teleport
        r = gate_teleport(pid, 0, target[0], target[1], target[2], RADIUS, pipe=pipe, m=m)
        print('   gated teleport: %s' % ('ok' if r['ok'] else r['why']))
        ok = ok and r['ok']
    results.append((name, expect, verdict, True if informational else ok))
    return allowed


show('player start', player_pos(m, 0), '(informational)', informational=True)

if items:
    e = items[0]
    p = pos_of(m, e)
    show('nearest item entity as the save left it', p, 'SKIP')
    if FORCE:
        print('\n=== forcing the item live (test-only write, as in TASK 15/16)')
        print('   wr %x 01000000 -> %s' % (e + 0x20, pipe.cmd('wr %x 01000000' % (e + 0x20))))
        import time
        time.sleep(0.4)
        room = scan_room(m, p, RADIUS, verbose=False)
        expect = 'SKIP' if (room['enemies'] or room['spawners']) else 'ALLOW'
        show('the same item, now live (+0x20 = 1)', p, expect, do_tp=(expect == 'ALLOW'))

far = (p1[0] + 3000.0, p1[1] + 3000.0, p1[2])
show('a point 3000 units away', far, 'SKIP')

print('\n== summary')
bad = 0
for (name, expect, verdict, ok) in results:
    print('  %-46s expect %-5s got %-5s %s' % (name[:46], expect, verdict, 'OK' if ok else 'MISMATCH'))
    bad += 0 if ok else 1
print('gate check: %s' % ('PASS' if bad == 0 else 'FAIL (%d mismatch)' % bad))
sys.exit(0 if bad == 0 else 1)
