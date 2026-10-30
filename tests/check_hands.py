"""Held weapons follow their owner (TASK 50).

Every character's four live weapon slots and the slot in its hand are read on BOTH copies
(human+0x704 + 4*i -> weapon+0x10, the selected slot at human+0x714) and the copy that OWNS the character
(host: player 1, guest: player 2) is the authority for it. The check:

  1. prints the hands and the saved party records of both copies;
  2. has EACH player switch weapons three times with the D-pad on their own copy and requires the PARTNER's
     copy of that character to show the same slot and the same weapon within 300 ms;
  3. after every switch watches the partner's copy for 1 s: a held weapon must not change unless its owner
     changed it (the 2.0 playtest flipped the guest's own GIR1 every 30-130 ms, FINDINGS_50);
  4. finally asserts that every character that exists on both copies has the same slot tags and slot.

Usage: python -I check_hands.py <host pid> <guest pid>
Exit 0 = PASS, 1 = FAIL.
"""
import sys, os, struct, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from peek import Proc
import bot

GAME = 0x6C3068
DPAD = (('RIGHT', 0x8), ('LEFT', 0x4), ('DOWN', 0x2), ('UP', 0x1))
SWITCH_MS = 300


def tag(v):
    if not v:
        return '-'
    b = struct.pack('<I', v)[::-1]
    if all(32 <= c < 127 for c in b):
        return b.decode('latin1')
    return '%08x' % v


def u32(m, a):
    try:
        return m.u32(a)
    except Exception:
        return 0


def world(m):
    go = u32(m, m.va(GAME))
    return u32(m, go + 0x378) if go else 0


def mode(m):
    go = u32(m, m.va(GAME))
    return u32(m, go + 0x310) if go else 0


def humans(m):
    w = world(m)
    mgr = u32(m, w + 0x175C) if w else 0
    if not mgr:
        return []
    n, arr = u32(m, mgr + 4) or 0, u32(m, mgr + 0xC)
    out = []
    for i in range(min(n, 8)):
        hp = u32(m, arr + 4 * i) if arr else 0
        if not hp:
            continue
        slots = []
        for s in range(4):
            wp = u32(m, hp + 0x704 + 4 * s)
            slots.append(tag(u32(m, wp + 0x10) if wp else 0))
        out.append(dict(ptr=hp, tag=tag(u32(m, hp + 0x14)), slots=slots, cur=u32(m, hp + 0x714)))
    return out


def own(m, pl):
    """The character this copy's own pad drives (host: pl 0, guest: pl 1)."""
    w = world(m)
    ctl = u32(m, w + 0x1748) if w else 0
    return u32(m, ctl + 4 + 0x764 * pl) if ctl else 0


def held(m, ptr):
    cur = u32(m, ptr + 0x714)
    slots = []
    for s in range(4):
        wp = u32(m, ptr + 0x704 + 4 * s)
        slots.append(tag(u32(m, wp + 0x10) if wp else 0))
    return cur, slots, (slots[cur] if isinstance(cur, int) and 0 <= cur < 4 else '?')


def records(m):
    go = u32(m, m.va(GAME))
    p = u32(m, go + 0x318) if go else 0
    out = []
    for i in range(8):
        base = p + 0x1B0C + i * 0x28
        t = u32(m, base)
        if not t:
            continue
        out.append((tag(t), [tag(u32(m, base + 0x14 + 4 * s)) for s in range(4)], u32(m, base + 0x24)))
    return out


def inv(m):
    w = world(m)
    i = u32(m, w + 0x1790) if w else 0
    return u32(m, i + 4) if i else None


def press_dpad(p, code):
    p.cmd('pad 0 %x' % code)
    time.sleep(0.08)
    p.cmd('pad 0 0')
    time.sleep(0.25)


def wait_for(fn, secs, step=0.02):
    t = time.time()
    while time.time() - t < secs:
        v = fn()
        if v:
            return True, time.time() - t
        time.sleep(step)
    return False, time.time() - t


