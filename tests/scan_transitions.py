"""TASK 20 step 1: where do the game's level transitions point, LIVE, in every save slot?

One host copy, all ten save slots in one game launch (the runner starts/stops it). For each slot it
loads the slot with the game's own menu-load path and then reads every level-list entity that can
carry a transition destination.

Fields (DERIVED from the decompile, verified live by this tool):

  * `FUN_0042aa70` (decompile 24666-24710, door class, called from `FUN_0042c0c0`) does
        if (entity[0x118] != world level tag)  ChangeLevel(entity[0x118], entity[4], 1);
    i.e. the destination level tag is `entity+0x118`, the entry id is `entity+4` (the entity's own
    instance id) and the flag is the constant 1.
  * The CToeDoor constructor `FUN_0042cd40` initialises `+0x118` to 0, so a door that stays in its
    level has no destination there.

For every entity of a door / loading-zone class it prints the RTTI class, the entity id, `+0x24`
(the "enabled" gate the door check reads first), `+0x118` (as text and hex), `+0x10c` (the
interaction anchor) and the vtable slots +0x34 / +0x70 / +0x74 so a class can be identified.
It also scans dwords +0x100..+0x150 for anything that looks like a 4-character level tag, so a
destination kept in another field of another class cannot be missed.

Every tag found is validated against `tests/level_tags.txt`, which is the level list of the test
copy's `datapack.hvp` (`_levels/<letter>/<tag>/` directories, read-only; a tag that is not there can
still exist in another pack, e.g. B101 was seen from a real ChangeLevel call in FINDINGS_12).

Usage: python -I scan_transitions.py <pid> [slot[,slot...]]
Read-only: no teleport, no pad press, no requested level.
"""
import os
import re
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe
from peek import Proc
from tp_to_items import entities, f32, level, player_pos, rtti, tag, u32, world

GAME = 0x6c3068
CLASSES = ('CToeLoadingZone', 'CToeDoor', 'CToeDoubleDoor', 'CToeSpecialDoor', 'CToeInternalDoor',
           'CToeFlapDoor', 'CToeElevator', 'CToeStair', 'CToeCrossing', 'CToeLadder', 'CToeLegupGrid',
           'CToeZoneHelp', 'CToeCharacterPos', 'CToeDangerousZone')

HERE = os.path.dirname(os.path.abspath(__file__))


def level_tags():
    try:
        txt = open(os.path.join(HERE, 'level_tags.txt'), 'r', encoding='latin-1').read().split()
    except OSError:
        return set()
    return set(t.strip().upper() for t in txt if re.match(r'^[A-Za-z][0-9]{3}$', t.strip()))


KNOWN_TAGS = level_tags()


def looks_like_tag(v):
    s = tag(v)
    return re.match(r'^[A-Za-z][0-9]{3}$', s) is not None


def slot_present(pid, slot):
    return True


def mode(m):
    g = u32(m, m.va(GAME))
    return u32(m, g + 0x310) if g else 0


def wait_world(m, lv0, w0, limit=60.0):
    t0 = time.time()
    while time.time() - t0 < limit:
        w = world(m)
        if mode(m) == 1 and w and len(entities(m)) > 0 and (tag(level(m)) != lv0 or w != w0):
            time.sleep(8.0)   # let the level build every entity
            return True
        time.sleep(1.0)
    return False


def vtslot(m, e, off):
    vt = u32(m, e)
    return u32(m, vt + off) if vt else 0


def main():
    pid = int(sys.argv[1])
    slots = [int(x) for x in sys.argv[2].split(',')] if len(sys.argv) > 2 else list(range(10))
    m = Proc(pid)
    t0 = time.time()
    pipe = None
    while time.time() - t0 < 90:
        try:
            pipe = Pipe(pid)
            break
        except Exception:
            time.sleep(1.0)
    if pipe is None:
        raise SystemExit('the command pipe never appeared')
    # at the main menu
    t0 = time.time()
    while time.time() - t0 < 90:
        if mode(m) == 2 and not world(m):
            break
        time.sleep(1.0)
    print('at the main menu after %.1f s; %d known level tags' % (time.time() - t0, len(KNOWN_TAGS)))

    rows = []
    for slot in slots:
        lv0, w0 = tag(level(m)), world(m)
        print('\n===== slot %d: %s' % (slot + 1, pipe.cmd('loadsave game%d.sav' % slot)))
        if not wait_world(m, lv0, w0):
            print('   slot did not reach a world')
            continue
        lv = tag(level(m))
        ents = entities(m)
        print('   level %s, %d entities, player 1 at %s' % (lv, len(ents), player_pos(m, 0)))
        found = 0
        for e in ents:
            name = rtti(m, e) or '?'
            idv = u32(m, e + 4)
            p118, p11c, p120, p124 = (u32(m, e + 0x118), u32(m, e + 0x11c), u32(m, e + 0x120), u32(m, e + 0x124))
            candidates = [(o, u32(m, e + o)) for o in range(0x100, 0x154, 4)]
            hits = [(o, v) for o, v in candidates if looks_like_tag(v)]
            interesting = any(name.startswith(c) for c in CLASSES) or p118 or hits
            if not interesting:
                continue
            found += 1
            p = (f32(m, e + 0x6c), f32(m, e + 0x70), f32(m, e + 0x74))
            print('   %-22s id %-5s +0x24 %d +0xb8 %d pos (%.1f, %.1f, %.1f) @%x'
                  % (name, tag(idv), u32(m, e + 0x24), u32(m, e + 0xb8), p[0], p[1], p[2], e))
            print('      +0x118 %s (0x%08x) %s | +0x11c %s +0x120 %s +0x124 %s'
                  % (tag(p118), p118, 'KNOWN-LEVEL' if tag(p118) in KNOWN_TAGS else
                     ('looks-like-tag' if looks_like_tag(p118) else '-'),
                     tag(p11c), tag(p120), tag(p124)))
            print('      vtable slots +0x34 %08x +0x70 %08x +0x74 %08x | anchor +0x10c (%.1f, %.1f, %.1f)'
                  % (vtslot(m, e, 0x34), vtslot(m, e, 0x70), vtslot(m, e, 0x74),
                     f32(m, e + 0x10c), f32(m, e + 0x110), f32(m, e + 0x114)))
            if hits:
                print('      tag-like dwords: %s' % ', '.join(
                    '+0x%x %s%s' % (o, tag(v), ' (known)' if tag(v) in KNOWN_TAGS else '') for o, v in hits))
            if looks_like_tag(p118):
                rows.append((slot + 1, lv, name, tag(idv), tag(p118), idv, 1,
                             'known' if tag(p118) in KNOWN_TAGS else 'NOT-in-datapack'))
        if not found:
            print('   no door / loading-zone entity in this level')
    print('\n===== TABLE (slot, level, entity class, entity id, target tag, entry, flag, tag check)')
    for r in rows:
        print('   %2d  %-4s  %-22s id %-5s -> %-4s entry %-5d flag %d  %s' % r)
    if not rows:
        print('   (no transition destination found in these slots)')
    print('DONE')


if __name__ == '__main__':
    main()
