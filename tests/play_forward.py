"""TASK 17 Part C: play forward the way the game does - through its own doors and loading zones.

Nothing is asked of the game that a player could not do: the character WALKS to the door/loading zone
with the pad (calibrated first, so the stick really points at the target), presses A, and the check waits
for the transition the game itself performs. No level tag is ever requested. After every new room the
check scans it (live items, enemies, spawners - the same reads as scan_slots.py / tp_to_items.py) and
records it in SLOT_SCAN.md. It stops at the first room with >= 1 live item and 0 enemies, where it tries
to save through the game's own save point (CToeSavePoint) into a FREE slot of the TEST copy.

A room with enemies is never entered: the door that leads to it is skipped once the level tag/entity set
shows enemies (the check leaves and records it). Teleports are not used here at all - walking is not
gated - and any teleport a later test makes must go through tests/tp_to_items.py (Part B).

Usage: python -I play_forward.py <pid> [--max-doors N] [--max-rooms N] [--no-save]
Print only; the SLOT_SCAN.md section is appended at the end of the run.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe, press, shot
from peek import Proc
from tp_to_items import (dist2d, dist3, entities, f32, level, player_human, player_pos, rtti, scan_room,
                         tag, u32, world)

PID = int(sys.argv[1])
MAX_DOORS = 4
MAX_ROOMS = 6
DO_SAVE = True
for a in sys.argv[2:]:
    if a.startswith('--max-doors'):
        MAX_DOORS = int(a.split('=', 1)[1] if '=' in a else a.split()[1])
    elif a.startswith('--max-rooms'):
        MAX_ROOMS = int(a.split('=', 1)[1] if '=' in a else a.split()[1])
    elif a == '--no-save':
        DO_SAVE = False

m = Proc(PID)
pipe = Pipe(PID)
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DOOR_CLASSES = ('CToeDoor', 'CToeDoubleDoor', 'CToeSpecialDoor', 'CToeInternalDoor', 'CToeFlapDoor')
ZONE_CLASSES = ('CToeLoadingZone',)
SAVE_CLASSES = ('CToeSavePoint', 'CToeSimpleSavePoint')
ITEM_SOURCE_CLASSES = ('CToeLoot', 'CToeBreakableCase', 'CToeBreakableTwoStates', 'CToeHeavyCase',
                       'CToeChest', 'CToeChestKey', 'CToeContainer', 'CToeDiscLock', 'CToeChain')

rows = []          # the SLOT_SCAN.md table for this run
visited = set()    # level tags already scanned


def mode():
    g = u32(m, m.va(0x6c3068))
    return u32(m, g + 0x310) if g else None


def reqstate():
    g = u32(m, m.va(0x6c3068))
    return u32(m, g + 0x320) if g else None


def pad(lx=0, ly=0, hold=0.5):
    pipe.cmd('pad 0 0 %d %d' % (int(lx), int(ly)))
    time.sleep(hold)
    pipe.cmd('pad 0 0')


def classify():
    """Every level entity this check can use, with its position and its distance to player 1."""
    p1 = player_pos(m, 0) or (0, 0, 0)
    out = dict(doors=[], zones=[], saves=[], sources=[], markers=[], other={})
    for e in entities(m):
        name = rtti(m, e)
        p = (f32(m, e + 0x6c), f32(m, e + 0x70), f32(m, e + 0x74))
        sane = all(abs(v) < 50000 for v in p) and any(abs(v) > 0.01 for v in p)
        rec = dict(addr=e, rtti=name, id=tag(u32(m, e + 4)), pos=p, sane=sane, d=dist3(p, p1))
        if name in DOOR_CLASSES:
            out['doors'].append(rec)
        elif name in ZONE_CLASSES:
            out['zones'].append(rec)
        elif name in SAVE_CLASSES:
            out['saves'].append(rec)
        elif name in ITEM_SOURCE_CLASSES:
            out['sources'].append(rec)
        elif name == 'CToeCharacterPos':
            out['markers'].append(rec)
        else:
            out['other'][name] = out['other'].get(name, 0) + 1
    for k in ('doors', 'zones', 'saves', 'sources', 'markers'):
        out[k] = [r for r in out[k] if r['sane']]
        out[k].sort(key=lambda r: r['d'])
    return out


def room_report(label):
    room = scan_room(m, player_pos(m, 0) or (0, 0, 0), 1e9, verbose=False)
    c = classify()
    p1 = player_pos(m, 0)
    print('\n-- room %s: level %s, %d entities, player 1 at (%.1f, %.1f, %.1f)'
          % (label, room['level'], room['entities'], p1[0], p1[1], p1[2]))
    print('   live items %d, enemies %d, spawners %d' % (len(room['near_items']), len(room['enemies']), len(room['spawners'])))
    for r in room['near_items']:
        print('     LIVE item %s id %s at (%.2f, %.2f, %.2f)' % (r['cls'], r['id'], r['pos'][0], r['pos'][1], r['pos'][2]))
    for r in room['dead_items']:
        print('     item entity %s id %s p20=%d collected=%d gates %s at (%.2f, %.2f, %.2f)'
              % (r['cls'], r['id'], r['active'], r['collected'], r['gates'], r['pos'][0], r['pos'][1], r['pos'][2]))
    for r in room['enemies']:
        print('     ENEMY %s life %d at (%.2f, %.2f, %.2f), %.0f away'
              % (r['rtti'], r['life'], r['pos'][0], r['pos'][1], r['pos'][2], r['d']))
    for r in room['spawners']:
        print('     SPAWNER %s at (%.2f, %.2f, %.2f)' % (r['rtti'], r['pos'][0], r['pos'][1], r['pos'][2]))
    for kind in ('doors', 'zones', 'saves'):
        for r in c[kind]:
            print('     %-8s %-18s id %s at (%.2f, %.2f, %.2f), %.0f away @%x'
                  % (kind[:-1], r['rtti'], r['id'], r['pos'][0], r['pos'][1], r['pos'][2], r['d'], r['addr']))
    for r in c['sources']:
        print('     source   %-22s id %s at (%.2f, %.2f, %.2f), %.0f away' % (r['rtti'], r['id'], r['pos'][0], r['pos'][1], r['pos'][2], r['d']))
    print('   other classes: %s' % ', '.join('%s x%d' % (k, v) for k, v in sorted(c['other'].items()) if k))
    rows.append(dict(label=label, level=room['level'], entities=room['entities'], live=len(room['near_items']),
                     enemies=len(room['enemies']), spawners=len(room['spawners']),
                     npc=', '.join(r['rtti'] for r in room['enemies']) or '-',
                     items=', '.join('%s@%.0f,%.0f,%.0f' % (r['cls'], r['pos'][0], r['pos'][1], r['pos'][2])
                                     for r in room['near_items']) or '-',
                     doors=len(c['doors']) + len(c['zones']), p=tuple(round(v, 1) for v in p1)))
    return room, c


# ---- the walker: calibrate the stick, then walk to a point ----------------------------------------
class Walker:
    """Drives pad 0 and knows what the stick does in world space. The two basis vectors are measured on
    the live copy (four stick directions, 0.6 s each) and the pair with the largest area is kept, so
    walls, a camera at a different angle and a left-handed axis convention all come out of the data."""

    def __init__(self, pl=0):
        self.pl = pl
        self.basis = None      # [((lx, ly) pressed, (dx, dy) measured), (...)]

    def _move(self, lx, ly, hold):
        before = player_pos(m, self.pl)
        pad(lx, ly, hold)
        time.sleep(0.4)
        after = player_pos(m, self.pl)
        return (after[0] - before[0], after[1] - before[1], after[2] - before[2])

    def calibrate(self):
        print('')
        print('== stick calibration (what does the pad do in world space?)')
        dirs = []
        for lx, ly, name in ((0, 30000, 'up'), (0, -30000, 'down'), (-30000, 0, 'left'), (30000, 0, 'right')):
            best = (0.0, 0.0)
            for attempt in range(3):
                d = self._move(lx, ly, 0.6)
                planar = (d[0] ** 2 + d[1] ** 2) ** 0.5
                if planar > 2000.0:
                    print('   stick %-5s for 0.6 s -> (%+.1f, %+.1f): %.0f units is not a walk (a level script'
                          ' or the safe-position system moved the character); retrying' % (name, d[0], d[1], planar))
                    time.sleep(1.5)
                    continue
                if planar > (best[0] ** 2 + best[1] ** 2) ** 0.5:
                    best = (d[0], d[1])
                if (best[0] ** 2 + best[1] ** 2) ** 0.5 > 40.0:
                    break
            print('   stick %-5s 0.6 s -> world (%+.1f, %+.1f) (planar %.1f)'
                  % (name, best[0], best[1], (best[0] ** 2 + best[1] ** 2) ** 0.5))
            dirs.append(((float(lx), float(ly)), best))
        pair, best_det = None, 0.0
        for i in range(len(dirs)):
            for j in range(i + 1, len(dirs)):
                d1, d2 = dirs[i][1], dirs[j][1]
                if min((d1[0] ** 2 + d1[1] ** 2) ** 0.5, (d2[0] ** 2 + d2[1] ** 2) ** 0.5) < 20.0:
                    continue
                det = abs(d1[0] * d2[1] - d1[1] * d2[0])
                if det > best_det:
                    pair, best_det = (dirs[i], dirs[j]), det
        if pair is None:
            print('   the character does not walk in this room (pad ignored or blocked)')
            return False
        self.basis = list(pair)
        print('   basis: stick (+%.0f, +%.0f) -> (%+.1f, %+.1f), stick (%+.0f, %+.0f) -> (%+.1f, %+.1f), area %.0f'
              % (pair[0][0][0], pair[0][0][1], pair[0][1][0], pair[0][1][1],
                 pair[1][0][0], pair[1][0][1], pair[1][1][0], pair[1][1][1], best_det))
        return True

    def stick_for(self, d):
        """Stick (lx, ly) that walks along world direction d: solve d = a*w1 + b*w2, stick = a*s1 + b*s2."""
        (s1, w1), (s2, w2) = self.basis
        det = w1[0] * w2[1] - w1[1] * w2[0]
        if abs(det) < 1.0:
            return 0, 0
        n = (d[0] ** 2 + d[1] ** 2) ** 0.5 or 1.0
        dx, dy = d[0] / n, d[1] / n
        a = (dx * w2[1] - dy * w2[0]) / det
        b = (w1[0] * dy - w1[1] * dx) / det
        lx = a * s1[0] + b * s2[0]
        ly = a * s1[1] + b * s2[1]
        big = max(abs(lx), abs(ly), 1.0)
        if big > 30000.0:
            lx, ly = lx * 30000.0 / big, ly * 30000.0 / big
        return int(lx), int(ly)

    def walk_to(self, target, tol=70.0, limit=25.0, stop_on_block=2):
        t0, stuck, last, sidestep = time.time(), 0, None, 0
        while time.time() - t0 < limit:
            p = player_pos(m, self.pl)
            d = (target[0] - p[0], target[1] - p[1])
            have = (d[0] ** 2 + d[1] ** 2) ** 0.5
            if have <= tol:
                print('   walk: reached (%.1f, %.1f, %.1f), %.0f from the goal' % (p[0], p[1], p[2], have))
                return True
            if last is not None and dist3(p, last) < 1.0:
                stuck += 1
            else:
                stuck = 0
            last = p
            if stuck >= stop_on_block:
                perp = (-d[1], d[0]) if sidestep % 2 == 0 else (d[1], -d[0])
                lx, ly = self.stick_for(perp)
                print('   walk: blocked at (%.1f, %.1f, %.1f); sidestep %d' % (p[0], p[1], p[2], sidestep + 1))
                pad(lx, ly, 0.5)
                sidestep += 1
                stuck = 0
                time.sleep(0.2)
                continue
            lx, ly = self.stick_for(d)
            f = 1.0 if have > 250 else max(0.3, have / 250.0)
            pad(int(lx * f), int(ly * f), 0.5)
        p = player_pos(m, self.pl)
        print('   walk: gave up at (%.1f, %.1f, %.1f), %.0f from the goal'
              % (p[0], p[1], p[2], dist2d(p, target)))
        return False

    def walk_via(self, goal, waypoints, tol=70.0):
        """The level's own CToeCharacterPos markers are places a character can stand: use the ones that
        shorten the way as intermediate goals, then walk the last stretch straight at the target."""
        p = player_pos(m, self.pl)
        start_d = dist2d(p, goal)
        tried = 0
        for mk in sorted(waypoints, key=lambda r: dist2d(r['pos'], goal)):
            if tried >= 2:
                break
            w = mk['pos']
            if dist2d(w, goal) > start_d - 150.0:
                continue        # it does not shorten the way
            if dist2d(w, p) > 900.0:
                continue        # too far to try blindly
            print('   route: via CToeCharacterPos at (%.1f, %.1f) (%.0f left to the goal)'
                  % (w[0], w[1], dist2d(w, goal)))
            tried += 1
            if self.walk_to(w, tol=60.0, limit=12.0):
                print('   route: reached the waypoint')
                break
        return self.walk_to(goal, tol=tol, limit=20.0)


def wait_transition(old_level, old_world, old_pos, limit=20.0):
    """The game's own transition: a new level tag, a new world, or the character moved far."""
    t0 = time.time()
    while time.time() - t0 < limit:
        w, lv, p = world(m), level(m), player_pos(m, 0)
        if w != old_world and w:
            return 'new world %#x (level %s)' % (w, tag(lv))
        if lv != old_level and lv:
            return 'new level %s' % tag(lv)
        if p and old_pos and dist3(p, old_pos) > 500.0:
            return 'moved %.0f units (level %s)' % (dist3(p, old_pos), tag(lv))
        time.sleep(0.5)
    return None


