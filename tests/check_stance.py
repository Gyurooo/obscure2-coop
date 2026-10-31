"""TASK 53: the ATTACK STANCE (LB) must come and go on the partner's copy too.

The owner's 2.1 playtest report: "the HOST's character is sometimes stuck in attack stance on the guest's
screen although the host left it". Holding LB puts the character in the aim/attack stance - the game's
state id character+0x2dc becomes 0x64 (GAME_MECHANICS; TASK 22 measured it) - and releasing LB returns it
to the locomotion states. On the copy that does not own the character the stance is applied through the
game's own state setter (puppet_anim) and the owner's streamed clip (puppet_clip), so anything the puppet's
copy does not clear shows as a character that keeps standing in the aim pose.

The check: each player enters and leaves the attack stance FIVE times on the copy that owns their
character; at the end of every release the PARTNER's copy of that character must be back in the idle state
with the idle clips (state 0, the same upper/lower clip tags the partner showed before the first press).
It prints the whole state/clip sequence of both copies, so a stuck stance names the field that stayed.

Usage: python -I check_stance.py <host pid> <guest pid>
Exit 0 = PASS, 1 = FAIL, 2 = cannot run (no world, no stance entered at all).
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe                 # noqa: E402
from peek import Proc               # noqa: E402

GAME = 0x6c3068
H_TAG, H_STATE, H_IDX_UP, H_IDX_LO, H_TAB, H_POS = 0x14, 0x2dc, 0x220, 0x224, 0x210, 0x23c
H_WUP, H_WLO = 0x228, 0x22c     # the weapon animation layers FUN_004e74c0 drives in the aim stance (in_ECX[0x8a]/[0x8b])
LB = 0x0100
RB = 0x0200
DT = 0.04
HOLD = 0.7          # s the stance is held
REST = 0.9           # s it is left
CYCLES = 5
LAG = 0.6            # s the partner may need to follow a change
ATTACK = True        # every cycle also ATTACKS from the stance (the state 200 the report names)
DPAD = (('LEFT', 0x4), ('RIGHT', 0x8), ('DOWN', 0x2), ('UP', 0x1))
THROWABLE = {'DYNA', 'FLBG', 'FLGU', 'AMFG', 'GREN'}


def tag4(v):
    if not v:
        return '----'
    return ''.join(chr((v >> s) & 0xff) if 32 <= ((v >> s) & 0xff) < 127 else '.' for s in (24, 16, 8, 0))


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
            h = self.p.u32(ctl + 4 + 0x764 * i) if ctl else 0
            tags.append(tag4(self.p.u32(h + H_TAG)) if h else '----')
        return tags

    def clip(self, ch, off):
        tab = self.p.u32(ch + H_TAB)
        idx = self.p.u32(ch + off)
        if not tab or idx is None or idx >= 0x1000:
            return 0
        return self.p.u32(tab + idx * 0x28 + 0xc)

    def snap(self, tag):
        ch = self.humans().get(tag, 0)
        if not ch:
            return None
        return dict(state=self.p.u32(ch + H_STATE), up=self.clip(ch, H_IDX_UP), lo=self.clip(ch, H_IDX_LO),
                    wup=self.p.u32(ch + H_WUP), wlo=self.p.u32(ch + H_WLO))

    def pos(self, tag):
        ch = self.humans().get(tag, 0)
        return struct.unpack('<3f', self.p.read(ch + H_POS, 12)) if ch else None

    def held(self, tag):
        """The weapon tag in the hand (the SELECTED slot) and the four slots, as check_explosives reads
        them: character+0x704 + i*4 -> weapon+0x10, the selected slot character+0x714."""
        ch = self.humans().get(tag, 0)
        if not ch:
            return '----', -1, []
        slots = []
        for s in range(4):
            wp = self.p.u32(ch + 0x704 + 4 * s)
            slots.append(tag4(self.p.u32(wp + 0x10) if wp else 0))
        cur = self.p.u32(ch + 0x714)
        return (slots[cur] if isinstance(cur, int) and 0 <= cur < 4 else '----'), cur, slots


def fmt(s):
    if not s:
        return 'missing'
    return 'state %-4d up %s lo %s w %d/%d' % (s['state'], tag4(s['up']), tag4(s['lo']), s['wup'], s['wlo'])


def idle_ish(s, base):
    """The partner is back in the idle stance the OWNER is in: the locomotion state, and the same clips
    the owner's own copy shows at that instant (the game's own aim stance leaves the lower body on LPAU -
    measured on both copies - so "the clips of the baseline" are not the idle clips)."""
    if not s or not base:
        return False
    return s['state'] == 0 and s['up'] == base['up'] and s['lo'] == base['lo']


def agree(side, who, label, wait=1.5):
    """Both copies must show the same state AND the same upper/lower clips: the owner's report is a
    partner whose LOWER clip stayed on the aim stance's LPAU while the owner was back on its base clip."""
    t0, ok, a, b = time.time(), False, None, None
    while time.time() - t0 < wait:
        a, b = side['own'].snap(who), side['peer'].snap(who)
        if a and b and a['state'] == 0 and b['state'] == 0 and a['up'] == b['up'] and a['lo'] == b['lo']:
            ok = True
            break
        time.sleep(DT)
    print('   %s: owner %s | partner %s -> %s' % (label, fmt(a), fmt(b), 'same' if ok else 'DIFFERENT'))
    if ok:
        return []
    return ['%s: %s (partner %s, owner %s)' % (who, label, fmt(b), fmt(a))]


