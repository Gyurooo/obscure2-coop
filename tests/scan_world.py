"""TASK 60 probe: what the ten test saves actually contain of the world-state families.

Read-only. For every slot (`loadsave gameN.sav`, the game's own menu-load path) it prints, from the
level's CToeManager entity lists:
  * every container-family entity (CToeContainer, CToeChest, CToeChestKey, CToePedestal) with the
    fields their open/use/give path reads,
  * every save point (CToeSavePoint, CToeSimpleSavePoint) with the fields its use check reads,
  * every CToeRespawner and every item-source class (CToeLoot, CToeBreakable*),
  * every CToeItem* entity with its live gate,
so the check can be written against what exists. Usage: python -I scan_world.py <pid> <slots>
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
FAMILY = ('Container', 'Chest', 'Pedestal', 'SavePoint', 'Respawner', 'Loot', 'Breakable', 'HeavyCase')


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
    g = u32(m, m.va(GAME))
    return u32(m, g + 0x378) if g else 0


def mode(m):
    g = u32(m, m.va(GAME))
    return u32(m, g + 0x310) if g else 0


def reqstate(m):
    g = u32(m, m.va(GAME))
    return u32(m, g + 0x320) if g else 0


def rtti_name(m, obj):
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


def walk(m, head):
    out, node, seen = [], head, set()
    while node and node not in seen and len(out) < 4000:
        seen.add(node)
        e = u32(m, node)
        if e:
            out.append(e)
        node = u32(m, node + 4)
    return out


def entities(m):
    w = world(m)
    mgr = u32(m, w + 0x1768) if w else 0
    if not mgr:
        return w, 0, []
    count = u32(m, mgr + 0x14)
    lists = {o: walk(m, u32(m, mgr + o)) for o in (0, 8, 0x18)}
    best = max(lists, key=lambda o: (len(lists[o]) == count, len(lists[o])))
    return w, mgr, lists[best]


def humans(m):
    w = world(m)
    mg = u32(m, w + 0x175c) if w else 0
    if not mg:
        return []
    return [u32(m, u32(m, mg + 0xc) + 4 * i) for i in range(min(u32(m, mg + 4), 8))]


def desc(m, e, rn):
    return ('%-22s tag %s id %s p14=%d p20=%d p24=%d pos (%.1f, %.1f, %.1f) '
            'a4=%d a8=%d ac=%d b0=%d c0=%d c4=%d r=%.0f p134=%s p13c=%x p150=%x vt=%x @%x' % (
                rn or '?', tag(u32(m, e + 0x10)), tag(u32(m, e + 4)), u32(m, e + 0x14), u32(m, e + 0x20),
                u32(m, e + 0x24), f32(m, e + 0x6c), f32(m, e + 0x70), f32(m, e + 0x74),
                u32(m, e + 0xa4), u32(m, e + 0xa8), u32(m, e + 0xac), u32(m, e + 0xb0),
                u32(m, e + 0xc0), u32(m, e + 0xc4), f32(m, e + 0xa0), tag(u32(m, e + 0x134)),
                u32(m, e + 0x13c), u32(m, e + 0x150), u32(m, e), e))


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
print('pipe open after %.1f s' % (time.time() - t0))
t0 = time.time()
while time.time() - t0 < 90:
    if mode(m) == 2 and not world(m):
        break
    time.sleep(1.0)
print('at the menu: mode %s world %#x' % (mode(m), world(m) or 0))
for slot in slots:
    t = time.time()
    w0 = world(m)
    lv0 = u32(m, w0 + 4) if w0 else 0
    print('=' * 110)
    print('loadsave game%d.sav -> %s' % (slot, p.cmd('loadsave game%d.sav' % slot)))
    ok = False
    while time.time() - t < 120:
        w1 = world(m)
        if mode(m) == 1 and w1 and humans(m) and reqstate(m) == 0 and (not w0 or w1 != w0 or u32(m, w1 + 4) != lv0):
            ok = True
            break
        time.sleep(1.0)
    print('slot %d world up: %s after %.1f s' % (slot, ok, time.time() - t))
    if not ok:
        time.sleep(3)
        continue
    time.sleep(10)
    time.sleep(3)
    w, mgr, ents = entities(m)
    print('level %s world %#x mgr %#x entities %d humans %d' % (tag(u32(m, w + 4)), w, mgr, len(ents), len(humans(m))))
    fam = 0
    for e in ents:
        rn = rtti_name(m, e)
        if any(k in rn for k in FAMILY) or u32(m, e + 0x10) in ITEM_TAGS:
            print('  ' + desc(m, e, rn))
            fam += 1
    print('  family/item entities: %d' % fam)
print('DONE')
