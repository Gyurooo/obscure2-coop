"""World entity count: the CToeManager list of both copies must be (nearly) the same.

world+0x1768 is the CToeManager; its entity list starts at manager+0x18 and every node is {entity,
next}. The host builds its entities from the level's inventory at world-build time (FINDINGS_11 s3:
43 entities); a guest that only had the host's world patched into a default one had 8 (the weapons the
mod created itself). This check prints every entity's tag (entity+0x10) and asserts the two counts are
close.

Usage: python -I check_entities.py <host pid> <guest pid>
"""
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from peek import Proc
h, g = int(sys.argv[1]), int(sys.argv[2])


def tag(v):
    if not v:
        return '-'
    b = struct.pack('<I', v)[::-1]
    return b.decode('latin1') if all(32 <= c < 127 for c in b) else '%08x' % v


def world(m):
    go = m.u32(m.va(0x6c3068))
    return m.u32(go + 0x378) if go else 0


def entities(m):
    w = world(m)
    mgr = m.u32(w + 0x1768) if w else 0
    head = m.u32(mgr + 0x18) if mgr else 0
    out, node, seen = [], head, set()
    while node and node not in seen and len(out) < 500:
        seen.add(node)
        ent = m.u32(node)
        nxt = m.u32(node + 4)
        if not ent or ent < 0x10000:
            break
        vt = m.u32(ent)
        tagv = m.u32(ent + 0x10)
        out.append((ent, vt, tagv, tag(tagv)))
        node = nxt
    return out


mh, mg = Proc(h), Proc(g)
eh, eg = entities(mh), entities(mg)
for name, es in (('host', eh), ('guest', eg)):
    print('%s: %d world entities' % (name, len(es)))
    print('  ' + ' '.join('%s@%x' % (t, e) for e, vt, tv, t in es))
th = sorted(t for _, _, _, t in eh)
tg = sorted(t for _, _, _, t in eg)
if th != tg:
    print('only host : %r' % [t for t in th if t not in tg])
    print('only guest: %r' % [t for t in tg if t not in th])
print('entity count: host %d guest %d' % (len(eh), len(eg)))
assert eh and eg, 'no world entity list on one copy'
assert abs(len(eh) - len(eg)) <= 3, 'world entity counts differ too much: host %d guest %d' % (len(eh), len(eg))
print('entities OK (host %d, guest %d)' % (len(eh), len(eg)))
