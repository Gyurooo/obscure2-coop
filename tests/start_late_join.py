"""CASE 1 (TASK 14, host first): the host copy starts alone and loads its save, and only THEN is the guest
copy started, at the main menu, to connect.

Order matters and is measured, not slept through blindly:
  1. wait for the host's main menu (mode 2, no world),
  2. ask the host for the game's own load of <save> (`loadsave <save>`: the save manager's open +
     LoadByName, exactly what the game's own menu does),
  3. wait until the HOST is in a level with its world up, then let it settle (default 10 s) — this is the
     "host already in game" moment the case is about,
  4. only now start the guest copy (`duo.py start-guest`), which sits at the main menu and connects,
  5. wait until the guest is in a level too, then print both copies' state and the log tails.

Usage: python -I start_late_join.py [save file] [settle seconds] [timeout]
Env: OBSCOOP_TEST_ROOT / OBSCOOP_DLL are inherited by the started guest copy (duo.py).
"""
import os, struct, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot, peek

R = os.path.dirname(os.path.abspath(__file__))
SAVE = sys.argv[1] if len(sys.argv) > 1 else 'game0.sav'
SETTLE = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
LIMIT = int(sys.argv[3]) if len(sys.argv) > 3 else 120
PY = sys.executable or 'python'


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


def log_tail(who):
    root = os.environ.get('OBSCOOP_TEST_ROOT') or os.path.dirname(os.path.dirname(R))
    d = os.environ.get('OBSCOOP_HOST_DIR' if who == 'host' else 'OBSCOOP_GUEST_DIR',
                       os.path.join(root, 'obscure2-test' if who == 'host' else 'obscure2-test2'))
    print('== %s log tail' % who)
    try:
        lines = open(os.path.join(d, 'obscoop.log'), 'r', errors='replace').read().splitlines()
        for ln in lines[-16:]:
            print('  ' + ln[:220])
    except Exception as e:
        print('  (no log: %s)' % e)


hp = int(open(R + r'\duo_host.pid').read())
mh = peek.Proc(hp)
host = bot.Pipe(hp)

show('host at start ', mh)
wait('the host at the main menu (mode 2, no world)', lambda m: mode(m) == 2 and not world(m), 60, (mh,))
time.sleep(2)
show('host at menu  ', mh)
print('host net: ', host.cmd('net')[:160])
print('host loadsave %s -> %s' % (SAVE, host.cmd('loadsave ' + SAVE)))
wait('the host in a level', lambda m: mode(m) == 1 and world(m) and humans(m) >= 1, LIMIT, (mh,))
show('host after load', mh)
print('host sync: ', host.cmd('sync')[:400])
print('--- the host is in game now; settling %.0f s before the guest even starts ---' % SETTLE)
time.sleep(SETTLE)

print('== starting the guest copy now (it stays at the main menu and connects)')
out = subprocess.run([PY, '-I', os.path.join(R, 'duo.py'), 'start-guest'], cwd=R, capture_output=True, text=True)
print((out.stdout or '').strip()[-400:])
if out.returncode:
    print((out.stderr or '').strip()[-400:])
gp = int(open(R + r'\duo_guest.pid').read())
mg = peek.Proc(gp)
guest = bot.Pipe(gp)
show('guest at start', mg)

wait('the guest at the main menu (it connected)', lambda m: mode(m) == 2 and not world(m), 60, (mg,))
print('guest net:', guest.cmd('net')[:160])
wait('the guest in a level (it must load the host file itself)',
     lambda m: mode(m) == 1 and world(m) and humans(m) >= 2, LIMIT, (mg,))
show('guest after join', mg)
print('guest sync:', guest.cmd('sync')[:400])
print('host sync: ', host.cmd('sync')[:400])
log_tail('host')
log_tail('guest')
print('late join: host level %s, guest level %s' % (level(mh), level(mg)))
