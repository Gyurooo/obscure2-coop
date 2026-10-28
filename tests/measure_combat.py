"""TASK 21 measurement: put BOTH copies into a level with live enemies through the host's own level
change (the guest follows, TASK 20), print every enemy's class/position/state(+0x2dc)/life(+0x320)/
last attacker(+0x750)/AI(+0x30c->+0x98) on both copies, then find the attack button and let the HOST's
player 1 attack one enemy and the GUEST's player 2 attack another, sampling both copies while it runs.

Read-only apart from the mod's own safe `tp`, the pad presses and the host's level change.

Usage: python -I measure_combat.py <host pid> <guest pid> [J001|J000] [--list] [--no-fight]
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe, press
from peek import Proc

GAME = 0x6c3068


def tag(v):
    return ''.join(chr((v >> s) & 0xff) if 32 <= ((v >> s) & 0xff) < 127 else '.'
                   for s in (24, 16, 8, 0))


def f32(m, addr):
    b = m.read(addr, 4)
    return struct.unpack('<f', b)[0] if b else 0.0


def u32(m, addr):
    try:
        return m.u32(addr) or 0
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


def rtti(m, obj):
    vt = u32(m, obj)
    if not vt:
        return ''
    col = u32(m, vt - 4)
    td = u32(m, col + 0xc) if col else 0
    b = m.read(td + 8, 96) if td else b''
    return ((b or b'').split(b'\0')[0].decode('latin1', 'replace')).replace('.?AV', '').replace('@@', '')


def manager_array(m, off):
    w = world(m)
    mg = u32(m, w + off) if w else 0
    if not mg:
        return []
    n, arr = u32(m, mg + 4), u32(m, mg + 0xc)
    out = []
    for i in range(min(n, 64)):
        a = u32(m, arr + 4 * i)
        if a:
            out.append(a)
    return out


def npcs(m):
    return manager_array(m, 0x1760)


def humans(m):
    return manager_array(m, 0x175c)


def human_tag(m, h):
    return tag(u32(m, h + 0x14))


def player(m, pl):
    """The player's own character: match the manager order to the player's slot only by tag would be
    wrong (the order can differ), so the mod's own rule is not available here; the manager order was
    player order in every earlier test. Kept."""
    hs = humans(m)
    return hs[pl] if pl < len(hs) else 0


def pos_char(m, o):
    return (f32(m, o + 0x23c), f32(m, o + 0x240), f32(m, o + 0x244))


def npc_rec(m, a):
    ctl = u32(m, a + 0x30c)
    la = u32(m, a + 0x750)
    return dict(addr=a, cls=rtti(m, a), tag=tag(u32(m, a + 0x14)), pos=pos_char(m, a),
                life=f32(m, a + 0x320), maxlife=f32(m, a + 0x31c), state=u32(m, a + 0x2dc),
                la=la, la_tag=tag(u32(m, la + 0x14)) if la else '.', ctl=ctl,
                ai=u32(m, ctl + 0x98) if ctl else 0)


def dist(a, b):
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5


def weapons(m, pl):
    h = player(m, pl)
    if not h:
        return 'none'
    slots = []
    for s in range(4):
        wp = u32(m, h + 0x704 + 4 * s)
        slots.append(tag(u32(m, wp + 0x10)) if wp else '----')
    return '%s slots %s cur %s' % (human_tag(m, h), ' '.join(slots), u32(m, h + 0x714))


def snapshot(m, name):
    print('  %s: level %s mode %d humans %d | world %#x'
          % (name, tag(level(m)), mode(m), len(humans(m)), world(m)))
    for pl in (0, 1):
        h = player(m, pl)
        if h:
            print('    player %d %s pos (%.1f, %.1f, %.1f) life %.1f state %#x  [%s]'
                  % (pl + 1, human_tag(m, h), *pos_char(m, h), f32(m, h + 0x320), u32(m, h + 0x2dc),
                     weapons(m, pl)))
    recs = [npc_rec(m, a) for a in npcs(m)]
    for r in recs:
        print('    npc %-22s %s @%#x pos (%.1f, %.1f, %.1f) life %6.1f/%-6.1f state %#8x alive %d'
              ' la %s ctl %#x ai %s'
              % (r['cls'], r['tag'], r['addr'], r['pos'][0], r['pos'][1], r['pos'][2], r['life'],
                 r['maxlife'], r['state'], 1 if r['life'] > 0 else 0, r['la_tag'], r['ctl'],
                 r['ai'] if r['ai'] else '-'))
    return recs


def nearest_npc(m, rec):
    """The same enemy on another copy: same class and nearest position (addresses differ per copy)."""
    best, bd = None, 1e30
    for a in npcs(m):
        r = npc_rec(m, a)
        if r['cls'] != rec['cls']:
            continue
        d = dist(r['pos'], rec['pos'])
        if d < bd:
            bd, best = d, r
    return best


def fail(msg):
    print(msg)
    sys.exit(1)


def anim_runs(m, pl, seconds, pipe, btn=None):
    """Sample one human's state +0x2dc every 50 ms while pressing `btn` once, return the run string."""
    outs = []
    if btn:
        pipe.cmd('pad 0 %x' % {'X': 0x4000, 'A': 0x1000, 'B': 0x2000, 'Y': 0x8000,
                               'RB': 0x200, 'LB': 0x100, 'RT': 0x80}[btn])
    t0 = time.time()
    while time.time() - t0 < seconds:
        hh = player(m, pl)
        outs.append(u32(m, hh + 0x2dc))
        time.sleep(0.05)
    if btn:
        pipe.cmd('pad 0 0')
    r = []
    for v in outs:
        if r and r[-1][0] == v:
            r[-1][1] += 1
        else:
            r.append([v, 1])
    return ' '.join('%#x x%d' % (v, n) for v, n in r)


