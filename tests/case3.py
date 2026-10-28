"""CASE 3 (TASK 14): a second load in the same session, from the game's own pause menu.

Prerequisite: both copies are already in a level from the first load (the runner did the main-menu load).
This script then

  1. notes both copies' world pointer and level (a load builds a NEW world, so the pointer must change),
  2. on the HOST opens the pause menu and picks "Load a saved game" -> slot 01 -> the confirm entry with
     pad keys (ESCAPE, DOWN, DOWN, A, A, UP, A — the sequence TASK 10/11 used for the pause-menu load),
  3. waits up to --pause-wait s (default 45) for the host's world to be rebuilt,
  4. if the keypresses did not produce a load, says so and falls back to the test-only `loadsave <save>`
     pipe command (the same two game calls the pause menu makes), so the core of the case is still tested;
     the report states which route produced the load,
  5. waits for the GUEST to follow into a rebuilt world of the same level,
  6. prints both copies' state and the log tails.

Usage: python -I case3.py [save file] [pause wait] [guest wait]
"""
import os, struct, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot, peek

R = os.path.dirname(os.path.abspath(__file__))
SAVE = sys.argv[1] if len(sys.argv) > 1 else 'game0.sav'
PAUSE_WAIT = int(sys.argv[2]) if len(sys.argv) > 2 else 45
GUEST_WAIT = int(sys.argv[3]) if len(sys.argv) > 3 else 90
SHOTS = os.path.join(R, 'shots')


def mode(m):
    try:
        g = m.u32(m.va(0x6c3068))
        return m.u32(g + 0x310) if g else None
    except Exception:
        return None


def world(m):
    try:
        g = m.u32(m.va(0x6c3068))
        return m.u32(g + 0x378) if g else 0
    except Exception:
        return 0


def level(m):
    w = world(m)
    if not w:
        return '----'
    try:
        return struct.pack('<I', m.u32(w + 4)).decode('latin1')[::-1]
    except Exception:
        return '????'


def humans(m):
    w = world(m)
    try:
        return m.u32(m.u32(w + 0x175c) + 4) if w else 0
    except Exception:
        return 0


def show(who, m, w0=None):
    w = world(m)
    print('%s: mode %s world %#x%s level %s humans %s' % (who, mode(m), w or 0,
          '' if w0 is None else (' (unchanged)' if w == w0 else ' (REBUILT)'), level(m), humans(m)))


def wait(label, pred, limit):
    t = time.time()
    while time.time() - t < limit:
        if pred():
            print('ok:', label, 'after %.1f s' % (time.time() - t))
            return True
        time.sleep(0.5)
    print('TIMEOUT waiting for', label)
    return False


def shot(pid, name):
    try:
        os.makedirs(SHOTS, exist_ok=True)
        print('  shot %s -> %s' % (name, bot.shot(pid, os.path.join(SHOTS, name))))
    except Exception as e:
        print('  (no screenshot %s: %s)' % (name, e))


def log_tail(who):
    root = os.environ.get('OBSCOOP_TEST_ROOT') or os.path.dirname(os.path.dirname(R))
    d = os.environ.get('OBSCOOP_HOST_DIR' if who == 'host' else 'OBSCOOP_GUEST_DIR',
                       os.path.join(root, 'obscure2-test' if who == 'host' else 'obscure2-test2'))
    print('== %s log tail' % who)
    try:
        lines = open(os.path.join(d, 'obscoop.log'), 'r', errors='replace').read().splitlines()
        for ln in lines[-18:]:
            print('  ' + ln[:220])
    except Exception as e:
        print('  (no log: %s)' % e)


hp = int(open(R + r'\duo_host.pid').read()); gp = int(open(R + r'\duo_guest.pid').read())
host, guest = bot.Pipe(hp), bot.Pipe(gp)
mh, mg = peek.Proc(hp), peek.Proc(gp)

ROOT = os.environ.get('OBSCOOP_TEST_ROOT') or os.path.dirname(os.path.dirname(R))
DIRS = {'host': os.environ.get('OBSCOOP_HOST_DIR', os.path.join(ROOT, 'obscure2-test')),
        'guest': os.environ.get('OBSCOOP_GUEST_DIR', os.path.join(ROOT, 'obscure2-test2'))}


def log_count(who, needle):
    """How often this copy's log has the line. The game rebuilds a level into the SAME world block when the
    same level is loaded again (the allocator reuses the freed memory), so a world-pointer change is not a
    usable "a load happened" signal; the game's own LoadByName line and the guest's real-load line are."""
    try:
        return open(os.path.join(DIRS[who], 'obscoop.log'), 'r', errors='replace').read().count(needle)
    except OSError:
        return 0

if not wait('both copies in a level (from the first load)', lambda: mode(mh) == 1 and world(mh) and mode(mg) == 1 and world(mg), 120):
    sys.exit('not in a level; is the first load done?')
show('host before', mh)
show('guest before', mg)
w0h, w0g, lv0 = world(mh), world(mg), level(mh)
print('host sync: ', host.cmd('sync')[:300])

print('== CASE 3: the host loads %s again from the pause menu' % SAVE)
h0 = log_count('host', 'request LoadByName')
g0 = log_count('guest', 'real load of')
bot.tap(host, 'ESCAPE')
time.sleep(2.0)
shot(hp, 'case3_pause.png')
bot.press(host, 0, 'DOWN'); time.sleep(0.6)
bot.press(host, 0, 'DOWN'); time.sleep(0.6)
bot.press(host, 0, 'A'); time.sleep(2.0)      # "Load a saved game"
shot(hp, 'case3_load_list.png')
bot.press(host, 0, 'A'); time.sleep(1.2)      # slot 01
shot(hp, 'case3_confirm.png')
bot.press(host, 0, 'UP'); time.sleep(0.5)
bot.press(host, 0, 'A'); time.sleep(2.5)      # the confirm entry

reloaded = wait('the host load issued from the pause menu (the game\'s own LoadByName)',
                lambda: log_count('host', 'request LoadByName') > h0, PAUSE_WAIT)
route = 'pause menu (pad keypresses: the game\'s own LoadByName, no pipe command)'
if not reloaded:
    print('the pause-menu keypresses did not produce a load on the host; falling back to loadsave %s' % SAVE)
    print('host loadsave -> %s' % host.cmd('loadsave ' + SAVE))
    route = 'test-only `loadsave %s` (the pause menu keypresses produced no load)' % SAVE
    reloaded = wait('the host load issued from loadsave', lambda: log_count('host', 'request LoadByName') > h0, PAUSE_WAIT)
show('host after ', mh, w0h)
bot.press(host, 0, 'B'); time.sleep(0.8)   # close anything the keypresses left open (the pause menu)
print('host sync: ', host.cmd('sync')[:300])
shot(hp, 'case3_host_after.png')

followed = wait('the guest loaded that file itself after its world existed',
                lambda: log_count('guest', 'real load of') > g0 and mode(mg) == 1 and humans(mg) >= 2, GUEST_WAIT)
show('guest after', mg, w0g)
print('guest sync:', guest.cmd('sync')[:300])
shot(gp, 'case3_guest_after.png')
print('second load route: %s' % route)
print('second load: host %s level %s -> %s; guest %s level %s -> %s; guest followed: %s' % (
    'reloaded' if reloaded else 'NOT reloaded', lv0, level(mh),
    'reloaded (its own real load)' if log_count('guest', 'real load of') > g0 else 'not reloaded',
    lv0, level(mg), 'YES' if followed else 'NO'))
log_tail('host')
log_tail('guest')
sys.exit(0 if reloaded and followed else 1)