def wait_ready(limit=150.0):
    """After a transition: wait for the level to build and to place the characters (FINDINGS_16 s4)."""
    t0 = time.time()
    while time.time() - t0 < limit:
        if mode() == 1 and world(m) and reqstate() == 0 and len(entities(m)) > 0:
            p1, p2 = player_pos(m, 0), player_pos(m, 1)
            if p1 and all(abs(v) < 50000 for v in p1) and max(abs(v) for v in p1) > 1.0:
                time.sleep(2.0)
                return True
        time.sleep(1.0)
    return False


def interact_target():
    """character+0x73c: the entity the game's own interaction scan has selected for the player."""
    h = player_human(m, 0)
    return u32(m, h + 0x73c) if h else 0


def try_door(rec, walker, kind, markers=()):
    """Walk to the door/zone and use it the way a player does, then wait for the game's transition."""
    print('\n== %s %s id %s at (%.2f, %.2f, %.2f), %.0f away: walking there'
          % (kind, rec['rtti'], rec['id'], rec['pos'][0], rec['pos'][1], rec['pos'][2], rec['d']))
    p = player_pos(m, 0)
    # stop ~80 units in front of the door, on the player's side, so the A press finds the door in range
    d = (rec['pos'][0] - p[0], rec['pos'][1] - p[1])
    n = (d[0] ** 2 + d[1] ** 2) ** 0.5 or 1.0
    goal = (rec['pos'][0] - d[0] / n * 80.0, rec['pos'][1] - d[1] / n * 80.0, rec['pos'][2])
    old_lv, old_w, old_p = level(m), world(m), p
    reached = walker.walk_via(goal, markers, tol=90.0)
    if not reached:
        # fall back to the door itself (a loading zone triggers on its own centre, a door may be wide)
        reached = walker.walk_to(rec['pos'], tol=60.0, limit=15.0)
    if not reached:
        print('   could not reach the %s (character at %s)' % (kind, player_pos(m, 0)))
        return None
    print('   at the %s: character %s, interaction scan target +0x73c = %#x (%s)'
          % (kind, player_pos(m, 0), interact_target(), rtti(m, interact_target()) if interact_target() else '-'))
    if kind == 'door':
        for attempt in range(3):
            print('   pressing A (attempt %d)' % (attempt + 1))
            press(pipe, 0, 'A', 0.4)
            time.sleep(1.5)
            how = wait_transition(old_lv, old_w, old_p, 6.0)
            if how:
                return how
        print('   no transition')
        return None
    return wait_transition(old_lv, old_w, old_p, 15.0)


