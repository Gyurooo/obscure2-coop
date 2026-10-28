"""TASK 20: put BOTH copies into J003 (the level with live items and no enemies) through the host's own
level change, and prove the guest follows it.

The pair is already in save 01 (I100) when this runs (tests/run_pair.sh did the menu load). The host
issues the door's own call `level J003 157 1`; the mod forwards a host ChangeLevel to the guest
(REQ_LEVEL -> the guest applies it), so both copies must end in J003 with the same entities.

Prints both levels, both players, and every live item on each copy. Exit 0 only when both copies are
in J003 with at least two live items each.

Usage: python -I pair_j003.py <host pid> <guest pid>
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe
from peek import Proc
from tp_to_items import ITEM_TAGS, entities, level, player_pos, pos_of, rtti, tag, u32, world

GAME = 0x6c3068


def mode(m):
    g = u32(m, m.va(GAME))
    return u32(m, g + 0x310) if g else 0


def live_items(m):
    out = []
    for e in entities(m):
        if u32(m, e + 0x10) in ITEM_TAGS and u32(m, e + 0xa8) == 0 and u32(m, e + 0x20) != 0:
            out.append((rtti(m, e), tag(u32(m, e + 0x10)), tag(u32(m, e + 4)), pos_of(m, e)))
    return out


h, g = int(sys.argv[1]), int(sys.argv[2])
host, guest = Pipe(h), Pipe(g)
mh, mg = Proc(h), Proc(g)
print('before: host level %s player 1 %s | guest level %s player 1 %s'
      % (tag(level(mh)), player_pos(mh, 0), tag(level(mg)), player_pos(mg, 0)))
rc = pipe = host.cmd('level J003 157 1')
print('host level J003 157 1 -> %s' % pipe)
t0 = time.time()
while time.time() - t0 < 90:
    lh, lg = tag(level(mh)), tag(level(mg))
    if lh == 'J003' and lg == 'J003' and mode(mh) == 1 and mode(mg) == 1:
        break
    time.sleep(1.0)
print('after %.1f s: host %s (mode %s) | guest %s (mode %s)'
      % (time.time() - t0, tag(level(mh)), mode(mh), tag(level(mg)), mode(mg)))
time.sleep(8.0)
lh, lg = live_items(mh), live_items(mg)
print('host player 1 %s player 2 %s | guest player 1 %s player 2 %s'
      % (player_pos(mh, 0), player_pos(mh, 1), player_pos(mg, 0), player_pos(mg, 1)))
print('host live items: %s' % ', '.join('%s id %s (%.1f, %.1f, %.1f)' % (r, i, *p) for r, c, i, p in lh))
print('guest live items: %s' % ', '.join('%s id %s (%.1f, %.1f, %.1f)' % (r, i, *p) for r, c, i, p in lg))
ok = (tag(level(mh)) == 'J003' and tag(level(mg)) == 'J003' and len(lh) >= 2 and len(lg) >= 2)
print('RESULT: %s' % ('both copies in J003 with 2 live items' if ok else 'NOT both in J003 with items'))
sys.exit(0 if ok else 1)
