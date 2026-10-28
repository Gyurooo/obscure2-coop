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
import math
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


def stick_set(lx, ly):
    """Hold a stick direction without releasing it (the walker re-aims 5x a second)."""
    pipe.cmd('pad 0 0 %d %d' % (int(lx), int(ly)))


def stick_off():
    pipe.cmd('pad 0 0')


def cam_yaw():
    """The camera's ground yaw in radians, as the mod sees it in the view matrix (sync.c g_cam_yaw,
    printed in degrees by the `cam` command). None when the game has no valid scene camera yet."""
    r = pipe.cmd('cam')
    try:
        parts = r.split()
        deg = float(parts[parts.index('own') + 1])
        valid = int(parts[parts.index('valid') + 1])
    except (ValueError, IndexError):
        return None
    if not valid:
        return None
    return deg * 3.14159265358979 / 180.0


def classify():
    """Every level entity this check can use, with its position and its distance to player 1.

    TASK 19: a door's eligibility check `FUN_0042a480` measures the 80-unit reach to **entity+0x10c..
    +0x114** (an interaction anchor the entity copies from its own position when it is parsed) and wants
    `dot(character forward, entity+0x13c..+0x144) >= 0.5`; a save point (`FUN_0046e6c0`) wants
    `dot(unit(character -> entity), character forward) > 0.5`. Both are recorded here so the walker aims
    at and faces the right point."""
    p1 = player_pos(m, 0) or (0, 0, 0)
    out = dict(doors=[], zones=[], saves=[], sources=[], markers=[], other={})
    for e in entities(m):
        name = rtti(m, e)
        p = (f32(m, e + 0x6c), f32(m, e + 0x70), f32(m, e + 0x74))
        sane = all(abs(v) < 50000 for v in p) and any(abs(v) > 0.01 for v in p)
        anchor = (f32(m, e + 0x10c), f32(m, e + 0x110), f32(m, e + 0x114))
        if max(abs(v) for v in anchor) < 0.01 or any(abs(v) > 50000 for v in anchor):
            anchor = None
        rec = dict(addr=e, rtti=name, id=tag(u32(m, e + 4)), pos=p, sane=sane, d=dist3(p, p1), anchor=anchor,
                   dir=(f32(m, e + 0x13c), f32(m, e + 0x140), f32(m, e + 0x144)))
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
    """Drives pad 0 and knows what the stick does in world space.

    TASK 18: the stick is CAMERA-RELATIVE ("stick up = the camera's forward", src/obscoop2.c
    remap_stick) and this game's camera turns to follow the character, so a stick held in one place
    curves the walk into a circle: the old walker measured one stick->world basis and kept using it,
    which is only true while the camera does not move. The fix is to aim with the live camera yaw the
    mod publishes (`cam` -> g_cam_yaw from the view matrix) and re-aim several times a second:

        world angle = up_world + (yaw_now - yaw_at_calibration) + sign * atan2(lx, ly)

    `sign` and `up_world` come from two short measured presses (up and right), so an unexpected axis
    convention still comes out of the data. When the mod has no valid camera yaw, the old measured
    two-vector basis is used instead."""

    def __init__(self, pl=0):
        self.pl = pl
        self.basis = None      # fallback: [((lx, ly) pressed, (dx, dy) measured), (...)]
        self.up_world = None   # world ground angle (radians) that "stick up" produced
        self.sign = 1.0        # world = up_world + sign * atan2(lx, ly)
        self.yaw_at_cal = None
        self.yaw_ok = False
        self.walked = 0.0      # path length walked by this walker (units)

    def _move(self, lx, ly, hold):
        before = player_pos(m, self.pl)
        y0 = cam_yaw()
        pad(lx, ly, hold)
        time.sleep(0.25)
        after = player_pos(m, self.pl)
        return (after[0] - before[0], after[1] - before[1], after[2] - before[2]), y0

    def calibrate(self):
        print('')
        print('== stick calibration (what does the pad do in world space, and is it camera-relative?)')
        dirs = []
        for lx, ly, name in ((0, 30000, 'up'), (0, -30000, 'down'), (-30000, 0, 'left'), (30000, 0, 'right')):
            best, best_yaw = (0.0, 0.0), None
            for attempt in range(3):
                d, y0 = self._move(lx, ly, 0.6)
                planar = (d[0] ** 2 + d[1] ** 2) ** 0.5
                if planar > 2000.0:
                    print('   stick %-5s for 0.6 s -> (%+.1f, %+.1f): %.0f units is not a walk (a level script'
                          ' or the safe-position system moved the character); retrying' % (name, d[0], d[1], planar))
                    time.sleep(1.5)
                    continue
                if planar > (best[0] ** 2 + best[1] ** 2) ** 0.5:
                    best, best_yaw = (d[0], d[1]), y0
                if (best[0] ** 2 + best[1] ** 2) ** 0.5 > 40.0:
                    break
            ang = None
            if (best[0] ** 2 + best[1] ** 2) ** 0.5 > 20.0:
                ang = math.atan2(best[1], best[0])
            print('   stick %-5s 0.6 s -> world (%+.1f, %+.1f) (planar %.1f, angle %s, camera yaw %s)'
                  % (name, best[0], best[1], (best[0] ** 2 + best[1] ** 2) ** 0.5,
                     '-' if ang is None else '%.0f deg' % (ang * 180 / math.pi),
                     '-' if best_yaw is None else '%.0f deg' % (best_yaw * 180 / math.pi)))
            dirs.append(((float(lx), float(ly)), best, ang, best_yaw))
        # the camera-relative model comes from the perpendicular presses. A tight room can block one of
        # them (a wall 12 units away), so the opposite press supplies the direction when needed.
        def flip(a):
            return None if a is None else math.atan2(math.sin(a + math.pi), math.cos(a + math.pi))

        up_ang, up_yaw = dirs[0][2], dirs[0][3]
        if up_ang is None:
            up_ang, up_yaw = flip(dirs[1][2]), dirs[1][3]
        right_ang = dirs[3][2] if dirs[3][2] is not None else flip(dirs[2][2])
        if up_ang is not None and right_ang is not None and up_yaw is not None:
            diff = math.atan2(math.sin(right_ang - up_ang), math.cos(right_ang - up_ang))
            self.up_world = up_ang
            self.sign = 1.0 if diff > 0 else -1.0
            self.yaw_at_cal = up_yaw
            self.yaw_ok = abs(abs(diff) - math.pi / 2) < math.pi / 4   # the presses are ~90 deg apart
            print('   camera-relative model: "up" is world %.0f deg at camera yaw %.0f deg, "right" is %+.0f deg '
                  'from "up" (expected +-90) -> %s'
                  % (self.up_world * 180 / math.pi, self.yaw_at_cal * 180 / math.pi, diff * 180 / math.pi,
                     'aiming with the live camera yaw' if self.yaw_ok else 'NOT camera-relative, measuring a basis'))
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
        self.basis = [(pair[0][0], pair[0][1]), (pair[1][0], pair[1][1])]
        print('   basis: stick (+%.0f, +%.0f) -> (%+.1f, %+.1f), stick (%+.0f, %+.0f) -> (%+.1f, %+.1f), area %.0f'
              % (pair[0][0][0], pair[0][0][1], pair[0][1][0], pair[0][1][1],
                 pair[1][0][0], pair[1][0][1], pair[1][1][0], pair[1][1][1], best_det))
        return True

    def stick_for(self, d):
        """Stick (lx, ly) that walks along world direction d."""
        n = (d[0] ** 2 + d[1] ** 2) ** 0.5 or 1.0
        dx, dy = d[0] / n, d[1] / n
        theta = math.atan2(dy, dx)
        y = cam_yaw()
        if self.yaw_ok and y is not None:
            up_now = self.up_world + (y - self.yaw_at_cal)
            phi = self.sign * (theta - up_now)
            phi = math.atan2(math.sin(phi), math.cos(phi))
            return int(math.sin(phi) * 30000), int(math.cos(phi) * 30000)
        if not self.basis:
            return 0, 0
        (s1, w1), (s2, w2) = self.basis
        det = w1[0] * w2[1] - w1[1] * w2[0]
        if abs(det) < 1.0:
            return 0, 0
        a = (dx * w2[1] - dy * w2[0]) / det
        b = (w1[0] * dy - w1[1] * dx) / det
        lx = a * s1[0] + b * s2[0]
        ly = a * s1[1] + b * s2[1]
        big = max(abs(lx), abs(ly), 1.0)
        if big > 30000.0:
            lx, ly = lx * 30000.0 / big, ly * 30000.0 / big
        return int(lx), int(ly)

    def walk_to(self, target, tol=70.0, limit=25.0, stop_on_block=4):
        """Hold the stick (it is never released) and re-aim about 6x a second from the live camera yaw
        and position: the camera turns with the character, so a stick set once curves the walk.
        A block is handled like a player would: keep walking along the obstacle (one side, chosen per
        goal), then re-aim; flip the side if that loses ground."""
        t0, stuck, last, sidestep = time.time(), 0, None, 0
        side = 1.0
        blocks = 0
        best_have = None
        have_at_side = None
        while time.time() - t0 < limit:
            p = player_pos(m, self.pl)
            if last is not None:
                self.walked += dist2d(p, last)
            d = (target[0] - p[0], target[1] - p[1])
            have = (d[0] ** 2 + d[1] ** 2) ** 0.5
            if have <= tol:
                stick_off()
                print('   walk: reached (%.1f, %.1f, %.1f), %.0f from the goal (%.0f units walked so far)'
                      % (p[0], p[1], p[2], have, self.walked))
                return True
            if best_have is None or have < best_have:
                best_have = have
            if last is not None and dist2d(p, last) < 2.0:
                stuck += 1
            else:
                stuck = 0
            last = p
            if stuck >= stop_on_block:
                blocks += 1
                if have_at_side is not None and have > have_at_side + 40.0:
                    side = -side          # that way lost ground: hug the other side
                have_at_side = have
                n = have or 1.0
                ux, uy = d[0] / n, d[1] / n
                if blocks % 4 == 0:
                    # cornered: back out the way we came, then try again
                    lx, ly = self.stick_for((-ux, -uy))
                    print('   walk: cornered at (%.1f, %.1f, %.1f); backing out' % (p[0], p[1], p[2]))
                    hold = 1.2
                    side = -side if blocks % 8 == 0 else side
                else:
                    lx, ly = self.stick_for((-uy * side, ux * side))
                    print('   walk: blocked at (%.1f, %.1f, %.1f); following the wall, side %+d (%d)'
                          % (p[0], p[1], p[2], int(side), sidestep + 1))
                    hold = 1.5
                sidestep += 1
                stick_set(lx, ly)
                t1 = time.time()
                while time.time() - t1 < hold:
                    q = player_pos(m, self.pl)
                    self.walked += dist2d(q, last)
                    last = q
                    time.sleep(0.15)
                stuck = 0
                continue
            lx, ly = self.stick_for(d)
            f = 1.0 if have > 200 else max(0.4, have / 200.0)
            stick_set(int(lx * f), int(ly * f))
            time.sleep(0.15)
        stick_off()
        p = player_pos(m, self.pl)
        print('   walk: gave up at (%.1f, %.1f, %.1f), %.0f from the goal (best %.0f)'
              % (p[0], p[1], p[2], dist2d(p, target), best_have if best_have is not None else 0))
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

    def face(self, target, want=0.6, limit=4.0):
        """Turn the character so its own forward vector (+0x248/+0x24c/+0x250, a unit vector) points at
        `target`: the door check `FUN_0042a480` wants dot(forward, door+0x13c..+0x144) >= 0.5 and the
        save point `FUN_0046e6c0` wants dot(unit(character -> entity), forward) > 0.5, so a character
        that stops walking sideways never qualifies however close it stands (TASK 19). Short stick
        bursts toward the target turn it without walking far."""
        t0, best = time.time(), -1.0
        while time.time() - t0 < limit:
            p = player_pos(m, self.pl)
            h = player_human(m, self.pl)
            fx, fy = (f32(m, h + 0x248), f32(m, h + 0x24c)) if h else (0.0, 0.0)
            d = (target[0] - p[0], target[1] - p[1])
            n = (d[0] ** 2 + d[1] ** 2) ** 0.5 or 1.0
            cur = (d[0] / n) * fx + (d[1] / n) * fy
            best = max(best, cur)
            if cur >= want:
                stick_off()
                print('   face: character forward is %.2f aligned with the target' % cur)
                return True
            lx, ly = self.stick_for(d)
            stick_set(lx * 0.35, ly * 0.35)     # a nudge: turns far more than it walks
            time.sleep(0.18)
        stick_off()
        print('   face: could not turn the character onto the target (best alignment %.2f)' % best)
        return False


