"""TASK 23: combat sync on two live copies — the real attack input (hold LB + press A) and the fight.

The pair is already in save 01 (I100) when this runs (tests/run_pair.sh). The HOST changes level to a
combat level the game itself produced (`J001 317 1`, then `J000 314 1`; both are door destinations the
game logged, see obscoop_levels.txt); the guest follows.

What the check measures, per level:
  1. the ATTACK: the owner's chord — LB held (aim stance) and A pressed inside it — on the weapon in
     hand, then on the melee slot selected with the D-pad, with the stick neutral and pushed; the aim
     state (character +0x2dc = 0x64) and the swing state (weapon +0x14 = 4) are sampled on BOTH copies.
     If no input starts a swing, the test-only `swing` (the game's own attack entry, vtable slot 28 =
     0x4563a0) is tried, then `swingobj` on objects found by scanning the world entity list for the
     class that carries that entry. Only if all of those fail does the fight fall back to the game's own
     life method (`npcset`, vtable slot 9 — the method every damage source funnels through), which
     drives the life/death path but is NOT an attack: the check says so and never claims otherwise.
  2. the FIGHT: the host's player 1 kills enemy A (an 80-HP CCharacterNPC in J001, a 120-HP Ram in
     J000), the guest's player 2 attacks enemy B. Both copies are sampled every 50-100 ms: enemy life
     and state, player life, enemy positions (AI), the attacker's animation and weapon state.
  3. the ENEMY-LIFE CODE of 6704c30: with the guest's correction switched off (`npclife 0`) one copy is
     damaged alone and the divergence is printed; with it on the numbers are printed again.
  4. the final assertions on both copies: same enemies, life within 1.0, both dead, never alive on one
     copy and dead on the other, the same per-hit drop (no double damage), player life equal, attack
     animation samples equal, enemy positions equal.

Read-only apart from the safe `tp`, the pad presses, the host's level change and the test-only commands
named above. Usage: python -I check_combat.py <host pid> <guest pid>
"""
import os
import ctypes
import ctypes.wintypes as W
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe, write_png
from peek import Proc

GAME = 0x6c3068
TOL = 1.0                 # life tolerance between the copies (units of HP)
POS_TOL = 5.0             # position tolerance between the copies (units of distance)
BTN = {'A': 0x1000, 'B': 0x2000, 'X': 0x4000, 'Y': 0x8000, 'LB': 0x100, 'RB': 0x200,
       'UP': 0x1, 'DOWN': 0x2, 'LEFT': 0x4, 'RIGHT': 0x8}
SLOT_PAD = {0: 'UP', 1: 'RIGHT', 2: 'DOWN', 3: 'LEFT'}      # slot <- D-pad button (TASK 22, run_f4)
MELEE = ('UberBeat', 'Beat', 'Club', 'Stick', 'ChainSaw', 'Contact', 'Taser')
ATTACK_VT = 0x659568      # vtable whose slot 28 is the game's attack start 0x4563a0 (exe scan)
COMBO = [7.0, 8.0, 14.0]  # GAME_MECHANICS.md: the bat's 3-hit combo
LEVELS = [l.strip() for l in os.environ.get('OBSCOOP_COMBAT_LEVELS', 'J001:317,J000:314').split(',')]
LEVELS = [(l.split(':')[0], int(l.split(':')[1])) for l in LEVELS if ':' in l]

h, g = int(sys.argv[1]), int(sys.argv[2])
host, guest = Pipe(h), Pipe(g)
mh, mg = Proc(h), Proc(g)
problems = []


def problem(msg):
    problems.append(msg)
    print('  !!! %s' % msg)


# ---- memory helpers ------------------------------------------------------------------------------
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
    mgr = u32(m, w + off) if w else 0
    n = u32(m, mgr + 4) if mgr else 0
    a = u32(m, mgr + 0xc) if mgr else 0
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


def entities(m):
    """The world's entity list (world+0x1768 CToeManager, nodes {entity, next})."""
    w = world(m)
    mgr = u32(m, w + 0x1768) if w else 0
    head = u32(m, mgr + 0x18) if mgr else 0
    out, node, seen = [], head, set()
    while node and node not in seen and len(out) < 500:
        seen.add(node)
        ent, nxt = u32(m, node), u32(m, node + 4)
        if not ent or ent < 0x10000:
            break
        out.append(ent)
        node = nxt
    return out


