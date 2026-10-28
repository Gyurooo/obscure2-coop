"""CASE 2 (TASK 14) test stand-in for the file the main menu's own Load Game is hard-wired to: o2.sav.

  python -I o2_file.py prepare   make o2.sav on the HOST copy a copy of game0.sav (level I100) in both
                                 places a save can live — Save\\o2.sav and the game's real save folder
                                 coop_profile\\remote\\o2.sav (the mod's Steam RemoteStorage proxy,
                                 obscoop2.c remote_path) — and remove it on the GUEST copy, so the guest's
                                 copy can only appear through the host's save transfer
  python -I o2_file.py check     print both copies' o2.sav in both places (size + sha256)

The real game's main menu Load Game is hard-wired to `o2.sav` (FINDINGS_12 (a)). Only the host gets this
extra file; the numbered slots are untouched. Both folders are the test copies, never the install.
"""
import hashlib, os, shutil, sys

R = os.path.dirname(os.path.abspath(__file__))
root = os.environ.get('OBSCOOP_TEST_ROOT') or os.path.dirname(os.path.dirname(R))
host = os.environ.get('OBSCOOP_HOST_DIR', os.path.join(root, 'obscure2-test'))
guest = os.environ.get('OBSCOOP_GUEST_DIR', os.path.join(root, 'obscure2-test2'))


def places(d, name):
    return [os.path.join(d, 'Save', name), os.path.join(d, 'coop_profile', 'remote', name)]


def sha(p):
    try:
        return hashlib.sha256(open(p, 'rb').read()).hexdigest()
    except OSError:
        return None


def report():
    for name, d in (('host', host), ('guest', guest)):
        for p in places(d, 'o2.sav'):
            h = sha(p)
            print('%s %s: %s' % (name, p[len(d) + 1:], 'MISSING' if h is None else '%d bytes %s' % (os.path.getsize(p), h[:16])))


if sys.argv[1] == 'prepare':
    src = os.path.join(host, 'Save', 'game0.sav')
    for p in places(host, 'o2.sav'):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        shutil.copyfile(src, p)
        print('host: %s = a copy of game0.sav (%d bytes)' % (p[len(host) + 1:], os.path.getsize(p)))
    for p in places(guest, 'o2.sav') + [os.path.join(guest, 'Save.bak', 'o2.sav')]:
        if os.path.exists(p):
            os.remove(p)
            print('guest: removed %s' % p[len(guest) + 1:])
    report()
else:
    report()