def main():
    hp, gp = int(sys.argv[1]), int(sys.argv[2])
    mh, mg = Proc(hp), Proc(gp)
    ph, pg = bot.Pipe(hp), bot.Pipe(gp)
    t = time.time()
    while time.time() - t < 90 and not (world(mh) and mode(mh) == 1 and world(mg) and mode(mg) == 1):
        time.sleep(0.5)
    time.sleep(2)
    hh, hg = humans(mh), humans(mg)
    print('host humans: ', [(x['tag'], x['slots'], x['cur']) for x in hh])
    print('guest humans:', [(x['tag'], x['slots'], x['cur']) for x in hg])
    print('in hand: host', [(x['tag'], x['slots'][x['cur']] if x['cur'] < 4 else '?') for x in hh],
          'guest', [(x['tag'], x['slots'][x['cur']] if x['cur'] < 4 else '?') for x in hg])
    print('host records: ', records(mh))
    print('guest records:', records(mg))
    print('inventory: host', inv(mh), 'guest', inv(mg))

    sides = [
        dict(name='host owns BOY1', own_m=mh, own_pl=0, own_pipe=ph, puppet_m=mg),
        dict(name='guest owns GIR1', own_m=mg, own_pl=1, own_pipe=pg, puppet_m=mh),
    ]
    fails = []
    switches = 0
    for side in sides:
        owner = own(side['own_m'], side['own_pl'])
        if not owner:
            fails.append('%s: no own character' % side['name'])
            continue
        otag = tag(u32(side['own_m'], owner + 0x14))
        puppet = next((x['ptr'] for x in humans(side['puppet_m']) if x['tag'] == otag), 0)
        if not puppet:
            fails.append('%s: the partner copy has no character %s' % (side['name'], otag))
            continue
        print('\n%s: owner %s @%x, partner copy of it @%x' % (side['name'], otag, owner, puppet))
        for rnd in range(3):
            cur0, slots0, held0 = held(side['own_m'], owner)
            # a D-pad step that changes the slot on the owner's own copy
            new = None
            for _name, code in DPAD:
                press_dpad(side['own_pipe'], code)
                ok, secs = wait_for(lambda: u32(side['own_m'], owner + 0x714) != cur0, 1.0)
                if ok:
                    new = u32(side['own_m'], owner + 0x714)
                    break
            if new is None:
                fails.append('%s: no D-pad step switched the slot (was %r)' % (side['name'], cur0))
                break
            switches += 1
            want = held(side['own_m'], owner)[2]
            t0 = time.time()
            ok, secs = wait_for(
                lambda: u32(side['puppet_m'], puppet + 0x714) == new and held(side['puppet_m'], puppet)[2] == want,
                SWITCH_MS / 1000.0)
            print('  switch %d: owner slot %d -> %d (%s); partner %s after %.0f ms' % (
                rnd + 1, cur0, new, want, 'shows it' if ok else 'DOES NOT show it', secs * 1000))
            if not ok:
                got = held(side['puppet_m'], puppet)
                fails.append('%s switch %d: partner still %r (slot %r, %s) after %.0f ms' % (
                    side['name'], rnd + 1, got[2], got[0], got[1], secs * 1000))
            # 1 s of quiet: the partner's hand must not move on its own
            stable, changes = True, 0
            prev = held(side['puppet_m'], puppet)[2]
            tq = time.time()
            while time.time() - tq < 1.0:
                now_w = held(side['puppet_m'], puppet)[2]
                if now_w != prev:
                    changes += 1
                    prev = now_w
                own_now = held(side['own_m'], owner)[2]
                if own_now != want:
                    stable = False   # the OWNER moved: not a partner-only flip-flop
                time.sleep(0.02)
            print('  partner held %s for 1.0 s: %d change(s)' % (want, changes))
            if changes and changes > 0:
                fails.append('%s switch %d: the partner hand changed %d time(s) without its owner' % (
                    side['name'], rnd + 1, changes))
            if not stable:
                fails.append('%s switch %d: the owner hand moved during the quiet second' % (side['name'], rnd + 1))

    bad = []
    hh, hg = humans(mh), humans(mg)
    byg = {x['tag']: x for x in hg}
    checked = 0
    for x in hh:
        y = byg.get(x['tag'])
        if not y:
            continue
        checked += 1
        if x['slots'] != y['slots'] or x['cur'] != y['cur']:
            bad.append((x['tag'], x['slots'], x['cur'], y['slots'], y['cur']))
    print('\nfinally: host humans ', [(x['tag'], x['slots'], x['cur']) for x in hh])
    print('finally: guest humans', [(x['tag'], x['slots'], x['cur']) for x in hg])
    if checked == 0:
        fails.append('no character exists on both copies')
    if bad:
        fails.append('held weapons differ: %r' % (bad,))
    if not any(any(s != '-' for s in x['slots']) for x in hh):
        fails.append('host has no weapon in any hand either')
    print('hands: %d D-pad switches, %d character(s) compared' % (switches, checked))
    if fails:
        print('hands FAIL:')
        for f in fails:
            print('  - ' + f)
        return 1
    print('hands OK (each player\'s D-pad switch reached the partner within %d ms; no flip-flop)' % SWITCH_MS)
    return 0


sys.exit(main())
