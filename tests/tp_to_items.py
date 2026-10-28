"""TASK 17 Part B: the item/enemy gate that EVERY teleport into a room must pass.

Before the mod's `tp` is allowed to move a character, this tool scans the target's neighbourhood and
refuses unless there is at least one LIVE collectable item and no enemy:

  live item  = a CToeItem* entity in the level list with +0x20 != 0 (the world gate the base entity
               constructor FUN_004020d0 sets), +0xa8 == 0 (not collected) and the three interaction
               gates +0xc0 / +0xac / +0xb0 clear - exactly what the game's own interaction check
               FUN_0044d6a0 tests (see ITEMS_FINDINGS section 1 and SLOT_SCAN.md).
  enemy      = an object in the NPC manager (world+0x1760) or in the level list whose RTTI class name
               starts with CCharacter, with a character attached and life (+0x320) > 0, within the
               radius; plus any spawner/respawner (RTTI CToeRespawn*) within the radius, because those
               can bring enemies in even when none is alive yet.

The tool then runs the mod's SAFE `tp` (TASK 17 Part A: the character physics must settle on a floor
within 8 units of the requested Z, otherwise the mod restores the old position) and watches the
character's Z for 3 s to prove it really stands still.

It is importable: `from tp_to_items import scan_room, gate_teleport` gives every test the same check, so
no test can teleport into a room without it.

Usage:
  python -I tp_to_items.py <pid> <player 0|1> <x> <y> [z] [--radius N] [--scan-only] [--json]
Exit: 0 = teleport done and the character stood still for 3 s (or --scan-only and the room passes),
      2 = refused/skipped (the target has no item, has enemies, or has no floor),
      1 = the tool or the game did not answer.
"""
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe, press   # noqa: F401  (press is re-exported for the tests that import this module)
from peek import Proc

GAME = 0x6c3068
ITEM_TAGS = {
    0x41434944, 0x42415454, 0x424b504b, 0x424c4541, 0x4341424f, 0x43524f57, 0x454e4452,
    0x474c5943, 0x4943414d, 0x49434500, 0x4943524e, 0x49445343, 0x4a454d4d, 0x4a455252,
    0x4a554241, 0x4b455900, 0x4c564552, 0x4d415000, 0x4d454449, 0x50415353, 0x53455255,
    0x534f4441, 0x53544154, 0x53545249, 0x53595249, 0x57454c44,
}
DEFAULT_RADIUS = 400.0


def tag(v):
    return ''.join(chr((v >> s) & 0xff) if 32 <= ((v >> s) & 0xff) < 127 else '.'
                   for s in (24, 16, 8, 0))


def f32(m, addr):
    b = m.read(addr, 4)
    return struct.unpack('<f', b)[0] if b else 0.0


def u32(m, addr):
    try:
        return m.u32(addr) or 0
    except Exception:
        return 0


def world(m):
    g0 = u32(m, m.va(GAME))
    return u32(m, g0 + 0x378) if g0 else 0


def level(m):
    w = world(m)
    return u32(m, w + 4) if w else 0


def rtti(m, obj):
    """Class name from the object's vtable RTTI (vtable-4 -> COL -> +0xc TypeDescriptor -> name at +8)."""
    vt = u32(m, obj)
    if not vt:
        return ''
    col = u32(m, vt - 4)
    td = u32(m, col + 0xc) if col else 0
    b = m.read(td + 8, 96) if td else b''
    return ((b or b'').split(b'\0')[0].decode('latin1', 'replace')).replace('.?AV', '').replace('@@', '')


def pos_of(m, obj):
    return (f32(m, obj + 0x6c), f32(m, obj + 0x70), f32(m, obj + 0x74))


def pos_char(m, obj):
    return (f32(m, obj + 0x23c), f32(m, obj + 0x240), f32(m, obj + 0x244))


def entities(m):
    """The level entity list: CToeManager at world+0x1768, list at manager+8, count at +0x14,
    node {entity at +0, next at +4} (FINDINGS_15 section 1)."""
    w = world(m)
    out = []
    mgr = u32(m, w + 0x1768) if w else 0
    if not mgr:
        return out
    node, seen = u32(m, mgr + 8), set()
    while node and node not in seen and len(out) < 4000:
        seen.add(node)
        e = u32(m, node)
        if e:
            out.append(e)
        node = u32(m, node + 4)
    return out


def manager_objects(m, off, limit=64):
    w = world(m)
    mg = u32(m, w + off) if w else 0
    out = []
    if not mg:
        return out
    n, arr = u32(m, mg + 4), u32(m, mg + 0xc)
    for i in range(min(n, limit) if arr else 0):
        o = u32(m, arr + 4 * i)
        if o:
            out.append(o)
    return out


def player_human(m, pl):
    w = world(m)
    ctl = u32(m, w + 0x1748) if w else 0
    return u32(m, ctl + 4 + 0x764 * pl) if ctl else 0


