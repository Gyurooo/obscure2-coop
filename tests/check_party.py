"""Both copies have the same party (character tags of the live humans) and the same inventory count."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import struct
from peek import Proc
h, g = int(sys.argv[1]), int(sys.argv[2])
mh, mg = Proc(h), Proc(g)
def world(m):
    go = m.u32(m.va(0x6c3068))
    return m.u32(go + 0x378) if go else 0
def party(m):
    w = world(m)
    mgr = m.u32(w + 0x175c) if w else 0
    arr = m.u32(mgr + 0xc) if mgr else 0
    if not arr:
        return []
    return sorted(struct.pack('<I', m.u32(m.u32(arr + 4 * i) + 0x14)).decode('latin1')[::-1] for i in range(m.u32(mgr + 4)))
def inv(m):
    w = world(m)
    i = m.u32(w + 0x1790) if w else 0
    return m.u32(i + 4) if i else None
ph, pg, ih, ig = party(mh), party(mg), inv(mh), inv(mg)
print('party: host', ph, 'guest', pg, '| inventory: host', ih, 'guest', ig)
assert ph and ph == pg, 'parties differ'
assert ih == ig, 'inventory counts differ'
print('party OK')
