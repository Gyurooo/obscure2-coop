#!/usr/bin/env python3
"""TASK 24 PART B: item use (healing) on two live copies.

The use path (FINDINGS_24 section 4): a medikit/energy drink is used through the item object's vtable
slot 28 (+0x70) with the character as argument; it heals maxlife*0.6 (MEDI) or *0.3 (ENDR) through the
character lie method (vtable slot 9), decrements the item quantity (+0xc8) once, and the whole body is
guarded by life < maxlife. The inventory (world+0x1790, count +4, 32-byte entries at +8) is mirrored
host -> guest by PKT_ITEM and character life travels in ch_state, so a use must land ONCE on both
copies and leave the inventories byte-identical.

The pad opens the item menu with player action slot 0x0e, which the owner's map binds to pad button code
1029 = RT on player 1 (measured: `probe_item24b`, RT fires slot 14 and A fires slot 9).

Phases:
  1. host's player 1 uses a MEDIKIT (life lowered to 30 with the test-only `charset` -> 60 points of
     heal are visible and the item is consumed),
  2. the guest's player 2 uses an ENERGY DRINK (life 40 -> 70).
Both phases check, on BOTH copies: life equal, quantity down by exactly one, inventories
byte-identical, and the item menu not left open.

Usage: python -I check_itemuse.py <host pid> <guest pid>
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe
from peek import Proc

GAME = 0x6c3068
BTN = {'A': 0x1000, 'B': 0x2000, 'X': 0x4000, 'Y': 0x8000, 'LB': 0x100, 'RB': 0x200,
       'UP': 0x1, 'DOWN': 0x2, 'LEFT': 0x4, 'RIGHT': 0x8, 'START': 0x10, 'BACK': 0x20}
RT_ARGS = '0 0 0 0 0 255'          # pad <user> <buttons> lx ly rx ry lt rt  -> right trigger full
MEDI_HEAL, ENDR_HEAL = 60.0, 30.0

h, g = int(sys.argv[1]), int(sys.argv[2])
host, guest = Pipe(h), Pipe(g)
mh, mg = Proc(h), Proc(g)
problems = []


def problem(msg):
    problems.append(msg)
    print('  !!! %s' % msg)


def tag(v):
    return ''.join(chr((v >> s) & 0xff) if 32 <= ((v >> s) & 0xff) < 127 else '.'
                   for s in (24, 16, 8, 0))


def f32(m, a):
    b = m.read(a, 4)
    return struct.unpack('<f', b)[0] if b else 0.0


def u32(m, a):
    try:
        return m.u32(a) or 0
    except Exception:
        return 0


def world(m):
    g0 = u32(m, m.va(GAME))
    return u32(m, g0 + 0x378) if g0 else 0


def level(m):
    w = world(m)
    return tag(u32(m, w + 4)) if w else '-'


def inv(m):
    w = world(m)
    return u32(m, w + 0x1790) if w else 0


def inv_entries(m):
    """[(index, tag, id, count)] of the shared inventory (world+0x1790)."""
    i0 = inv(m)
    if not i0:
        return []
    return [(i, tag(u32(m, i0 + 8 + i * 0x20 + 4)), u32(m, i0 + 8 + i * 0x20 + 8),
             u32(m, i0 + 8 + i * 0x20 + 0xc)) for i in range(min(u32(m, i0 + 4), 128))]


def inv_raw(m):
    """The whole 32-byte entry array as bytes (the OBSCOOP_PICKUP_TRACE-style raw diff)."""
    i0 = inv(m)
    if not i0:
        return b''
    n = min(u32(m, i0 + 4), 128)
    return m.read(i0 + 8, n * 0x20) or b''


def count_of(m, want):
    for i, t, ident, q in inv_entries(m):
        if t == want:
            return q
    return 0


def ctl(m, pl):
    w = world(m)
    base = u32(m, w + 0x1748) if w else 0
    return base + 0x764 * pl if base else 0


def char(m, pl):
    c = ctl(m, pl)
    return u32(m, c + 4) if c else 0


def life(m, pl):
    c = char(m, pl)
    return f32(m, c + 0x320) if c else -1.0


def ui_state(m, pl):
    """The input controller's UI state: 0 none, 1 item use?, 3 weapon wheel, 4 item menu."""
    c = ctl(m, pl)
    return u32(m, c + 0xa4) if c else -1


