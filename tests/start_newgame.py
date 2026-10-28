"""Put the pair into a 2-player new game and STOP with the level's intro cutscene still running.

`duo_start_game.py` skips the intro with ESCAPE at the end; this one does not: the world comes up in
B101 and both copies are in the scripted presentation (world+0x11c = 6, FINDINGS_30 §5). Used by
tests/run_cutscene_pair.sh before check_cutscene.py.

Usage: python -I start_newgame.py [timeout s]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot
import peek

R = os.path.dirname(os.path.abspath(__file__))
hp = int(open(os.path.join(R, 'duo_host.pid')).read())
gp = int(open(os.path.join(R, 'duo_guest.pid')).read())
host, guest = bot.Pipe(hp), bot.Pipe(gp)
mh, mg = peek.Proc(hp), peek.Proc(gp)
LIMIT = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0


def mode(m):
    try:
        g = m.u32(m.va(0x6c3068))
        return m.u32(g + 0x310) if g else None
    except Exception:
        return None


def humans(m):
    try:
        g = m.u32(m.va(0x6c3068))
        w = m.u32(g + 0x378) if g else 0
        return m.u32(m.u32(w + 0x175c) + 4) if w else 0
    except Exception:
        return 0


def both(pred, label, limit):
    t = time.time()
    while time.time() - t < limit:
        if all(pred(m) for m in (mh, mg)):
            return True
        time.sleep(0.5)
    print('timeout waiting for %s: %r' % (label, [pred(m) for m in (mh, mg)]))
    return False


def press_both(btn, wait=1.0):
    for p in (host, guest):
        bot.press(p, 0, btn)
    time.sleep(wait)


print('mode at start:', [mode(m) for m in (mh, mg)])
both(lambda m: mode(m) is not None, 'game object', 40)
time.sleep(10)
press_both('A')            # New game
press_both('DOWN', 0.8)    # Two players
press_both('A')            # choose it -> the notice
both(lambda m: mode(m) == 2, '2-player notice', 20)
press_both('A')            # dismiss the notice
ok = both(lambda m: mode(m) == 1 and humans(m) >= 2, 'level with two humans', LIMIT)
time.sleep(2)
print('new game: level up on both copies (mode %r, humans %r / %r), intro NOT skipped'
      % ([mode(m) for m in (mh, mg)], humans(mh), humans(mg)))
print('host scene : %s' % host.cmd('scene'))
print('guest scene: %s' % guest.cmd('scene'))
sys.exit(0 if ok else 1)
