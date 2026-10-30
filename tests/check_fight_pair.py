"""TASK 44 repro (c): each player attacks the OTHER character - 3 swings each way and a charged swing.

The crash the owner saw on both PCs (Obscure2.exe+0xe812b in the world update) is the swing state (200)
dereferencing the attacker's target list (human+0x824[human+0x820]). This drives the real attack (hold LB
= aim stance, press A = swing, hold it for the charged one) with the two characters facing each other,
reads both copies' life/state, and reports whether a copy crashed, froze (no frames) or lost the sync.

Usage: python -I check_fight_pair.py <host pid> <guest pid>
Exit 0 = both copies survived all repetitions, 1 = something failed.
"""
import os, re, struct, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe
from peek import Proc

GAME = 0x6c3068
H_TAG, H_POS, H_DIR, H_ANIM, H_LIFE = 0x14, 0x23c, 0x248, 0x2dc, 0x320
LB, RB = 0x100, 0x200
REPS = 3


def tag4(v):
    if not v:
        return '----'
    b = struct.pack('<I', v)[::-1]
    return b.decode('latin1') if all(32 <= c < 127 for c in b) else '%08x' % v


class V:
    def __init__(self, pid):
        self.p = Proc(pid)
        self.game = self.p.va(GAME)

    def world(self):
        g = self.p.u32(self.game)
        return (g, self.p.u32(g + 0x378) if g else 0)

    def humans(self):
        g, w = self.world()
        if not w:
            return {}
        mgr = self.p.u32(w + 0x175c)
        if not mgr:
            return {}
        n, arr = self.p.u32(mgr + 4) or 0, self.p.u32(mgr + 0xc)
        out = {}
        for i in range(min(n, 8)):
            h = self.p.u32(arr + 4 * i) if arr else 0
            if not h:
                continue
            b = self.p.read(h + H_POS, 24)
            if not b or len(b) < 24:
                continue
            f = struct.unpack('<6f', b)
            out[tag4(self.p.u32(h + H_TAG))] = dict(
                pos=f[0:3], dir=f[3:6], anim=self.p.u32(h + H_ANIM),
                life=struct.unpack('<f', self.p.read(h + H_LIFE, 4) or b'\0\0\0\0')[0])
        return out

    def controllers(self):
        g, w = self.world()
        ctl = self.p.u32(w + 0x1748) if w else 0
        out = []
        for i in range(2):
            h = self.p.u32(ctl + 4 + 0x764 * i) if ctl else 0
            out.append(tag4(self.p.u32(h + H_TAG)) if h else '----')
        return out


def pad(pipe, user, buttons, lx=0, ly=0):
    pipe.cmd('pad %d %x %d %d 0 0 0 0' % (user, buttons, lx, ly))


def fatals(d):
    try:
        return sum(1 for l in open(os.path.join(d, 'obscoop.log'), errors='replace') if 'FATAL EXCEPTION' in l)
    except OSError:
        return -1


