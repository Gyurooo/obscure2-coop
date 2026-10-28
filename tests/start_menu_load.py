"""New real flow: both copies start into the main menu, the guest is left completely untouched, and the
HOST loads save 01 through the game's own menu-load path (`loadsave game0.sav` = the save manager's open
+ LoadByName, the same two calls the pause menu makes). Waits for the host's level and for the guest to
bring itself into the same level from the transferred save file.

Usage: python -I start_menu_load.py [host save file] [timeout]
Prints what each copy has (mode, world, level, humans) and the sync lines, so the run log says exactly
how far each copy got.
"""
import sys, os, time, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot, peek

R = os.path.dirname(os.path.abspath(__file__))
# The save to load: argv[1], else OBSCOOP_MENU_SAVE (CASE 2 uses o2.sav, the file the main menu's own Load
# Game is hard-wired to), else the slot named by OBSCOOP_SLOT (0..9 -> game0.sav..game9.sav, TASK 15),
# else save 01.
if len(sys.argv) > 1:
    SAVE = sys.argv[1]
elif os.environ.get('OBSCOOP_MENU_SAVE'):
    SAVE = os.environ['OBSCOOP_MENU_SAVE']
elif os.environ.get('OBSCOOP_SLOT') not in (None, ''):
    SAVE = 'game%s.sav' % os.environ['OBSCOOP_SLOT']
else:
    SAVE = 'game0.sav'
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 90
hp = int(open(R + r'\duo_host.pid').read()); gp = int(open(R + r'\duo_guest.pid').read())
host, guest = bot.Pipe(hp), bot.Pipe(gp)
mh, mg = peek.Proc(hp), peek.Proc(gp)


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


def show(who, m):
    print('%s: mode %s world %#x level %s humans %s' % (who, mode(m), world(m) or 0, level(m), humans(m)))


def wait(label, pred, limit, procs):
    t = time.time()
    while time.time() - t < limit:
        if all(pred(m) for m in procs):
            print('ok:', label, 'after %.1f s' % (time.time() - t))
            return True
        time.sleep(0.5)
    print('TIMEOUT waiting for', label, [bool(pred(m)) for m in procs])
    return False


show('host at start ', mh)
show('guest at start', mg)
wait('the game object', lambda m: mode(m) is not None, 40, (mh, mg))
# This build's front end is mode 2 (mode 4 is the in-game pause menu); no world until the load.
wait('both copies at the main menu (mode 2, no world)', lambda m: mode(m) == 2 and not world(m), LIMIT, (mh, mg))
time.sleep(2)
show('host at menu  ', mh)
show('guest at menu ', mg)
print('host net: ', host.cmd('net')[:160])
print('guest net:', guest.cmd('net')[:160])

# The guest may only load a save the host has finished transferring; the host announces that with
# PKT_SAVES_DONE, which the guest's `sync` line reports as saves_done 1.
t = time.time()
g_sync = ''
while time.time() - t < 45:
    g_sync = guest.cmd('sync')
    if 'saves_done 1' in g_sync:
        break
    time.sleep(1)
print('guest sync after the transfer wait: %s' % g_sync[:260])

print('host loadsave %s -> %s' % (SAVE, host.cmd('loadsave ' + SAVE)))
wait('the host in a level', lambda m: mode(m) == 1 and world(m) and humans(m) >= 1, LIMIT, (mh,))
show('host after load', mh)
wait('the guest in the same level (it loads the save itself)',
     lambda m: mode(m) == 1 and world(m) and humans(m) >= 1, LIMIT, (mg,))
show('guest after load', mg)
print('host sync: ', host.cmd('sync')[:400])
print('guest sync:', guest.cmd('sync')[:400])
root = os.environ.get('OBSCOOP_TEST_ROOT') or os.path.dirname(os.path.dirname(R))
for name, d in (('host', os.environ.get('OBSCOOP_HOST_DIR', os.path.join(root, 'obscure2-test'))),
                ('guest', os.environ.get('OBSCOOP_GUEST_DIR', os.path.join(root, 'obscure2-test2')))):
    print('== %s log tail' % name)
    try:
        lines = open(os.path.join(d, 'obscoop.log'), 'r', errors='replace').read().splitlines()
        for ln in lines[-14:]:
            print('  ' + ln[:220])
    except Exception as e:
        print('  (no log: %s)' % e)
