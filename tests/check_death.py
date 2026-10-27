"""After P1's death the host pad moves the alive partner."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import time, struct
from bot import Pipe
from peek import Proc
h, g = int(sys.argv[1]), int(sys.argv[2])
p, mh = Pipe(h), Proc(h)
def pos(m):
    go = m.u32(m.va(0x6c3068)); w = m.u32(go+0x378); mgr = m.u32(w+0x175c); arr = m.u32(mgr+0xc)
    f = lambda a: struct.unpack('<f', struct.pack('<I', a))[0]
    return {struct.pack('<I', m.u32(m.u32(arr+4*i)+0x14)).decode('latin1')[::-1]: (f(m.u32(m.u32(arr+4*i)+0x23c)), f(m.u32(m.u32(arr+4*i)+0x240))) for i in range(m.u32(mgr+4))}
p.cmd('life 0 0'); time.sleep(1)
p.cmd('pad 1 0 0 0 0 0 0 0')   # player 2's vpad must be on for the merged host pad
before = pos(mh)
p.cmd('pad 0 0 0 32000 0 0 0 0'); time.sleep(2); p.cmd('unpad 0'); time.sleep(0.5)
after = pos(mh)
d = lambda a, b: ((a[0]-b[0])**2 + (a[1]-b[1])**2) ** 0.5
print('death: BOY1 moved %.1f, GIR1 moved %.1f' % (d(before.get('BOY1',(0,0)), after.get('BOY1',(0,0))), d(before.get('GIR1',(0,0)), after.get('GIR1',(0,0)))))
assert d(before['GIR1'], after['GIR1']) > 10, 'alive partner did not move'
print('death OK')
