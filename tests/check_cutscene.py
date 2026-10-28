"""TASK 30: a cutscene runs on both copies, a skip on ONE of them ends it on BOTH.

The pair must be in a scripted event when this starts (tests/run_cutscene_pair.sh puts it there with
tests/start_newgame.py: the B101 new-game intro, world+0x11c = 6 on both copies, FINDINGS_30 §5).

The check reads the mod's own `scene` pipe command on both copies (`scene local state ... | peer ... |
sent ... rcv ... skips ... left ...`), which reports world+0x11c / world+0x12c as the mod sees them:

 1. both copies are in the same scripted event (state 6, same level, same scene id);
 2. SKIP_BY presses the game's own skip (ESCAPE) on that copy only;
 3. that copy leaves the event, and the OTHER copy leaves it too without any input of its own - the mod
    forward the skip and applies it through the game's own input path (before TASK 30 the other copy
    stayed in the intro for 18+ s, FINDINGS_30 §5);
 4. both copies end in the same state: normal play (world+0x11c = 1), same level, same party and the
    same player positions.

Usage: python -I check_cutscene.py <host pid> <guest pid> [--skip-by host|guest]
"""
import os
import re
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot
from peek import Proc

GAME = 0x6c3068
SKIP_WINDOW = float(os.environ.get('OBSCOOP_SKIP_WINDOW', '8'))


def parse_scene(text):
    """'scene local state 6 scene 0 id 1_00 level B101 cine 1 | peer ... | sent 4 rcv 3 skips 0 ...'"""
    d = {}
    m = re.match(r'scene local state (\d+) scene (\d+) id (\S+) level (\S+) cine (\d+) \| peer (.*?) state (\d+) '
                 r'scene (\d+) id (\S+) level (\S+) cine (\d+) \| sent (\d+) rcv (\d+) skips (\d+) left (\d+) '
                 r'stuck (\d+) missed (\d+) energy (\d+)', text)
    if not m:
        raise AssertionError('unexpected scene reply: %r' % text)
    g = m.groups()
    d['state'], d['scene'], d['id'], d['level'], d['cine'] = int(g[0]), int(g[1]), g[2], g[3], int(g[4])
    d['peer_seen'] = g[5].strip() != '(none)'
    d['peer_state'], d['peer_scene'], d['peer_id'], d['peer_level'], d['peer_cine'] = \
        int(g[6]), int(g[7]), g[8], g[9], int(g[10])
    d['sent'], d['rcv'], d['skips'], d['left'], d['stuck'], d['missed'], d['energy'] = [int(x) for x in g[11:18]]
    return d


def state(m):
    go = m.u32(m.va(GAME))
    w = m.u32(go + 0x378) if go else 0
    if not w:
        return dict(world=0)
    hm = m.u32(w + 0x175c)
    n = m.u32(hm + 4) if hm else 0
    arr = m.u32(hm + 0xc) if hm else 0
    hs = []
    for i in range(min(n or 0, 4)):
        p = m.u32(arr + 4 * i) if arr else 0
        if not p:
            continue
        tag = struct.pack('<I', m.u32(p + 0x14)).decode('latin1')[::-1]
        pos = tuple(round(struct.unpack('<f', m.read(p + 0x23c + 4 * k, 4))[0], 1) for k in range(3))
        hs.append((tag, pos))
    return dict(world=w, level=struct.pack('<I', m.u32(w + 4)).decode('latin1')[::-1], humans=sorted(hs))


hp, gp = int(sys.argv[1]), int(sys.argv[2])
skip_by = 'host'
if '--skip-by' in sys.argv:
    skip_by = sys.argv[sys.argv.index('--skip-by') + 1]
H, G = Proc(hp), Proc(gp)
hp_, gp_ = bot.Pipe(hp), bot.Pipe(gp)
P = {'host': (H, hp_), 'guest': (G, gp_)}
other = 'guest' if skip_by == 'host' else 'host'
RC = 0


def fail(msg):
    global RC
    RC = 1
    print('FAIL: ' + msg)


def scene_of(who):
    return parse_scene(P[who][1].cmd('scene'))


