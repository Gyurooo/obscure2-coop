"""A host character life change is mirrored to the guest."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import time, struct
from bot import Pipe
from peek import Proc
h, g = int(sys.argv[1]), int(sys.argv[2])
p, mh, mg = Pipe(h), Proc(h), Proc(g)
def life(m):
    go = m.u32(m.va(0x6c3068)); w = m.u32(go+0x378); mgr = m.u32(w+0x175c); arr = m.u32(mgr+0xc)
    f = lambda a: struct.unpack('<f', struct.pack('<I', a))[0]
    return {struct.pack('<I', m.u32(m.u32(arr+4*i)+0x14)).decode('latin1')[::-1]: f(m.u32(m.u32(arr+4*i)+0x320)) for i in range(m.u32(mgr+4))}
print('health: before host', life(mh), 'guest', life(mg))
p.cmd('life 0 0')
for _ in range(8):
    time.sleep(0.5)
    if life(mg).get('BOY1', 1) == 0: break
print('health: after host', life(mh), 'guest', life(mg))
assert life(mg).get('BOY1') == 0, 'guest life did not mirror'
print('health OK')
