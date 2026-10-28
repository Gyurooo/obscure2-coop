"""TASK 15 Part A: load every save slot on ONE copy (the host test copy) and scan the live level.

For each slot: `loadsave gameN.sav` (the game's own menu-load path), wait for the world, then print
  * game mode / request state and the level tag,
  * the CToeManager entity list (world+0x1768, count +0x14, list head mgr+0x18, node {ent,next}):
    total count, class-tag histogram, and every item-class entity with its collected flag (+0xa8),
    the active/world gate (+0x20), the three interaction gates (+0xc0, +0xac, +0xb0) and radius (+0xa0),
  * the RTTI class name of an entity's vtable where readable (vtable-4 -> COL -> +0xc type
    descriptor -> +8 name), so doors/breakables/enemies can be classified,
  * the NPC/enemy manager (world+0x1760: count +4, array +0xc; NPC vtable, tag +0x14, pos +0x23c,
    life +0x320, anim +0x2dc),
  * the humans (world+0x175c) and both player characters.

Read-only. The caller starts/stops the single host copy (see run_scan_slots.sh).
Usage: python -I scan_slots.py <pid> <slot[,slot...]> [--keep]
"""
import sys, os, struct, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot
from peek import Proc

GAME = 0x6c3068
ITEM_TAGS = {
    0x41434944, 0x42415454, 0x424b504b, 0x424c4541, 0x4341424f, 0x43524f57, 0x454e4452,
    0x474c5943, 0x4943414d, 0x49434500, 0x4943524e, 0x49445343, 0x4a454d4d, 0x4a455252,
    0x4a554241, 0x4b455900, 0x4c564552, 0x4d415000, 0x4d454449, 0x50415353, 0x53455255,
    0x534f4441, 0x53544154, 0x53545249, 0x53595249, 0x57454c44,
}


def tag(v):
    return ''.join(chr((v >> s) & 0xff) if 32 <= ((v >> s) & 0xff) < 127 else '.'
                   for s in (24, 16, 8, 0))


def f32(m, addr):
    b = m.read(addr, 4)
    return struct.unpack('<f', b)[0] if b else 0.0


def u32(m, addr):
    try:
        return m.u32(addr)
    except Exception:
        return 0


def game(m):
    try:
        return m.u32(m.va(GAME))
    except Exception:
        return 0


def world(m):
    g = game(m)
    return u32(m, g + 0x378) if g else 0


def mode(m):
    g = game(m)
    return u32(m, g + 0x310) if g else None


def reqstate(m):
    g = game(m)
    return u32(m, g + 0x320) if g else None


def rtti_name(m, obj):
    """Class name from the object's vtable RTTI (MSVC: vtable-4 -> CompleteObjectLocator,
    COL+0xc -> TypeDescriptor, and the decorated name is stored inline at TypeDescriptor+8)."""
    vt = u32(m, obj)
    if not vt:
        return ''
    col = u32(m, vt - 4)
    if not col:
        return ''
    td = u32(m, col + 0xc)
    if not td:
        return ''
    raw = m.read(td + 8, 160) or b''
    s = raw.split(b'\x00')[0].decode('latin1', 'replace')
    i = s.find('AV')
    if i >= 0:
        s = s[i + 2:]
    return s.rstrip('@')


def humans(m):
    w = world(m)
    mg = u32(m, w + 0x175c) if w else 0
    if not mg:
        return []
    n, arr = u32(m, mg + 4), u32(m, mg + 0xc)
    out = []
    for i in range(min(n, 8) if arr else 0):
        h = u32(m, arr + 4 * i)
        if h:
            out.append(h)
    return out


def npcs(m):
    w = world(m)
    mg = u32(m, w + 0x1760) if w else 0
    if not mg:
        return []
    n, arr = u32(m, mg + 4), u32(m, mg + 0xc)
    out = []
    for i in range(min(n, 64) if arr else 0):
        h = u32(m, arr + 4 * i)
        if h:
            out.append(h)
    return out


def walk_list(m, head):
    out, node, seen = [], head, set()
    while node and node not in seen and len(out) < 4000:
        seen.add(node)
        ent = u32(m, node)
        if ent:
            out.append(ent)
        node = u32(m, node + 4)
    return out