def stance_reachable(side, who):
    """Can the owner enter the aim stance at all? LB needs a WEAPON IN THE HAND: with the empty slot that
    check_explosives leaves selected after throwing the only DYNA, LB does nothing (TASK 54 run 4: the
    owner stayed on 0/PAUS/WALK through every cycle, FINDINGS_54 section 3.6)."""
    side['pipe'].cmd('pad 0 %x 0 0' % LB)
    t0, ok = time.time(), False
    while time.time() - t0 < 0.45:
        s = side['own'].snap(who)
        if s and s['state'] != 0:
            ok = True
            break
        time.sleep(DT)
    side['pipe'].cmd('pad 0 0 0 0')
    time.sleep(0.30)
    return ok


def pick_weapon(side, who):
    """D-pad steps the weapon slot until LB puts the owner in the stance (the D-pad is weapon select,
    GAME_MECHANICS), so the stance cycles measure something after a throw consumed the selected item."""
    for _ in range(2):
        if stance_reachable(side, who):
            return True
        for _name, code in DPAD:
            side['pipe'].cmd('pad 0 %x' % code)
            time.sleep(0.12)
            side['pipe'].cmd('pad 0 0')
            time.sleep(0.35)
            if stance_reachable(side, who):
                return True
    return False


def warmup_sequence(side, who):
    """TASK 55: the stance is checked right AFTER a throw/attack sequence too, which is the sequence the
    owner's report came from (and the one TASK 54's stance run never ran: it was the first check of its
    run). Two swings from the stance, then a throw when the hand holds a throwable."""
    pipe = side['pipe']
    for _ in range(2):
        pipe.cmd('pad 0 %x 0 0' % LB)
        time.sleep(0.35)
        pipe.cmd('pad 0 %x 0 0' % (LB | RB))
        time.sleep(0.12)
        pipe.cmd('pad 0 %x 0 0' % LB)
        time.sleep(0.35)
    pipe.cmd('pad 0 0 0 0')
    time.sleep(0.4)
    held = side['own'].held(who)[0]
    if held in THROWABLE:
        print('   warm-up: throw %s (owner %s)' % (held, who))
        pipe.cmd('pad 0 %x 0 0' % LB)
        time.sleep(0.4)
        for _ in range(3):
            pipe.cmd('pad 0 %x 0 0' % (LB | RB))
            time.sleep(0.10)
            pipe.cmd('pad 0 %x 0 0' % LB)
            time.sleep(0.30)
        pipe.cmd('pad 0 0 0 0')
        time.sleep(1.2)
    else:
        print('   warm-up: attack sequence only (the hand holds no throwable: %s)' % held)


