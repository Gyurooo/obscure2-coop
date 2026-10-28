"""Load one save slot into ONE copy through the game's own menu-load path and wait until the level has
actually placed the characters.

`loadsave gameN.sav` is the mod's replay of the menu's Load (save manager open + LoadByName). The world
is up within a second, but the intro places the characters later and a pad/tp before that is overwritten
(FINDINGS_16 section 4), so this waits for both players to sit away from the origin and stop changing.

Usage: python -I load_slot.py <pid> <slot 0..9> [timeout]
Exit 0 when the world is up and both characters are placed, 1 otherwise.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe
from peek import Proc
from tp_to_items import entities, level, player_pos, tag, u32, world

pid = int(sys.argv[1])
slot = int(sys.argv[2])
LIMIT = int(sys.argv[3]) if len(sys.argv) > 3 else 120

m = Proc(pid)
t0 = time.time()
pipe = None
while time.time() - t0 < 90:
    try:
        pipe = Pipe(pid)
        break
    except Exception:
        time.sleep(1.0)
if pipe is None:
    print('the command pipe never appeared')
    sys.exit(1)
print('command pipe open after %.1f s' % (time.time() - t0))


def mode():
    g = u32(m, m.va(0x6c3068))
    return u32(m, g + 0x310) if g else None


def reqstate():
    g = u32(m, m.va(0x6c3068))
    return u32(m, g + 0x320) if g else None


t0 = time.time()
while time.time() - t0 < 90:
    if mode() == 2 and not world(m):
        break
    time.sleep(1.0)
print('at the main menu (mode %s, world %#x) after %.1f s' % (mode(), world(m) or 0, time.time() - t0))
print('loadsave game%d.sav -> %s' % (slot, pipe.cmd('loadsave game%d.sav' % slot)))

t0 = time.time()
ok = False
while time.time() - t0 < LIMIT:
    w = world(m)
    if mode() == 1 and w and reqstate() == 0 and entities(m):
        ok = True
        break
    time.sleep(1.0)
print('world up: %s after %.1f s (level %s, %d entities)'
      % (ok, time.time() - t0, tag(level(m)), len(entities(m))))
if not ok:
    sys.exit(1)

# The level intro places the characters: wait until player 1 sits away from the origin and holds still.
# (A solo copy has no attached second input controller after a menu load, so only player 1 is required.)
t0 = time.time()
placed = False
last = None
while time.time() - t0 < 150:
    p1 = player_pos(m, 0)
    if p1 and all(abs(v) < 50000 for v in p1) and max(abs(v) for v in p1) > 1.0:
        if last and all(abs(p1[i] - last[i]) < 0.05 for i in range(3)):
            placed = True
            break
        last = p1
    time.sleep(1.0)
print('characters placed: %s after %.1f s | player 1 %s player 2 %s'
      % (placed, time.time() - t0, player_pos(m, 0), player_pos(m, 1)))
# settle: the level keeps building entities for a few seconds after the world pointer appears
time.sleep(3.0)
print('ready: level %s, %d entities, player 1 at %s' % (tag(level(m)), len(entities(m)), player_pos(m, 0)))
sys.exit(0 if placed else 1)
