"""TASK 21: combat sync on two live copies — player attacks, enemy position/animation/life/death.

The pair is already in save 01 (I100) when this runs (tests/run_pair.sh did the menu load). The HOST
changes level to a combat level the game itself produced (the J002 door's own destination data:
`J001 317 1`, fallback `J000 314 1`); the guest follows (TASK 20). Then:

  * control probe: 1.2 s of each stick direction on the host's player 1 — a level that has not given
    control (story intro) is reported and the next level is tried;
  * per enemy on BOTH copies: class, position, life (+0x320), AI/death state (+0x2dc), last attacker
    (+0x750), AI state (controller +0x30c -> +0x98);
  * the attack button is found by standing next to enemy A (`tp`, facing it) and trying X, B, Y, A, LB,
    RB and the two analog triggers until the enemy's life drops;
  * phase 1: the HOST's player 1 attacks enemy A until it dies;
  * phase 2: the GUEST's player 2 attacks enemy B until it dies (both copies' player 2 teleported);
  * every press samples both copies: enemy life/state, the attacking player's animation state (+0x2dc).

Asserts on BOTH copies: the same enemies, life within 1.0 during the fight, both enemies dead at the
end, no enemy alive on one copy and dead on the other, player life equal, and attack animation samples
that match. Read-only apart from the safe `tp`, the pad presses and the host's level change.

Usage: python -I check_combat.py <host pid> <guest pid>
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe, shot
from peek import Proc

GAME = 0x6c3068
LEVELS = [('J001', 317), ('J000', 314)]   # both are door destinations recorded in TASK 20
BTN = {'A': 0x1000, 'B': 0x2000, 'X': 0x4000, 'Y': 0x8000, 'LB': 0x100, 'RB': 0x200,
       'UP': 0x1, 'DOWN': 0x2, 'LEFT': 0x4, 'RIGHT': 0x8}
TOL = 1.0


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
    g0 = u32(m, m.va(GAME))
    return u32(m, g0 + 0x378) if g0 else 0


def level(m):
    w = world(m)
    return u32(m, w + 4) if w else 0


def mode(m):
    g0 = u32(m, m.va(GAME))
    return u32(m, g0 + 0x310) if g0 else 0


def rtti(m, o):
    vt = u32(m, o)
    col = u32(m, vt - 4) if vt else 0
    td = u32(m, col + 0xc) if col else 0
    b = m.read(td + 8, 96) if td else b''
    return (b or b'').split(b'\0')[0].decode('latin1', 'replace').replace('.?AV', '').replace('@@', '')


def arr(m, off, cap=64):
    w = world(m)
    mg = u32(m, w + off) if w else 0
    n = u32(m, mg + 4) if mg else 0
    a = u32(m, mg + 0xc) if mg else 0
    out = []
    for i in range(min(n, cap)):
        p = u32(m, a + 4 * i) if a else 0
        if p:
            out.append(p)
    return out


def humans(m):
    return arr(m, 0x175c)


def npcs(m):
    return arr(m, 0x1760)


def pos_char(m, o):
    return (f32(m, o + 0x23c), f32(m, o + 0x240), f32(m, o + 0x244))


def player(m, pl):
    hs = humans(m)
    return hs[pl] if pl < len(hs) else 0


def rec(m, a):
    ctl, la = u32(m, a + 0x30c), u32(m, a + 0x750)
    return dict(addr=a, cls=rtti(m, a), tag=tag(u32(m, a + 0x14)), pos=pos_char(m, a),
                life=f32(m, a + 0x320), maxlife=f32(m, a + 0x31c), state=u32(m, a + 0x2dc),
                la=tag(u32(m, la + 0x14)) if la else '.', ai=u32(m, ctl + 0x98) if ctl else 0)


def enemies(m):
    return [rec(m, a) for a in npcs(m) if rtti(m, a).startswith('CCharacter')]


def match(m, r):
    """The same enemy on another copy: same class, nearest position."""
    best, bd = None, 1e30
    for o in enemies(m):
        if o['cls'] != r['cls']:
            continue
        d = dist(o['pos'], r['pos'])
        if d < bd:
            bd, best = d, o
    return best


def dist(a, b):
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5


def press_btn(pipe, btn, hold=0.5):
    if btn == 'RT':
        pipe.cmd('pad 0 0 0 0 0 0 0 255')
    elif btn == 'LT':
        pipe.cmd('pad 0 0 0 0 0 0 255 0')
    else:
        pipe.cmd('pad 0 %x' % BTN[btn])
    time.sleep(hold)
    pipe.cmd('pad 0 0')


def stick(pipe, btn, hold=1.2):
    press_btn(pipe, btn, hold)


def tp_near(pipe, m, pl, target, who, back=28.0):
    h = player(m, pl)
    if not h:
        return 'no character'
    p = pos_char(m, h)
    dx, dy = target[0] - p[0], target[1] - p[1]
    d = (dx * dx + dy * dy) ** 0.5 or 1.0
    x, y = target[0] - dx / d * back, target[1] - dy / d * back
    return pipe.cmd('tp %d %.3f %.3f %.3f %.3f %.3f' % (pl, x, y, target[2], target[0] - x, target[1] - y))


h, g = int(sys.argv[1]), int(sys.argv[2])
host, guest = Pipe(h), Pipe(g)
mh, mg = Proc(h), Proc(g)
problems = []


def problem(msg):
    problems.append(msg)
    print('  !!! %s' % msg)


def control_probe(m):
    """Best displacement over the four stick directions (one direction can be a wall)."""
    hh = player(m, 0)
    if not hh:
        return 0.0
    best = 0.0
    for d in ('LEFT', 'RIGHT', 'UP', 'DOWN'):
        a = pos_char(m, hh)
        stick(host, d, 1.2)
        time.sleep(0.2)
        b = pos_char(m, hh)
        best = max(best, dist(a, b))
    return best


def enemy_line(m):
    return ', '.join('%s%s life %.1f st %#x' % (r['cls'], r['tag'], r['life'], r['state'])
                     for r in enemies(m))


def track(ref, m=None):
    """The same enemy on copy m: nearest of the same class to the last known position. Updates the
    reference position, so a moving enemy stays tracked across the fight."""
    mm = m or mh
    best, bd = ref, 1e30
    for o in enemies(mm):
        if o['cls'] != ref['cls']:
            continue
        d = dist(o['pos'], ref['pos'])
        if d < bd:
            bd, best = d, o
    if best is not ref:
        ref['pos'] = best['pos']
    return best


def now_a(m=None):
    return track(enemy_a, m)


def now_b(m=None):
    return track(enemy_b, m)


def discover_attack(target):
    """Stand next to the enemy and try each button; the one that lowers its life is the attack."""
    print('   tp host player 1 next to it: %s' % tp_near(host, mh, 0, target['pos'], 'host'))
    for btn in ('X', 'B', 'Y', 'A', 'LB', 'RB', 'RT', 'LT'):
        before = track(target)['life']
        for _ in range(3):
            press_btn(host, btn, 0.5)
            time.sleep(0.3)
        after = track(target)
        print('   %-3s enemy life %.1f -> %.1f  last attacker %s  state %#x  player anim %#x'
              % (btn, before, after['life'], after['la'], after['state'],
                 u32(mh, player(mh, 0) + 0x2dc) if player(mh, 0) else 0))
        if after['life'] < before - 0.4:
            print('   *** the attack button is %s' % btn)
            return btn
    return None


def prepare(lvl, arrive):
    """Wait for the level both copies were sent to, pick the enemies and find the attack button."""
    global enemy_a, enemy_b, two_enemies
    arrive()
    print('arrived: host %s (mode %d) | guest %s (mode %d)'
          % (tag(level(mh)), mode(mh), tag(level(mg)), mode(mg)))
    time.sleep(8.0)
    print('enemies host:  %s' % enemy_line(mh))
    print('enemies guest: %s' % enemy_line(mg))
    snap = enemies(mh)
    for r in snap:
        o = match(mg, r)
        print('  %-22s %s host (%.1f, %.1f, %.1f) life %6.1f st %#8x | guest %s'
              % (r['cls'], r['tag'], *r['pos'], r['life'], r['state'],
                 ('(%.1f, %.1f, %.1f) life %6.1f st %#8x' % (*o['pos'], o['life'], o['state'])) if o else 'MISSING'))
    moved = control_probe(mh)
    print('control probe: player 1 best 1.2 s stick displacement %.1f units' % moved)
    live = [r for r in snap if r['life'] > 0 and r['maxlife'] > 0]
    if not live:
        print('   %s has no live enemy' % lvl)
        return None
    strong = sorted(live, key=lambda r: -r['maxlife'])
    enemy_a = strong[0]
    enemy_b = strong[1] if len(strong) > 1 else strong[0]
    two_enemies = len(strong) > 1
    if not two_enemies:
        print('   only one live enemy here; the guest-player-2 phase will be skipped')
    print('   enemy A %s %s at (%.1f, %.1f, %.1f) life %.1f | enemy B %s %s at (%.1f, %.1f, %.1f) life %.1f'
          % (enemy_a['cls'], enemy_a['tag'], *enemy_a['pos'], enemy_a['life'],
             enemy_b['cls'], enemy_b['tag'], *enemy_b['pos'], enemy_b['life']))
    return discover_attack(enemy_a)


attack = None
lvl = None
two_enemies = True


def by_level(lvl, entry):
    def arrive():
        print('\n== host level %s %d 1 -> %s' % (lvl, entry, host.cmd('level %s %d 1' % (lvl, entry))))
        t0 = time.time()
        while time.time() - t0 < 90:
            if tag(level(mh)) == lvl and tag(level(mg)) == lvl and mode(mh) == 1 and mode(mg) == 1:
                break
            time.sleep(1.0)
        print('   waited %.1f s for the level' % (time.time() - t0))
    return prepare(lvl, arrive)


def by_save(save, lvl):
    def arrive():
        print('\n== host loadsave %s (expecting %s) -> %s' % (save, lvl, host.cmd('loadsave %s' % save)))
        t0 = time.time()
        while time.time() - t0 < 150:
            if tag(level(mh)) == lvl and tag(level(mg)) == lvl and mode(mh) == 1 and mode(mg) == 1:
                break
            time.sleep(1.0)
        print('   waited %.1f s for the load' % (time.time() - t0))
    return prepare(lvl, arrive)


for lvl_try, entry in LEVELS:
    attack = by_level(lvl_try, entry)
    if attack:
        lvl = lvl_try
        break
    print('   no enemy could be hurt in %s -> trying the next level' % lvl_try)
if attack is None:
    # TASK 18 measured the pads working in the save-loaded worlds (H000 among them), so the game's own
    # save 06 is a level where a real swing can be measured even though both door levels above keep the
    # player frozen. The guest follows a host load (REQ_LOAD_NAME / REQ_LEVEL).
    print('\n== fallback: host loads save 06 (H000, its enemy is live; the pads work in save-loaded worlds)')
    attack = by_save('game6.sav', 'H000')
    if attack:
        lvl = 'H000'
if attack is None:
    problem('no enemy could be hurt in any combat level; the attack button was not identified')
    print('\nRESULT: no enemy could be hurt in any combat level -> combat not proven')
    print('sync host: %s' % host.cmd('sync'))
    print('sync guest: %s' % guest.cmd('sync'))
    sys.exit(1)


# ---- the fight ----------------------------------------------------------------------------------
def sample(tagline, pl_h, pl_g):
    ra, ga = now_a(mh), match(mg, now_a(mh))
    rb, gb = now_b(mh), match(mg, now_b(mh))
    ah = u32(mh, player(mh, pl_h) + 0x2dc) if player(mh, pl_h) else 0
    ag = u32(mg, player(mg, pl_g) + 0x2dc) if player(mg, pl_g) else 0
    print('   %-10s A h %6.1f/%#7x  g %6.1f/%#7x | B h %6.1f/%#7x  g %6.1f/%#7x | attack anim p%d h %#x g %#x %s'
          % (tagline, ra['life'], ra['state'], ga['life'] if ga else -1, ga['state'] if ga else 0,
             rb['life'], rb['state'], gb['life'] if gb else -1, gb['state'] if gb else 0,
             pl_h + 1, ah, ag, 'SAME' if ah == ag else 'DIFF'))
    return (ra, ga, rb, gb, ah, ag)


def fight(name, pipe, pl_h, pl_g, target, m_target, which):
    print('\n== %s: player %d attacks %s' % (name, pl_h + 1, target['cls']))
    print('   tp: %s' % tp_near(pipe, m_target, pl_h, target['pos'], name))
    if pipe is not host:
        print('   tp peer: %s' % tp_near(host, mh, pl_g, target['pos'], 'peer'))
    samples = []
    anim_eq = anim_nz = 0
    for i in range(14):
        press_btn(pipe, attack, 0.55)
        time.sleep(0.35)
        s = sample('press %d' % (i + 1), pl_h, pl_g)
        samples.append(s)
        if s[4] == s[5]:
            anim_eq += 1
            if s[4] != 0:
                anim_nz += 1
        if (s[0]['life'] if pipe is host else s[2]['life']) <= 0:
            break
        if i == 6:   # enemy may have moved; walk up again
            t = now_a() if which == 'A' else now_b()
            print('   re-tp: %s' % tp_near(pipe, m_target, pl_h, t['pos'], name))
            if pipe is not host:
                print('   re-tp peer: %s' % tp_near(host, mh, pl_g, t['pos'], 'peer'))
    # assertions
    end_h = now_a() if which == 'A' else now_b()
    end_g = match(mg, end_h)
    if not end_g or end_g['life'] > 0:
        problem('%s: %s is not dead on the guest copy (life %.1f)'
                % (name, end_h['cls'], end_g['life'] if end_g else -1))
    if end_h['life'] > 0:
        problem('%s: %s is not dead on the host copy (life %.1f)' % (name, end_h['cls'], end_h['life']))
    if end_g and end_h['state'] != end_g['state']:
        problem('%s: death state differs host %#x guest %#x' % (name, end_h['state'], end_g['state']))
    worst = 0.0
    for s in samples:
        if s[1]:
            worst = max(worst, abs(s[0]['life'] - s[1]['life']))
        if s[3]:
            worst = max(worst, abs(s[2]['life'] - s[3]['life']))
    print('   %s: worst life difference between the copies %.2f (tolerance %.1f)' % (name, worst, TOL))
    if worst > TOL:
        problem('%s: life drifted apart between the copies by %.2f' % (name, worst))
    print('   %s: attack animation samples equal on both copies %d/%d (non-zero %d)'
          % (name, anim_eq, len(samples), anim_nz))
    if anim_eq < len(samples) * 0.8:
        problem('%s: attack animation samples differ between the copies (%d/%d equal)'
                % (name, anim_eq, len(samples)))
    return end_h


p1 = fight('phase 1 (host player 1)', host, 0, 0, now_a(), mh, 'A')
p2 = fight('phase 2 (guest player 2)', guest, 1, 1, now_b(), mg, 'B') if two_enemies else None
if p2 is None:
    print('\n== phase 2 skipped: this level has only one live enemy')

print('\n== final state on both copies')
print('enemies host:  %s' % enemy_line(mh))
print('enemies guest: %s' % enemy_line(mg))
for pl in (0, 1):
    lh = f32(mh, player(mh, pl) + 0x320) if player(mh, pl) else -1
    lg = f32(mg, player(mg, pl) + 0x320) if player(mg, pl) else -1
    print('player %d life host %.1f guest %.1f' % (pl + 1, lh, lg))
    if abs(lh - lg) > 0.01:
        problem('player %d life differs: host %.1f guest %.1f' % (pl + 1, lh, lg))
# no enemy alive on one copy and dead on the other
for r in enemies(mh):
    o = match(mg, r)
    if not o:
        problem('%s has no counterpart on the guest' % r['cls'])
    elif (r['life'] > 0) != (o['life'] > 0):
        problem('%s: alive host %s / guest %s (host life %.1f guest %.1f)'
                % (r['cls'], r['life'] > 0, o['life'] > 0, r['life'], o['life']))
print('sync host: %s' % host.cmd('sync'))
print('sync guest: %s' % guest.cmd('sync'))
try:
    print('shot host: %s' % (shot(h, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'combat_host.png')),))
except Exception as e:
    print('shot host failed: %s' % e)
try:
    print('shot guest: %s' % (shot(g, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'combat_guest.png')),))
except Exception as e:
    print('shot guest failed: %s' % e)

print('\nRESULT: %s' % ('combat OK' if not problems else 'combat FAILED'))
for p in problems:
    print('  - %s' % p)
sys.exit(0 if not problems else 1)
