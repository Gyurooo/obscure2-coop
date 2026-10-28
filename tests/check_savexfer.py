"""The guest's saves are byte-identical to the host's.

TASK 14: the game does not read <exe>\\Save. Its save manager goes through Steam RemoteStorage, which this
mod's proxy maps to <exe>\\coop_profile\\remote (obscoop2.c remote_path); the game rewrites those files when
it loads a save, so they are the live copies. The save transfer now sends THOSE (the transfer's
save_existing_path prefers them) and the guest writes both folders, so the guest's live copies must match
the host's live copies and the guest's Save\\ mirror must match them too. The host's own Save\\ folder is
only the owner's snapshot of the same slots (the game never writes it), so it is printed but not compared.

Run after a transfer (duo.py start of the pair, no games needed afterwards).
"""
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
    hl = sha(os.path.join(host, 'coop_profile', 'remote', n))      # the live copy the game reads
    hs = sha(os.path.join(host, 'Save', n))                        # the owner's snapshot
    gl = sha(os.path.join(guest, 'coop_profile', 'remote', n))
    gs = sha(os.path.join(guest, 'Save', n))
    print('%s host live %s, guest live %s, guest Save %s (host Save snapshot %s)' % (
        n, (hl or 'MISSING')[:12], (gl or 'MISSING')[:12], (gs or 'MISSING')[:12], (hs or 'MISSING')[:12]))
    if hl is None or gl != hl or gs != hl:
        bad += 1
assert not bad, '%d save file(s) missing or different on the guest' % bad
print('save transfer OK (both guest folders hold the host\'s live saves)')
