"""TASK 34 item 5: the aim stance and an attack animation show on BOTH copies for BOTH players.

The owner's two-PC playtest had no attack animation on the other screen. The mod streams each owner's
character+0x2dc (the animation/death state) to the other copy; before this task the other copy wrote it
on every packet, which reset whatever the local simulation was playing. This check presses the real
controls (GAME_MECHANICS.md, corrected: HOLD LB = aim stance, TAP RB = attack) on each pad and samples
character+0x2dc on both copies, for both characters, every 50 ms.

A phase passes when the using player's character on BOTH copies
  * shows a non-zero animation state while LB is held (the aim stance, +0x2dc = 0x64 in FINDINGS_22), and
  * shows at least one other value while the attack button is tapped (the swing/attack animation).
The other player's character must stay at 0 (no cross-talk). No enemy is needed: the test levels have
none, so this proves the animation, as the task allows.

Usage: python -I check_attack_anim.py <host pid> <guest pid>
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe
from peek import Proc
from tp_to_items import level, player_human, rtti, tag, u32

LB, RB = 0x0100, 0x0200
DT = 0.05
STANCE_MS = 1200
TAP_MS = 260
TAIL_MS = 1200

host_pid, guest_pid = int(sys.argv[1]), int(sys.argv[2])
H, G = Proc(host_pid), Proc(guest_pid)
HP, GP = Pipe(host_pid), Pipe(guest_pid)

GAME = 0x6c3068


def in_level(m):
    g = u32(m, m.va(GAME))
    if not g:
        return False
    w = u32(m, g + 0x378)
    return u32(m, g + 0x310) == 1 and u32(m, g + 0x320) == 0 and w and (u32(m, w + 4) or 0) != 0


def anim(m, pl):
    h = player_human(m, pl)
    return u32(m, h + 0x2dc) if h else None


def tags(m):
    return [tag(u32(m, player_human(m, 0) + 0x14)) if player_human(m, 0) else '-',
            tag(u32(m, player_human(m, 1) + 0x14)) if player_human(m, 1) else '-']


def sample():
    return (anim(H, 0), anim(H, 1), anim(G, 0), anim(G, 1), tag(level(H)), tag(level(G)))


def show(label, s):
    print('   %-26s host %s=%s %s=%s | guest %s=%s %s=%s | level %s/%s'
          % (label, TAGS[0], s[0], TAGS[1], s[1], TAGS[0], s[2], TAGS[1], s[3], s[4], s[5]))


def phase(name, by):
    pl = 0 if by == 'host' else 1
    pipe = HP if by == 'host' else GP
    other = 1 - pl
    # Each copy's own controller is virtual pad 0 (LOCAL_PAD) on both PCs; on the guest it is served as
    # XInput user 1 (player 2), on the host as user 0 (player 1).
    print('== phase %s: the %s own pad (vpad 0) holds LB and taps RB' % (name, by))
    pipe.cmd('pad 0 0')
    time.sleep(0.3)
    base = sample()
    show('before', base)
    seq = []
    pipe.cmd('pad 0 0x%x' % LB)
    t0 = time.time()
    while time.time() - t0 < STANCE_MS / 1000.0:
        seq.append(('LB', sample()))
        time.sleep(DT)
    pipe.cmd('pad 0 0x%x' % (LB | RB))
    t0 = time.time()
    while time.time() - t0 < TAP_MS / 1000.0:
        seq.append(('LB+RB', sample()))
        time.sleep(DT)
    pipe.cmd('pad 0 0x%x' % LB)
    t0 = time.time()
    while time.time() - t0 < TAIL_MS / 1000.0:
        seq.append(('LB', sample()))
        time.sleep(DT)
    pipe.cmd('pad 0 0')
    time.sleep(0.2)
    seq.append(('after', sample()))
    for lbl, s in seq:
        show(lbl, s)
    ik = 0 if pl == 0 else 2   # index of the using player's anim on the host and on the guest
    io = 1 if pl == 0 else 3
    stance_h = [s[ik] for _, s in seq]
    stance_g = [s[ik + 1] for _, s in seq]
    # the using character's samples: host index 0/1, guest index 2/3; the same index pair per copy
    hist_h = [s[0] if pl == 0 else s[1] for _, s in seq]
    hist_g = [s[2] if pl == 0 else s[3] for _, s in seq]
    other_h = [s[1] if pl == 0 else s[0] for _, s in seq]
    other_g = [s[3] if pl == 0 else s[2] for _, s in seq]
    vals_h = [v for v in hist_h if v is not None]
    vals_g = [v for v in hist_g if v is not None]
    nz_h = [v for v in vals_h if v]
    nz_g = [v for v in vals_g if v]
    distinct_h = sorted(set(nz_h))
    distinct_g = sorted(set(nz_g))
    print('   using character %s: host states %s, guest states %s' % (TAGS[pl], distinct_h, distinct_g))
    print('   other character %s: host states %s, guest states %s' % (TAGS[other], sorted(set(x for x in other_h if x)),
                                                                        sorted(set(x for x in other_g if x))))
    ok_h = bool(nz_h) and len(distinct_h) >= 2
    ok_g = bool(nz_g) and len(distinct_g) >= 2
    crosstalk = any(x for x in other_h if x) or any(x for x in other_g if x)
    print('   %s: host %s, guest %s, cross-talk %s' % (name, 'PASS' if ok_h else 'FAIL',
                                                       'PASS' if ok_g else 'FAIL', 'yes' if crosstalk else 'no'))
    return ok_h and ok_g and not crosstalk and not (base[0] or base[1] or base[2] or base[3])


t0 = time.time()
while time.time() - t0 < 40 and not (in_level(H) and in_level(G)):
    time.sleep(0.5)
if not (in_level(H) and in_level(G)):
    print('NOT IN A LEVEL on both copies: check skipped')
    sys.exit(1)
if tag(level(H)) != tag(level(G)):
    print('the copies are in different levels (%s / %s): check skipped' % (tag(level(H)), tag(level(G))))
    sys.exit(1)
TAGS = tags(H)
if tags(G) != TAGS:
    print('the paired characters differ between the copies: host %s guest %s' % (TAGS, tags(G)))
print('level %s, characters %s' % (tag(level(H)), TAGS))
ok = [phase('host pad', 'host'), phase('guest pad', 'guest')]
if all(ok):
    print('attack animation OK (stance + attack animation on both copies, both players)')
    sys.exit(0)
print('attack animation FAIL (%s)' % ', '.join('PASS' if x else 'FAIL' for x in ok))
sys.exit(1)
