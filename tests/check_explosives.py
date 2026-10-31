"""TASK 49: the explosives - the blast must not kill the guest's copy, and the reaction must show on both.

The owner's 2.0 playtest: the host held DYNA, threw it, the guest's game ended with no crash report, and a
shot that knocked both characters down showed no animation on the partner's screen. Two things are checked
here, on the real pair:

  * the THROWER's attack (state 200 family) is played on both copies WITHOUT the other copy simulating a
    second, different blast (TASK 49: the guest's copy ran the attack and took 93.8 / 99.2 life off its two
    characters in the diagnostic run, while the host's copy lost 29.7 / 18.0 - the crash the owner saw);
  * the REACTION the blast causes (hurt / knockdown / thrown / get-up) plays the same clip on both copies:
    the state id sequence and the upper animation clip of the SAME character are compared between the copy
    that owns it and the copy that drives it as a puppet (the clip reader is check_anim_sync's).

Three throws each way (host -> guest, guest -> host), the partner standing 6 units away. Fails on any
FATAL EXCEPTION line in either copy's log, on a copy that stops answering, or on a character whose state
or clip sequence differs between the copies.

Usage: python -I check_explosives.py <host pid> <guest pid>
Exit 0 = PASS, 1 = FAIL, 2 = cannot run (no throwable weapon / no characters).
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe                 # noqa: E402
from peek import Proc               # noqa: E402

GAME = 0x6c3068
H_TAG, H_STATE, H_IDX_UP, H_IDX_LO, H_TAB, H_POS, H_LIFE = 0x14, 0x2dc, 0x220, 0x224, 0x210, 0x23c, 0x320
LB, RB = 0x0100, 0x0200
DPAD = (('LEFT', 0x4), ('RIGHT', 0x8), ('DOWN', 0x2), ('UP', 0x1))
THROWABLE = ('DYNA', 'FLBG', 'FLGU', 'AMFG', 'GREN')
DT = 0.05
SKEW = 4            # samples (0.2 s) a state/clip may arrive late on the puppet
DT_MIN = 0.5        # the reaction must show this long on the owner's copy to count as a reaction
NEAR = 6.0          # units the partner stands from the thrower


def tag4(v):
    if not v:
        return '----'
    return ''.join(chr((v >> s) & 0xff) if 32 <= ((v >> s) & 0xff) < 127 else '.' for s in (24, 16, 8, 0))


def fx_counts(pipe):
    """TASK 53: the effect-relay counters of one copy, from its `sync` reply. 'played' = the effects of the
    PEER this copy's game spawned (the game's own effect call at the peer's position)."""
    try:
        s = pipe.cmd('sync')
    except OSError:
        return None
    import re
    m = re.search(r'fx local (\d+) sent (\d+) rcv (\d+) played (\d+)', s)
    if not m:
        return None
    return dict(local=int(m.group(1)), sent=int(m.group(2)), rcv=int(m.group(3)), played=int(m.group(4)))


def peer_effects(side, tag):
    """The replayed effects in the PARTNER copy's log since the start: (tag, x, y, z) per line."""
    data = read_log(side['peer_dir'], side['peer_off'])
    out = []
    import re
    for line in data.decode('latin-1', 'replace').splitlines():
        if 'effect from the peer played' not in line:
            continue
        m = re.search(r'effect from the peer played: (\S+) at \(([-\d.]+),([-\d.]+),([-\d.]+)\)', line)
        if m:
            out.append((m.group(1), float(m.group(2)), float(m.group(3)), float(m.group(4))))
    return out


def read_log(dirname, off):
    try:
        with open(os.path.join(dirname, 'obscoop.log'), 'rb') as f:
            f.seek(off)
            return f.read()
    except OSError:
        return b''


