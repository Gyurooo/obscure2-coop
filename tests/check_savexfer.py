"""The guest's Save/game0..9.sav are byte-identical to the host's (run after deleting the guest's saves, then duo.py start)."""
import hashlib, os, sys
root = os.environ.get('OBSCOOP_TEST_ROOT', os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
host = os.environ.get('OBSCOOP_HOST_DIR', os.path.join(root, 'obscure2-test'))
guest = os.environ.get('OBSCOOP_GUEST_DIR', os.path.join(root, 'obscure2-test2'))
def sha(p):
    try:
        return hashlib.sha256(open(p, 'rb').read()).hexdigest()
    except OSError:
        return None
bad = 0
for i in range(10):
    n = 'game%d.sav' % i
    h, g = sha(os.path.join(host, 'Save', n)), sha(os.path.join(guest, 'Save', n))
    print(n, 'host', (h or 'MISSING')[:12], 'guest', (g or 'MISSING')[:12])
    if h is None or h != g:
        bad += 1
assert not bad, '%d save file(s) missing or different on the guest' % bad
print('save transfer OK')
