"""Start one copy into save 01: new 2P at the main menu, then pause -> Load a saved game -> slot 01 -> YES."""
import sys, os, time, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot, peek
pid = int(sys.argv[1]); p = bot.Pipe(pid); m = peek.Proc(pid)
def gobj():
    try: return m.u32(m.va(0x6c3068))
    except Exception: return 0
def level():
    g = gobj(); w = m.u32(g+0x378) if g else 0
    return struct.pack('<I', m.u32(w+4)).decode('latin1')[::-1] if w else '----'
t = time.time()
while time.time()-t < 60 and not gobj(): time.sleep(0.5)
time.sleep(15)
print('menu at', level())
bot.press(p, 0, 'A'); time.sleep(1.2); bot.press(p, 0, 'DOWN'); time.sleep(0.8); bot.press(p, 0, 'A')
time.sleep(6); bot.press(p, 0, 'A'); time.sleep(8)
bot.tap(p, 'ESCAPE'); time.sleep(1.5)
print('new game level', level())
bot.press(p, 0, 'DOWN'); time.sleep(0.4); bot.press(p, 0, 'DOWN'); time.sleep(0.4)
bot.press(p, 0, 'A'); time.sleep(1.5)   # Load a saved game
bot.press(p, 0, 'A'); time.sleep(1.0)   # slot 01
bot.press(p, 0, 'UP'); time.sleep(0.4); bot.press(p, 0, 'A'); time.sleep(2)
for i in range(15):
    time.sleep(1); l = level(); print('t', i+1, l)
    if l not in ('B101', '----'): break
