"""TASK 17 Part C probe: does a save-loaded world ever give the pad back?

Standing question from FINDINGS_15/16 and from this task's forward-play runs: the pad moves the character
for the first seconds after the load and then the character stops dead (I007: after ~250 units; G003:
after ~177 units). This probe measures it instead of guessing:

  1. mode / level / position / anim / interaction target (+0x73c)
  2. the game's own menu buttons (A, START, B, BACK) pressed one at a time, position after each - if a
     cutscene or a "waiting" state is holding the character, this is what a player would press
  3. four 1-second stick presses, with the displacement of each
  4. then a 20 s walk in the best direction, sampled every 2 s, so the log shows exactly when it stops

Usage: python -I probe_control.py <pid>
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe, press
from peek import Proc
from tp_to_items import dist2d, dist3, level, player_human, player_pos, rtti, tag, u32, world

pid = int(sys.argv[1])
m, pipe = Proc(pid), Pipe(pid)


def mode():
    g = u32(m, m.va(0x6c3068))
    return u32(m, g + 0x310) if g else None


def anim():
    h = player_human(m, 0)
    return u32(m, h + 0x2dc) if h else 0


def itarget():
    h = player_human(m, 0)
    return u32(m, h + 0x73c) if h else 0


def show(label):
    p = player_pos(m, 0)
    it = itarget()
    print('  %-28s mode %s level %s pos (%.2f, %.2f, %.2f) anim %d +0x73c %#x %s'
          % (label, mode(), tag(level(m)), p[0], p[1], p[2], anim(), it, rtti(m, it) if it else ''))


show('start')
print('\n== game buttons (a player would use these to leave a cutscene/pause)')
for name in ('A', 'A', 'START', 'B', 'BACK', 'A'):
    press(pipe, 0, name, 0.3)
    time.sleep(1.2)
    show('after %s' % name)

print('\n== one-second stick presses in four directions')
base = player_pos(m, 0)
for lx, ly, name in ((0, 30000, 'up'), (0, -30000, 'down'), (-30000, 0, 'left'), (30000, 0, 'right')):
    before = player_pos(m, 0)
    pipe.cmd('pad 0 0 %d %d' % (lx, ly))
    time.sleep(1.0)
    pipe.cmd('pad 0 0')
    time.sleep(0.4)
    after = player_pos(m, 0)
    print('  stick %-5s -> moved (%.1f, %.1f, %.1f)  (planar %.1f)'
          % (name, after[0] - before[0], after[1] - before[1], after[2] - before[2],
             dist2d(after, before)))

print('\n== 20 s walk in the direction that moved most (sampled every 2 s)')
moves = {}
for lx, ly, name in ((0, 30000, 'up'), (0, -30000, 'down'), (-30000, 0, 'left'), (30000, 0, 'right')):
    before = player_pos(m, 0)
    pipe.cmd('pad 0 0 %d %d' % (lx, ly))
    time.sleep(0.6)
    pipe.cmd('pad 0 0')
    time.sleep(0.3)
    after = player_pos(m, 0)
    moves[name] = (dist2d(after, before), lx, ly)
name, (d, lx, ly) = max(moves.items(), key=lambda kv: kv[1][0])
print('  best: %s (%.1f units in 0.6 s)' % (name, d))
start = player_pos(m, 0)
pipe.cmd('pad 0 0 %d %d' % (lx, ly))
t0 = time.time()
while time.time() - t0 < 20.0:
    time.sleep(2.0)
    p = player_pos(m, 0)
    print('   t+%4.1f s pos (%.2f, %.2f, %.2f)  moved %.1f  anim %d  +0x73c %#x'
          % (time.time() - t0, p[0], p[1], p[2], dist3(p, start), anim(), itarget()))
pipe.cmd('pad 0 0')
print('\nverdict: the character moved %.1f units in 20 s of held stick (%.1f from the start position)'
      % (dist3(player_pos(m, 0), start), dist3(player_pos(m, 0), base)))
