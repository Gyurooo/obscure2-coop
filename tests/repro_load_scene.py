"""TASK 38: load + the level's scripted event, again and again - the shape that crashed the guest.

TASK 37's soak run 2 lost the guest's game thread at Obscure2.exe+0xf16a9 (write to address 8) at its
third load, a couple of seconds after the level's intro scripted event. The game's world update, in its
state-7 branch (world+0x12c = 7, the scripted event; decompile 110439-110480), leaves the event with

    manager->vtable[0x1c]( *(world+0x174c + 4), world+0x1748 + 0x764 )

i.e. it attaches the TEAMMATE controller's character to input controller 2 - and the mod's TASK 35 door
fix had set that character to 0 (an unlinked teammate controller). The callee (FUN_004f16a0) writes
human+8 and virtual-calls controller 2, so the NULL character is a write to address 8.

This script repeats exactly that: the host loads one of the two test saves, the pair settles into the
level, the script waits for the scripted event (state 7) on either copy, presses the game's own skip
(the same ESCAPE the mod's scene sync presses) on the copies that are in it, and then checks that both
processes are alive, both game threads still run frames, and neither log gained a crash or a stall line.
N iterations of that are the proof the fix holds.

Usage: python -I repro_load_scene.py <host pid> <guest pid> [iterations]
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe
from peek import Proc
from tp_to_items import level, tag, u32, world

GAME = 0x6c3068
SAVES = ('game0.sav', 'game3.sav')       # I100 and J002
WAIT_LEVEL = 45.0
WAIT_SCENE = 18.0

host_pid, guest_pid = int(sys.argv[1]), int(sys.argv[2])
iters = int(sys.argv[3]) if len(sys.argv) > 3 else 10
try:
    sys.stdout.reconfigure(line_buffering=True)   # progress is polled from a file by the runner
except Exception:
    pass
H, G = Proc(host_pid), Proc(guest_pid)
HP, GP = Pipe(host_pid), Pipe(guest_pid)


def in_level(m):
    g = u32(m, m.va(GAME))
    if not g:
        return False
    w = u32(m, g + 0x378)
    return u32(m, g + 0x310) == 1 and u32(m, g + 0x320) == 0 and w and (u32(m, w + 4) or 0) != 0


def scene_state(m):
    """(world+0x11c, world+0x12c): the current state and the scripted event / requested state."""
    g = u32(m, m.va(GAME))
    w = u32(m, g + 0x378) if g else 0
    if not w:
        return (None, None)
    return (u32(m, w + 0x11c), u32(m, w + 0x12c))


def in_scene(m):
    st, nxt = scene_state(m)
    return st == 7 or nxt == 7


def frames(pipe):
    r = pipe.cmd('sync')
    for part in r.split('|'):
        if 'frames ' in part:
            try:
                return int(part.split()[-1])
            except (IndexError, ValueError):
                return -1
    return -1


def alive(pid):
    # tasklist prints in the system code page (not UTF-8): decode as latin-1, we only look for the quote.
    out = subprocess.run(['tasklist', '/FI', 'PID eq %d' % pid, '/FO', 'CSV', '/NH'],
                         capture_output=True).stdout
    return out.decode('latin-1', 'replace').strip().startswith('"')


def log_path(role):
    d = os.environ.get('OBSCOOP_%s_DIR' % role.upper())
    if not d:
        root = os.environ.get('OBSCOOP_TEST_ROOT', '')
        d = os.path.join(root, 'obscure2-test' if role == 'host' else 'obscure2-test2')
    return os.path.join(d, 'obscoop.log')


def log_count(role, marker):
    p = log_path(role)
    if not p or not os.path.exists(p):
        return 0
    try:
        with open(p, 'r', errors='replace') as f:
            return sum(1 for line in f if marker in line)
    except OSError:
        return 0


def crashes():
    return (log_count('host', 'FATAL EXCEPTION'), log_count('guest', 'FATAL EXCEPTION'))


def stalls():
    return (log_count('host', 'GAME THREAD STALLED'), log_count('guest', 'GAME THREAD STALLED'))


def wait_same(t=WAIT_LEVEL):
    t0 = time.time()
    while time.time() - t0 < t:
        if in_level(H) and in_level(G) and tag(level(H)) == tag(level(G)):
            return True, time.time() - t0
        time.sleep(0.3)
    return False, time.time() - t0


def wait_scene(t=WAIT_SCENE):
    t0 = time.time()
    while time.time() - t0 < t:
        if in_scene(H) or in_scene(G):
            return True, time.time() - t0
        time.sleep(0.2)
    return False, time.time() - t0


def skip(pipe):
    """The game's own scripted-event skip: ESCAPE, the key the mod's scene sync presses (FINDINGS_30)."""
    pipe.cmd('key 1 1')
    time.sleep(0.18)
    pipe.cmd('key 1 0')


def drive(i=0, seconds=1.2):
    """Walk both characters - the soak's drive(); a level's scripted event starts on movement through a
    trigger zone. The direction cycles so four iterations cover the ground around the spawn point."""
    dirs = ((0, 26000), (0, -26000), (26000, 0), (-26000, 0))
    hx, hy = dirs[i % len(dirs)]
    HP.cmd('pad 0 0 %d %d' % (hx, hy))
    GP.cmd('pad 0 0 %d %d' % (-hx, -hy))
    time.sleep(seconds)
    HP.cmd('pad 0 0')
    GP.cmd('pad 0 0')
    time.sleep(0.25)


def wait_out_of_scene(t=8.0):
    t0 = time.time()
    while time.time() - t0 < t:
        if not in_scene(H) and not in_scene(G):
            return True, time.time() - t0
        time.sleep(0.2)
    return False, time.time() - t0


c0, s0 = crashes(), stalls()
ok_all = True
warm, el = wait_same()
print('start: both copies in one level after %.1fs (%s / %s)' % (el, tag(level(H)), tag(level(G))))
if not warm:
    print('repro FAIL: the two copies never reached a common level')
    sys.exit(1)
# The level's intro scripted event may already be running (it plays on the first entry; the runner's
# main-menu load is where it happens). Skip it on the copies that are in it BEFORE the first load, so the
# game's own state-7 -> normal-play path runs on this run too.
hs, hn = scene_state(H)
gs, gn = scene_state(G)
print('start: scene states %s / %s -> %s' % ((hs, hn), (gs, gn),
      'in a scripted event, pressing the game\'s own skip' if (in_scene(H) or in_scene(G)) else 'normal play'))
if in_scene(H):
    skip(HP)
if in_scene(G):
    skip(GP)
if in_scene(H) or in_scene(G):
    out, oel = wait_out_of_scene(10.0)
    print('start: left the scripted event %s after %.1fs' % ('yes' if out else 'NO', oel))
    time.sleep(0.5)

for i in range(iters):
    sv = SAVES[i % len(SAVES)]
    before = tag(level(H))
    HP.cmd('loadsave %s' % sv)
    t0 = time.time()
    changed = False
    while time.time() - t0 < WAIT_LEVEL:
        lt = tag(level(H))
        if in_level(H) and lt and time.time() - t0 > 2.0 and (lt != before or time.time() - t0 > 20.0):
            changed = True
            break
        time.sleep(0.3)
    same, el = wait_same(30 if changed else 5)
    lv = '%s/%s' % (tag(level(H)), tag(level(G)))
    # The soak's drive: the level's intro script starts on movement (TASK 36/37 saw the state-7 scene a
    # couple of seconds after a load + drive), so walk both characters before looking for the event.
    drive(i)
    saw, sel = wait_scene()
    hs, hn = scene_state(H)
    gs, gn = scene_state(G)
    # The copies that are in the event get the game's own skip, exactly like a player pressing it.
    pressed = []
    if in_scene(H):
        skip(HP)
        pressed.append('host')
    if in_scene(G):
        skip(GP)
        pressed.append('guest')
    out, oel = wait_out_of_scene(8.0 if saw else 1.0)
    # Let the world run a moment after the event (the game's enter-normal-play path runs there).
    time.sleep(1.0)
    f0 = (frames(HP), frames(GP))
    time.sleep(1.0)
    f1 = (frames(HP), frames(GP))
    c1, s1 = crashes(), stalls()
    dc = (c1[0] - c0[0], c1[1] - c0[1])
    ds = (s1[0] - s0[0], s1[1] - s0[1])
    running = (f1[0] > f0[0] >= 0) and (f1[1] > f0[1] >= 0)
    alive_now = (alive(host_pid), alive(guest_pid))
    good = changed and same and running and alive_now[0] and alive_now[1] and dc == (0, 0) and ds == (0, 0)
    print('== %2d: host loads %-9s -> %s, level %s -> %s (%.1fs, %s) | scene %s after %.1fs (states %s/%s, '
          'skipped by %s, out %s after %.1fs)' % (
              i + 1, sv, 'load done' if changed else 'NO change', before, lv, el,
              'one level' if same else 'NOT one level', 'seen' if saw else 'none', sel, (hs, hn), (gs, gn),
              '+'.join(pressed) if pressed else 'nobody', 'yes' if out else 'NO', oel))
    print('     frames host %s -> %s, guest %s -> %s (%s) | alive %s | new crashes %s, new stalls %s | %s' % (
        f0[0], f1[0], f0[1], f1[1], 'both running' if running else 'STOPPED', alive_now, dc, ds,
        'PASS' if good else 'FAIL'))
    if not good:
        ok_all = False
        if not (alive_now[0] and alive_now[1] and running):
            print('     repro stops here: a game copy is not running any more')
            break
    c0, s0 = c1, s1

print('repro %s (%d iterations)' % ('PASS' if ok_all else 'FAIL', iters))
sys.exit(0 if ok_all else 1)