def player_pos(m, pl):
    h = player_human(m, pl)
    return pos_char(m, h) if h else None


def dist3(a, b):
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5


def dist2d(a, b):
    return sum((a[i] - b[i]) ** 2 for i in range(2)) ** 0.5


def is_enemy_class(name):
    """CCharacterNPC* and the AI characters. CCharacterNPCAura is a trigger (life 0), so the life test
    below is what actually decides; the class test only keeps non-characters out."""
    return name.startswith('CCharacter')


def scan_room(m, target, radius=DEFAULT_RADIUS, verbose=True):
    """Everything the gate needs, read-only: the live items, the enemies and the spawners around
    `target` (x, y, z) inside `radius` (3-D for characters, 2-D from the target for items because an
    item can sit a floor above the target and still be the room's item)."""
    w = world(m)
    lvl = tag(level(m))
    ents = entities(m)
    live, dead, near_items = [], [], []
    spawners = []
    for e in ents:
        cls = u32(m, e + 0x10)
        if cls in ITEM_TAGS:
            p = pos_of(m, e)
            coll, p20 = u32(m, e + 0xa8), u32(m, e + 0x20)
            g = (u32(m, e + 0xc0), u32(m, e + 0xac), u32(m, e + 0xb0))
            sane = all(abs(v) < 50000 for v in p)
            rec = dict(addr=e, cls=tag(cls), id=tag(u32(m, e + 4)), pos=p, collected=coll, active=p20,
                       gates=g, rtti=rtti(m, e), d2=dist2d(p, target), d3=dist3(p, target))
            if coll == 0 and sane and any(abs(v) > 0.01 for v in p) and g == (0, 0, 0):
                if p20 != 0:
                    live.append(rec)
                    if rec['d2'] <= radius:
                        near_items.append(rec)
                else:
                    dead.append(rec)
        else:
            name = rtti(m, e)
            if name.startswith('CToeRespawn'):
                p = pos_of(m, e)
                if all(abs(v) < 50000 for v in p) and dist2d(p, target) <= radius:
                    spawners.append(dict(addr=e, rtti=name, id=tag(u32(m, e + 4)), pos=p))
    enemies = []
    seen = set()
    for src in ('npc', 'level'):
        objs = manager_objects(m, 0x1760) if src == 'npc' else ents
        for o in objs:
            if o in seen:
                continue
            name = rtti(m, o)
            if not is_enemy_class(name):
                continue
            life = u32(m, o + 0x320)
            if life == 0:
                continue
            seen.add(o)
            p = pos_char(m, o)
            if all(abs(v) < 50000 for v in p) and dist3(p, target) <= radius:
                enemies.append(dict(addr=o, rtti=name, src=src, life=life, tag=tag(u32(m, o + 0x14)),
                                    pos=p, d=dist3(p, target)))
    res = dict(level=lvl, world=w, entities=len(ents), live_total=len(live),
               near_items=near_items, dead_items=dead, enemies=enemies, spawners=spawners,
               radius=radius, target=tuple(target))
    if verbose:
        print('room scan: level %s, %d level entities, target (%.1f, %.1f, %.1f), radius %.0f'
              % (lvl, len(ents), target[0], target[1], target[2], radius))
        print('  live items in the level: %d (near the target: %d), inactive/gated item entities: %d'
              % (len(live), len(near_items), len(dead)))
        for r in near_items:
            print('    LIVE item %s id %s at (%.2f, %.2f, %.2f), %.0f from the target @%x'
                  % (r['cls'], r['id'], r['pos'][0], r['pos'][1], r['pos'][2], r['d2'], r['addr']))
        for r in dead:
            if r['d2'] <= radius:
                print('    not live: %s id %s p20=%d collected=%d gates %s at (%.2f, %.2f, %.2f), %.0f from the target'
                      % (r['cls'], r['id'], r['active'], r['collected'], r['gates'], r['pos'][0], r['pos'][1],
                         r['pos'][2], r['d2']))
        print('  enemies within %.0f: %d' % (radius, len(enemies)))
        for r in enemies:
            print('    ENEMY %s %s life %d at (%.2f, %.2f, %.2f), %.0f from the target (%s)'
                  % (r['rtti'], r['tag'], r['life'], r['pos'][0], r['pos'][1], r['pos'][2], r['d'], r['src']))
        print('  spawners within %.0f: %d' % (radius, len(spawners)))
        for r in spawners:
            print('    SPAWNER %s id %s at (%.2f, %.2f, %.2f)' % (r['rtti'], r['id'], r['pos'][0], r['pos'][1], r['pos'][2]))
    return res


