"""TASK 28 Part A: load every save slot on ONE copy and list the aptitude objects of the level.

Read-only survey (like scan_slots.py): for every slot it prints
  * the party (live humans) and the 8 progress character records (progress+0x1b0c, tag + level),
  * every level entity whose RTTI class is an "aptitude object":
    CToeLockPick (Stan), CToeDiscLock / CToeDigicode / CToeCardReader (Mei hacking),
    CToeDarkAura* (Shannon), CToeHeavyCase / strength doors (Sven/Kenny), CToeLadder/legup (Corey),
    CToeDocument (Amy), plus the doors/cases they belong to,
  * for each of those: position, interaction anchor +0x10c, radius +0xa0, the flags the game's own
    use/eligibility check reads (+0x20 active, +0x24 usable, +0xa8 collected, +0xb8/+0xc0/+0xac/+0xb0
    gates, +0x1a4 / +0x140 / +0x10c aptitude fields), the vtable and its slots 0x1c/0x20/0x34/0x38/0x70,
  * the distance from player 1 and player 2 and the Z difference (an aptitude object on another floor
    cannot be reached by the safe tp).

Usage: python -I scan_abilities.py <pid> <slot[,slot...]>
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot
from peek import Proc

GAME = 0x6c3068

APT = ('LockPick', 'DiscLock', 'Digicode', 'CardReader', 'DarkAura', 'HeavyCase', 'Document',
       'Ladder', 'Legup', 'Chain', 'Crank', 'ChemistryBench', 'Crane', 'Pedestal', 'ChestKey',
       'Chest', 'BreakableCase', 'Door', 'InteractHelp', 'SpecialDoor')


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


def game(m):
    return u32(m, m.va(GAME))


def world(m):
    g = game(m)
    return u32(m, g + 0x378) if g else 0


def mode(m):
    g = game(m)
    return u32(m, g + 0x310) if g else None


def reqstate(m):
    g = game(m)
    return u32(m, g + 0x320) if g else None


def progress(m):
    g = game(m)
    return u32(m, g + 0x318) if g else 0


def rtti_name(m, obj):
    vt = u32(m, obj)
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
    if i >= 0:
        s = s[i + 2:]
    return s.rstrip('@')


def slot_name(m, obj):
    vt = u32(m, obj)
    return u32(m, vt + 0x70) if vt else 0


def walk(m, head):
    out, node, seen = [], head, set()
    while node and node not in seen and len(out) < 4000:
        seen.add(node)
        e = u32(m, node)
        if e:
            out.append(e)
        node = u32(m, node + 4)
    return out


def ents(m, off=8):
    w = world(m)
    mgr = u32(m, w + 0x1768) if w else 0
    return walk(m, u32(m, mgr + off)) if mgr else []


def npcs(m):
    w = world(m)
    mg = u32(m, w + 0x1760) if w else 0
    if not mg:
        return []
    n, arr = u32(m, mg + 4), u32(m, mg + 0xc)
    out = []
    for i in range(min(n, 64) if arr else 0):
        h = u32(m, arr + 4 * i)
        if h:
            out.append(h)
    return out


def humans(m):
    w = world(m)
    mg = u32(m, w + 0x175c) if w else 0
    if not mg:
        return []
    n, arr = u32(m, mg + 4), u32(m, mg + 0xc)
    out = []
    for i in range(min(n, 8) if arr else 0):
        h = u32(m, arr + 4 * i)
        if h:
            out.append(h)
    return out


def player_human(m, pl):
    w = world(m)
    ctl = u32(m, w + 0x1748) if w else 0
    return u32(m, ctl + 4 + 0x764 * pl) if ctl else 0


def pos(m, h):
    return (f32(m, h + 0x23c), f32(m, h + 0x240), f32(m, h + 0x244))


def epos(m, e):
    return (f32(m, e + 0x6c), f32(m, e + 0x70), f32(m, e + 0x74))


def sane(p):
    return all(abs(v) < 1e6 for v in p)


def dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def scan(m, slot):
    print('=' * 100)
    w = world(m)
    print('SLOT %d level %s mode %s req %s world %#x' % (
        slot, tag(u32(m, w + 4)) if w else '----', mode(m), reqstate(m), w or 0))
    if not w:
        print('  NO WORLD')
        return
    hs = humans(m)
    print('  party (live humans): %s' % ', '.join(
        '%s @%x at (%.1f, %.1f, %.1f)' % (tag(u32(m, h + 0x14)), h, *pos(m, h)) for h in hs))
    obj = progress(m)
    if obj:
        recs = []
        for i in range(8):
            r = obj + 0x1b0c + i * 0x28
            ct = u32(m, r)
            if ct:
                recs.append('%s@%s id%d ctl%s hp%.0f' % (
                    tag(ct), tag(u32(m, r + 4)), u32(m, r + 8), tag(u32(m, r + 0xc)), f32(m, r + 0x10)))
        print('  progress characters: %s' % ('; '.join(recs) if recs else 'none'))
    else:
        print('  progress object none')
    for pl in (0, 1):
        ph = player_human(m, pl)
        print('  player %d: %s' % (pl + 1, ('%s at (%.1f, %.1f, %.1f)' % (tag(u32(m, ph + 0x14)), *pos(m, ph)))
                                   if ph else 'none'))
    seen_apt = 0
    for e in ents(m):
        rn = rtti_name(m, e)
        if not any(a.lower() in rn.lower() for a in APT):
            continue
        seen_apt += 1
        p = epos(m, e)
        an = (f32(m, e + 0x10c), f32(m, e + 0x110), f32(m, e + 0x114))
        vt = u32(m, e)
        sl = lambda off: u32(m, vt + off) if vt else 0
        d = []
        for pl in (0, 1):
            ph = player_human(m, pl)
            if ph:
                pp = pos(m, ph)
                d.append('p%d %.0f (dz %.0f)' % (pl + 1, dist(pp, p), p[2] - pp[2]))
        print('  %-24s cls %s id %s @%x pos (%.1f, %.1f, %.1f) anchor (%.1f, %.1f, %.1f) r %.0f %s' % (
            rn, tag(u32(m, e + 0x10)), tag(u32(m, e + 4)), e, p[0], p[1], p[2],
            an[0], an[1], an[2], f32(m, e + 0xa0), ' | '.join(d)))
        print('      flags p20=%d p24=%d coll=%d gates b8=%d c0=%d ac=%d b0=%d p14=%d p18=%d p1a4=%d p140=%d p108=%d p10c=%d p118=%d p150=%d' % (
            u32(m, e + 0x20), u32(m, e + 0x24), u32(m, e + 0xa8), u32(m, e + 0xb8), u32(m, e + 0xc0),
            u32(m, e + 0xac), u32(m, e + 0xb0), u32(m, e + 0x14), u32(m, e + 0x18), u32(m, e + 0x1a4),
            u32(m, e + 0x140), u32(m, e + 0x108), u32(m, e + 0x10c), u32(m, e + 0x118), u32(m, e + 0x150)))
        print('      user +0xc4 %#x vt %#x slots 1c=%#x 20=%#x 34=%#x 38=%#x 70=%#x' % (
            u32(m, e + 0xc4), vt, sl(0x1c), sl(0x20), sl(0x34), sl(0x38), sl(0x70)))
    print('  aptitude-ish entities: %d of %d' % (seen_apt, len(ents(m))))
    if ALL:
        print('  --- all level-list entities (mgr+8) ---')
        for e in ents(m):
            print('    %-24s cls %s id %s @%x pos (%.1f, %.1f, %.1f) p20=%d p24=%d p1a4=%d' % (
                rtti_name(m, e) or '?', tag(u32(m, e + 0x10)), tag(u32(m, e + 4)), e, *epos(m, e),
                u32(m, e + 0x20), u32(m, e + 0x24), u32(m, e + 0x1a4)))
        print('  --- second list (mgr+0x18) ---')
        for e in ents(m, 0x18):
            print('    %-24s cls %s id %s @%x pos (%.1f, %.1f, %.1f) p20=%d p24=%d p1a4=%d' % (
                rtti_name(m, e) or '?', tag(u32(m, e + 0x10)), tag(u32(m, e + 4)), e, *epos(m, e),
                u32(m, e + 0x20), u32(m, e + 0x24), u32(m, e + 0x1a4)))
        print('  --- NPC manager ---')
        for h in npcs(m):
            print('    %-24s tag %s @%x pos (%.1f, %.1f, %.1f) life %.0f anim %d' % (
                rtti_name(m, h) or '?', tag(u32(m, h + 0x14)), h, *pos(m, h),
                f32(m, h + 0x320), u32(m, h + 0x2dc)))


pid = int(sys.argv[1])
slots = [int(x) for x in sys.argv[2].split(',') if x != '']
ALL = len(sys.argv) > 3 and sys.argv[3] == 'all'
m = Proc(pid)
p = None
t0 = time.time()
while time.time() - t0 < 90:
    try:
        p = bot.Pipe(pid)
        break
    except Exception:
        time.sleep(1.0)
if p is None:
    raise SystemExit('the command pipe never appeared')
t0 = time.time()
while time.time() - t0 < 90:
    if mode(m) == 2 and not world(m):
        break
    time.sleep(1.0)
print('at the main menu (mode %s, world %#x)' % (mode(m), world(m) or 0))
for slot in slots:
    t = time.time()
    w0, lv0 = world(m), u32(m, world(m) + 4) if world(m) else 0
    print('loadsave game%d.sav -> %s' % (slot, p.cmd('loadsave game%d.sav' % slot)))
    ok = False
    while time.time() - t < 120:
        w1 = world(m)
        if mode(m) == 1 and w1 and len(humans(m)) >= 1 and reqstate(m) == 0 and \
                (not w0 or w1 != w0 or u32(m, w1 + 4) != lv0):
            ok = True
            break
        time.sleep(1.0)
    print('world up for slot %d: %s after %.1f s' % (slot, ok, time.time() - t))
    if ok:
        time.sleep(12.0)   # the level builds its entities and places the characters over the first frames
        scan(m, slot)
    else:
        print('SLOT %d did not reach a world (mode %s world %#x req %s)' % (slot, mode(m), world(m) or 0, reqstate(m)))
        time.sleep(3)
print('DONE')