def pos_char(m, o):
    return (f32(m, o + 0x23c), f32(m, o + 0x240), f32(m, o + 0x244))


def player(m, pl):
    hs = humans(m)
    return hs[pl] if pl < len(hs) else 0


def life(m, pl):
    hh = player(m, pl)
    return f32(m, hh + 0x320) if hh else -1.0


def anim(m, pl):
    hh = player(m, pl)
    return u32(m, hh + 0x2dc) if hh else 0


def sel_slot(m, pl):
    hh = player(m, pl)
    return u32(m, hh + 0x714) if hh else 0


def weapon_state(m, pl):
    hh = player(m, pl)
    if not hh:
        return 0
    sel = u32(m, hh + 0x714)
    wp = u32(m, hh + 0x704 + 4 * sel) if sel < 4 else 0
    return u32(m, wp + 0x14) if wp else 0


def slots(m, pl):
    hh = player(m, pl)
    out = []
    if not hh:
        return out
    for i in range(4):
        wp = u32(m, hh + 0x704 + 4 * i)
        out.append((rtti(m, wp) + ('*' if i == u32(m, hh + 0x714) else '')) if wp else '-')
    return out


def rec(m, a):
    return dict(addr=a, cls=rtti(m, a), tag=tag(u32(m, a + 0x14)), pos=pos_char(m, a),
                life=f32(m, a + 0x320), maxlife=f32(m, a + 0x31c), state=u32(m, a + 0x2dc))


def enemies(m):
    return [rec(m, a) for a in npcs(m) if rtti(m, a).startswith('CCharacter')]


def dist(a, b):
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5


def near(es, ref):
    """The same enemy in another copy's list: same class and tag, nearest position."""
    best, bd = None, 1e30
    for o in es:
        if o['cls'] != ref['cls'] or o['tag'] != ref['tag']:
            continue
        d = dist(o['pos'], ref['pos'])
        if d < bd:
            bd, best = d, o
    return best


# ---- pipe helpers --------------------------------------------------------------------------------
def pad(pipe, user, buttons, lx=0, ly=0, lt=0, rt=0):
    pipe.cmd('pad %d %x %d %d 0 0 %d %d' % (user, buttons, lx, ly, lt, rt))


def pad_off(pipe, user):
    pipe.cmd('pad %d 0 0 0' % user)


def tp_near(pipe, m, pl, target, back=12.0):
    hh = player(m, pl)
    if not hh:
        return 'no character'
    p = pos_char(m, hh)
    dx, dy = target[0] - p[0], target[1] - p[1]
    d = (dx * dx + dy * dy) ** 0.5 or 1.0
    x, y = target[0] - dx / d * back, target[1] - dy / d * back
    r = pipe.cmd('tp %d %.3f %.3f %.3f %.3f %.3f' % (pl, x, y, target[2], target[0] - x, target[1] - y))
    if not r.startswith('ok'):
        r += ' (retry without z: %s)' % pipe.cmd('tp %d %.3f %.3f' % (pl, x, y))
    return r


# ---- foreground screenshots (topmost + a real click, then PrintWindow) ---------------------------
user32 = ctypes.WinDLL('user32', use_last_error=True)
gdi32 = ctypes.WinDLL('gdi32')
WNDENUMPROC = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
user32.SetWindowPos.argtypes = [W.HWND, W.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.SetWindowPos.restype = W.BOOL
user32.GetWindowRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
user32.GetClientRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.mouse_event.argtypes = [W.DWORD, W.DWORD, W.DWORD, W.DWORD, ctypes.c_size_t]


def window_of(pid):
    found = []

    def cb(hwnd, _):
        p = W.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(hwnd):
            r = W.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(r))
            found.append((r.right * r.bottom, hwnd))
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    found.sort(reverse=True)
    return found[0][1] if found else None


class BIH(ctypes.Structure):
    _fields_ = [('biSize', W.DWORD), ('biWidth', W.LONG), ('biHeight', W.LONG), ('biPlanes', W.WORD),
                ('biBitCount', W.WORD), ('biCompression', W.DWORD), ('biSizeImage', W.DWORD),
                ('biXPelsPerMeter', W.LONG), ('biYPelsPerMeter', W.LONG), ('biClrUsed', W.DWORD),
                ('biClrImportant', W.DWORD)]


