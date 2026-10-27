"""Both copies into a 2-player new game, driven by game state instead of fixed sleeps.

Waits for the main menu (game+0x310 == 4), presses New game -> Two players, waits for the
"2 player mode" notice (mode 2), confirms it, then waits until a level is up (mode 1, two humans)
and skips the intro movie on both copies. Usage: python -I duo_start_game.py [timeout]"""
import sys, os, time
sys.path.insert(0, r'C:\Users\gyuro\coop-anything-obscure\local\runs')
import bot, peek
R = os.path.dirname(os.path.abspath(__file__))
hp = int(open(R + r'\duo_host.pid').read()); gp = int(open(R + r'\duo_guest.pid').read())
host, guest = bot.Pipe(hp), bot.Pipe(gp)
mh, mg = peek.Proc(hp), peek.Proc(gp)

def mode(m):
    try:
        g = m.u32(m.va(0x6c3068))
        return m.u32(g + 0x310) if g else None
    except Exception:
        return None

def humans(m):
    try:
        g = m.u32(m.va(0x6c3068)); w = m.u32(g + 0x378) if g else 0
        return m.u32(m.u32(w + 0x175c) + 4) if w else 0
    except Exception:
        return 0

def wait_for(label, pred, limit, both=(mh, mg)):
    t = time.time()
    while time.time() - t < limit:
        if all(pred(m) for m in both): return True
        time.sleep(0.5)
    print('timeout waiting for', label, [pred(m) for m in both])
    return False

def press_both(btn, wait=1.0):
    for p in (host, guest):
        bot.press(p, 0, btn)
    time.sleep(wait)

print('mode at start:', [mode(m) for m in (mh, mg)])
wait_for('game object', lambda m: mode(m) is not None, 40)
time.sleep(10)   # the main menu is up by now (mode 2 covers menu, notice and loading)
press_both('A')            # New game
press_both('DOWN', 0.8)    # Two players
press_both('A')            # choose it -> notice
wait_for('2-player notice', lambda m: mode(m) == 2, 20)
press_both('A')            # dismiss the notice
wait_for('level with two humans', lambda m: mode(m) == 1 and humans(m) >= 2, 90)
time.sleep(3)
for p in (host, guest):
    bot.tap(p, 'ESCAPE')   # skip the intro movie
time.sleep(4)
print('host mode', mode(mh), 'humans', humans(mh), '| guest mode', mode(mg), 'humans', humans(mg))
print('host ', host.cmd('sync'))
print('guest', guest.cmd('sync'))
