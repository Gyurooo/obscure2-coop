"""Character abilities on both copies (TASK 28): lock picking (Stan) and the heavy case (Sven).

The runner loads ONE save slot into both copies (OBSCOOP_SLOT). The check finds the live aptitude objects
of the level (`CToeLockPick` class tag LCKP, `CToeHeavyCase` HCAS, `CToeDiscLock` DISL, `CToeDocument`
DOC., `CToeDarkAura*`) and the character each one needs (from the decompile: LCKP is BOY1 only, HCAS
BOY3/BOY4, DISL GIR2, DOC. GIR3, the dark aura GIR1).

  phase 1  the host's own player 1 (host copy, controller 0) performs the ability it owns;
  phase 2  the guest's own player 2 (guest copy, controller 1) performs the ability it owns.

For each phase it prints, on BOTH copies, the object's state (position, +0x20 active, +0x24 usable,
+0xa8 collected, the user +0xc4, the aptitude fields +0x104/+0x124/+0x128/+0x184/+0x1ec/+0x1f0), the
character (+0x2bc action object, +0x2dc animation), the nearby doors' state and a digest of the progress
entity table (+0x814) before and after, plus a screenshot of both copies.

PASS = the object's result state is the same on both copies after the action, and the acting copy's
character really ran the action. `--probe` prints the same data and never fails (measurement mode).

Read-only memory reads, the mod's own safe `tp`, normal pad presses. Exit 0 = PASS or SKIP, 1 = FAIL.
Usage: python -I check_abilities.py <host pid> <guest pid> [--probe]
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot
from peek import Proc

GAME = 0x6c3068
SLOT = os.environ.get('SAVE_SLOT', '?')
PROBE = '--probe' in sys.argv

# class tags (little-endian dwords, printed by tag())
LCKP = 0x4c434b50
HCAS = 0x48434153
DISL = 0x4449534c
DOC_ = 0x444f432e
CHKE = 0x43484b45
AURA = (0x44415552, 0x44415531, 0x44415532, 0x44415533)   # DAUR-ish variants, RTTI is the filter
T_BOY1, T_BOY3, T_BOY4 = 0x424f5931, 0x424f5933, 0x424f5934
T_GIR1, T_GIR2, T_GIR3 = 0x47495231, 0x47495232, 0x47495233


def u32(m, a):
    try:
        return m.u32(a) or 0
    except Exception:
        return 0


def f32(m, a):
    b = m.read(a, 4)
    return struct.unpack('<f', b)[0] if b else 0.0


def tag(v):
    return ''.join(chr((v >> s) & 0xff) if 32 <= ((v >> s) & 0xff) < 127 else '.' for s in (24, 16, 8, 0))


def game(m):
    return u32(m, m.va(GAME))


def world(m):
    g = game(m)
    return u32(m, g + 0x378) if g else 0


def mode(m):
    g = game(m)
    return u32(m, g + 0x310) if g else 0


def progress(m):
    g = game(m)
    return u32(m, g + 0x318) if g else 0


def rtti(m, o):
    vt = u32(m, o)
    if not vt:
        return ''
    col = u32(m, vt - 4)
    if not col:
        return ''
    td = u32(m, col + 0xc)
    if not td:
        return ''
    raw = m.read(td + 8, 160) or b''
    s = raw.split(b'\x00')[0].decode('latin1', 'replace')
    i = s.find('AV')
    return (s[i + 2:] if i >= 0 else s).rstrip('@')


def walk(m, head):
    out, node, seen = [], head, set()
    while node and node not in seen and len(out) < 800:
        seen.add(node)
        e = u32(m, node)
        if e:
            out.append(e)
        node = u32(m, node + 4)
    return out


def ents(m):
    w = world(m)
    mgr = u32(m, w + 0x1768) if w else 0
    out = []
    for off in (8, 0x18):
        out += walk(m, u32(m, mgr + off)) if mgr else []
    return out


def ctl_human(m, pl):
    w = world(m)
    ctl = u32(m, w + 0x1748) if w else 0
    return u32(m, ctl + 4 + 0x764 * pl) if ctl else 0


def humans(m):
    w = world(m)
    mg = u32(m, w + 0x175c) if w else 0
    if not mg:
        return []
    n, arr = u32(m, mg + 4), u32(m, mg + 0xc)
    return [u32(m, arr + 4 * i) for i in range(min(n, 8) if arr else 0) if u32(m, arr + 4 * i)]


def hpos(m, h):
    return (f32(m, h + 0x23c), f32(m, h + 0x240), f32(m, h + 0x244))


def epos(m, e):
    return (f32(m, e + 0x6c), f32(m, e + 0x70), f32(m, e + 0x74))


def level_of(m):
    w = world(m)
    return tag(u32(m, w + 4)) if w else '----'


def d3(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def sane(p):
    return all(abs(v) < 100000.0 for v in p)


def apt_kind(m, e):
    """Which aptitude object this entity is, or ''."""
    rn = rtti(m, e)
    if 'CToeLockPick' in rn:
        return 'LCKP'
    if 'CToeHeavyCase' in rn:
        return 'HCAS'
    if 'CToeDiscLock' in rn:
        return 'DISL'
    if 'CToeDocument' in rn:
        return 'DOC'
    if 'CToeDarkAura' in rn:
        return 'AURA'
    return ''


def apt_objects(m):
    out = []
    for e in ents(m):
        k = apt_kind(m, e)
        if k:
            out.append((e, k))
    return out


def owner_of(kind):
    """The character tags the decompile says can really run this ability."""
    return {'LCKP': (T_BOY1,), 'HCAS': (T_BOY3, T_BOY4), 'DISL': (T_GIR2,),
            'DOC': (T_GIR3,), 'AURA': (T_GIR1,)}.get(kind, ())


def describe(m, e, kind):
    p = epos(m, e)
    return ('%s/%s @%x (%.2f,%.2f,%.2f) p20=%d p24=%d coll=%d user=%x f104=%d f108=%d f124=%d f128=%d '
            'f184=%d f1ec=%d f1f0=%d f224=%d f22c=%d objs=%d' % (
                kind, tag(u32(m, e + 0x10)), e, p[0], p[1], p[2], u32(m, e + 0x20), u32(m, e + 0x24),
                u32(m, e + 0xa8), u32(m, e + 0xc4), u32(m, e + 0x104), u32(m, e + 0x108), u32(m, e + 0x124),
                u32(m, e + 0x128), u32(m, e + 0x184), u32(m, e + 0x1ec), u32(m, e + 0x1f0),
                u32(m, e + 0x224), u32(m, e + 0x22c), u32(m, e + 0x108)))


def snap_obj(m, e):
    """The fields an aptitude action changes (the result), plus the position."""
    p = epos(m, e)
    return (u32(m, e + 0x20), u32(m, e + 0x24), u32(m, e + 0xa8), u32(m, e + 0xc4),
            u32(m, e + 0x104), u32(m, e + 0x124), u32(m, e + 0x128), u32(m, e + 0x184),
            round(p[0], 2), round(p[1], 2), round(p[2], 2))


def char_state(m, h):
    if not h:
        return 'none'
    return ('%s @%x pos (%.2f,%.2f,%.2f) anim=%d life=%.0f action=@%x animobj=%x' % (
        tag(u32(m, h + 0x14)), h, *hpos(m, h), u32(m, h + 0x2dc), f32(m, h + 0x320), u32(m, h + 0x2bc),
        u32(m, h + 0x2c0)))


def prog_digest(m):
    """A stable digest of the progress entity table (+0x814) and the counters after the characters."""
    obj = progress(m)
    if not obj:
        return 'no progress', 0, ''
    n = u32(m, obj + 0x814)
    if n > 380:
        n = 380
    data = m.read(obj + 0x814, 4 + 12 * n) or b''
    h = 2166136261
    for b in data:
        h = ((h ^ b) * 16777619) & 0xffffffff
    tail = m.read(obj + 0x1c50, 0x84) or b''
    h2 = 2166136261
    for b in tail:
        h2 = ((h2 ^ b) * 16777619) & 0xffffffff
    return ('count %d hash %08x tail %08x' % (n, h, h2)), n, data


def prog_entries(m, n=380):
    obj = progress(m)
    if not obj:
        return []
    cnt = min(u32(m, obj + 0x814), n)
    out = []
    for i in range(cnt):
        o = obj + 0x818 + 12 * i
        out.append((u32(m, o), u32(m, o + 4), u32(m, o + 8)))
    return out


def doors_near(m, p, radius=500.0):
    out = []
    for e in ents(m):
        rn = rtti(m, e)
        if 'Door' not in rn:
            continue
        q = epos(m, e)
        if not sane(q) or d3(p, q) > radius:
            continue
        out.append('%s @%x at (%.1f,%.1f,%.1f) p24=%d f120=%d f13c=%.2f,%.2f,%.2f' % (
            rn, e, q[0], q[1], q[2], u32(m, e + 0x24), u32(m, e + 0x120),
            f32(m, e + 0x13c), f32(m, e + 0x140), f32(m, e + 0x144)))
    return out


def door_snaps(m, p, radius=500.0):
    """The state of the doors around an ability object: a picked lock / absorbed aura opens its door."""
    out = []
    for e in ents(m):
        if 'Door' not in rtti(m, e):
            continue
        q = epos(m, e)
        if not sane(q) or d3(p, q) > radius:
            continue
        out.append((u32(m, e + 0x10), round(q[0], 1), round(q[1], 1), round(q[2], 1),
                    u32(m, e + 0x24), u32(m, e + 0x120), round(f32(m, e + 0x13c), 2),
                    round(f32(m, e + 0x140), 2)))
    return tuple(sorted(out))


def door_states(m, p, radius=500.0):
    return tuple((c, a, b, d, st, op, x, y) for (c, a, b, d, st, op, x, y) in door_snaps(m, p, radius))


def frames(pipe):
    s = pipe.cmd('sync')
    i = s.find('| frames ')
    return s[i + 9:].strip() if i >= 0 else '?'


def wait_for(fn, secs, step=0.1):
    t = time.time()
    while time.time() - t < secs:
        if fn():
            return True, time.time() - t
        time.sleep(step)
    return False, time.time() - t


def tp_near(pipe, m, pl, target, radii=(60.0, 45.0, 75.0, 90.0, 35.0, 110.0), away=False):
    """Place player `pl` next to `target` facing it, through the mod's safe tp."""
    hp = hpos(m, ctl_human(m, pl))
    tried = 0
    for radius in radii:
        for ang in (0, 45, 90, 135, 180, 225, 270, 315):
            dx, dy = hp[0] - target[0], hp[1] - target[1]
            dd = (dx * dx + dy * dy) ** 0.5 or 1.0
            base = (dx / dd, dy / dd)
            ca, sa = __import__('math').cos(__import__('math').radians(ang)), __import__('math').sin(__import__('math').radians(ang))
            ux, uy = base[0] * ca - base[1] * sa, base[0] * sa + base[1] * ca
            stand = (target[0] + ux * radius, target[1] + uy * radius, target[2])
            sign = -1.0 if away else 1.0
            r = pipe.cmd('tp %d %.3f %.3f %.3f %.3f %.3f' % (pl, stand[0], stand[1], stand[2],
                                                             sign * (target[0] - stand[0]), sign * (target[1] - stand[1])))
            tried += 1
            if r.startswith('ok'):
                return True, 'safe tp at %.0f units (%s)' % (radius, r)
    return False, 'safe tp refused every spot (%d tried)' % tried