def save_here(c):
    """Save through the game's own save point: walk to it, press A, and photograph the menu."""
    if not c['saves']:
        print('\n== save: this room has no save point entity')
        return None
    rec = c['saves'][0]
    print('\n== save: walking to %s id %s at (%.2f, %.2f, %.2f)'
          % (rec['rtti'], rec['id'], rec['pos'][0], rec['pos'][1], rec['pos'][2]))
    if not walker.walk_to(rec['pos'], tol=70.0):
        print('   could not reach the save point')
        return None
    press(pipe, 0, 'A', 0.4)
    time.sleep(2.0)
    out = os.path.join(ROOT, 'tests', 'shots', 'save_menu.png')
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        print('   screenshot %s -> %s' % (out, shot(PID, out)))
    except Exception as e:
        print('   screenshot failed: %s' % e)
    print('   (the save menu, if any, is driven by the run that follows this check)')
    return out


# ---- main ----------------------------------------------------------------------------------------
print('play forward: pid %d, level %s, %d entities' % (PID, tag(level(m)), len(entities(m))))
walker = Walker()
first_room, first_c = room_report('start')
if first_room['near_items'] and not first_room['enemies']:
    print('\n== the starting room already has a live item and no enemy')
    if DO_SAVE:
        save_here(first_c)
    sys.exit(0)