def main():
    if len(sys.argv) < 3:
        fail(__doc__)
    h, g = int(sys.argv[1]), int(sys.argv[2])
    lvl = 'J001'
    for a in sys.argv[3:]:
        if a in ('J001', 'J000'):
            lvl = a
    just_list = '--list' in sys.argv
    no_fight = '--no-fight' in sys.argv
    entry = {'J001': 317, 'J000': 314}[lvl]
    host, guest = Pipe(h), Pipe(g)
    mh, mg = Proc(h), Proc(g)

    print('before: host %s mode %d | guest %s mode %d'
          % (tag(level(mh)), mode(mh), tag(level(mg)), mode(mg)))
    print('host level %s %d 1 -> %s' % (lvl, entry, host.cmd('level %s %d 1' % (lvl, entry))))
    t0 = time.time()
    while time.time() - t0 < 120:
        if tag(level(mh)) == lvl and tag(level(mg)) == lvl and mode(mh) == 1 and mode(mg) == 1:
            break
        time.sleep(1.0)
    print('after %.1f s: host %s mode %d | guest %s mode %d'
          % (time.time() - t0, tag(level(mh)), mode(mh), tag(level(mg)), mode(mg)))
    time.sleep(8.0)

    print('\n== both copies after the level change')
    rh = snapshot(mh, 'host')
    rg = snapshot(mg, 'guest')
    print('\nmatch by class + nearest position: host %d guest %d enemies' % (len(rh), len(rg)))
    for a in rh:
        b = nearest_npc(mg, a)
        if b:
            print('  %-22s %s  host pos (%.1f, %.1f, %.1f) life %6.1f state %#8x | guest pos (%.1f, %.1f, %.1f)'
                  ' life %6.1f state %#8x  dpos %.1f dlife %.1f'
                  % (a['cls'], a['tag'], *a['pos'], a['life'], a['state'], *b['pos'], b['life'], b['state'],
                     dist(a['pos'], b['pos']), a['life'] - b['life']))

    # Does the pad reach the game at all? 1 s of LEFT on the host's player 1.
    p0 = pos_char(mh, player(mh, 0))
    press(host, 0, 'LEFT', 1.0)
    time.sleep(0.3)
    p1 = pos_char(mh, player(mh, 0))
    print('\npad probe: player 1 moved %.1f units on LEFT (host)' % dist(p0, p1))
    print('weapons host: %s | %s' % (weapons(mh, 0), weapons(mh, 1)))
    print('weapons guest: %s | %s' % (weapons(mg, 0), weapons(mg, 1)))

    live_h = [r for r in rh if r['life'] > 0 and r['cls'].startswith('CCharacter')]
    if len(live_h) < 2:
        fail('fewer than two live enemies on the host copy -> cannot run the two-enemy test')
    # The two strongest enemies (CCharacterNPC 80 HP), else the two farthest apart.
    strong = sorted(live_h, key=lambda r: -r['maxlife'])
    if len(strong) >= 2:
        enemy_a, enemy_b = strong[0], strong[1]
    else:
        enemy_a, enemy_b = live_h[0], live_h[1]
    print('\n== enemy A: %s %s at (%.1f, %.1f, %.1f) life %.1f | enemy B: %s %s at (%.1f, %.1f, %.1f) life %.1f'
          % (enemy_a['cls'], enemy_a['tag'], *enemy_a['pos'], enemy_a['life'],
             enemy_b['cls'], enemy_b['tag'], *enemy_b['pos'], enemy_b['life']))
    if just_list or no_fight:
        return 0

    def place(pipe, m, pl, target, who):
        hp = player(m, pl)
        if not hp or not target:
            print('   %s: no character for player %d' % (who, pl + 1))
            return None
        tp = pos_char(m, hp)
        dx, dy = target[0] - tp[0], target[1] - tp[1]
        d = (dx * dx + dy * dy) ** 0.5 or 1.0
        x, y = target[0] - dx / d * 28.0, target[1] - dy / d * 28.0
        fx, fy = target[0] - x, target[1] - y
        r = pipe.cmd('tp %d %.3f %.3f %.3f %.3f %.3f' % (pl, x, y, target[2], fx, fy))
        print('   tp %s player %d near (%.1f, %.1f, %.1f): %s' % (who, pl + 1, x, y, target[2], r))
        return r

    def enemy_now(rec):
        for a in npcs(mh):
            if a == rec['addr']:
                return npc_rec(mh, a)
        return rec

    def sample(tagline):
        ha, ga = enemy_now(enemy_a), nearest_npc(mg, enemy_a)
        hb, gb = enemy_now(enemy_b), nearest_npc(mg, enemy_b)
        print('   %-12s A h life %6.1f st %#7x la %-4s ai %s | A g life %6.1f st %#7x ||'
              ' B h life %6.1f st %#7x | B g life %6.1f st %#7x || p1 h %#x g %#x | p2 h %#x g %#x'
              % (tagline,
                 ha['life'], ha['state'], ha['la_tag'], ha['ai'], ga['life'] if ga else -1, ga['state'] if ga else 0,
                 hb['life'], hb['state'], gb['life'] if gb else -1, gb['state'] if gb else 0,
                 u32(mh, player(mh, 0) + 0x2dc), u32(mg, player(mg, 0) + 0x2dc),
                 u32(mh, player(mh, 1) + 0x2dc), u32(mg, player(mg, 1) + 0x2dc)))

    # Which button swings? Stand next to enemy A and try each one, watching the player's state and A's life.
    print('\n== button probe next to enemy A')
    place(host, mh, 0, enemy_a['pos'], 'host')
    for btn in ('X', 'A', 'B', 'Y', 'RB', 'LB', 'RT'):
        before = enemy_now(enemy_a)
        runs = anim_runs(mh, 0, 1.2, host, btn)
        after = enemy_now(enemy_a)
        print('   %-3s player 1 state: %-40s A life %.1f -> %.1f  la %s' % (
            btn, runs, before['life'], after['life'], after['la_tag']))

    print('\n== phase 1: HOST player 1 attacks enemy A')
    place(host, mh, 0, enemy_now(enemy_a)['pos'], 'host')
    sample('before')
    for i in range(12):
        press(host, 0, 'X', 0.35)
        time.sleep(0.35)
        sample('after X %d' % (i + 1))
        if i == 5:
            place(host, mh, 0, enemy_now(enemy_a)['pos'], 'host')
        if enemy_now(enemy_a)['life'] <= 0:
            print('   enemy A is dead on the host')
            break

    bpos = enemy_now(enemy_b)['pos']
    print('\n== phase 2: GUEST player 2 attacks enemy B')
    place(host, mh, 1, bpos, 'peer')
    place(guest, mg, 1, bpos, 'guest')
    sample('before')
    for i in range(12):
        press(guest, 0, 'X', 0.35)
        time.sleep(0.35)
        sample('after X %d' % (i + 1))
        if i == 5:
            place(host, mh, 1, enemy_now(enemy_b)['pos'], 'peer')
            place(guest, mg, 1, enemy_now(enemy_b)['pos'], 'guest')
        if enemy_now(enemy_b)['life'] <= 0:
            print('   enemy B is dead on the host')
            break

    print('\n== final')
    snapshot(mh, 'host')
    snapshot(mg, 'guest')
    print('host sync: %s' % host.cmd('sync'))
    print('guest sync: %s' % guest.cmd('sync'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