def entities(m):
    """CToeManager (world+0x1768). Three candidate list heads are reported: +0, +8 and +0x18; the
    caller picks the one that matches the manager's own count (+0x14)."""
    w = world(m)
    mgr = u32(m, w + 0x1768) if w else 0
    if not mgr:
        return 0, 0, {}
    count = u32(m, mgr + 0x14)
    lists = {}
    for off in (0, 8, 0x18):
        lists[off] = walk_list(m, u32(m, mgr + off))
    return mgr, count, lists


def pick_list(m, count, lists):
    """The CToeManager list is the one whose length matches the manager's count; ties go to the list
    with the most entities that have a real position."""
    def score(off):
        ents = lists[off]
        match = 1 if len(ents) == count else 0
        real = sum(1 for e in ents if sane(pos(m, e)) and any(abs(v) > 0.01 for v in pos(m, e)))
        return (match, real, len(ents))
    best = max(lists, key=score)
    return best, lists[best]


def player_human(m, pl):
    w = world(m)
    ctl = u32(m, w + 0x1748) if w else 0
    return u32(m, ctl + 4 + 0x764 * pl) if ctl else 0


def pos(m, h):
    return (f32(m, h + 0x23c), f32(m, h + 0x240), f32(m, h + 0x244))


def sane(p):
    return all(abs(v) < 1e6 for v in p)


def scan(m, slot):
    print('=' * 100)
    w = world(m)
    print('SLOT game%d.sav  mode %s request-state %s world %#x level %s' % (
        slot, mode(m), reqstate(m), w or 0, tag(u32(m, w + 4)) if w else '----'))
    if not w:
        print('  NO WORLD')
        return None
    mgr, count, lists = entities(m)
    print('  CToeManager @%x count+0x14 %d; list lengths: %s' % (
        mgr or 0, count, ', '.join('+0x%x:%d' % (o, len(l)) for o, l in sorted(lists.items()))))
    chosen, ents = pick_list(m, count, lists)
    print('  using list at mgr+0x%x (%d entities)' % (chosen, len(ents)))
    hist, items, other = {}, [], []
    for ent in ents:
        cls = u32(m, ent + 0x10)
        hist[tag(cls)] = hist.get(tag(cls), 0) + 1
        rec = (ent, cls, u32(m, ent + 4), u32(m, ent + 0xa8), pos(m, ent),
               u32(m, ent + 0x20), u32(m, ent + 0x34), u32(m, ent + 0xc0), u32(m, ent + 0xac),
               u32(m, ent + 0xb0), f32(m, ent + 0xa0), rtti_name(m, ent))
        if cls in ITEM_TAGS:
            items.append(rec)
        else:
            other.append(rec)
    print('  class-tag histogram: %s' % ', '.join('%s:%d' % (k, v) for k, v in sorted(hist.items())))
    print('  item-class entities: %d' % len(items))
    for (ent, cls, idv, coll, p, p20, p34, c0, ac, b0, rad, rn) in items:
        live = (coll == 0 and p20 != 0 and c0 == 0 and ac == 0 and b0 == 0 and sane(p))
        print('    item %s id %s collected %d p20=%d p34=%x pos (%.2f, %.2f, %.2f) gates c0=%d ac=%d b0=%d r=%.1f @%x %s %s' % (
            tag(cls), tag(idv), coll, p20, p34, p[0], p[1], p[2], c0, ac, b0, rad, ent, rn, 'LIVE' if live else 'dead'))
    # non-item entity classes, with RTTI names, so doors / breakables / enemies can be classified
    byrtti = {}
    for rec in other:
        key = '%s [%s]' % (rec[11] or '?', tag(rec[1]))
        byrtti[key] = byrtti.get(key, 0) + 1
    print('  non-item entities by class: %s' % ', '.join('%s x%d' % (k, v) for k, v in sorted(byrtti.items())))
    for rec in other:
        ent, cls, idv, coll, p, p20 = rec[0], rec[1], rec[2], rec[3], rec[4], rec[5]
        print('    ent %s id %s collected %s p20=%s pos (%.2f, %.2f, %.2f) @%x %s' % (
            tag(cls), tag(idv), coll, p20, p[0], p[1], p[2], ent, rec[11]))
    hs = humans(m)
    print('  humans: %d' % len(hs))
    for h in hs:
        p = pos(m, h)
        print('    human %s @%x pos (%.2f, %.2f, %.2f) life %d anim %d' % (
            tag(u32(m, h + 0x14)), h, p[0], p[1], p[2], u32(m, h + 0x320), u32(m, h + 0x2dc)))
    ns = npcs(m)
    print('  NPC/enemy manager: %d' % len(ns))
    for h in ns:
        p = pos(m, h)
        print('    npc %s @%x pos (%.2f, %.2f, %.2f) life %d anim %d rtti %s' % (
            tag(u32(m, h + 0x14)), h, p[0], p[1], p[2], u32(m, h + 0x320), u32(m, h + 0x2dc), rtti_name(m, h)))
    for pl in (0, 1):
        ph = player_human(m, pl)
        if ph:
            p = pos(m, ph)
            print('  player %d human %s pos (%.2f, %.2f, %.2f)' % (pl + 1, tag(u32(m, ph + 0x14)), p[0], p[1], p[2]))
        else:
            print('  player %d human none' % (pl + 1))
    live = [r for r in items if r[3] == 0 and r[5] != 0 and r[7] == 0 and r[8] == 0 and r[9] == 0 and sane(r[4])]
    print('  SUMMARY slot %d level %s entities %d items %d live-items %d npcs %d humans %d' % (
        slot, tag(u32(m, w + 4)), len(ents), len(items), len(live), len(ns), len(hs)))
    return dict(slot=slot, level=tag(u32(m, w + 4)), entities=len(ents), items=len(items),
                live=len(live), npcs=len(ns), humans=len(hs), hist=hist,
                live_items=[(tag(r[1]), tag(r[2]), r[4]) for r in live],
                npc_names=[rtti_name(m, h) for h in ns])


