"""TASK 46: what is actually PLAYED - the remote character's animation CLIPS, not just its state id.

The owner, watching the TASK 45 build live: "Animations are not properly synced on screen". The old
checks (check_movement, check_attack_anim, check_visible) compare character+0x2dc, the state id. This
check opens the animation system itself:

  * human+0x210 = the character's animation table (count +0x20c, stride 0x28, the clip TAG at entry+0xc;
    FUN_004c76e0, decompile 121599);
  * human+0x220 = the index of the PRIMARY (upper body / state) clip, set by the state setter
    FUN_004e3ed0 (vtable slot 0x48);
  * human+0x224 = the index of the LOWER-BODY clip (idle LPAU / LWAF / LWAB / LWAR / LWAL), set by
    FUN_004e7420 (vtable slot 0x4c) - and that is only called by the MOVEMENT STATE MACHINE FUN_004e76c0
    (decompile 140084 / 142331), which TASK 42 gates for the puppet;
  * instance = animtable[index*0x28 + 8], playback clock = instance+0xc (FUN_004c5f30, ms).

So on HEAD the puppet's upper clip follows the owner while its lower-body clip stays at whatever the
character was built with: the legs do not follow the direction the owner walks in (FINDINGS_46 §2).

For every driven phase (walk, turn left, walk down, run, aim stance, swing) the check samples both
characters on both copies every 100 ms and compares, owner vs puppet:
  * the upper clip tag and the lower clip tag (with a one-sample transition allowance),
  * that each layer's playback clock advances (not frozen) on the puppet while it advances on the owner.

Usage: python -I check_anim_sync.py <host pid> <guest pid>
Exit 0 = PASS, 1 = FAIL.
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe
from peek import Proc

GAME = 0x6c3068
H_TAG, H_STATE, H_IDX_UP, H_IDX_LO, H_TAB = 0x14, 0x2dc, 0x220, 0x224, 0x210
LB, RB, A = 0x0100, 0x0200, 0x1000
DT = 0.1
SKEW = 1               # samples a transition may arrive late on the puppet (0.1 s + the playback delay)
UP_OK = 0.80           # fraction of samples the upper clip tag must agree (a transition sample may miss)
LO_OK = 0.60           # ... the lower-body clip tag (driven by the movement machine's gait direction)
ADV_OK = 0.80          # ... of the puppet's samples where a clip's clock must have advanced


def tag4(v):
    if not v:
        return '----'
    b = struct.pack('<I', v)[::-1]
    return b.decode('latin1') if all(32 <= c < 127 for c in b) else '%08x' % v


class View:
    def __init__(self, pid):
        self.p = Proc(pid)
        self.game = self.p.va(GAME)

    def humans(self):
        g = self.p.u32(self.game)
        w = self.p.u32(g + 0x378) if g else 0
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
        """(owned tag, peer tag) from the controller records: game player 1 = this copy's own character."""
        g = self.p.u32(self.game)
        w = self.p.u32(g + 0x378) if g else 0
        ctl = self.p.u32(w + 0x1748) if w else 0
        tags = []
        for i in range(2):
            rec = ctl + 0x764 * i if ctl else 0
            h = self.p.u32(rec + 4) if rec else 0
            tags.append(tag4(self.p.u32(h + H_TAG)) if h else '----')
        return tags[0], tags[1]

    def clip(self, ch, idx_off):
        tab = self.p.u32(ch + H_TAB)
        idx = self.p.u32(ch + idx_off)
        if not tab or idx is None or idx >= 0x1000:
            return None, None
        e = tab + idx * 0x28
        tag = self.p.u32(e + 0xc)
        inst = self.p.u32(e + 8)
        return tag, (self.p.u32(inst + 0xc) if inst else None)

    def sample(self, ch):
        up, upt = self.clip(ch, H_IDX_UP)
        lo, lot = self.clip(ch, H_IDX_LO)
        return dict(state=self.p.u32(ch + H_STATE), up=up, upt=upt, lo=lo, lot=lot,
                    pos=struct.unpack('<2f', self.p.read(ch + 0x23c, 8)))


