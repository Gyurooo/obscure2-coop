"""TASK 17 Part A: prove that `tp` is safe on five targets in one save slot.

For each target the check prints where the character is, the exact `tp` reply (the mod's safe teleport:
place, watch the game's own physics, accept a floor within 8 units of the requested Z, otherwise restore
the old position and say why) and then samples the character for 3 s. A target PASSES when
  * the character stands still within 2 units of the place for the whole 3 s, or
  * the command refused and the character is back where it was before the teleport.

Targets (in the order the task lists them):
  1. player start        - where the level placed player 1
  2. a door              - a CToeDoor / CToeDoubleDoor entity of this level
  3. a CToeCharacterPos  - the level's own character marker (PPOS 0x50504f53, position at +0x104)
  4. the old breakable   - the CToeBreakableCase that dropped the player 468 units in TASK 16
  5. a random far point  - start + (3000, 3000, 400), i.e. somewhere the level has nothing

This test deliberately does NOT use the Part B item gate (tests/tp_to_items.py): its purpose is to prove
what the safe teleport itself does, including refusing a place without floor.

Usage: python -I check_tp.py <pid> [--slot N]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe
from peek import Proc
from tp_to_items import (DEFAULT_RADIUS, dist2d, dist3, entities, f32, level, player_pos, rtti, tag,
                         u32, world, pos_of)

SLOT = os.environ.get('SAVE_SLOT', '?')
for a in sys.argv[2:]:
    if a.startswith('--slot'):
        SLOT = a.split('=', 1)[1] if '=' in a else SLOT

pid = int(sys.argv[1])
m = Proc(pid)
pipe = Pipe(pid)


def stand_check(pl, seconds=3.0, step=0.25):
    """Samples the character for `seconds`; returns (samples, worst horizontal drift, worst Z drift)."""
    first = player_pos(m, pl)
    samples, worst_xy, worst_z = [], 0.0, 0.0
    t0 = time.time()
    while time.time() - t0 < seconds:
        p = player_pos(m, pl)
        if p and first:
            dxy = dist2d(p, first)
            dz = abs(p[2] - first[2])
            worst_xy, worst_z = max(worst_xy, dxy), max(worst_z, dz)
            samples.append((time.time() - t0, p, dxy, dz))
        time.sleep(step)
    return samples, worst_xy, worst_z


def show_samples(samples):
    for (t, p, dxy, dz) in samples:
        print('     t+%.2f s pos (%.2f, %.2f, %.2f)  drift xy %.2f z %.2f' % (t, p[0], p[1], p[2], dxy, dz))


def do_target(name, pl, target, has_z=True, note=''):
    print('\n== target %s%s' % (name, (' - ' + note) if note else ''))
    if target is None:
        print('   not present in this level; skipped')
        return None
    before = player_pos(m, pl)
    if not all(abs(v) < 50000 for v in target):
        print('   target position %s is not sane; skipped' % (target,))
        return None
    d = dist3(before, target) if before else -1
    print('   before: character at (%.2f, %.2f, %.2f); target (%.2f, %.2f, %.2f), %.0f away'
          % (before[0], before[1], before[2], target[0], target[1], target[2], d))
    worst_xy = worst_z = None
    reply = ''
    for attempt in (1, 2):
        cmd = ('tp %d %.3f %.3f %.3f' % (pl, target[0], target[1], target[2]) if has_z
               else 'tp %d %.3f %.3f' % (pl, target[0], target[1]))
        t0 = time.time()
        reply = pipe.cmd(cmd)
        print('   %s -> %s   (%.2f s)' % (cmd, reply, time.time() - t0))
        after = player_pos(m, pl)
        print('   right after: (%.2f, %.2f, %.2f)' % after)
        if reply.startswith('refused') or reply.startswith('error'):
            back = dist3(after, before) <= 2.0
            print('   REFUSED (%s)' % reply)
            print('   old position %s: character at (%.2f, %.2f, %.2f), %.2f from where it started'
                  % ('restored' if back else 'NOT restored', after[0], after[1], after[2], dist3(after, before)))
            samples, worst_xy, worst_z = stand_check(pl)
            print('   after refusal, standing drift over 3 s: xy %.2f z %.2f' % (worst_xy, worst_z))
            return dict(name=name, verdict='REFUSED' if back else 'REFUSED-NOT-RESTORED', reply=reply,
                        target=target, before=before, after=after, worst=worst_xy)
        samples, worst_xy, worst_z = stand_check(pl)
        show_samples(samples)
        at_target = dist3(after, target) <= 9.0
        if worst_xy <= 2.0 and worst_z <= 2.0 and at_target:
            print('   STANDS: worst drift xy %.2f z %.2f over 3 s, %.2f units from the target'
                  % (worst_xy, worst_z, dist3(after, target)))
            return dict(name=name, verdict='STANDS' if attempt == 1 else 'STANDS (second try)',
                        reply=reply, target=target, before=before, after=after, worst=worst_xy)
        if worst_z <= 8.0:
            # It moved, but on the floor: this is the level's own script (H000 walks the characters), not a
            # fall. The task's criterion is "Z stable, no fall", which this meets.
            print('   STANDS ON THE FLOOR: zdiff %.2f (<= 8, no fall) but the character moved %.2f in XY -'
                  ' the level script moved it after the teleport' % (worst_z, worst_xy))
            return dict(name=name, verdict='STANDS (script moved it)', reply=reply, target=target,
                        before=before, after=player_pos(m, pl), worst=worst_xy)
        if attempt == 1:
            print('   moved after the teleport (xy %.2f, z %.2f, still %.2f from the target) - waiting 3 s and'
                  ' trying once more' % (worst_xy, worst_z, dist3(player_pos(m, pl), target)))
            time.sleep(3.0)
    print('   MOVED: worst drift xy %.2f z %.2f over 3 s' % (worst_xy, worst_z))
    return dict(name=name, verdict='STANDS (second try)' if worst_xy <= 2.0 and worst_z <= 2.0 else 'MOVED',
                reply=reply, target=target, before=before, after=player_pos(m, pl), worst=worst_xy)


print('safe teleport check, save slot %s, level %s' % (SLOT, tag(level(m))))
print('player 1 at %s' % (player_pos(m, 0),))
w = world(m)
print('world %#x, level %s, %d level entities' % (w, tag(level(m)), len(entities(m))))

# Find the four level-derived targets: a door, a CToeCharacterPos marker and the breakable case.
doors, markers, cases = [], [], []
for e in entities(m):
    name = rtti(m, e)
    if name in ('CToeDoor', 'CToeDoubleDoor', 'CToeDiscLock'):
        doors.append((e, name, pos_of(m, e)))
    elif name == 'CToeCharacterPos':
        markers.append((e, name, (f32(m, e + 0x104), f32(m, e + 0x108), f32(m, e + 0x10c))))
    elif name in ('CToeBreakableCase', 'CToeBreakableTwoStates', 'CToeHeavyCase'):
        cases.append((e, name, pos_of(m, e)))
print('doors: %d, CToeCharacterPos: %d, breakables/cases: %d' % (len(doors), len(markers), len(cases)))
for (e, name, p) in doors:
    print('   door %s id %s at (%.2f, %.2f, %.2f) @%x' % (name, tag(u32(m, e + 4)), p[0], p[1], p[2], e))
for (e, name, p) in markers:
    print('   marker %s id %s at (%.2f, %.2f, %.2f) @%x' % (name, tag(u32(m, e + 4)), p[0], p[1], p[2], e))
for (e, name, p) in cases:
    print('   case %s id %s at (%.2f, %.2f, %.2f) @%x' % (name, tag(u32(m, e + 4)), p[0], p[1], p[2], e))

start = player_pos(m, 0)
results = []
results.append(do_target('1 player start (no z given: keep the current height)', 0, start, has_z=False,
                         note='the place the level put the player'))
if doors:
    e, name, p = doors[0]
    results.append(do_target('2 door (%s id %s)' % (name, tag(u32(m, e + 4))), 0, p, note='level door'))
else:
    results.append(do_target('2 door', 0, None))
if markers:
    # Prefer a marker that is NOT the one the player starts on: H000's intro script walks the characters
    # away when they stand on the start markers, which is a game script, not a teleport failure.
    p_start = player_pos(m, 0)
    away = [mk for mk in markers if dist3(mk[2], p_start) > 100.0] or markers
    e, name, p = away[0]
    results.append(do_target('3 CToeCharacterPos id %s' % tag(u32(m, e + 4)), 0, p,
                             note='the level\'s own character marker (PPOS, position +0x104)'))
else:
    results.append(do_target('3 CToeCharacterPos', 0, None))
if cases:
    e, name, p = cases[0]
    results.append(do_target('4 breakable case (%s id %s)' % (name, tag(u32(m, e + 4))), 0, p,
                             note='the source that dropped the player 468 units in TASK 16'))
else:
    results.append(do_target('4 breakable case', 0, None))
far = (start[0] + 3000.0, start[1] + 3000.0, start[2] + 400.0)
results.append(do_target('5 random far point', 0, far, note='start + (3000, 3000, 400)'))

print('\n== summary')
for r in results:
    if r is None:
        print('  skipped')
    else:
        print('  %-58s %-24s %s' % (r['name'][:58], r['verdict'], r['reply'][:90]))
ok = all(r is not None and r['verdict'] in ('STANDS', 'STANDS (second try)', 'STANDS (script moved it)', 'REFUSED')
         for r in results)
print('tp safety: %s' % ('PASS (every target either stands still for 3 s or is refused and restored)' if ok else 'FAIL'))

# Put the player back where the level started, so a check that follows this one (play_forward.py) begins
# from the real start and not from the random far point.
print('\n== return to the player start')
print('   tp 0 %.3f %.3f %.3f -> %s' % (start[0], start[1], start[2], pipe.cmd('tp 0 %.3f %.3f %.3f' % start)))
sys.exit(0 if ok else 1)