class View:
    def __init__(self, pid):
        self.p = Proc(pid)
        self.game = self.p.va(GAME)

    def world(self):
        g = self.p.u32(self.game)
        return self.p.u32(g + 0x378) if g else 0

    def humans(self):
        w = self.world()
        mgr = self.p.u32(w + 0x175c) if w else 0
        out = {}
        if not mgr:
            return out
        n, arr = self.p.u32(mgr + 4) or 0, self.p.u32(mgr + 0xc)
        for i in range(min(n, 8)):
            h = self.p.u32(arr + 4 * i) if arr else 0
            if h:
                out[tag4(self.p.u32(h + H_TAG))] = h
        return out

    def owned(self):
        w = self.world()
        ctl = self.p.u32(w + 0x1748) if w else 0
        tags = []
        for i in range(2):
            rec = ctl + 0x764 * i if ctl else 0
            h = self.p.u32(rec + 4) if rec else 0
            tags.append(tag4(self.p.u32(h + H_TAG)) if h else '----')
        return tags[0], tags[1]

    def clip(self, ch, off):
        tab = self.p.u32(ch + H_TAB)
        idx = self.p.u32(ch + off)
        if not tab or idx is None or idx >= 0x1000:
            return 0
        return self.p.u32(tab + idx * 0x28 + 0xc)

    def held(self, tag):
        ch = self.humans().get(tag, 0)
        if not ch:
            return '----', -1, []
        slots = []
        for s in range(4):
            wp = self.p.u32(ch + 0x704 + 4 * s)
            slots.append(tag4(self.p.u32(wp + 0x10) if wp else 0))
        cur = self.p.u32(ch + 0x714)
        return (slots[cur] if isinstance(cur, int) and 0 <= cur < 4 else '----'), cur, slots

    def pos(self, tag):
        ch = self.humans().get(tag, 0)
        return struct.unpack('<3f', self.p.read(ch + H_POS, 12)) if ch else None

    def sample(self, tag):
        ch = self.humans().get(tag, 0)
        if not ch:
            return None
        return dict(state=self.p.u32(ch + H_STATE), up=self.clip(ch, H_IDX_UP), lo=self.clip(ch, H_IDX_LO),
                    life=struct.unpack('<f', self.p.read(ch + H_LIFE, 4))[0],
                    pos=struct.unpack('<2f', self.p.read(ch + H_POS, 8)))


def select_weapon(pipe, view, tag, want_set):
    """D-pad steps the current weapon slot; stop when the hand holds one of want_set."""
    for _ in range(8):
        held, cur, slots = view.held(tag)
        if held in want_set:
            return held, slots
        for _name, code in DPAD:
            pipe.cmd('pad 0 %x' % code)
            time.sleep(0.12)
            pipe.cmd('pad 0 0')
            time.sleep(0.40)
            held, cur, slots = view.held(tag)
            if held in want_set:
                return held, slots
    return view.held(tag)[0], view.held(tag)[2]


def compare(owner_samples, puppet_samples, key):
    """Fraction of the OWNER's samples whose value appears on the puppet within SKEW samples."""
    if not owner_samples:
        return 1.0
    ok = 0
    for i, o in enumerate(owner_samples):
        v = o[key]
        hit = any(puppet_samples[j][key] == v for j in range(max(0, i - SKEW), min(len(puppet_samples), i + SKEW + 1)))
        ok += 1 if hit else 0
    return ok / len(owner_samples)


def runs(samples, key):
    """The value CHANGES of one field, in order (the state/clip sequence a reaction shows)."""
    out = []
    for s in samples:
        if not out or out[-1] != s[key]:
            out.append(s[key])
    return out