def wait_leave(who, limit):
    """Seconds until this copy's own world leaves the scripted event, or None."""
    t0 = time.time()
    while time.time() - t0 < limit:
        s = scene_of(who)
        if not s['cine']:
            return time.time() - t0, s
        time.sleep(0.2)
    return None, scene_of(who)


print('== 1. both copies in the same scripted event')
t0 = time.time()
hs = gs = None
while time.time() - t0 < 30:
    hs, gs = scene_of('host'), scene_of('guest')
    if hs['cine'] and gs['cine']:
        break
    time.sleep(0.5)
print('host : %s' % P['host'][1].cmd('scene'))
print('guest: %s' % P['guest'][1].cmd('scene'))
if not hs['cine'] or not gs['cine']:
    fail('the pair is not in a scripted event on both copies (host cine %d, guest cine %d); run '
         'tests/run_cutscene_pair.sh, which starts the new-game intro' % (hs['cine'], gs['cine']))
    sys.exit(1)
if hs['level'] != gs['level']:
    fail('the two copies are in different levels (%s / %s)' % (hs['level'], gs['level']))
if hs['id'] != gs['id']:
    print('note: the scene ids differ (host %s, guest %s)' % (hs['id'], gs['id']))
print('both copies are in the scripted event: level %s, scene id %s, world state %d'
      % (hs['level'], hs['id'], hs['state']))

time.sleep(3)
print('== 2. skip on the %s only (ESCAPE, the game\'s own skip)' % skip_by)
t_skip = time.time()
bot.tap(P[skip_by][1], 'ESCAPE')

print('== 3. both copies leave the scripted event')
dt_self, s_self = wait_leave(skip_by, SKIP_WINDOW)
dt_other, s_other = wait_leave(other, SKIP_WINDOW)
print('  %-5s left the event after %.1f s (skips %d)' % (skip_by, dt_self or -1, s_self['skips']))
print('  %-5s left the event after %.1f s (skips %d, its own input: none)' % (other, dt_other or -1, s_other['skips']))
if dt_self is None:
    fail('the %s did not leave the scripted event after its own skip' % skip_by)
if dt_other is None:
    fail('the %s is STILL in the scripted event %.0f s after the %s skipped (no forwarding)'
         % (other, time.time() - t_skip, skip_by))
elif s_other['skips'] < 1:
    fail('the %s left, but its skip counter is 0: it was not the forwarded skip' % other)
else:
    print('  PASS: the skip on the %s ended the event on the %s (forwarded skip applied, skips %d)'
          % (skip_by, other, s_other['skips']))

print('== 4. both copies end in the same state')
time.sleep(2)
sh, sg = state(H), state(G)
hs2, gs2 = scene_of('host'), scene_of('guest')
print('host : %s level %s state %d scene %d humans %r' % (sh['level'], hs2['level'], hs2['state'], hs2['scene'], sh['humans']))
print('guest: %s level %s state %d scene %d humans %r' % (sg['level'], gs2['level'], gs2['state'], gs2['scene'], sg['humans']))
if hs2['cine'] or gs2['cine']:
    fail('a copy is still in a scripted event (host %d, guest %d)' % (hs2['cine'], gs2['cine']))
if hs2['state'] != 1 or gs2['state'] != 1:
    fail('a copy is not back in normal play (host state %d, guest state %d)' % (hs2['state'], gs2['state']))
if hs2['level'] != gs2['level']:
    fail('the copies are in different levels (%s / %s)' % (hs2['level'], gs2['level']))
if sh['humans'] and sg['humans'] and [t for t, _ in sh['humans']] != [t for t, _ in sg['humans']]:
    fail('the parties differ after the cutscene: %r / %r' % (sh['humans'], sg['humans']))
for who, (m, p) in (('host', (H, hp_)), ('guest', (G, gp_))):
    print('%s sync: %s' % (who, p.cmd('sync')))
print('host scene : %s' % hp_.cmd('scene'))
print('guest scene: %s' % gp_.cmd('scene'))
print('cutscene sync: %s' % ('PASS' if RC == 0 else 'FAIL'))
sys.exit(RC)