def press_a(pipe, user, hold=0.2):
    bot.press(pipe, user, 'A', hold)


def shots(host, guest, base):
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shots')
    os.makedirs(d, exist_ok=True)
    for name, pid in (('host', host), ('guest', guest)):
        try:
            bot.shot(pid, os.path.join(d, '%s_%s.png' % (base, name)))
        except SystemExit as e:
            print('abilities: screenshot %s failed: %s' % (name, e))


def main():
    hp, gp = int(sys.argv[1]), int(sys.argv[2])
    mh, mg = Proc(hp), Proc(gp)
    ph, pg = bot.Pipe(hp), bot.Pipe(gp)
    t = time.time()
    while time.time() - t < 120 and not (world(mh) and mode(mh) == 1 and world(mg) and mode(mg) == 1):
        time.sleep(0.5)
    time.sleep(3)
    print('abilities: level host %s guest %s (save slot %s) probe=%d' % (level_of(mh), level_of(mg), SLOT, PROBE))
    fails = []
    for m, name in ((mh, 'host'), (mg, 'guest')):
        o1, o2 = ctl_human(m, 0), ctl_human(m, 1)
        print('abilities: %s player1 %s | player2 %s' % (name, char_state(m, o1), char_state(m, o2)))
        print('abilities: %s progress %s' % (name, prog_digest(m)[0]))
        objs = apt_objects(m)
        print('abilities: %s aptitude objects: %d' % (name, len(objs)))
        for e, k in objs:
            print('   %s' % describe(m, e, k))
            if k in ('LCKP', 'HCAS'):
                print('   doors: %s' % ('; '.join(doors_near(m, epos(m, e))) or 'none'))
    phases = (('player 1 (host)', mh, mg, ph, 0, 'host'),
              ('player 2 (guest)', mg, mh, pg, 1, 'guest'))
    for label, m_own, m_oth, pipe_own, pl, side in phases:
        me = ctl_human(m_own, pl)
        if not me:
            print('\nabilities: %s: no character (SKIP)' % label)
            continue
        mytag = u32(m_own, me + 0x14)
        mine = [(e, k) for e, k in apt_objects(m_own) if mytag in owner_of(k) and u32(m_own, e + 0x24)]
        print('\nabilities: %s = %s; usable aptitude objects for it: %s' % (
            label, tag(mytag), ', '.join('%s@%x' % (k, e) for e, k in mine) or 'none'))
        if not mine:
            print('abilities: %s SKIP (this character has no active aptitude object in this level)' % label)
            continue
        e, kind = min(mine, key=lambda x: d3(epos(m_own, x[0]), hpos(m_own, me)))
        print('abilities: %s -> %s %s' % (label, kind, describe(m_own, e, kind)))
        ok, how = tp_near(pipe_own, m_own, pl, epos(m_own, e))
        print('abilities: tp %s: %s' % (label, how))
        if not ok:
            fails.append('%s: could not reach the object' % label)
            continue
        time.sleep(0.5)
        ents_before = prog_entries(m_own)
        other = 0
        # the other copy's object: same class tag, nearest placed position
        for oe, ok2 in apt_objects(m_oth):
            if ok2 == kind and sane(epos(m_oth, oe)):
                if not other or abs(d3(epos(m_oth, oe), epos(m_own, e))) < abs(d3(epos(m_oth, other), epos(m_own, e))):
                    other = oe
        print('  before own  %s' % describe(m_own, e, kind))
        print('  before other %s' % describe(m_oth, other or e, kind) if other else '  before other (no object)')
        shots(hp, gp, 'apt_%s_before' % side)
        # The action button starts the object's own action when the character is in reach and faces it.
        # A lock pick used from the front side runs the game's completion branch, from the back side it
        # starts the mini-game (the character links to the object, human+0x2bc). A heavy case starts a
        # push (the character links to the case and the case starts to move).
        before = (snap_obj(m_own, e), door_snaps(m_own, epos(m_own, e)))
        started = False
        acted = False

        def try_presses(n, why):
            nonlocal started, acted
            for i in range(n):
                press_a(pipe_own, 0)
                time.sleep(0.45)
                now = (snap_obj(m_own, e), door_snaps(m_own, epos(m_own, e)))
                if u32(m_own, me + 0x2bc) == e:
                    started = True
                    print('  %s: action started on press %d (character linked to the object)' % (why, i + 1))
                    return True
                if now != before:
                    acted = True
                    print('  %s: the object changed on press %d' % (why, i + 1))
                    return True
            return False

        if not try_presses(2, 'facing the object'):
            okf, howf = tp_near(pipe_own, m_own, pl, epos(m_own, e), away=True)
            print('  no action facing the object; turning the back to it (%s)' % howf)
            if okf:
                time.sleep(0.4)
                try_presses(3, 'back to the object')
        print('  after the presses: own %s' % describe(m_own, e, kind))
        print('  after the presses char %s' % char_state(m_own, me))
        # The lock-picking mini-game is a 3-D lock turned with the sticks; the bot cannot play it. Drive
        # some stick motion first, then (if it is still running) use the test-only pipe command that runs
        # the game's OWN completion (the lock's use branch + its stop method).
        if started and kind == 'LCKP':
            for i in range(3):
                pipe_own.cmd('pad 0 0 22000 0 0 -22000')
                time.sleep(0.5)
                pipe_own.cmd('pad 0 1000 0 22000 -22000 0')
                time.sleep(0.5)
                pipe_own.cmd('pad 0 0')
                time.sleep(0.3)
                press_a(pipe_own, 0)
                time.sleep(0.3)
            print('  after mini-game input: own %s char %s' % (describe(m_own, e, kind), char_state(m_own, me)))
            if u32(m_own, me + 0x2bc) == e:
                print('  mini-game still running; test-only completion: %s' % pipe_own.cmd('aptdone %d' % pl))
                time.sleep(0.5)
        if not started and not acted:
            print('  the action button did not start an action on %s (own %s char %s)' % (
                kind, describe(m_own, e, kind), char_state(m_own, me)))
        # let the result settle (the game's own event has a 2 s delay), then read both copies
        time.sleep(4.0)
        ents_after = prog_entries(m_own)
        after = (snap_obj(m_own, e), door_snaps(m_own, epos(m_own, e)))
        print('  after own   %s' % describe(m_own, e, kind))
        print('  after own char %s' % char_state(m_own, me))
        print('  after other %s' % (describe(m_oth, other, kind) if other else '(no object)'))
        print('  after other char %s' % char_state(m_oth, ctl_human(m_oth, 1 - pl)))
        print('  progress own %s' % prog_digest(m_own)[0])
        print('  progress other %s' % prog_digest(m_oth)[0])
        print('  doors own   %s' % ('; '.join(doors_near(m_own, epos(m_own, e))) or 'none'))
        print('  doors other %s' % ('; '.join(doors_near(m_oth, epos(m_oth, other))) if other else 'none'))
        changed = [(i, a, b) for i, (a, b) in enumerate(zip(ents_before, ents_after)) if a != b]
        print('  progress entries changed on the acting copy: %d%s' % (
            len(changed), ''.join('\n    #%d %s -> %s' % (i, a, b) for i, a, b in changed[:12])))
        print('  result own   %s' % (after,))
        result_changed = after != before
        print('  the acting copy shows a result: %s' % ('yes' if result_changed else 'NO'))
        if not started and not acted and not result_changed:
            fails.append('%s: the action never ran on the acting copy' % label)
        shots(hp, gp, 'apt_%s_after' % side)
        # PASS: the result state of the object must be the same on both copies
        if other:
            oth = (snap_obj(m_oth, other), door_snaps(m_oth, epos(m_oth, other)))
            print('  result other %s' % (oth,))
            if result_changed and oth != after:
                print('  RESULT DIFFERS between the copies')
                fails.append('%s: the object result differs between the copies' % label)
            elif not result_changed:
                print('  (no result on the acting copy to compare)')
    print('\nabilities: game ticks (frames) host %s guest %s' % (frames(ph), frames(pg)))
    print('abilities: sync host  %s' % ph.cmd('sync'))
    print('abilities: sync guest %s' % pg.cmd('sync'))
    if fails and not PROBE:
        print('abilities FAIL:')
        for f in fails:
            print('  - ' + f)
        return 1
    if fails:
        print('abilities PROBE: %d difference(s) recorded (probe mode never fails)' % len(fails))
        return 0
    print('abilities OK (ability objects and their results are the same on both copies)')
    return 0


sys.exit(main())
