"""TASK 20: what does the pause menu offer in a level reached through a door? (screenshots)

Starts in a save-loaded world (the runner loads slot 01), jumps to J003 with the mod's `level` command,
then opens the pause menu and walks down the entries, taking a screenshot of each step. Used to find a
"Save game" entry, if the game has one outside a save point.

Usage: python -I probe_pause.py <pid> [outdir]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot
from bot import Pipe
from peek import Proc
from tp_to_items import entities, level, player_pos, tag, u32, world

GAME = 0x6c3068


def mode(m):
    g = u32(m, m.va(GAME))
    return u32(m, g + 0x310) if g else 0


pid = int(sys.argv[1])
outdir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.environ.get('TMPDIR', '.'), 'pause')
os.makedirs(outdir, exist_ok=True)
m, pipe = Proc(pid), Pipe(pid)
print('start level %s' % tag(level(m)))
print('level J003 157 1 -> %s' % pipe.cmd('level J003 157 1'))
t0 = time.time()
while time.time() - t0 < 45:
    if mode(m) == 1 and tag(level(m)) == 'J003' and entities(m):
        break
    time.sleep(1.0)
time.sleep(7.0)
print('in level %s, player 1 %s' % (tag(level(m)), player_pos(m, 0)))


def snap(name):
    p = os.path.join(outdir, name)
    try:
        ok, w, h = bot.shot(pid, p)
        print('   shot %s (%s, %dx%d)' % (p, ok, w, h))
    except Exception as e:
        print('   shot failed: %s' % e)


snap('00_level.png')
for name, btn in (('01_start', 'START'), ('02_down1', 'DOWN'), ('03_down2', 'DOWN'), ('04_down3', 'DOWN'),
                  ('05_down4', 'DOWN')):
    bot.press(pipe, 0, btn, 0.2)
    time.sleep(1.2)
    print('   after %s: mode %s level %s' % (btn, mode(m), tag(level(m))))
    snap(name + '.png')
print('DONE')