pid = int(sys.argv[1])
slots = [int(x) for x in sys.argv[2].split(',') if x != '']
m = Proc(pid)
p = None
t0 = time.time()
while time.time() - t0 < 90:
    try:
        p = bot.Pipe(pid)
        break
    except Exception:
        time.sleep(1.0)
if p is None:
    raise SystemExit('the command pipe never appeared')
print('command pipe open after %.1f s' % (time.time() - t0))
t0 = time.time()
while time.time() - t0 < 90:
    if mode(m) == 2 and not world(m):
        break
    time.sleep(1.0)
print('at the main menu (mode %s, world %#x) after %.1f s' % (mode(m), world(m) or 0, time.time() - t0))
out = []
print('pid %d; slots %s' % (pid, slots))
for slot in slots:
    t = time.time()
    w0, lv0 = world(m), u32(m, world(m) + 4) if world(m) else 0
    r = p.cmd('loadsave game%d.sav' % slot)
    print('loadsave game%d.sav -> %s (before: world %#x level %s)' % (slot, r, w0 or 0, tag(lv0) if lv0 else '----'))
    ok = False
    while time.time() - t < 120:
        w1 = world(m)
        # a new world pointer, or the same world rebuilt for another level: the old world's data must
        # not be scanned, so require the level tag to differ (or no world before the load)
        if mode(m) == 1 and w1 and len(humans(m)) >= 1 and reqstate(m) == 0 and (not w0 or w1 != w0 or u32(m, w1 + 4) != lv0):
            ok = True
            break
        time.sleep(1.0)
    if ok:
        # the level builds its entities over the first frames: settle before reading them
        time.sleep(10.0)
    print('world up for slot %d: %s after %.1f s' % (slot, ok, time.time() - t))
    if ok:
        time.sleep(3.0)   # let the level finish creating its entities
        res = scan(m, slot)
        if res:
            out.append(res)
    else:
        print('SLOT %d did not reach a world (mode %s world %#x req %s)' % (slot, mode(m), world(m) or 0, reqstate(m)))
        # give the game a moment, then continue with the next slot from wherever it is
        time.sleep(3)
print('=' * 100)
print('TABLE')
for r in out:
    print('%d\t%s\t%d\t%d\t%d\t%d\t%d\t%s' % (r['slot'], r['level'], r['entities'], r['items'], r['live'],
                                              r['npcs'], r['humans'], ','.join('%s@%.1f,%.1f,%.1f' % (a, *p) for a, b, p in r['live_items'])))
print('DONE %d/%d slots scanned' % (len(out), len(slots)))
