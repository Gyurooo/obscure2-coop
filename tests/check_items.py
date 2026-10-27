"""A host inventory change is mirrored to the guest."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import time
from bot import Pipe
from peek import Proc
h, g = int(sys.argv[1]), int(sys.argv[2])
p, mh, mg = Pipe(h), Proc(h), Proc(g)
def inv(m):
    go = m.u32(m.va(0x6c3068)); w = m.u32(go+0x378) if go else 0
    i = m.u32(w+0x1790) if w else 0
    return i, (m.u32(i+4) if i else None)
hi, hc = inv(mh); gi, gc = inv(mg)
print('items: before host', hc, 'guest', gc)
p.cmd('wr 0x%x 2d000000' % (hi+4))
for _ in range(6):
    time.sleep(0.5)
    if inv(mg)[1] == 45: break
print('items: after host', inv(mh)[1], 'guest', inv(mg)[1])
assert inv(mg)[1] == 45, 'guest did not mirror the inventory change'
p.cmd('wr 0x%x 2c000000' % (hi+4))
print('items OK')
