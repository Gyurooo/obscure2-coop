"""Start / stop a host and a guest copy of Obscure II on one PC.
  python -I duo.py start [extra host env K=V ...] -- [extra guest env K=V ...]
  python -I duo.py stop
Host: obscure2-test, guest: obscure2-test2, UDP on loopback. Pids in runs2/duo_host.pid / duo_guest.pid.
Owner files are snapshotted before and diffed after (runs2/snapshot.sh)."""
import os, subprocess, sys, shutil, time
L = os.environ.get('OBSCOOP_TEST_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
R = os.path.dirname(os.path.abspath(__file__))
dll = L + r'\obscure2-coop-repo\build\xinput1_3.dll'
BASH = r'C:\Program Files\Git\bin\bash.exe'

def sh(args, **kw):
    return subprocess.run([BASH, '-c', args], capture_output=True, text=True, **kw).stdout

def alive(name):
    out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq ' + name, '/FO', 'CSV', '/NH'], capture_output=True, text=True, errors='replace').stdout
    return [int(l.split('","')[1]) for l in out.strip().splitlines() if l.startswith('"')]

def launch(dirname, env_extra, pidfile):
    d = os.path.join(L, dirname)
    shutil.copy(dll, os.path.join(d, 'xinput1_3.dll'))
    open(os.path.join(d, 'obscoop.log'), 'w').close()
    env = dict(os.environ, SteamAppId='254480', SteamGameId='254480', OBSCOOP_BACKGROUND='1', OBSCOOP_HIDE_REAL_PADS='1',
               OBSCOOP_WINDOWED='1', OBSCOOP_MULTI='1', OBSCOOP_UDP='27961', **({'OBSCOOP_DEBUG_SYNC': '1'} if os.environ.get('DUO_DEBUG') else {}))
    env.update(env_extra)
    p = subprocess.Popen([os.path.join(d, 'Obscure2.exe')], cwd=d, env=env, creationflags=0x00000008 | 0x00000200)
    open(pidfile, 'w').write(str(p.pid))
    return p.pid

def other_only(me):
    other = 'duo_guest.pid' if me == 'start-host' else 'duo_host.pid'
    try:
        return alive('Obscure2.exe') == [int(open(other).read())]
    except Exception:
        return False


def kv(items):
    return dict(i.split('=', 1) for i in items)

if sys.argv[1] in ('start-host', 'start-guest'):
    rest = sys.argv[2:]
    if sys.argv[1] == 'start-host':
        if alive('Obscure2.exe') and not other_only('start-host'): sys.exit('an Obscure2 process is already running; refusing')
        sh('sh ' + R + '/snapshot.sh > ' + R + '/duo-before.txt 2>&1')
        print('host pid', launch(os.environ.get('OBSCOOP_HOST_DIR', os.path.join(L, 'obscure2-test')), dict(OBSCOOP_ROLE='host', OBSCOOP_WINX='20', OBSCOOP_WINY='20', **kv(rest)), R + r'\duo_host.pid'))
    else:
        print('guest pid', launch(os.environ.get('OBSCOOP_GUEST_DIR', os.path.join(L, 'obscure2-test2')), dict(OBSCOOP_ROLE='guest', OBSCOOP_WINX='840', OBSCOOP_WINY='20', OBSCOOP_REGSUFFIX='_2', **kv(rest)), R + r'\duo_guest.pid'))
    time.sleep(6)
elif sys.argv[1] == 'start':
    rest = sys.argv[2:]
    if '--' in rest:
        i = rest.index('--'); h, g = rest[:i], rest[i + 1:]
    else:
        h, g = rest, []
    if alive('Obscure2.exe'):
        sys.exit('an Obscure2 process is already running; refusing')
    sh('sh ' + R + '/snapshot.sh > ' + R + '/duo-before.txt 2>&1')
    hp = launch(os.environ.get('OBSCOOP_HOST_DIR', os.path.join(L, 'obscure2-test')), dict(OBSCOOP_ROLE='host', OBSCOOP_WINX='20', OBSCOOP_WINY='20', **kv(h)), R + r'\duo_host.pid')
    time.sleep(2)
    gp = launch(os.environ.get('OBSCOOP_GUEST_DIR', os.path.join(L, 'obscure2-test2')), dict(OBSCOOP_ROLE='guest', OBSCOOP_WINX='840', OBSCOOP_WINY='20', OBSCOOP_REGSUFFIX='_2', **kv(g)), R + r'\duo_guest.pid')
    time.sleep(8)
    print('host pid', hp, 'guest pid', gp, 'running', alive('Obscure2.exe'))
elif sys.argv[1] == 'stop':
    for n in ('host', 'guest'):
        try:
            pid = int(open(R + r'\duo_%s.pid' % n).read())
            subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True)
        except Exception as e:
            print(n, e)
    time.sleep(2)
    print('still running:', alive('Obscure2.exe'))
    sh('sh ' + R + '/snapshot.sh > ' + R + '/duo-after.txt 2>&1')
    d = sh('diff ' + R + '/duo-before.txt ' + R + '/duo-after.txt | grep -v remotecache | grep -v "^---" | grep -v "^[0-9,c]*$"')
    print('OWNER FILES UNCHANGED (apart from Steam remotecache.vdf)' if not d.strip() else 'OWNER FILES CHANGED:\n' + d[:600])