def main():
    host_pid, guest_pid = int(sys.argv[1]), int(sys.argv[2])
    H, G = View(host_pid), View(guest_pid)
    HP, GP = Pipe(host_pid), Pipe(guest_pid)
    hs, gs = H.humans(), G.humans()
    if not hs or not gs:
        print('no human characters on one of the copies (host %s, guest %s)' % (sorted(hs), sorted(gs)))
        return 2
    # The host copy owns game player 1, the guest copy owns player 2 (src/sync.c char_send_local). The
    # puppet of that character is the character with the SAME tag on the other copy.
    h_rec, g_rec = H.owned(), G.owned()
    own_h, own_g = h_rec[0], g_rec[1]
    print('host copy: player1 %s player2 %s | guest copy: player1 %s player2 %s'
          % (h_rec[0], h_rec[1], g_rec[0], g_rec[1]))
    if own_h not in hs or own_g not in gs or own_h not in gs or own_g not in hs:
        print('the controller records do not name the characters on both copies')
        return 2
    print('the host plays %s, the guest plays %s' % (own_h, own_g))

    rows = []       # (label, samples[(owner_tag, owner sample, puppet sample)])

    def run(label, which, buttons, lx=0, ly=0, n=20):
        pipe, owner_view, peer_view = (HP, H, G) if which == 0 else (GP, G, H)
        owner_tag = own_h if which == 0 else own_g
        peer_tag = own_h if which == 0 else own_g
        # each copy's OWN pad is XInput user 0 on its own process (src/obscoop2.c g_local_pad)
        pipe.cmd('pad 0 %x %d %d 0 0' % (buttons, lx, ly))
        samples = []
        for _ in range(n):
            time.sleep(DT)
            o = owner_view.sample(owner_view.humans().get(owner_tag, 0))
            p = peer_view.sample(peer_view.humans().get(peer_tag, 0))
            samples.append((owner_tag, o, p))
        pipe.cmd('pad 0 0 0 0 0 0')
        rows.append((label, samples, lx != 0 or ly != 0))
        print('-- %s (%s pad %s lx %d ly %d)' % (label, 'host' if which == 0 else 'guest', hex(buttons), lx, ly))
        for tag, o, p in samples[:6] + samples[-2:]:
            print('   %s owner st %-4s up %-4s t %-6s lo %-4s t %-6s | puppet st %-4s up %-4s t %-6s lo %-4s t %-6s'
                  % (tag, o['state'], tag4(o['up']), o['upt'], tag4(o['lo']), o['lot'],
                     p['state'], tag4(p['up']), p['upt'], tag4(p['lo']), p['lot']))
        time.sleep(0.4)   # back to rest between phases

    run('walk', 0, 0, 0, 24000)
    run('turn-left', 0, 0, -24000, 0)
    run('walk-down', 0, 0, 0, -24000)
    run('run', 0, 0, 0, 32767)
    run('aim', 0, LB)
    run('aim-walk', 0, LB, 0, 24000)
    run('aim-strafe', 0, LB, -24000, 0)
    run('aim-run', 0, LB, 0, 32767)
    run('swing', 0, LB | RB)
    run('guest-walk', 1, 0, 0, 24000)
    run('guest-turn', 1, 0, -24000, 0)
    # recovery: leave both copies in normal play (a released pad, BACK cancels an action, then a walk).
    # Not judged - it exists so the checks that run after this one find a character that can move.
    for pipe in (HP, GP):
        pipe.cmd('pad 0 0 0 0 0 0')
    HP.cmd('pad 0 %x 0 0 0 0' % RB)
    time.sleep(0.2)
    HP.cmd('pad 0 0 0 0 0 0')
    time.sleep(0.4)
    HP.cmd('pad 0 0 0 24000 0 0')
    time.sleep(1.2)
    HP.cmd('pad 0 0 0 0 0 0')

    # ---- the verdict -------------------------------------------------------------------------------
    def agree(samples, key):
        """Fraction of samples where the puppet's clip tag equals the owner's (a transition may arrive
        SKEW samples late, so a sample matches if the owner's tag is the puppet's now or within SKEW)."""
        ok = 0
        for i in range(len(samples)):
            o = samples[i][1][key]
            hit = any(samples[j][2][key] == o for j in range(max(0, i - SKEW), min(len(samples), i + SKEW + 1)))
            ok += 1 if hit else 0
        return ok / len(samples)

    def advances(samples, key, timekey):
        """Does the PUPPET's clock for this layer advance whenever the OWNER's does? A clip the game
        freezes on the owner too (the lower layer during a run keeps its walk clock, measured) is not a
        puppet defect, so those samples are not counted against it."""
        n = same = 0
        for i in range(1, len(samples)):
            oa, ob = samples[i - 1][1], samples[i][1]
            a, b = samples[i - 1][2], samples[i][2]
            if a[key] != b[key] or a[timekey] is None or b[timekey] is None:
                continue
            if oa[key] != ob[key] or oa[timekey] is None or ob[timekey] is None or oa[timekey] == ob[timekey]:
                continue          # the owner's clock did not advance either
            n += 1
            if b[timekey] != a[timekey]:
                same += 1
        return (same / n) if n else 1.0

    rc = 0
    print('== verdict (owner vs the puppet on the other copy)')
    for label, samples, moving in rows:
        up, lo = agree(samples, 'up'), agree(samples, 'lo')
        upd, lod = advances(samples, 'up', 'upt'), advances(samples, 'lo', 'lot')
        # every clip the OWNER plays in a phase must appear on the puppet at least once (a phase where
        # the owner never changes clip is not evidence of anything, so it cannot pass on its own either)
        o_up = {s[1]['up'] for s in samples}
        moved = max(abs(s[1]['pos'][0] - samples[0][1]['pos'][0]) + abs(s[1]['pos'][1] - samples[0][1]['pos'][1])
                    for s in samples) if samples else 0.0
        o_lo = {s[1]['lo'] for s in samples}
        p_up = {s[2]['up'] for s in samples}
        p_lo = {s[2]['lo'] for s in samples}
        seen = o_up <= p_up and o_lo <= p_lo
        # a phase in which the owner did not actually move proves nothing (a character stuck in a combat
        # state stands in the same clip on both copies and would "agree" perfectly) - measured: the
        # check_controls run right after a stuck swing phase saw BOY1 travel 0.0 units
        ok = up >= UP_OK and lo >= LO_OK and upd >= ADV_OK and lod >= ADV_OK and seen and (moved >= 20.0 or not moving)
        if not ok:
            rc = 1
        print('%-10s upper clip %3.0f%%  lower clip %3.0f%%  upper plays %3.0f%%  lower plays %3.0f%%  '
              'clips seen %-3s  owner moved %6.1f units  %s'
              % (label, 100 * up, 100 * lo, 100 * upd, 100 * lod, 'yes' if seen else 'NO', moved,
                 'PASS' if ok else 'FAIL'))
    print('anim-sync %s (what is played, not the state id)' % ('OK' if rc == 0 else 'FAIL'))
    return rc


if __name__ == '__main__':
    sys.exit(main())