def both(label):
    print('   %-34s life host %.1f / guest %.1f | MEDI %d/%d ENDR %d/%d | ui %d/%d'
          % (label, life(mh, 0), life(mg, 0), count_of(mh, 'MEDI'), count_of(mg, 'MEDI'),
             count_of(mh, 'ENDR'), count_of(mg, 'ENDR'), ui_state(mh, 0), ui_state(mg, 0)))


def inv_equal():
    a, b = inv_raw(mh), inv_raw(mg)
    if a == b:
        return True
    n = sum(1 for i in range(min(len(a), len(b))) if a[i] != b[i])
    print('   inventory raw diff: %d bytes differ (host %d bytes, guest %d)'
          % (n + abs(len(a) - len(b)), len(a), len(b)))
    return False


def diff_report(wa, wb, what):
    """Print the first few differing entries between two entry lists."""
    da = {i: (t, q) for i, t, ident, q in wa}
    db = {i: (t, q) for i, t, ident, q in wb}
    for i in sorted(set(da) | set(db)):
        if da.get(i) != db.get(i):
            print('   %s entry %d: host %s guest %s' % (what, i, da.get(i), db.get(i)))


def pad_seq(pipe, user, steps):
    """steps = [(mask_or_None, lt, rt, seconds), ...]; releases at the end."""
    for mask, lt, rt, secs in steps:
        pipe.cmd('pad %d %d 0 0 0 0 %d %d' % (user, mask or 0, lt, rt))
        time.sleep(secs)
    pipe.cmd('pad %d 0 0 0 0 0 0 0' % user)
    time.sleep(0.2)


def watch(seconds, step=0.1):
    """Sample both copies; return (worst life difference, samples)."""
    worst, n = 0.0, 0
    end = time.time() + seconds
    while time.time() < end:
        lh, lg = life(mh, 0), life(mg, 0)
        if lh > 0 and lg > 0:
            worst = max(worst, abs(lh - lg))
            n += 1
        time.sleep(step)
    return worst, n


print('== level host %s guest %s' % (level(mh), level(mg)))
if not world(mh) or not world(mg):
    problem('no world on one copy (startup flake?) - rerun')
    print('RESULT: item use NOT CHECKED')
    sys.exit(1)

print('\n== 0. baseline inventory')
for name, m in (('host', mh), ('guest', mg)):
    print('   %s: %d entries, MEDI %d ENDR %d' % (name, len(inv_entries(m)), count_of(m, 'MEDI'),
                                                 count_of(m, 'ENDR')))
base_h, base_g = inv_entries(mh), inv_entries(mg)
if base_h != base_g:
    diff_report(base_h, base_g, 'baseline')
    problem('the inventories differ before the test')
if count_of(mh, 'MEDI') < 1:
    problem('no medikit in the inventory')
if count_of(mh, 'ENDR') < 1:
    problem('no energy drink in the inventory')

# ---- phase 1: the host's player 1 uses a medikit -------------------------------------------------
print('\n== 1. host player 1 uses a MEDIKIT (life 30 -> 90 expected, one item)')
medi0h, medi0g = count_of(mh, 'MEDI'), count_of(mg, 'MEDI')
lv0h, lv0g = life(mh, 0), life(mg, 0)
print('   host charset 0 30 ->', host.cmd('charset 0 30'))
time.sleep(1.2)
both('after charset (both copies)')
if abs(life(mh, 0) - life(mg, 0)) > 1.0:
    problem('player 1 life did not settle on both copies before the use (%.1f / %.1f)'
            % (life(mh, 0), life(mg, 0)))
lv_h, lv_g = life(mh, 0), life(mg, 0)

print('   host useitem MEDI 0 ->', host.cmd('useitem MEDI 0'))
worst, n = watch(2.5)
both('after the use')
lh1, lg1 = life(mh, 0), life(mg, 0)
medi1h, medi1g = count_of(mh, 'MEDI'), count_of(mg, 'MEDI')
used = lh1 - lv_h
print('   heal %.1f on the host (%.1f -> %.1f), life difference on %d samples max %.2f'
      % (used, lv_h, lh1, n, worst))

if abs(used - MEDI_HEAL) > 1.0:
    problem('the medikit heal is %.1f, expected %.0f' % (used, MEDI_HEAL))
if abs(lh1 - lg1) > 1.0:
    problem('player 1 life differs after the use: host %.1f guest %.1f' % (lh1, lg1))