def main():
    host_pid, guest_pid = int(sys.argv[1]), int(sys.argv[2])
    H, G = View(host_pid), View(guest_pid)
    HP, GP = Pipe(host_pid), Pipe(guest_pid)
    t = time.time()
    while time.time() - t < 90 and not (H.world() and G.world()):
        time.sleep(0.5)
    if not H.world() or not G.world():
        print('no world on one of the copies')
        return 2
    time.sleep(2)
    hs, gs = H.humans(), G.humans()
    if not hs or not gs:
        print('no human characters on one of the copies (host %s, guest %s)' % (sorted(hs), sorted(gs)))
        return 2
    own_h, own_g = H.owned()[0], G.owned()[1]
    print('the host plays %s, the guest plays %s' % (own_h, own_g))
    if own_h not in hs or own_g not in gs or own_h not in gs or own_g not in hs:
        print('the controller records do not name the characters on both copies')
        return 2
    SIDE = {own_h: dict(own=H, peer=G, pipe=HP), own_g: dict(own=G, peer=H, pipe=GP)}

    fails = []
    stance_seen = 0
    for who in (own_h, own_g):
        side = SIDE[who]
        base_o, base_p = side['own'].snap(who), side['peer'].snap(who)
        print('\n-- %s: baseline on its own copy %s | partner copy %s' % (who, fmt(base_o), fmt(base_p)))
        if not base_o or not base_p:
            fails.append('%s: missing on one copy' % who)
            continue
        # TASK 55: the state the reviewer's run failed on, measured BEFORE this check touches anything:
        # the check that ran before this one ended with a throw/attack, and the two copies must agree on
        # the state and BOTH clips.
        fails += agree(side, who, 'right after the previous check (its throw/attack)')
        # ... and the same sequence is part of this check too (the weapon a throw consumed must be
        # replaced before LB can enter the stance at all).
        warmup_sequence(side, who)
        if not pick_weapon(side, who):
            print('   %s: LB enters no stance even after cycling the weapon slots' % who)
        fails += agree(side, who, 'after the throw/attack')
        for k in range(CYCLES):
            t_first, t_last, seen = 0.0, 0.0, []
            side['pipe'].cmd('pad 0 %x 0 0' % LB)     # hold LB = attack stance
            end = time.time() + HOLD * 0.45
            while time.time() < end:
                a, b = side['own'].snap(who), side['peer'].snap(who)
                if a:
                    seen.append((time.time(), a, b))
                    if a['state'] != 0:
                        stance_seen += 1
                time.sleep(DT)
            if ATTACK:   # tap the attack from the stance: the swing (state 200) is what TASK 49 skips here
                for _ in range(2):
                    side['pipe'].cmd('pad 0 %x 0 0' % (LB | RB))
                    time.sleep(0.10)
                    side['pipe'].cmd('pad 0 %x 0 0' % LB)
                    time.sleep(0.12)
            end = time.time() + HOLD * 0.55
            while time.time() < end:
                a, b = side['own'].snap(who), side['peer'].snap(who)
                if a:
                    seen.append((time.time(), a, b))
                    if a['state'] != 0:
                        stance_seen += 1
                time.sleep(DT)
            side['pipe'].cmd('pad 0 0 0 0')
            end = time.time() + REST
            while time.time() < end:
                a, b = side['own'].snap(who), side['peer'].snap(who)
                if a:
                    seen.append((time.time(), a, b))
                time.sleep(DT)
            # the state/clip sequences this cycle (value changes only)
            def runs(idx):
                out = []
                for s in seen:
                    v = s[idx]
                    key = (v['state'], v['up'], v['lo']) if v else None
                    if not out or out[-1] != key:
                        out.append(key)
                return out
            o, p = runs(1), runs(2)
            print('   cycle %d/%d: owner    %s' % (k + 1, CYCLES, ['%d/%s/%s' % (a, tag4(b), tag4(c)) for a, b, c in o]))
            print('   cycle %d/%d: partner  %s' % (k + 1, CYCLES, ['%d/%s/%s' % (a, tag4(b), tag4(c)) for a, b, c in p]))
            # after the release: wait (up to LAG) for the owner to be idle AND the partner to show the
            # same state/clips (the aim stance leaves the lower body on LPAU on BOTH copies - measured -
            # so the test compares the two copies at the same instant, not the first baseline)
            t0 = time.time()
            ok = False
            ow = last = None
            while time.time() - t0 < LAG:
                ow = side['own'].snap(who)
                last = side['peer'].snap(who)
                if ow and last and ow['state'] == 0 and last['state'] == 0 and \
                        last['up'] == ow['up'] and last['lo'] == ow['lo']:
                    ok = True
                    break
                time.sleep(DT)
            if not ok:
                fails.append('%s cycle %d: the partner did not return to the idle stance (%s, owner %s)'
                             % (who, k + 1, fmt(last), fmt(ow)))
            print('   cycle %d/%d: after release owner %s | partner %s -> %s'
                  % (k + 1, CYCLES, fmt(ow), fmt(last), 'idle' if ok else 'NOT IDLE'))
        side['pipe'].cmd('pad 0 0 0 0')
        time.sleep(0.4)
    for p in (HP, GP):
        p.cmd('pad 0 0 0 0')
    if not stance_seen:
        print('the stance was never entered on either copy (no weapon in hand?): cannot run')
        return 2
    alive = []
    for name, pipe in (('host', HP), ('guest', GP)):
        try:
            alive.append((name, pipe.cmd('ping').startswith('pong')))
        except OSError:
            alive.append((name, False))
    print('\ncopies: %s' % alive)
    if not all(ok for _n, ok in alive):
        fails.append('a copy stopped answering')
    for f in fails:
        print('   FAIL: %s' % f)
    print('stance %s (5 stance cycles each way)' % ('OK' if not fails else 'FAIL'))
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