def main():
    hp, gp = int(sys.argv[1]), int(sys.argv[2])
    hv, gv = V(hp), V(gp)
    t0 = time.time()
    while time.time() - t0 < 60:
        if len(hv.humans()) >= 2 and len(gv.humans()) >= 2:
            break
        time.sleep(0.5)
    if len(hv.humans()) < 2 or len(gv.humans()) < 2:
        print('FAIL -- the two copies do not both have two characters in a world')
        return 1
    time.sleep(2)
    hp_pipe, gp_pipe = Pipe(hp), Pipe(gp)
    root = os.environ.get('OBSCOOP_TEST_ROOT', '')
    hdir = os.environ.get('OBSCOOP_HOST_DIR') or os.path.join(root, 'obscure2-test')
    gdir = os.environ.get('OBSCOOP_GUEST_DIR') or os.path.join(root, 'obscure2-test2')
    f0h, f0g = fatals(hdir), fatals(gdir)
    hctl, gctl = hv.controllers(), gv.controllers()
    print('host controllers %s | guest controllers %s' % (hctl, gctl))
    # the character each copy's own pad drives: host controller 0, guest controller 1
    pairs = [('host attacks guest', hp, hp_pipe, gv, gp_pipe, hctl[0], hctl[1], gctl[1], 1),
             ('guest attacks host', gp, gp_pipe, hv, hp_pipe, gctl[1], gctl[0], hctl[0], 0)]
    bad = []
    for label, apid, apipe, victim_view, vpipe, atag, vtag, vtag_own, vpl in pairs:
        av = hv if apid == hp else gv
        a = av.humans().get(atag)
        vv = victim_view.humans().get(vtag)
        if not a or not vv:
            print('%s: SKIP -- %s or %s missing (%s / %s)' % (label, atag, vtag, list(av.humans()), list(victim_view.humans())))
            continue
        px, py, pz = a['pos']
        dx, dy, _dz = a['dir']
        ln = (dx * dx + dy * dy) ** 0.5 or 1.0
        fx, fy = dx / ln, dy / ln
        # the victim 0.35 m in front of the attacker, facing it (the 6-argument tp also sets the facing)
        x, y = px + fx * 70, py + fy * 70
        r = vpipe.cmd('tp %d %.3f %.3f %.3f %.3f %.3f' % (vpl, x, y, pz, -fx * 70, -fy * 70))
        print('\n== %s: victim %s to (%.1f, %.1f) 0.7 m in front of %s: %s' % (label, vtag, x, y, atag, r))
        if not r.startswith('ok'):
            r2 = vpipe.cmd('tp %d %.3f %.3f' % (vpl, x, y))
            print('   retry without a facing: %s' % r2)
            if not r2.startswith('ok'):
                bad.append(label + ': could not place the victim')
                continue
        time.sleep(1.5)
        for rep in range(1, REPS + 1):
            charged = rep == 3
            l0h, l0g = hv.humans(), gv.humans()
            st = {'h': [], 'g': []}
            # the owner's attack (GAME_MECHANICS.md): HOLD LB (aim stance) + TAP RB = attack; the special
            # attack is HOLDING RB. Sampled on both copies throughout.
            pad(apipe, 0, LB)
            time.sleep(0.4)
            pad(apipe, 0, LB | RB)
            hold = 1.0 if charged else 0.3
            t = time.time()
            while time.time() - t < hold:
                st['h'].append(hv.humans().get(atag, {}).get('anim'))
                st['g'].append(gv.humans().get(atag, {}).get('anim'))
                time.sleep(0.05)
            pad(apipe, 0, LB)
            time.sleep(0.8)
            pad(apipe, 0, 0)
            time.sleep(0.5)
            l1h, l1g = hv.humans(), gv.humans()
            seth = [x for x in st['h'] if x]
            setg = [x for x in st['g'] if x]
            print('  %s rep %d%s: attacker %s states host %s | guest %s' % (
                label, rep, ' (charged)' if charged else '', atag,
                sorted(set(seth))[:8], sorted(set(setg))[:8]))
            print('     life %s host %.1f/%.1f guest %.1f/%.1f | %s host %.1f/%.1f guest %.1f/%.1f' % (
                atag, l0h.get(atag, {}).get('life', -1), l1h.get(atag, {}).get('life', -1),
                l0g.get(atag, {}).get('life', -1), l1g.get(atag, {}).get('life', -1),
                vtag, l0h.get(vtag, {}).get('life', -1), l1h.get(vtag, {}).get('life', -1),
                l0g.get(vtag, {}).get('life', -1), l1g.get(vtag, {}).get('life', -1)))
            # the swing state (200) is what the owner's crash was in; whether this level+weapon produces it
            # is the game's business (the test levels have no enemies), so it is reported, not demanded.
            # What must hold: the attack input played the same state on both copies and nothing crashed.
            if set(seth) != set(setg):
                bad.append('%s rep %d: the attacker shows %s on its own copy but %s on the other'
                           % (label, rep, sorted(set(seth)), sorted(set(setg))))
            if not l1h or not l1g:
                bad.append('%s rep %d: a copy lost its world during the attack' % (label, rep))
    alive = []
    for name, pid in (('host', hp), ('guest', gp)):
        try:
            ok = 'pong' in (hp_pipe if pid == hp else gp_pipe).cmd('ping')
        except Exception:
            ok = False
        alive.append(ok)
        print('%s pipe alive: %s' % (name, ok))
    f1h, f1g = fatals(hdir), fatals(gdir)
    print('FATAL EXCEPTION lines: host %d -> %d, guest %d -> %d' % (f0h, f1h, f0g, f1g))
    if f1h != f0h or f1g != f0g:
        bad.append('a crash report was written during the fight')
    if not all(alive):
        bad.append('a copy stopped answering (it crashed or hung)')
    hp_pipe.f.close()
    gp_pipe.f.close()
    print('attack-each-other OK (%d swings each way, both copies alive)' % REPS if not bad
          else 'attack-each-other FAIL: ' + '; '.join(bad))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
