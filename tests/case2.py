"""CASE 2 (TASK 14): the file the host's load names must reach the guest before the guest loads.

What this run establishes, in order:

1. `o2.sav` (the main menu's own Continue/Load Game file, FINDINGS_12 (a)) exists on the HOST copy only
   (Save\\o2.sav and the game's real save folder coop_profile\\remote\\o2.sav) — the guest has neither.
2. The join transfer finishes (the guest's `sync` says saves_done 1), then this script deletes the guest's
   copy of the slot file it is about to be asked for (<save>, both folders), so the guest can only get it
   from the host's transfer.
3. The host tries o2.sav with the game's own two calls (`loadsave o2.sav`) and reports what the game does
   with it (in this build its save manager refuses the name — OBSERVED in the log).
4. The host then loads <save> through the MAIN MENU's own save list (Continue -> slot -> confirm, pad
   keypresses), with the test-only `loadsave <save>` as a fallback when the keypresses do not load it.
   The file the load names is a slot the guest has just lost, i.e. exactly "the file the host's load
   names": the host must send it, the guest must wait for it and then build its world from it.
5. Both copies' state and the log tails are printed; the runner then runs the checks.

Usage: python -I case2.py [save file] [guest wait]
"""
import os, struct, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot, peek

R = os.path.dirname(os.path.abspath(__file__))
SAVE = sys.argv[1] if len(sys.argv) > 1 else 'game1.sav'
GUEST_WAIT = int(sys.argv[2]) if len(sys.argv) > 2 else 120
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


def show(who, m):
    print('%s: mode %s world %#x level %s humans %s' % (who, mode(m), world(m) or 0, level(m), humans(m)))


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


def log_tail(who, n=20):
    root = os.environ.get('OBSCOOP_TEST_ROOT') or os.path.dirname(os.path.dirname(R))
    d = os.environ.get('OBSCOOP_HOST_DIR' if who == 'host' else 'OBSCOOP_GUEST_DIR',
                       os.path.join(root, 'obscure2-test' if who == 'host' else 'obscure2-test2'))
    print('== %s log tail' % who)
    try:
        lines = open(os.path.join(d, 'obscoop.log'), 'r', errors='replace').read().splitlines()
        for ln in lines[-n:]:
            print('  ' + ln[:220])
    except Exception as e:
        print('  (no log: %s)' % e)


def save_files(d, name):
    return [os.path.join(d, 'Save', name), os.path.join(d, 'coop_profile', 'remote', name)]


hp = int(open(R + r'\duo_host.pid').read()); gp = int(open(R + r'\duo_guest.pid').read())
host, guest = bot.Pipe(hp), bot.Pipe(gp)
mh, mg = peek.Proc(hp), peek.Proc(gp)
root = os.environ.get('OBSCOOP_TEST_ROOT') or os.path.dirname(os.path.dirname(R))
hostdir = os.environ.get('OBSCOOP_HOST_DIR', os.path.join(root, 'obscure2-test'))
guestdir = os.environ.get('OBSCOOP_GUEST_DIR', os.path.join(root, 'obscure2-test2'))

wait('both copies at the main menu', lambda: mode(mh) == 2 and not world(mh) and mode(mg) == 2 and not world(mg), 90)
# The join transfer must be over before the guest's file is deleted, or the transfer would simply re-create it.
t = time.time()
while time.time() - t < 60 and 'saves_done 1' not in guest.cmd('sync'):
    time.sleep(1)
print('guest sync after the join transfer: %s' % guest.cmd('sync')[:200])
print('o2.sav on the host: %s' % ['yes' if os.path.exists(p) else 'no' for p in save_files(hostdir, 'o2.sav')])
print('o2.sav on the guest: %s' % ['yes' if os.path.exists(p) else 'no' for p in save_files(guestdir, 'o2.sav')])

print('== the host tries o2.sav, the file the main menu is hard-wired to (game\'s own two calls)')
print('host loadsave o2.sav -> %s' % host.cmd('loadsave o2.sav'))
time.sleep(12)
show('host after o2.sav attempt', mh)
shot(hp, 'case2_o2_attempt.png')

print('== the guest loses its own copy of %s (both save folders): it can only come from the host now' % SAVE)
for p in save_files(guestdir, SAVE):
    if os.path.exists(p):
        os.remove(p)
        print('  removed %s' % p)
print('  guest %s now: %s' % (SAVE, ['yes' if os.path.exists(p) else 'no' for p in save_files(guestdir, SAVE)]))

print('== the host loads %s from the main menu\'s own save list (Continue -> slot -> confirm)' % SAVE)
w0h = world(mh)
bot.press(host, 0, 'DOWN'); time.sleep(0.6)
bot.press(host, 0, 'A'); time.sleep(2.0)       # Continue opens the save list
shot(hp, 'case2_continue_list.png')
bot.press(host, 0, 'DOWN'); time.sleep(0.8)    # slot 02 (game1.sav)
bot.press(host, 0, 'A'); time.sleep(1.5)
shot(hp, 'case2_slot_confirm.png')
bot.press(host, 0, 'UP'); time.sleep(0.5)
bot.press(host, 0, 'A'); time.sleep(2.5)
loaded = wait('the host in a level from the main menu save list', lambda: mode(mh) == 1 and world(mh) and world(mh) != w0h, 40)
route = 'main menu save list (Continue -> slot, pad keypresses)'
if not loaded:
    print('the main-menu keypresses did not load it; falling back to the test-only loadsave %s' % SAVE)
    print('host loadsave %s -> %s' % (SAVE, host.cmd('loadsave ' + SAVE)))
    route = 'test-only `loadsave %s` (the main-menu keypresses produced no load)' % SAVE
    loaded = wait('the host in a level from loadsave', lambda: mode(mh) == 1 and world(mh) and world(mh) != w0h, 60)
show('host after load', mh)
shot(hp, 'case2_host_after.png')
print('host sync: ', host.cmd('sync')[:300])

followed = wait('the guest in the same level (it loaded the transferred file itself)',
                lambda: mode(mg) == 1 and world(mg) and humans(mg) >= 2, GUEST_WAIT)
show('guest after load', mg)
print('guest sync:', guest.cmd('sync')[:300])
shot(gp, 'case2_guest_after.png')
print('load route: %s' % route)
print('levels: host %s guest %s; guest followed: %s' % (level(mh), level(mg), 'YES' if followed else 'NO'))
log_tail('host')
log_tail('guest')
sys.exit(0 if loaded and followed else 1)
