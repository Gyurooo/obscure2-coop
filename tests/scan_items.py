"""Read-only: list the level entities of a running Obscure2.exe (no writes, no debugger attach).

Walks the level's CToeManager (world+0x1768: count at +0x14, linked-list head at +0, next node at +4)
and prints, for every entity, the class tag at +0x10, the instance id at +4, the collected flag at
+0xa8 and the position at +0x6c/+0x70/+0x74. Item-class entities (the tags the CToeItem* constructors
write, ITEMS_FINDINGS.md section 1) are printed in detail with the gates the game's interaction check
uses (+0xc0, +0xac, +0xb0, radius +0xa0); all other classes are only counted. It also prints the level
tag, the game state, and player 1's position so the nearest live item can be seen.

Usage: python -I scan_items.py <pid>
"""
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from peek import Proc

GAME = 0x6c3068
ITEMS = {
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


def world(m):
    g0 = m.u32(m.va(GAME))
    return g0, (m.u32(g0 + 0x378) if g0 else 0)


def player_human(m, pl):
    w = world(m)[1]
    ctl = m.u32(w + 0x1748) if w else 0
    return m.u32(ctl + 4 + 0x764 * pl) if ctl else 0


pid = int(sys.argv[1])
m = Proc(pid)
g, w = world(m)
print('pid %d game @%x world @%x mode %s level %s' % (
    pid, g or 0, w or 0, m.u32(g + 0x310) if g else None, tag(m.u32(w + 4)) if w else '----'))
if not w:
    raise SystemExit('no world')
mgr = m.u32(w + 0x1768)
print('CToeManager @%x count(+0x14) %s' % (mgr or 0, m.u32(mgr + 0x14) if mgr else None))
h0 = player_human(m, 0)
if h0:
    print('player 1 @%x pos (%.2f, %.2f, %.2f)' % (h0, f32(m, h0 + 0x23c), f32(m, h0 + 0x240), f32(m, h0 + 0x244)))
if not mgr:
    raise SystemExit('no CToeManager')

ents = []
node = m.u32(mgr + 8)   # CToeManager's entity list object is at manager+8: head +0, next +4, count +0x14
seen = set()
while node and node not in seen and len(ents) < 4000:
    seen.add(node)
    ent = m.u32(node)
    if ent:
        ents.append(ent)
    node = m.u32(node + 4)

classes = {}
live_items = []
for ent in ents:
    cls = m.u32(ent + 0x10)
    idv = m.u32(ent + 4)
    coll = m.u32(ent + 0xa8)
    pos = (f32(m, ent + 0x6c), f32(m, ent + 0x70), f32(m, ent + 0x74))
    classes[tag(cls)] = classes.get(tag(cls), 0) + 1
    if cls in ITEMS:
        line = ('  class %s id %s collected %s p20=%s p34=%s pos (%.3f, %.3f, %.3f) @%x  gate c0=%s ac=%s b0=%s r=%.1f' % (
            tag(cls), tag(idv), coll, m.u32(ent + 0x20), m.u32(ent + 0x34), pos[0], pos[1], pos[2], ent,
            m.u32(ent + 0xc0), m.u32(ent + 0xac), m.u32(ent + 0xb0), f32(m, ent + 0xa0)))
        print(line)
        if not coll and m.u32(ent + 0x20) != 0:
            live_items.append((ent, cls, idv, pos))
    else:
        print('  [other] class %s id %s collected %s pos (%.2f, %.2f, %.2f) @%x' % (
            tag(cls), tag(idv), coll, pos[0], pos[1], pos[2], ent))

print('walked %d entities; class counts: %s' % (len(ents), classes))
print('LIVE ITEMS: %d' % len(live_items))
for ent, cls, idv, pos in live_items:
    d = None
    if h0:
        dx, dy, dz = pos[0] - f32(m, h0 + 0x23c), pos[1] - f32(m, h0 + 0x240), pos[2] - f32(m, h0 + 0x244)
        d = (dx * dx + dy * dy + dz * dz) ** 0.5
    print('  LIVE %s %s @%x pos (%.3f, %.3f, %.3f) distance from player 1 %s' % (
        tag(cls), tag(idv), ent, pos[0], pos[1], pos[2], '%.1f' % d if d is not None else '?'))
