"""TASK 18 probe: why does a save-loaded world stop the player dead?

Measures, per save slot, in ONE game process (the slots are loaded one after another through the game's
own menu-load path, as scan_slots.py does):

  * the world's script state: world+0x300 (the state machine) and world+0x11c (the state the character
    input update FUN_004cf940 checks; 0x11 makes it return before reading any pad)
  * every party character: tag, position, anim/death state +0x2dc, life +0x320, off-screen flags
    +0x880/+0x884, interaction target +0x73c
  * the input controller records (world+0x1748, two records of 0x764): which human each drives
  * which window is in the foreground
  * the pad: 1 s in each of four directions, then a 15 s held walk sampled every second

Usage: python -I probe_move.py <pid> <slot> [slot ...]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe
from peek import Proc
from tp_to_items import entities, f32, level, player_human, player_pos, tag, u32, world

GAME = 0x6c3068


def mode(m):
    g = u32(m, m.va(GAME))
    return u32(m, g + 0x310) if g else 0


def reqstate(m):
    g = u32(m, m.va(GAME))
    return u32(m, g + 0x320) if g else 0


def progress(m):
    g = u32(m, m.va(GAME))
    return u32(m, g + 0x318) if g else 0


def game(m):
    return u32(m, m.va(GAME))


def humans(m):
    """world+0x175c: the human manager, count +4, array +0xc."""
    w = world(m)
    mgr = u32(m, w + 0x175c) if w else 0
    out = []
    if not mgr:
        return out
    n, arr = u32(m, mgr + 4), u32(m, mgr + 0xc)
    for i in range(min(n, 8) if arr else 0):
        h = u32(m, arr + 4 * i)
        if h:
            out.append(h)
    return out


def controllers(m):
    w = world(m)
    ctl = u32(m, w + 0x1748) if w else 0
    out = []
    for i in range(2):
        c = ctl + 0x764 * i if ctl else 0
        h = u32(m, c + 4) if c else 0
        out.append((c, h, tag(u32(m, c + 0xc)) if c else '-'))
    return out


def fg_pid():
    import ctypes
    import ctypes.wintypes as W
    u = ctypes.WinDLL('user32', use_last_error=True)
    h = u.GetForegroundWindow()
    p = W.DWORD()
    u.GetWindowThreadProcessId(h, ctypes.byref(p))
    return p.value


def state(m, pipe, label):
    w = world(m)
    print('-- %s: mode %s req %s level %s world %#x entities %d'
          % (label, mode(m), reqstate(m), tag(level(m)), w, len(entities(m))))
    print('   world+0x300 (state) %s   world+0x11c (input gate) %s   progress+0x1c68 %s'
          % (u32(m, w + 0x300) if w else None, u32(m, w + 0x11c) if w else None,
             u32(m, progress(m) + 0x1c68) if progress(m) else None))
    print('   foreground pid %d  (this copy %d)' % (fg_pid(), os.getpid()))
    for i, (c, h, ct) in enumerate(controllers(m)):
        if h:
            p = player_pos(m, i)
            print('   ctl%d @%#x tag %s -> human %#x tag %s pos (%.1f, %.1f, %.1f) anim/death +0x2DC %d '
                  'life +0x320 %d offscreen +0x880 %d +0x884 %d target +0x73c %#x'
                  % (i, c, ct, h, tag(u32(m, h + 0x14)), p[0], p[1], p[2], u32(m, h + 0x2dc),
                     u32(m, h + 0x320), u32(m, h + 0x880), u32(m, h + 0x884), u32(m, h + 0x73c)))
    for h in humans(m):
        p = player_pos(m, 0) if h == player_human(m, 0) else None
        if p is None:
            import struct
            b = m.read(h + 0x23c, 12)
            p = struct.unpack('<3f', b) if b else (0, 0, 0)
        print('   human %#x tag %s pos (%.1f, %.1f, %.1f) anim/death +0x2DC %d life +0x320 %d '
              'controller +8 %#x'
              % (h, tag(u32(m, h + 0x14)), p[0], p[1], p[2], u32(m, h + 0x2dc), u32(m, h + 0x320),
                 u32(m, h + 8)))


def stick(m, pipe, lx, ly, hold):
    before = player_pos(m, 0)
    pipe.cmd('pad 0 0 %d %d' % (lx, ly))
    time.sleep(hold)
    pipe.cmd('pad 0 0')
    time.sleep(0.3)
    after = player_pos(m, 0)
    if not before or not after:
        return 0.0, before, after
    d = sum((after[i] - before[i]) ** 2 for i in range(2)) ** 0.5
    return d, before, after


def movement(m, pipe):
    print('   == pad: 1 s in four directions')
    moves = {}
    dirs = ((0, 30000, 'up'), (0, -30000, 'down'), (-30000, 0, 'left'), (30000, 0, 'right'))
    for lx, ly, name in dirs:
        d, b, a = stick(m, pipe, lx, ly, 1.0)
        moves[name] = (d, lx, ly)
        print('      %-5s moved %6.1f units  -> (%.1f, %.1f, %.1f)'
              % (name, d, a[0] if a else 0, a[1] if a else 0, a[2] if a else 0))
    name, (d, lx, ly) = max(moves.items(), key=lambda kv: kv[1][0])
    print('   == held walk: best direction %s, 15 s' % name)
    start = player_pos(m, 0)
    pipe.cmd('pad 0 0 %d %d' % (lx, ly))
    t0 = time.time()
    last = start
    while time.time() - t0 < 15.0:
        time.sleep(1.0)
        p = player_pos(m, 0)
        print('      t+%4.1f s pos (%.2f, %.2f, %.2f)  moved %.1f  (step %.2f)  gate %s'
              % (time.time() - t0, p[0], p[1], p[2],
                 sum((p[i] - start[i]) ** 2 for i in range(3)) ** 0.5,
                 sum((p[i] - last[i]) ** 2 for i in range(3)) ** 0.5,
                 u32(m, world(m) + 0x11c) if world(m) else None))
        last = p
    pipe.cmd('pad 0 0')
    end = player_pos(m, 0)
    print('   == walk total %.1f units in 15 s' % (sum((end[i] - start[i]) ** 2 for i in range(3)) ** 0.5,))
    return start, (lx, ly)


def stuck_test(m, pipe, start, dir_used):
    """Is a stop an INPUT loss or a SPATIAL block? Press the opposite stick, then all four again."""
    print('   == after the held walk: is the stop input loss or a block?')
    lx, ly = dir_used
    for label, sx, sy in (('opposite', -lx, -ly), ('same', lx, ly)):
        d, b, a = stick(m, pipe, sx, sy, 2.0)
        print('      %-8s 2 s -> moved %6.1f units  now (%.1f, %.1f, %.1f)' % (label, d, a[0], a[1], a[2]))
    print('   == all four directions again (1 s each)')
    for sx, sy, name in ((0, 30000, 'up'), (0, -30000, 'down'), (-30000, 0, 'left'), (30000, 0, 'right')):
        d, b, a = stick(m, pipe, sx, sy, 1.0)
        print('      %-5s moved %6.1f units' % (name, d))
    print('   == re-arm the virtual pad (unpad + pad), then 2 s up')
    pipe.cmd('unpad 0')
    time.sleep(0.3)
    d, b, a = stick(m, pipe, 0, 30000, 2.0)
    print('      re-armed moved %6.1f units' % d)
    print('   == safe tp back to the start, then 4 s in the best direction')
    r = pipe.cmd('tp 0 %.3f %.3f %.3f' % (start[0], start[1], start[2]))
    print('      tp -> %s' % r)
    time.sleep(0.5)
    print('      now at (%.1f, %.1f, %.1f)' % player_pos(m, 0))
    d, b, a = stick(m, pipe, dir_used[0], dir_used[1], 4.0)
    print('      after tp moved %6.1f units in 4 s -> (%.1f, %.1f, %.1f)' % (d, a[0], a[1], a[2]))


def gate_dump(m):
    """TASK 18: the interaction gate fields on every level entity. The game's own interaction scan
    FUN_0044d6a0 only offers an entity when +0x20 != 0, +0xa8 == 0 and +0xc0/+0xac/+0xb0 are 0, and it
    is within the entity's radius +0xa0 (TASK 16 section on items). Printing them shows whether a door
    the character stands next to is even eligible."""
    from tp_to_items import rtti
    w = world(m)
    if not w:
        return
    print('   == entity gate fields (class, id, p20, collected +0xa8, gates +0xc0/+0xac/+0xb0, radius +0xa0)')
    for e in entities(m):
        name = rtti(m, e)
        if name.startswith('CToeAddictive') or name.startswith('CToeStepSound') or name.startswith('CToePhysic'):
            continue
        print('      %-24s id %-5s p20 %d coll %d gates (%d, %d, %d) radius %s at (%8.1f, %8.1f, %7.1f)'
              % (name, tag(u32(m, e + 4)), u32(m, e + 0x20), u32(m, e + 0xa8),
                 u32(m, e + 0xc0), u32(m, e + 0xac), u32(m, e + 0xb0), f32(m, e + 0xa0),
                 f32(m, e + 0x6c), f32(m, e + 0x70), f32(m, e + 0x74)))


def pause_test(m, pipe):
    """TASK 18: is the TASK 17 'the pad moves the character 0.0 units' measurement a paused game?
    probe_control.py presses A, A, START, B, BACK, A before measuring. START opens the pause menu."""
    from bot import press
    print('   == pause test (what probe_control.py did before it measured 0.0 units)')
    d, b, a = stick(m, pipe, 0, 30000, 1.5)
    print('      before any button: 1.5 s up moved %.1f units' % d)
    for name in ('A', 'A', 'START'):
        press(pipe, 0, name, 0.3)
        time.sleep(1.2)
        print('      after %-5s: mode %s pos (%.1f, %.1f, %.1f)' % (name, mode(m), *player_pos(m, 0)))
    d, b, a = stick(m, pipe, 0, 30000, 1.5)
    print('      with START pressed (pause menu): 1.5 s up moved %.1f units' % d)
    press(pipe, 0, 'START', 0.3)
    time.sleep(1.5)
    print('      after START again: mode %s' % mode(m))
    d, b, a = stick(m, pipe, 0, 30000, 1.5)
    print('      unpaused: 1.5 s up moved %.1f units' % d)


if __name__ == '__main__':
    pid = int(sys.argv[1])
    slots = [int(s) for s in (sys.argv[2:] or os.environ.get('PROBE_SLOTS', '').split())]
    m = Proc(pid)
    pipe = Pipe(pid)
    for slot in slots:
        print('\n================ slot %d ================' % slot)
        r = pipe.cmd('loadsave game%d.sav' % slot)
        print('loadsave game%d.sav -> %s' % (slot, r))
        t0 = time.time()
        ok = False
        while time.time() - t0 < 90:
            w = world(m)
            if mode(m) == 1 and w and reqstate(m) == 0 and entities(m):
                ok = True
                break
            time.sleep(1.0)
        print('world up: %s after %.1f s' % (ok, time.time() - t0))
        if not ok:
            continue
        last, placed = None, False
        t0 = time.time()
        while time.time() - t0 < 40:
            p1 = player_pos(m, 0)
            if p1 and all(abs(v) < 50000 for v in p1) and max(abs(v) for v in p1) > 1.0:
                if last and all(abs(p1[i] - last[i]) < 0.05 for i in range(3)):
                    placed = True
                    break
                last = p1
            time.sleep(0.5)
        print('characters placed: %s after %.1f s' % (placed, time.time() - t0))
        time.sleep(3.0)
        state(m, pipe, 'before the pad')
        if os.environ.get('PROBE_GATES'):
            gate_dump(m)
        start, dir_used = movement(m, pipe)
        state(m, pipe, 'after the pad')
        stuck_test(m, pipe, start, dir_used)
        if os.environ.get('PROBE_PAUSE'):
            pause_test(m, pipe)
