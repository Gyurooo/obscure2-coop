"""Both copies are in the same saved level with the same inventory count."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import struct
from bot import Pipe
from peek import Proc
h, g = int(sys.argv[1]), int(sys.argv[2])
mh, mg = Proc(h), Proc(g)
def level(m):
    go = m.u32(m.va(0x6c3068)); w = m.u32(go+0x378) if go else 0
    return struct.pack('<I', m.u32(w+4)).decode('latin1')[::-1] if w else '----'
def inv(m):
    go = m.u32(m.va(0x6c3068)); w = m.u32(go+0x378) if go else 0
    i = m.u32(w+0x1790) if w else 0
    return m.u32(i+4) if i else None
lh, lg, ih, ig = level(mh), level(mg), inv(mh), inv(mg)
print('save: host', lh, ih, 'guest', lg, ig)
assert lh == lg == 'I100', 'levels differ'
assert ih == ig == 44, 'inventory counts differ'
print('save OK')