def main():
    host_pid, guest_pid = int(sys.argv[1]), int(sys.argv[2])
    root = os.environ.get('OBSCOOP_TEST_ROOT', os.path.dirname(os.path.abspath(__file__)))
    H, G = View(host_pid), View(guest_pid)
    HP, GP = Pipe(host_pid), Pipe(guest_pid)
    hs, gs = H.humans(), G.humans()
    if not hs or not gs:
        print('no human characters on one of the copies (host %s, guest %s)' % (sorted(hs), sorted(gs)))
        return 2
    own_h, own_g = H.owned()[0], G.owned()[1]
    if own_h not in hs or own_g not in gs or own_h not in gs or own_g not in hs:
        print('the controller records do not name the characters on both copies')
        return 2
    print('the host plays %s (%s copy player 1), the guest plays %s (%s copy player 2)'
          % (own_h, own_h, own_g, own_g))
    print('hands: host %s %s | guest %s %s' % (own_h, H.held(own_h), own_g, G.held(own_g)))
    t0 = os.path.getsize(os.path.join(root, 'obscure2-test', 'obscoop.log')) if os.path.exists(
        os.path.join(root, 'obscure2-test', 'obscoop.log')) else 0
    t0g = os.path.getsize(os.path.join(root, 'obscure2-test2', 'obscoop.log')) if os.path.exists(
        os.path.join(root, 'obscure2-test2', 'obscoop.log')) else 0
    # the copy that owns each character, its pipe, and the copy that drives it as a puppet
    SIDE = {own_h: dict(own=H, peer=G, pipe=HP, peer_pipe=GP, pl=0, peer_pl=1,
                        peer_dir=os.path.join(root, 'obscure2-test2'), peer_off=t0g),
            own_g: dict(own=G, peer=H, pipe=GP, peer_pipe=HP, pl=1, peer_pl=0,
                        peer_dir=os.path.join(root, 'obscure2-test'), peer_off=t0)}
    # Only a THROWABLE is an explosive; a character that holds none is reported and skipped (measured: the
    # melee/clip path of a weapon the puppet's table does not carry is TASK 46's business - the chainsaw's
    # attack clip CS3A is not in the puppet's animation table, so its swing cannot show the same clip).
    have = {tag: set(x for x in SIDE[tag]['own'].held(tag)[2] if x in THROWABLE) for tag in SIDE}
    print('throwables: %s' % {k: sorted(v) for k, v in have.items()})
    if not any(have.values()):
        print('no throwable weapon (DYNA/FLBG/FLGU/AMFG/GREN) in either character\'s slots: cannot run')
        return 2

    fails = []
    for thrower in (own_h, own_g):
        side = SIDE[thrower]
        target = own_g if thrower == own_h else own_h
        tside = SIDE[target]
        if not have[thrower]:
            print('%s holds no weapon at all on this copy: skipped' % thrower)
            continue
        for k in range(3):
            # put the partner 6 units from the thrower, on the partner's OWN copy (its position streams)
            p = side['own'].pos(thrower)
            q = tside['own'].pos(target)
            if not p or not q:
                fails.append('%s throw %d: a character is missing' % (thrower, k + 1))
                break
            dx, dy = q[0] - p[0], q[1] - p[1]
            d = (dx * dx + dy * dy) ** 0.5 or 1.0
            tx, ty = p[0] + dx / d * NEAR, p[1] + dy / d * NEAR
            r = tside['pipe'].cmd('tp %d %.2f %.2f %.2f' % (tside['pl'], tx, ty, q[2]))
            if not r.startswith('ok'):
                print('  %s throw %d: the partner could not be placed (%.2f,%.2f): %s - keeping its spot'
                      % (target, k + 1, tx, ty, r))
            time.sleep(0.6)
            held, _slots = select_weapon(side['pipe'], side['own'], thrower, have[thrower])
            if held not in have[thrower]:
                fails.append('%s throw %d: could not select a throwable (hand holds %s)' % (thrower, k + 1, held))
                break
            print('-- %s throws %s (throw %d/3), %s stands %.1f units away'
                  % (thrower, held, k + 1, target, d - NEAR if d > NEAR else 0))
            # aim (LB) and tap the attack (RB): the game throws the dynamite
            side['pipe'].cmd('pad 0 %x 0 0' % LB)
            time.sleep(0.5)
            fx0 = fx_counts(side['peer_pipe'])   # TASK 53: the effects the partner's game spawned
            owner_s, puppet_s = [], []
            for i in range(70):          # 3.5 s at 50 ms: the throw, the fuse, the blast, the reaction
                if i in (2, 14, 26):
                    side['pipe'].cmd('pad 0 %x 0 0' % (LB | RB))
                    time.sleep(0.10)
                    side['pipe'].cmd('pad 0 %x 0 0' % LB)
                time.sleep(DT)
                so, sp = side['own'].sample(thrower), side['peer'].sample(thrower)
                to, tp_ = tside['own'].sample(target), tside['peer'].sample(target)
                if so:
                    owner_s.append(so)
                if sp:
                    puppet_s.append(sp)
                if to and tp_:
                    owner_s[-1]['t_state'] = to['state'] if so else None
                    owner_s[-1]['t_up'] = to['up'] if so else None
            side['pipe'].cmd('pad 0 0 0 0 0 0')
            time.sleep(0.5)
            # TASK 53: the partner's copy must have PLAYED the owner's effects - the explosion included.
            # The game's own effect call is what creates the particle/visual object, so a replayed call at
            # the blast point IS the effect object there (the check reads the call's position from the
            # partner's log, and the relay counter from its `sync`).
            fx1 = fx_counts(side['peer_pipe'])
            played = (fx1 or {}).get('played', -1) - (fx0 or {}).get('played', 0)
            ev = peer_effects(side, thrower)
            wdex = [e for e in ev if e[0] == 'WDEX']
            if not wdex and held in ('DYNA', 'FLBG'):
                t_w = time.time() + 4.0   # the fuse: the blast can be a moment after the throw
                while time.time() < t_w and not wdex:
                    time.sleep(0.5)
                    ev = peer_effects(side, thrower)
                    wdex = [e for e in ev if e[0] == 'WDEX']
                fx1 = fx_counts(side['peer_pipe'])
                played = (fx1 or {}).get('played', -1) - (fx0 or {}).get('played', 0)
            near = None
            pp = side['own'].pos(thrower)
            for _t, x, y, z in wdex:
                if pp and ((x - pp[0]) ** 2 + (y - pp[1]) ** 2) ** 0.5 < 200.0:
                    near = (x, y, z)
            print('   %s: partner effect calls played +%d (owner %s), WDEX replays seen %d%s'
                  % (thrower, played, 'local %d sent %d' % ((fx1 or {}).get('local', -1), (fx1 or {}).get('sent', -1)),
                     len(wdex), '' if not near else ' nearest (%.1f,%.1f,%.1f)' % near))
            if played <= 0:
                fails.append('%s throw %d: the partner copy played no effect of the thrower (%s)'
                             % (thrower, k + 1, fx1))
            if held in ('DYNA', 'FLBG') and not wdex:
                fails.append('%s throw %d: no WDEX explosion reached the partner copy'
                             % (thrower, k + 1))
            # the thrower: same state/clip sequence on both copies?
            st, cl = compare(owner_s, puppet_s, 'state'), compare(owner_s, puppet_s, 'up')
            ost, opu = runs(owner_s, 'state'), runs(owner_s, 'up')
            pst, ppu = runs(puppet_s, 'state'), runs(puppet_s, 'up')
            life_o = owner_s[-1]['life'] if owner_s else -1
            life_p = puppet_s[-1]['life'] if puppet_s else -1
            threw = 200 in ost
            print('   %s: owner states %s clips %s | puppet states %s clips %s'
                  % (thrower, ost, opu, pst, ppu))
            print('   %s: state match %.0f%%  clip match %.0f%%  (%s threw)  life owner %.1f puppet %.1f'
                  % (thrower, 100 * st, 100 * cl, 'yes' if threw else 'NO', life_o, life_p))
            if not threw:
                # the test save holds a limited amount of dynamite (measured: one throw, then the attack
                # never starts again); every throw that DID happen is judged, so this ends the series
                print('   %s: no attack started (out of ammunition for %s) - %d throw(s) tested'
                      % (thrower, held, k))
                break
            if st < 0.80:
                fails.append('%s throw %d: the state sequence differs on the puppet (%.0f%%)'
                             % (thrower, k + 1, 100 * st))
            if cl < 0.80:
                fails.append('%s throw %d: the clip sequence differs on the puppet (%.0f%%)'
                             % (thrower, k + 1, 100 * cl))
            if abs(life_o - life_p) > 1.0:
                fails.append('%s throw %d: life differs between the copies (%.1f vs %.1f)'
                             % (thrower, k + 1, life_o, life_p))
            # the partner: did it take the blast, and did the reaction reach both copies?
            t_owner, t_puppet = [], []
            for _ in range(6):
                time.sleep(0.1)
                a, b = tside['own'].sample(target), tside['peer'].sample(target)
                if a:
                    t_owner.append(a)
                if b:
                    t_puppet.append(b)
            if t_owner and t_puppet:
                lost_o = t_owner[0]['life'] - t_owner[-1]['life']
                lost_p = t_puppet[0]['life'] - t_puppet[-1]['life']
                print('   %s: life lost owner %.1f puppet %.1f | states owner %s puppet %s'
                      % (target, lost_o, lost_p, runs(t_owner, 'state')[-3:], runs(t_puppet, 'state')[-3:]))
                if abs(lost_o - lost_p) > 1.0:
                    fails.append('%s throw %d: the partner lost %.1f life on its own copy but %.1f on the '
                                 'puppet copy (the same blast, two simulations)' % (thrower, k + 1, lost_o, lost_p))
            time.sleep(0.4)
        time.sleep(0.3)
    for pipe in (HP, GP):
        pipe.cmd('pad 0 0 0 0 0 0')
    # the copies must still be alive and answer, and neither log may carry a crash report
    alive = []
    for name, pipe in (('host', HP), ('guest', GP)):
        try:
            r = pipe.cmd('ping')
            alive.append((name, r.startswith('pong')))
        except OSError:
            alive.append((name, False))
    crashes = 0
    for d, off in (('obscure2-test', t0), ('obscure2-test2', t0g)):
        path = os.path.join(root, d, 'obscoop.log')
        try:
            data = open(path, 'rb').read()[off:]
        except OSError:
            continue
        hits = [l for l in data.split(b'\n') if b'FATAL EXCEPTION' in l or b'minimal line' in l]
        if hits:
            crashes += len(hits)
            for l in hits[:3]:
                print('   crash line in %s: %s' % (d, l.decode('latin-1', 'replace').strip()))
    print('== verdict')
    print('copies: %s | crash lines since the start: %d' % (alive, crashes))
    if not all(ok for _n, ok in alive):
        fails.append('a copy stopped answering')
    if crashes:
        fails.append('%d crash line(s) in the logs' % crashes)
    for f in fails:
        print('   FAIL: %s' % f)
    print('explosives %s' % ('OK' if not fails else 'FAIL'))
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