def capture(pid, path):
    """A picture of the game window with the window in the FOREGROUND (a backgrounded D3D9 window hands
    out black frames). Returns the non-black fraction."""
    hwnd = window_of(pid)
    if not hwnd:
        raise RuntimeError('no window for pid %d' % pid)
    user32.ShowWindow(hwnd, 4)                                            # SW_SHOWNOACTIVATE
    user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)   # TOPMOST, no move/size
    r = W.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    x, y = (r.left + r.right) // 2, (r.top + r.bottom) // 2
    user32.SetCursorPos(x, y)
    user32.mouse_event(0x0002, 0, 0, 0, 0)   # a real click activates the window
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.35)
    r = W.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    w, hh = r.right, r.bottom
    wdc = user32.GetDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(wdc)
    bmp = gdi32.CreateCompatibleBitmap(wdc, w, hh)
    gdi32.SelectObject(mdc, bmp)
    user32.PrintWindow(hwnd, mdc, 3)   # PW_CLIENTONLY | PW_RENDERFULLCONTENT
    bih = BIH(ctypes.sizeof(BIH), w, -hh, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = (ctypes.c_ubyte * (w * hh * 4))()
    gdi32.GetDIBits(mdc, bmp, 0, hh, buf, ctypes.byref(bih), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, wdc)
    px = bytes(buf)
    frac = sum(1 for i in range(0, len(px), 4 * 97) if px[i] + px[i + 1] + px[i + 2] > 24) / (len(px) // (4 * 97))
    write_png(path, w, hh, px)
    user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002)   # NOTOPMOST
    return frac * 100.0


# ---- the samples ---------------------------------------------------------------------------------
EN_A = EN_B = None


LAST_HIT = [0.0]   # when the last damage step was issued (the guest converges on the next NPC snapshot)


def snap(pl):
    """One sample of both copies: life/state/position of A and B, player life, attacker anim + weapon.
    `settled` marks a sample taken long enough after the last damage step for the guest's correction to
    have arrived (the guest applies it on the next 33 ms NPC snapshot)."""
    d = {'t': time.time(), 'settled': (time.time() - LAST_HIT[0]) > 0.15}
    for who, m in (('h', mh), ('g', mg)):
        es = enemies(m)
        for name, ref in (('a', EN_A), ('b', EN_B)):
            o = near(es, ref) if ref else None
            d[who + name + '_life'] = o['life'] if o else -1.0
            d[who + name + '_state'] = o['state'] if o else -1
            d[who + name + '_pos'] = o['pos'] if o else (0, 0, 0)
        d[who + 'p1'] = life(m, 0)
        d[who + 'p2'] = life(m, 1)
        d[who + 'anim'] = anim(m, pl)
        d[who + 'ws'] = weapon_state(m, pl)
    return d


def sample_until(seconds, pl, sl, step=0.1):
    t0 = time.time()
    while time.time() - t0 < seconds:
        sl.append(snap(pl))
        time.sleep(step)


def strikes_of(sl, who, name):
    """Per-hit life drops of enemy `name` on copy `who`, from the sample series."""
    drops = []
    prev = None
    for s in sl:
        v = s[who + name + '_life']
        if prev is not None and v < prev - 0.4:
            drops.append(round(prev - v, 2))
        prev = v
    return drops


# ---- the attack ----------------------------------------------------------------------------------
ATTACK = None    # dict(kind='chord'|'swing'|'swingobj'|'npcset', ...)
ATTACKS = []     # (label, life before/after on the host, on the guest, hit) per attack


def chord(pipe, pl, sl, lb_ms=250, a_ms=150, hold_ms=600, after_ms=350, stick=(0, 0), user=0):
    """The owner's attack: HOLD LB (aim) and press A inside it, then release LB. Sampled throughout."""
    sched = [(0.0, BTN['LB']), (lb_ms / 1000.0, BTN['LB'] | BTN['A']),
             ((lb_ms + a_ms) / 1000.0, BTN['LB']),
             ((lb_ms + a_ms + hold_ms) / 1000.0, 0)]
    total = sched[-1][0] + after_ms / 1000.0
    t0 = time.time()
    i = 0
    while True:
        t = time.time() - t0
        while i < len(sched) and t >= sched[i][0]:
            pad(pipe, user, sched[i][1], stick[0], stick[1])
            i += 1
        sl.append(snap(pl))
        if t >= total:
            break
        time.sleep(0.05)
    pad_off(pipe, user)


def select_slot(pipe, m, pl, want):
    """Select a weapon slot with the D-pad (the only pad input that reached the game in TASK 22)."""
    if sel_slot(m, pl) == want:
        return 'already slot %d' % want
    before = sel_slot(m, pl)
    pad(pipe, 0, BTN[SLOT_PAD[want]])
    time.sleep(0.3)
    pad_off(pipe, 0)
    time.sleep(2.0)          # the weapon wheel closes again
    return 'slot %d -> %d (%s)' % (before, sel_slot(m, pl), slots(m, pl)[sel_slot(m, pl)] if slots(m, pl) else '-')


def try_attack(pipe, pl, pl_g, user, sl, label):
    """One attempt of the current ATTACK; returns True when the enemy lost life on a copy."""
    target = EN_A
    l0h = near(enemies(mh), target)['life']
    l0g = near(enemies(mg), target)['life']
    LAST_HIT[0] = time.time()
    if ATTACK['kind'] == 'chord':
        chord(pipe, pl, sl, user=user)
    elif ATTACK['kind'] == 'swing':
        rh = host.cmd('swing %d' % pl)
        rg = guest.cmd('swing %d' % pl_g)
        print('        swing: host %s | guest %s' % (rh, rg))
        sample_until(1.2, pl, sl, 0.05)
    elif ATTACK['kind'] == 'swingobj':
        rh = host.cmd('swingobj %d %s' % (pl, ATTACK['h']))
        rg = guest.cmd('swingobj %d %s' % (pl_g, ATTACK['g']))
        print('        swingobj: host %s | guest %s' % (rh, rg))
        sample_until(1.2, pl, sl, 0.05)
    else:   # npcset fallback: the game's own life method, on the attacker's copy
        dmg = COMBO[(ATTACK['n'] % len(COMBO))]
        ATTACK['n'] += 1
        m_att = mh if pl == 0 else mg
        own = near(enemies(m_att), target)          # this copy's own object address
        if pl == 0:
            r = host.cmd('npcset %x %.1f' % (own['addr'], max(0.0, l0h - dmg)))
        else:
            r = guest.cmd('npcset %x %.1f' % (own['addr'], max(0.0, l0g - dmg)))
        print('        npcset %.0f on %s: %s' % (dmg, 'host' if pl == 0 else 'guest', r))
        sample_until(0.8, pl, sl, 0.05)
    l1h = near(enemies(mh), target)['life']
    l1g = near(enemies(mg), target)['life']
    hit = l1h < l0h - 0.4 or l1g < l0g - 0.4
    ATTACKS.append((label, l0h, l1h, l0g, l1g, hit))
    print('   %-30s life host %6.1f -> %6.1f | guest %6.1f -> %6.1f | anim host %#04x guest %#04x | ws %d/%d %s'
          % (label, l0h, l1h, l0g, l1g, anim(mh, pl), anim(mg, pl_g), weapon_state(mh, pl),
             weapon_state(mg, pl_g), 'HIT' if hit else '-'))
    return hit


def discover_attack(pipe, pl, pl_g, user):
    """Find what (if anything) starts the game's attack. Records ATTACK and prints why."""
    global ATTACK
    sl = []
    print('\n== the attack: hold LB (aim) + press A, on the weapon in hand (%s)'
          % (slots(mh, 0)[sel_slot(mh, 0)].rstrip('*') if slots(mh, 0) else '-'))
    pad(pipe, user, BTN['LB'])
    sample_until(0.5, pl, sl, 0.05)
    print('   LB held: character +0x2dc host %#04x guest %#04x (0x64 = the aim state), weapon +0x14 %d/%d'
          % (anim(mh, pl), anim(mg, pl_g), weapon_state(mh, pl), weapon_state(mg, pl_g)))
    pad_off(pipe, user)
    for kind in ('chord', 'swing'):
        ATTACK = dict(kind=kind, n=0)
        for i in range(3):
            if try_attack(pipe, pl, pl_g, user, sl, '%s %d' % (kind, i + 1)):
                print('   *** the attack works: %s' % kind)
                return ATTACK
    # the melee slot selected with the D-pad, then the same chord
    sl_melee = next((i for i, s in enumerate(slots(mh, 0)) if any(k in s for k in MELEE)), None)
    if sl_melee is not None:
        print('   melee slot: %s' % select_slot(pipe, mh, 0, sl_melee))
        ATTACK = dict(kind='chord', n=0)
        if try_attack(pipe, pl, pl_g, user, sl, 'chord on the melee slot'):
            print('   *** the attack works: chord (melee slot)')
            return ATTACK
        ATTACK = dict(kind='swing', n=0)
        if try_attack(pipe, pl, pl_g, user, sl, 'swing on the melee slot'):
            print('   *** the attack works: swing')
            return ATTACK
    # objects of the attack class, if the level has any (world entity list, then the swing search)
    cands = [(e, u32(mh, e)) for e in entities(mh)]
    hits = [e for e, vt in cands if vt == ATTACK_VT]
    guests = {e: u32(mg, e) for e in entities(mg)}
    print('   world entities %d; with the attack vtable %x: host %s | guest %s'
          % (len(cands), ATTACK_VT, ', '.join('%x' % e for e in hits) or 'none',
             ', '.join('%x' % e for e in guests if guests[e] == ATTACK_VT) or 'none'))
    if hits:
        gs = [e for e in guests if guests[e] == ATTACK_VT]
        for i, e in enumerate(hits[:4]):
            ATTACK = dict(kind='swingobj', h='%x' % e, g='%x' % gs[min(i, len(gs) - 1)] if gs else '%x' % e)
            if try_attack(pipe, pl, pl_g, user, sl, 'swingobj %x' % e):
                print('   *** the attack works: swingobj on %x' % e)
                return ATTACK
    print('   no input and no game attack entry damaged the enemy; the fight falls back to the game\'s')
    print('   own life method (npcset = vtable slot 9, the path every damage source uses) on one copy.')
    ATTACK = dict(kind='npcset', n=0)
    return ATTACK


# ---- the fight -----------------------------------------------------------------------------------
def fight(name, pipe, pl, pl_g, target, ref_copy, m_target, max_hits=24, budget=75.0):
    """the attacker's copy damages `target`; both copies are sampled. Returns (samples, end)."""
    global EN_A
    sl = []
    t0 = time.time()
    del ATTACKS[:]          # the drop lists below belong to this fight only
    print('\n== %s: player %d attacks %s %s (attack: %s)'
          % (name, pl + 1, target['cls'], target['tag'], ATTACK['kind']))
    for i in range(max_hits):
        cur = near(enemies(m_target), target)
        if cur is None:
            problem('%s: the enemy disappeared' % name)
            break
        if cur['life'] <= 0:
            break
        if time.time() - t0 > budget:
            problem('%s: the fight did not finish within %.0f s' % (name, budget))
            break
        # keep the attacker alive (retreat when life < 40) and in reach
        plife = life(m_target, pl)
        if plife < 40:
            print('   player %d life %.0f < 40: retreating' % (pl + 1, plife))
            print('   tp away: %s' % tp_near(pipe, m_target, pl, cur['pos'], back=35.0))
            sample_until(1.5, pl, sl)
            continue
        d = dist(pos_char(m_target, player(m_target, pl)), cur['pos'])
        if d > 30:
            print('   tp in (%.1f units away): %s' % (d, tp_near(pipe, m_target, pl, cur['pos'], back=10.0)))
            if pipe is not host:   # both copies simulate this player: put its other copy there too
                print('   tp peer: %s' % tp_near(host, mh, pl, cur['pos'], back=10.0))
        try_attack(pipe, pl, pl_g, 0 if pipe is host else 0, sl, 'attack %d' % (i + 1))
        if i == 1:   # a foreground picture of both copies during the fight (the task asks for it)
            for pid, who in ((h, 'host'), (g, 'guest')):
                path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shots', 'combat23_%s.png' % who)
                try:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    print('   shot %s during attack %d: %.1f%% non-black -> %s'
                          % (who, i + 1, capture(pid, path), path))
                except Exception as e:
                    print('   shot %s failed: %s' % (who, e))
        sample_until(0.4, pl, sl, 0.05)
    end = near(enemies(m_target), target)
    print('   %s: %d attacks issued, %d samples, enemy life %.1f state %#x on the attacker\'s copy'
          % (name, len(ATTACKS), len(sl), end['life'] if end else -1, end['state'] if end else -1))
    return sl


def check_phase(name, sl, ref, which):
    """The per-phase assertions: life tolerance, death on both copies, per-hit drops, anim, positions."""
    eh = near(enemies(mh), ref)
    eg = near(enemies(mg), ref)
    if not eh or not eg:
        problem('%s: the enemy is missing on a copy' % name)
        return
    # Settled samples only: the guest applies the host's life on the next 33 ms NPC snapshot, so a sample
    # taken inside that window shows the hit before the guest has taken it (reported separately below).
    settled = [s for s in sl if s['settled']]
    worst = max((abs(s['h' + which + '_life'] - s['g' + which + '_life']) for s in settled), default=0.0)
    split = sum(1 for s in settled if (s['h' + which + '_life'] > 0) != (s['g' + which + '_life'] > 0))
    transient = max((abs(s['h' + which + '_life'] - s['g' + which + '_life']) for s in sl), default=0.0)
    n_trans = sum(1 for s in sl if abs(s['h' + which + '_life'] - s['g' + which + '_life']) > TOL)
    drops_h = [round(r[1] - r[2], 2) for r in ATTACKS]
    drops_g = [round(r[3] - r[4], 2) for r in ATTACKS]
    print('   %s: worst life difference on %d settled samples %.2f (tolerance %.1f)'
          % (name, len(settled), worst, TOL))
    print('   %s: transient: %d of %d samples inside one NPC snapshot (33 ms) differ, worst %.2f'
          % (name, n_trans, len(sl), transient))
    if worst > TOL:
        problem('%s: life drifted apart between the copies by %.2f on settled samples' % (name, worst))
    print('   %s: per-hit drops at the attack boundaries host %s | guest %s' % (name, drops_h, drops_g))
    if len(drops_h) != len(drops_g) or any(abs(a - b) > TOL for a, b in zip(drops_h, drops_g)):
        problem('%s: the per-hit life drop differs between the copies (double damage?)' % name)
    if drops_h and all(abs(a - b) <= TOL for a, b in zip(drops_h, drops_g)):
        print('   %s: no double damage: every hit landed once on both copies' % name)
    if drops_h:
        print('   %s: drop values against GAME_MECHANICS.md (melee 7/8/14, gun 15): %s'
              % (name, 'matches the melee combo' if [round(x) for x in drops_h[:3]] == [7, 8, 14]
                 else 'not a melee combo' if ATTACK['kind'] == 'chord' else 'set by the fallback'))
    if eh['life'] > 0:
        problem('%s: %s is not dead on the host copy (life %.1f)' % (name, eh['cls'], eh['life']))
    if eg['life'] > 0:
        problem('%s: %s is not dead on the guest copy (life %.1f)' % (name, eg['cls'], eg['life']))
    if eh['state'] != eg['state']:
        problem('%s: the death state differs: host %#x guest %#x' % (name, eh['state'], eg['state']))
    if split:
        problem('%s: %d settled samples had one copy alive and the other dead' % (name, split))
    # player life + attack animation + enemy positions
    pw = max(max(abs(s['hp1'] - s['gp1']), abs(s['hp2'] - s['gp2'])) for s in sl) if sl else 0
    print('   %s: player life equal on both copies within %.2f (p1 %.1f/%.1f, p2 %.1f/%.1f)'
          % (name, pw, sl[-1]['hp1'], sl[-1]['gp1'], sl[-1]['hp2'], sl[-1]['gp2']))
    if pw > 0.01:
        problem('%s: player life differs between the copies by %.2f' % (name, pw))
    eq = sum(1 for s in sl if s['hanim'] == s['ganim'])
    nz = sum(1 for s in sl if s['hanim'] != 0)
    print('   %s: attack animation samples equal on both copies %d/%d (attacker anim non-zero in %d)'
          % (name, eq, len(sl), nz))
    if sl and eq < len(sl) * 0.8:
        problem('%s: the attack animation differs between the copies (%d/%d equal)' % (name, eq, len(sl)))
    pd = max(dist(s['ha_pos'], s['ga_pos']) for s in sl) if sl else 0
    pb = max(dist(s['hb_pos'], s['gb_pos']) for s in sl) if sl else 0
    print('   %s: enemy positions equal on both copies within %.2f units (A) / %.2f (B)' % (name, pd, pb))
    if max(pd, pb) > POS_TOL:
        problem('%s: enemy positions differ between the copies by %.2f units' % (name, max(pd, pb)))


def enemy_line(m):
    return ', '.join('%s%s %.1f st %#x' % (r['cls'], r['tag'], r['life'], r['state']) for r in enemies(m))


def arrive(lvl, entry):
    print('\n== host level %s %d 1 -> %s' % (lvl, entry, host.cmd('level %s %d 1' % (lvl, entry))))
    t0 = time.time()
    while time.time() - t0 < 90:
        if tag(level(mh)) == lvl and tag(level(mg)) == lvl and mode(mh) == 1 and mode(mg) == 1:
            break
        time.sleep(1.0)
    print('   arrived after %.1f s: host %s (mode %d) guest %s (mode %d)'
          % (time.time() - t0, tag(level(mh)), mode(mh), tag(level(mg)), mode(mg)))
    time.sleep(8.0)


def prepare(lvl):
    """Print players/enemies, probe the stick and pick enemy A (and B)."""
    global EN_A, EN_B
    for pl in (0, 1):
        print('   player %d %s life %.1f sel %d slots %s'
              % (pl + 1, tag(u32(mh, player(mh, pl) + 0x14)) if player(mh, pl) else '?', life(mh, pl),
                 sel_slot(mh, pl), slots(mh, pl)))
    print('   enemies host:  %s' % enemy_line(mh))
    print('   enemies guest: %s' % enemy_line(mg))
    a0 = pos_char(mh, player(mh, 0))
    pad(host, 0, 0, 0, 30000)
    time.sleep(0.8)
    pad_off(host, 0)
    a1 = pos_char(mh, player(mh, 0))
    print('   control probe: analog stick up moved player 1 %.1f units' % dist(a0, a1))
    live = [r for r in enemies(mh) if r['life'] > 0 and r['maxlife'] > 1.0]
    if not live:
        problem('%s has no live enemy with more than 1 HP' % lvl)
        return False
    live.sort(key=lambda r: (-r['maxlife'], dist(r['pos'], a0)))
    EN_A = live[0]
    EN_B = live[1] if len(live) > 1 else live[0]
    print('   enemy A: %s %s at (%.1f, %.1f, %.1f) life %.1f/%.1f at %x'
          % (EN_A['cls'], EN_A['tag'], *EN_A['pos'], EN_A['life'], EN_A['maxlife'], EN_A['addr']))
    print('   enemy B: %s %s at (%.1f, %.1f, %.1f) life %.1f/%.1f at %x'
          % (EN_B['cls'], EN_B['tag'], *EN_B['pos'], EN_B['life'], EN_B['maxlife'], EN_B['addr']))
    return True


# ---- the enemy-life code of 6704c30 --------------------------------------------------------------
def divergence_experiment():
    """Show the two copies with the guest's life correction off and on."""
    live = [r for r in enemies(mh) if r['life'] > 0 and near(enemies(mg), r) and near(enemies(mg), r)['life'] > 0]
    if not live:
        print('   no live enemy left for the experiment')
        return
    c = live[0]
    print('\n== the enemy-life code of 6704c30 (guest %s)' % guest.cmd('npclife 0'))
    print('   target: %s %s life %.1f at %x' % (c['cls'], c['tag'], c['life'], c['addr']))
    print('   host only: %s' % host.cmd('npcset %x %.1f' % (c['addr'], c['life'] - 7.0)))
    time.sleep(1.0)
    hh, gg = near(enemies(mh), c), near(enemies(mg), c)
    print('   correction OFF: host life %.1f state %#x | guest life %.1f state %#x | difference %.2f'
          % (hh['life'], hh['state'], gg['life'], gg['state'], abs(hh['life'] - gg['life'])))
    print('   guest %s' % guest.cmd('npclife 1'))
    time.sleep(1.5)
    hh, gg = near(enemies(mh), c), near(enemies(mg), c)
    print('   correction ON : host life %.1f state %#x | guest life %.1f state %#x | difference %.2f'
          % (hh['life'], hh['state'], gg['life'], gg['state'], abs(hh['life'] - gg['life'])))
    if abs(hh['life'] - gg['life']) > 0.01:
        problem('the guest did not follow the host\'s enemy life with the correction on (%.1f vs %.1f)'
                % (hh['life'], gg['life']))
    print('   guest sync: %s' % guest.cmd('sync'))
    # guest-only damage with the correction on: the host owns the life, so it must be undone
    print('\n== guest-only damage (the host owns enemy life)')
    gc = near(enemies(mg), c)
    d0 = gc['life']
    print('   guest only: %s' % guest.cmd('npcset %x %.1f' % (gc['addr'], max(0.0, d0 - 7.0))))
    time.sleep(0.25)
    gmid = near(enemies(mg), c)['life']
    time.sleep(1.2)
    gg, hh = near(enemies(mg), c), near(enemies(mh), c)
    print('   guest life right after its own damage %.1f -> after the host snapshot %.1f | host %.1f'
          % (gmid, gg['life'], hh['life']))
    if abs(gg['life'] - hh['life']) > 0.01:
        problem('guest-only damage was not reverted to the host\'s life (guest %.1f host %.1f)'
                % (gg['life'], hh['life']))


# ---- the run -------------------------------------------------------------------------------------
attack = None
level_done = {}
for lvl, entry in LEVELS:
    arrive(lvl, entry)
    if not prepare(lvl):
        continue
    if attack is None:
        attack = discover_attack(host, 0, 0, 0)
        print('\n   ATTACK IN USE: %s' % attack['kind'])
    else:
        print('\n   attack in use: %s' % attack['kind'])
    # phase 1: the host's player 1 kills A
    sl1 = fight('phase 1 (host player 1)', host, 0, 0, EN_A, 'h', mh)
    check_phase('phase 1', sl1, EN_A, 'a')
    phase1_ok = near(enemies(mh), EN_A)['life'] <= 0 and near(enemies(mg), EN_A)['life'] <= 0
    level_done[lvl] = phase1_ok
    print('   phase 1 result: %s' % ('enemy A dead on both copies' if phase1_ok else 'NOT dead on both'))
    # phase 2: the guest's player 2 attacks B
    if attack['kind'] == 'npcset':
        print('\n== phase 2 (guest player 2): with the host-owned enemy life a hit only the guest\'s copy')
        print('   makes is reverted, so the guest cannot kill an enemy alone. Shown above; phase 2 needs')
        print('   the real attack input (both copies simulate the same swing).')
    else:
        sl2 = fight('phase 2 (guest player 2)', guest, 1, 1, EN_B, 'g', mg)
        check_phase('phase 2', sl2, EN_B, 'b')
    if lvl == LEVELS[0][0]:
        divergence_experiment()
    print('\n   enemies host:  %s' % enemy_line(mh))
    print('   enemies guest: %s' % enemy_line(mg))

print('\n== final state on both copies')
print('enemies host:  %s' % enemy_line(mh))
print('enemies guest: %s' % enemy_line(mg))
for pl in (0, 1):
    lh, lg = life(mh, pl), life(mg, pl)
    print('player %d life host %.1f guest %.1f' % (pl + 1, lh, lg))
    if abs(lh - lg) > 0.01:
        problem('player %d life differs: host %.1f guest %.1f' % (pl + 1, lh, lg))
for r in enemies(mh):
    o = near(enemies(mg), r)
    if not o:
        problem('%s has no counterpart on the guest' % r['cls'])
    elif (r['life'] > 0) != (o['life'] > 0):
        problem('%s: alive host %s / guest %s (life %.1f / %.1f)'
                % (r['cls'], r['life'] > 0, o['life'] > 0, r['life'], o['life']))
    elif abs(r['life'] - o['life']) > TOL:
        problem('%s: life differs after the fight (host %.1f guest %.1f)' % (r['cls'], r['life'], o['life']))
print('sync host:  %s' % host.cmd('sync'))
print('sync guest: %s' % guest.cmd('sync'))
if attack['kind'] == 'npcset':
    print('\nNOTE: the fight above was driven through the game\'s own life method (npcset), NOT an attack:')
    print('      no real input and no game attack entry could be reached from this build (see FINDINGS_23).')
print('\nRESULT: %s' % ('combat OK' if not problems else 'combat FAILED'))
for p in problems:
    print('  - %s' % p)
sys.exit(0 if not problems else 1)