def room_verdict(room):
    """(allowed, reason): the owner's rule - items >= 1 and enemies == 0 before any teleport."""
    if room['enemies']:
        return False, ('%d enemy/enemies within %.0f units of the target (%s)'
                       % (len(room['enemies']), room['radius'],
                          ', '.join(r['rtti'] for r in room['enemies'][:4])))
    if room['spawners']:
        return False, ('%d spawner(s) within %.0f units of the target (%s)'
                       % (len(room['spawners']), room['radius'],
                          ', '.join(r['rtti'] for r in room['spawners'][:4])))
    if not room['near_items']:
        return False, 'no live collectable item within %.0f units of the target' % room['radius']
    return True, '%d live item(s), no enemy, no spawner within %.0f units' % (len(room['near_items']), room['radius'])


def wait_standing(m, pl, want, seconds=3.0, step=0.25):
    """Sample the character for `seconds`; it must stay within 2 units of `want` (3-D) the whole time.
    Returns (ok, samples, worst_distance)."""
    samples, worst, t0 = [], 0.0, time.time()
    while time.time() - t0 < seconds:
        p = player_pos(m, pl)
        if p:
            d = dist3(p, want)
            samples.append((round(time.time() - t0, 2), tuple(round(v, 2) for v in p), round(d, 2)))
            worst = max(worst, d)
        time.sleep(step)
    return worst <= 2.0, samples, worst


def gate_teleport(pid, pl, x, y, z=None, radius=DEFAULT_RADIUS, verbose=True, stand_seconds=3.0,
                  pipe=None, m=None):
    """The one entry point every test should use: scan the room, refuse unless items >= 1 and no enemy,
    then run the mod's safe `tp` and prove the character stands still.

    Returns dict(ok, why, room, tp_reply, standing, worst). `ok` is False whenever the teleport did not
    happen or did not hold; `why` is the human-readable reason to print."""
    m = m or Proc(pid)
    # The mod's command pipe serves ONE client at a time: a caller that already holds a Pipe must pass it
    # in (check_gate.py does), or a second open() fails with OSError 22.
    own_pipe = pipe is None
    if own_pipe:
        pipe = Pipe(pid)
    target = (x, y, z if z is not None else (player_pos(m, pl) or (0, 0, 0))[2])
    room = scan_room(m, target, radius, verbose=verbose)
    allowed, why = room_verdict(room)
    if not allowed:
        if verbose:
            print('SKIP teleport: %s (the owner\'s rule: items >= 1 and no enemies before any tp)' % why)
        return dict(ok=False, why='skipped: ' + why, room=room, tp_reply='', standing=None, worst=None)
    cmd = 'tp %d %.3f %.3f %.3f' % (pl, target[0], target[1], target[2])
    if z is None:
        cmd = 'tp %d %.3f %.3f' % (pl, target[0], target[1])
    reply = pipe.cmd(cmd)
    if verbose:
        print('  %s -> %s' % (cmd, reply))
    if not reply.startswith('ok'):
        return dict(ok=False, why='tp refused: ' + reply, room=room, tp_reply=reply, standing=None, worst=None)

    settled = player_pos(m, pl) or target
    held, samples, worst = wait_standing(m, pl, settled, stand_seconds)
    if verbose:
        for s in samples:
            print('    t+%.2fs pos (%.2f, %.2f, %.2f)  drift %.2f' % (s[0], s[1][0], s[1][1], s[1][2], s[2]))
        print('  standing still for %.1f s: %s (worst drift %.2f units, limit 2.0)' % (stand_seconds, held, worst))
    return dict(ok=held, why='ok' if held else 'did not stand still (worst drift %.2f)' % worst,
                room=room, tp_reply=reply, standing=held, worst=worst)


def main(argv):
    if len(argv) < 4:
        print(__doc__)
        return 1
    pid, pl = int(argv[0]), int(argv[1])
    x, y = float(argv[2]), float(argv[3])
    z, radius, scan_only, as_json = None, DEFAULT_RADIUS, False, False
    rest = argv[4:]
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == '--radius' and i + 1 < len(rest):
            radius = float(rest[i + 1])
            i += 2
        elif a == '--scan-only':
            scan_only = True
            i += 1
        elif a == '--json':
            as_json = True
            i += 1
        elif a.startswith('--'):
            print('unknown option %s' % a)
            return 1
        else:
            z = float(a)
            i += 1
    m = Proc(pid)
    target = (x, y, z if z is not None else (player_pos(m, pl) or (0, 0, 0))[2])
    room = scan_room(m, target, radius, verbose=not as_json)
    allowed, why = room_verdict(room)
    if as_json:
        print(json.dumps(dict(level=room['level'], entities=room['entities'], live=len(room['near_items']),
                              enemies=len(room['enemies']), spawners=len(room['spawners']),
                              allowed=allowed, why=why)))
    else:
        print('verdict: %s -- %s' % ('ALLOW' if allowed else 'SKIP', why))
    if scan_only or not allowed:
        return 0 if (scan_only and allowed) else 2
    res = gate_teleport(pid, pl, x, y, z, radius, verbose=not as_json)
    return 0 if res['ok'] else 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