if medi0h - medi1h != 1:
    problem('MEDI count changed by %d on the host, expected 1 (%d -> %d)'
            % (medi0h - medi1h, medi0h, medi1h))
if medi0g - medi1g != 1:
    problem('MEDI count changed by %d on the guest, expected 1 (%d -> %d)'
            % (medi0g - medi1g, medi0g, medi1g))
if not inv_equal():
    problem('inventories differ after the medikit use')
    diff_report(inv_entries(mh), inv_entries(mg), 'after MEDI')
if ui_state(mh, 0) != 0 or ui_state(mg, 0) != 0:
    problem('the item menu is still open after the medikit (host %d guest %d)'
            % (ui_state(mh, 0), ui_state(mg, 0)))

# ---- phase 2: the guest's player 2 uses an energy drink -------------------------------------------
print('\n== 2. guest player 2 uses an ENERGY DRINK (life 40 -> 70 expected, one item)')
endr0h, endr0g = count_of(mh, 'ENDR'), count_of(mg, 'ENDR')
print('   host charset 1 40 ->', host.cmd('charset 1 40'))
time.sleep(1.2)
print('   life p2 host %.1f guest %.1f' % (life(mh, 1), life(mg, 1)))
if abs(life(mh, 1) - life(mg, 1)) > 1.0:
    problem('player 2 life did not settle on both copies before the guest use (%.1f / %.1f)'
            % (life(mh, 1), life(mg, 1)))
lv2h, lv2g = life(mh, 1), life(mg, 1)

print('   guest useitem ENDR 1 ->', guest.cmd('useitem ENDR 1'))
time.sleep(2.5)
print('   life p2 host %.1f guest %.1f | ENDR %d/%d | MEDI %d/%d | ui p2 %d/%d'
      % (life(mh, 1), life(mg, 1), count_of(mh, 'ENDR'), count_of(mg, 'ENDR'),
         count_of(mh, 'MEDI'), count_of(mg, 'MEDI'), ui_state(mh, 1), ui_state(mg, 1)))
lh2, lg2 = life(mh, 1), life(mg, 1)
endr1h, endr1g = count_of(mh, 'ENDR'), count_of(mg, 'ENDR')
used2 = lh2 - lv2h
print('   heal %.1f on the host for player 2 (%.1f -> %.1f)' % (used2, lv2h, lh2))
if abs(used2 - ENDR_HEAL) > 1.0 and abs(used2 - MEDI_HEAL) > 1.0:
    problem('player 2 healed %.1f, expected %.0f (energy drink) or %.0f (medikit)'
            % (used2, ENDR_HEAL, MEDI_HEAL))
if abs(lh2 - lg2) > 1.0:
    problem('player 2 life differs after the guest use: host %.1f guest %.1f' % (lh2, lg2))
if endr0h - endr1h > 1 or endr0g - endr1g > 1:
    problem('an item was consumed more than once: ENDR host %d->%d guest %d->%d'
            % (endr0h, endr1h, endr0g, endr1g))
if endr0h - endr1h != endr0g - endr1g:
    problem('ENDR consumption differs between the copies: host %d guest %d'
            % (endr0h - endr1h, endr0g - endr1g))
if not inv_equal():
    problem('inventories differ after the guest use')
    diff_report(inv_entries(mh), inv_entries(mg), 'after ENDR')
if ui_state(mh, 1) != 0 or ui_state(mg, 1) != 0:
    problem('the item menu is still open for player 2 (host %d guest %d)'
            % (ui_state(mh, 1), ui_state(mg, 1)))

# ---- verdict -------------------------------------------------------------------------------------
print('\n== final')
print('   player 1 life host %.1f guest %.1f | player 2 life host %.1f guest %.1f'
      % (life(mh, 0), life(mg, 0), life(mh, 1), life(mg, 1)))
print('   inventory host %d entries guest %d entries | MEDI %d/%d ENDR %d/%d'
      % (len(inv_entries(mh)), len(inv_entries(mg)), count_of(mh, 'MEDI'), count_of(mg, 'MEDI'),
         count_of(mh, 'ENDR'), count_of(mg, 'ENDR')))
if problems:
    print('RESULT: item use OK' if False else 'RESULT: item use FAILED')
    for p in problems:
        print('   - %s' % p)
    sys.exit(1)
print('RESULT: item use OK (each use landed once on both copies, lives equal, inventories identical)')