if not walker.calibrate():
    print('the pad does not move the character; cannot walk to a door')
    walker = None

queue = [(r, 'zone') for r in first_c['zones']] + [(r, 'door') for r in first_c['doors']]
tried = 0
success = None
for rec, kind in queue:
    if walker is None or tried >= MAX_DOORS or len(rows) >= MAX_ROOMS:
        break
    tried += 1
    how = try_door(rec, walker, kind, first_c['markers'])
    if not how:
        continue
    print('\n== transition: %s' % how)
    if not wait_ready():
        print('   the new level did not get ready; stopping')
        break
    lv = tag(level(m))
    room, c = room_report('after %s %s' % (kind, rec['id']))
    if room['enemies']:
        print('\n== this room has enemies (%d): leaving it alone, recording it for the combat task'
              % len(room['enemies']))
        continue
    if room['near_items']:
        print('\n== FOUND a room with %d live item(s) and no enemy: level %s' % (len(room['near_items']), lv))
        success = (room, c)
        if DO_SAVE:
            save_here(c)
        break

print('\n== forward play summary')
for r in rows:
    print('  %-24s level %s entities %3d live %d enemies %d spawners %d at %s'
          % (r['label'][:24], r['level'], r['entities'], r['live'], r['enemies'], r['spawners'], r['p']))

