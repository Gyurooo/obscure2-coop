"""TASK 21 probe: is the pad accepted in a combat level, and which button swings?

Both copies are already in save 01 (I100), started by tests/run_pair.sh. The host changes level to J001
(the door's own call `J001 317 1`), the guest follows. Then, on the host copy:

  * `padshow` / `stats` (does the game poll the virtual pad at all?),
  * player 1 position + state (+0x2dc) + current weapon slot (+0x714),
  * each button in turn (A B X Y LB RB LS RS-click), holding it 2 s, with position/state/weapon after,
  * then the same short probe in J000 (`J000 314 1`).

Read-only apart from the safe tp, the pad presses and the host's level changes.

Usage: python -I probe_combat_input.py <host pid> <guest pid>
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe
from peek import Proc

GAME = 0x6c3068
MASKS = {'A': 0x1000, 'B': 0x2000, 'X': 0x4000, 'Y': 0x8000, 'LB': 0x100, 'RB': 0x200,
         'LS': 0x40, 'RS': 0x80, 'START': 0x10, 'BACK': 0x20, 'UP': 0x1, 'DOWN': 0x2,
         'LEFT': 0x4, 'RIGHT': 0x8}


def u32(m, a):
    try:
        return m.u32(a) or 0
    except Exception:
        return 0


def f32(m, a):
    b = m.read(a, 4)
    return struct.unpack('<f', b)[0] if b else 0.0


def tag(v):
    return ''.join(chr((v >> s) & 0xff) if 32 <= ((v >> s) & 0xff) < 127 else '.'
                   for s in (24, 16, 8, 0))


def world(m):
    g0 = u32(m, m.va(GAME))
    return u32(m, g0 + 0x378) if g0 else 0


def level(m):
    w = world(m)
    return u32(m, w + 4) if w else 0


def human(m, pl):
    w = world(m)
    mg = u32(m, w + 0x175c) if w else 0
    arr = u32(m, mg + 0xc) if mg else 0
    return u32(m, arr + 4 * pl) if arr else 0


def state(m, pl=0):
    h = human(m, pl)
    if not h:
        return 'no character'
    wp = u32(m, h + 0x704 + 4 * u32(m, h + 0x714))
    return ('pos (%.1f, %.1f, %.1f) state %#x life %.1f cur %d wep %s +0x2bc %#x +0x73c %#x'
            % (f32(m, h + 0x23c), f32(m, h + 0x240), f32(m, h + 0x244), u32(m, h + 0x2dc),
               f32(m, h + 0x320), u32(m, h + 0x714), tag(u32(m, wp + 0x10)) if wp else '----',
               u32(m, h + 0x2bc), u32(m, h + 0x73c)))


def npcs(m):
    w = world(m)
    mg = u32(m, w + 0x1760) if w else 0
    n = u32(m, mg + 4) if mg else 0
    arr = u32(m, mg + 0xc) if mg else 0
    out = []
    for i in range(min(n, 32)):
        a = u32(m, arr + 4 * i)
        if a:
            out.append(a)
    return out


def enemy_line(m):
    out = []
    for a in npcs(m):
        out.append('%s life %.1f st %#x' % (tag(u32(m, a + 0x14)) or '.', f32(m, a + 0x320), u32(m, a + 0x2dc)))
    return ' | '.join(out)


def button(pipe, name, hold=2.0):
    pipe.cmd('pad 0 %x' % MASKS[name])
    time.sleep(hold)
    pipe.cmd('pad 0 0')
    time.sleep(0.2)


h, g = int(sys.argv[1]), int(sys.argv[2])
host, guest = Pipe(h), Pipe(g)
mh, mg = Proc(h), Proc(g)


def probe_level(lvl, entry):
    print('\n===== %s' % lvl)
    print('host level %s %d 1 -> %s' % (lvl, entry, host.cmd('level %s %d 1' % (lvl, entry))))
    t0 = time.time()
    while time.time() - t0 < 90:
        if tag(level(mh)) == lvl and tag(level(mg)) == lvl:
            break
        time.sleep(1.0)
    print('level up after %.1f s: host %s guest %s' % (time.time() - t0, tag(level(mh)), tag(level(mg))))
    time.sleep(8.0)
    print('padshow host: %s' % host.cmd('padshow'))
    print('stats host: %s' % host.cmd('stats')[:300])
    print('before: %s' % state(mh))
    print('enemies: %s' % enemy_line(mh))
    try:
        import bot as _bot
        print('shot host: %s' % (_bot.shot(h, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shot_%s_host.png' % lvl)),))
    except Exception as e:
        print('shot failed: %s' % e)
    # Does control ever arrive? LEFT for 1 s every 5 s, up to 25 s.
    for i in range(5):
        a = hpos(mh, 0)
        button(host, 'LEFT', 1.0)
        b = hpos(mh, 0)
        d = sum((a[k] - b[k]) ** 2 for k in range(3)) ** 0.5 if a and b else -1
        print('t=%2ds LEFT 1s moved %.1f  %s' % (i * 5, d, state(mh)))
        if d > 5.0:
            print('*** the pad works now in %s' % lvl)
            break
        time.sleep(4.0)
    for btn in ('X', 'A', 'B', 'Y', 'LB', 'RB', 'LS', 'RS', 'START'):
        before = state(mh)
        button(host, btn, 1.0)
        after = state(mh)
        ws = after.split(' cur ')[1].split(' wep ')[0] if ' cur ' in after else '?'
        print('%-5s %s\n      -> %s' % (btn, before, after))
        time.sleep(0.3)
    print('enemies after: %s' % enemy_line(mh))


if __name__ == '__main__':
    probe_level('J000', 314)
    probe_level('J001', 317)