def used_by(rec):
    """The entity's own "user" field +0xc4: the base use path `FUN_00402840(character)` (called first by
    the door's `FUN_0042c2b0` and the save point's `FUN_0046e830`) stores the character there. A door use
    need not change the level, so this is the only reliable sign that the interaction fired."""
    return u32(m, rec['addr'] + 0xc4)


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
    """Walk to the door/zone and use it the way a player does, then wait for the game's transition.

    TASK 19: the door's own eligibility check (`FUN_0042a480`) measures its 80-unit reach from
    **entity+0x10c..+0x114** (an interaction anchor 54-90 units off the rendered position in the levels
    measured) and wants `dot(character forward, door+0x13c..+0x144) >= 0.5`, so the walk goal is the
    anchor and `Walker.face()` turns the character onto it before A. `used_by(rec)` (entity+0xc4 = the
    character, written by the use function `FUN_0042c2b0`) catches a door that opens without a level
    change, which level/world watching alone cannot see."""
    print('\n== %s %s id %s at (%.2f, %.2f, %.2f), %.0f away: walking there'
          % (kind, rec['rtti'], rec['id'], rec['pos'][0], rec['pos'][1], rec['pos'][2], rec['d']))
    p = player_pos(m, 0)
    aim = rec.get('anchor') or rec['pos']
    if aim is not rec['pos'] and dist3(aim, rec['pos']) > 1.0:
        print('   its interaction anchor +0x10c is at (%.2f, %.2f, %.2f), %.0f from the rendered position'
              % (aim[0], aim[1], aim[2], dist3(aim, rec['pos'])))
    d = (aim[0] - p[0], aim[1] - p[1])
    n = (d[0] ** 2 + d[1] ** 2) ** 0.5 or 1.0
    goal = (aim[0] - d[0] / n * 45.0, aim[1] - d[1] / n * 45.0, aim[2])
    old_lv, old_w = level(m), world(m)
    reached = walker.walk_via(goal, markers, tol=60.0)
    if not reached:
        reached = walker.walk_to(goal, tol=40.0, limit=15.0)
    near = dist2d(player_pos(m, 0), aim)
    if not reached and near > 250.0:
        print('   could not reach the %s (character at %s, %.0f from its anchor)' % (kind, player_pos(m, 0), near))
        return None
    if not reached:
        print('   gave up %.0f short of the %s anchor but that is close enough to try it' % (near, kind))
    old_p = player_pos(m, 0)   # the transition is measured from HERE, not from where the walk started
    print('   at the %s: character %s (%.0f from its anchor, radius +0xa0 = %s, entity+0xc4 = %#x)'
          % (kind, old_p, near, f32(m, rec['addr'] + 0xa0), used_by(rec)))
    if kind == 'door':
        for attempt in range(4):
            walker.face(aim)
            print('   pressing A (attempt %d)' % (attempt + 1))
            press(pipe, 0, 'A', 0.4)
            time.sleep(1.2)
            how = wait_transition(old_lv, old_w, old_p, 5.0)
            if how:
                return how
            if player_human(m, 0) and used_by(rec) == player_human(m, 0):
                print('   *** the door took the character (entity+0xc4 = %#x): the interaction fired'
                      % used_by(rec))
                return 'used (door opened, level unchanged)'
            if attempt in (0, 1):
                # step onto the anchor itself, face it again, then press once more
                walker.walk_to(aim, tol=25.0, limit=8.0)
        print('   no transition')
        return None
    walker.face(aim)
    return wait_transition(old_lv, old_w, old_p, 15.0)


def save_here(c):
    """Save through the game's own save point: walk to it, press A, and photograph the menu."""
    if not c['saves']:
        print('\n== save: this room has no save point entity')
        return None
    rec = c['saves'][0]
    print('\n== save: walking to %s id %s at (%.2f, %.2f, %.2f)'
          % (rec['rtti'], rec['id'], rec['pos'][0], rec['pos'][1], rec['pos'][2]))
    if not walker.walk_to(rec['pos'], tol=45.0):
        print('   could not reach the save point')
        return None
    walker.face(rec['pos'])     # FUN_0046e6c0 wants dot(unit(char -> entity), forward) > 0.5
    press(pipe, 0, 'A', 0.4)
    time.sleep(2.0)
    print('   after A: entity+0xc4 = %#x (character %#x), mode %s'
          % (u32(m, rec['addr'] + 0xc4), player_human(m, 0), mode()))
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
if walker is not None:
    print('   %d units of walking measured by the walker (camera-yaw aiming, TASK 18)' % round(walker.walked))
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