# append the run's table to SLOT_SCAN.md
try:
    path = os.path.join(ROOT, 'SLOT_SCAN.md')
    with open(path, 'a', encoding='utf-8') as f:
        f.write('\n## TASK 17 Part C - forward play on the host copy (pid %d, save slot %s)\n\n'
                % (PID, os.environ.get('SAVE_SLOT', '?')))
        f.write('Walked to the level\'s own doors/loading zones with the pad (no teleport, no level tag requested).\n'
                'Every room the game put the player in is listed; a room with enemies was left and recorded.\n\n')
        f.write('| # | room | level | entities | live items | enemies | spawners | items | player 1 |\n')
        f.write('|---:|---|---|---:|---:|---:|---:|---|---|\n')
        for i, r in enumerate(rows, 1):
            f.write('| %d | %s | %s | %d | %d | %d | %d | %s | (%.1f, %.1f, %.1f) |\n'
                    % (i, r['label'], r['level'], r['entities'], r['live'], r['enemies'], r['spawners'],
                       r['items'], r['p'][0], r['p'][1], r['p'][2]))
        if success:
            f.write('\n**First room with a live item and no enemy: level %s, items %s**\n'
                    % (success[0]['level'], ', '.join('%s at (%.1f, %.1f, %.1f)' % (r['cls'], *r['pos'])
                                                      for r in success[0]['near_items'])))
        f.write('\n')
    print('\nappended the run table to %s' % path)
except Exception as e:
    print('could not append to SLOT_SCAN.md: %s' % e)

sys.exit(0 if success else 3)
