"""Breakables on both copies (TASK 26): a CToeChair picked up with the action button, carried, swung and
broken, and the state reaching the other copy.

What it does on the level the runner loaded (the chair is a level prop, class tag CHAI):
  1. prints every chair's position and state (+0x24 enabled, +0xa4 broken, +0xc4 carrier, +0x118 drop);
  2. player 1 (the host's own character) is put next to the nearest usable chair, presses A (pick up) and
     A again (swing -> break): the carry and the break must appear on BOTH copies, and the drop item the
     break enabled must be the same entity on both;
  3. the same for player 2 (the guest's own character) on the guest copy, with the chair it owns;
  4. (removed in TASK 27) the paused-link apply-path phase: neither `netpause` nor a receive-only drop can
     make a copy miss the break while it stays able to play - see the note in main().

Read-only memory reads, the mod's own safe `tp` and normal
pad presses; `netpause` is the existing test-only link pause. Exit 0 = PASS or SKIP, 1 = FAIL.
Usage: python -I check_breakables.py <host pid> <guest pid>
"""
import sys, os, struct, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot
from peek import Proc

GAME = 0x6c3068
CHAI = 0x43484149
SLOT = os.environ.get('SAVE_SLOT', '?')


def u32(m, a):
    try:
        return m.u32(a)
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


def ents(m):
    w = world(m)
    mgr = u32(m, w + 0x1768) if w else 0
    out = []
    for head in ((u32(m, mgr + 8) if mgr else 0), (u32(m, mgr + 0x18) if mgr else 0)):
        node, seen = head, set()
        while node and node not in seen and len(out) < 800:
            seen.add(node)
            e, nxt = u32(m, node), u32(m, node + 4)
            if e:
                out.append(e)
            if nxt == node:
                break
            node = nxt
    return out


def ctl_human(m, pl):
    w = world(m)
    ctl = u32(m, w + 0x1748) if w else 0
    return u32(m, ctl + 4 + 0x764 * pl) if ctl else 0


def hpos(m, h):
    return (f32(m, h + 0x23c), f32(m, h + 0x240), f32(m, h + 0x244))


def epos(m, e):
    return (f32(m, e + 0x6c), f32(m, e + 0x70), f32(m, e + 0x74))


def level_of(m):
    w = world(m)
    return tag(u32(m, w + 4)) if w else '----'


def mode(m):
    g = game(m)
    return u32(m, g + 0x310) if g else 0


def chairs(m):
    return [e for e in ents(m) if u32(m, e + 0x10) == CHAI or 'CToeChair' in rtti(m, e)]


def d3(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def sane(p):
    return all(abs(v) < 100000.0 for v in p)


def chair_key(m, e):
    p = epos(m, e)
    return (round(p[0], 1), round(p[1], 1), round(p[2], 1))


def chair_of(m, key, tol=60.0):
    best, bd = 0, tol
    for e in chairs(m):
        d = d3(epos(m, e), key)
        if d <= bd:
            bd, best = d, e
    return best


def chair_index(m, e):
    """The chair's place in the copy's entity list. Both copies build that list from the same level file in
    the same order (every run's listing shows it), so the index is a stable name for a prop that moves -
    a chair in a character's hand is nowhere near where it was picked up."""
    for i, c in enumerate(chairs(m)):
        if c == e:
            return i
    return -1


def chair_same(m_own, e_own, m_oth):
    """The other copy's chair for this one: by list index when the two lists agree (same length and the same
    class tag at that index), else by position."""
    co = chairs(m_oth)
    i = chair_index(m_own, e_own)
    if 0 <= i < len(co) and u32(m_oth, co[i] + 0x10) == u32(m_own, e_own + 0x10):
        return co[i]
    return chair_of(m_oth, chair_key(m_own, e_own))


def inv_count(m):
    w = world(m)
    inv = u32(m, w + 0x1790) if w else 0
    return u32(m, inv + 4) if inv else 0


def describe(m, e):
    if not e:
        return '(none)'
    p = epos(m, e)
    drop = u32(m, e + 0x118)
    return ('@%x tag %s (%.2f,%.2f,%.2f) enabled %d broken %d carrier %x drop %s' % (
        e, tag(u32(m, e + 0x10)), p[0], p[1], p[2], u32(m, e + 0x24), u32(m, e + 0xa4), u32(m, e + 0xc4),
        ('%s id %s live %d' % (tag(u32(m, drop + 0x10)), tag(u32(m, drop + 4)), 1 - u32(m, drop + 0xa8))) if drop else 'none'))


def carry_of(m, pl):
    h = ctl_human(m, pl)
    return u32(m, h + 0x2bc) if h else 0


def wait_for(fn, secs, step=0.1):
    t = time.time()
    while time.time() - t < secs:
        if fn():
            return True, time.time() - t
        time.sleep(step)
    return False, time.time() - t


def tp_near(pipe, m, pl, target):
    """Put player `pl` next to `target` (x, y, z), facing it, through the mod's safe tp (it waits for the
    game's own floor settle and restores the old position when there is none). Returns (ok, how).
    A raw write is not used: the guest's own player 2 is re-snapped from the host's stream, so `tpraw`
    reports `ok` for a position the game undoes a frame later, and the check then stood next to nothing."""
    hp = hpos(m, ctl_human(m, pl))
    tried = 0
    for radius in (55.0, 45.0, 65.0, 75.0, 40.0, 95.0):
        for ang in ((0, 45, 90, 135, 180, 225, 270, 315) if radius == 55.0 else (0, 90, 180, 270)):
            dx, dy = hp[0] - target[0], hp[1] - target[1]
            dd = (dx * dx + dy * dy) ** 0.5 or 1.0
            base = (dx / dd, dy / dd)
            ca, sa = __import__('math').cos(__import__('math').radians(ang)), __import__('math').sin(__import__('math').radians(ang))
            ux, uy = base[0] * ca - base[1] * sa, base[0] * sa + base[1] * ca
            stand = (target[0] + ux * radius, target[1] + uy * radius, target[2])
            r = pipe.cmd('tp %d %.3f %.3f %.3f %.3f %.3f' % (pl, stand[0], stand[1], stand[2],
                                                             target[0] - stand[0], target[1] - stand[1]))
            tried += 1
            if r.startswith('ok'):
                return True, 'safe tp at %.0f units (%s)' % (radius, r)
    return False, 'safe tp refused every spot (%d tried)' % tried


def press_a(pipe, user, hold=0.2):
    bot.press(pipe, user, 'A', hold)


def frames(pipe):
    """The game ticks this copy has run (the `frames` counter at the end of `sync`). A copy whose game
    thread stopped (a hang in the game's own update) stops counting while its network thread and the pipe
    keep answering, so this is the only way a memory-reading check can tell the two apart."""
    s = pipe.cmd('sync')
    i = s.find('| frames ')
    return s[i + 9:].strip() if i >= 0 else '?'


def usable(m):
    # a chair in a character's hand is not a target: it moves with the character and its copy on the other
    # side can be anywhere (TASK 27 run: a carried chair drifted 119 units away from its own pickup point)
    return [e for e in chairs(m) if u32(m, e + 0x24) and not u32(m, e + 0xa4) and not u32(m, e + 0xc4)
            and sane(epos(m, e))]


def main():
    hp, gp = int(sys.argv[1]), int(sys.argv[2])
    mh, mg = Proc(hp), Proc(gp)
    ph, pg = bot.Pipe(hp), bot.Pipe(gp)
    t = time.time()
    while time.time() - t < 90 and not (world(mh) and mode(mh) == 1 and world(mg) and mode(mg) == 1):
        time.sleep(0.5)
    time.sleep(2)
    lv_h, lv_g = level_of(mh), level_of(mg)
    print('breakables: level host %s guest %s (save slot %s)' % (lv_h, lv_g, SLOT))
    ch = chairs(mh)
    print('breakables: %d chair(s) on the host copy, %d on the guest copy' % (len(ch), len(chairs(mg))))
    for e in ch:
        print('  host  chair %s' % describe(mh, e))
    for e in chairs(mg):
        print('  guest chair %s' % describe(mg, e))
    if not ch:
        print('breakables: SKIP - this level has no CToeChair (the save has no breakable prop here)')
        return 0
    if not usable(mh):
        print('breakables: SKIP - every chair in this level is already broken (enabled 0, broken 1); '
              'the save slot recorded them destroyed. Load a slot with a usable chair (SAVE_SLOT=3, J002).')
        return 0
    print('breakables: player 1 on the host carries chair %s, player 2 on the guest carries another'
          % describe(mh, min(usable(mh), key=lambda e: d3(epos(mh, e), hpos(mh, ctl_human(mh, 0))))))
    fails = []
    used = set()

    def one_player(owner, other, m_own, m_oth, pipe_own, pl, label):
        """pl 0 = player 1 (host copy), pl 1 = player 2 (guest copy)."""
        me = ctl_human(m_own, pl)
        mine = [e for e in usable(m_own) if chair_index(m_own, e) not in used]
        if not mine:
            print('breakables: no chair left for %s (SKIP)' % label)
            return
        e = 0
        ok, how = False, ''
        for cand in sorted(mine, key=lambda x: d3(epos(m_own, x), hpos(m_own, me)))[:4]:
            ok, how = tp_near(pipe_own, m_own, pl, epos(m_own, cand))
            print('breakables: tp %s -> chair #%d: %s' % (label, chair_index(m_own, cand), how))
            if ok:
                e = cand
                break
        if not e:
            fails.append('%s: no chair could be approached' % label)
            return
        used.add(chair_index(m_own, e))
        print('\nbreakables: %s -> chair #%d %s' % (label, chair_index(m_own, e), describe(m_own, e)))
        time.sleep(0.6)

        def other_chair():
            return chair_same(m_own, e, m_oth)

        eo = other_chair()
        if not eo:
            print('breakables: the other copy has no chair for #%d %s (FAIL)' % (chair_index(m_own, e), chair_key(m_own, e)))
            fails.append('%s: the other copy has no chair for #%d' % (label, chair_index(m_own, e)))
            return
        print('  before: own %s | other %s' % (describe(m_own, e), describe(m_oth, eo)))
        # --- pick up
        got = False
        for i in range(3):
            press_a(pipe_own, 0)
            okc, secs = wait_for(lambda: carry_of(m_own, pl) != 0, 1.2)
            if okc:
                got = True
                break
        if not got:
            # the safe tp can settle the character further from the chair than the interaction reaches:
            # place it again (it may settle closer this time) and press once more
            ok, how = tp_near(pipe_own, m_own, pl, epos(m_own, e))
            print('  no pickup after 3 presses; placed again: %s' % how)
            time.sleep(0.4)
            for i in range(2):
                press_a(pipe_own, 0)
                okc, secs = wait_for(lambda: carry_of(m_own, pl) != 0, 1.5)
                if okc:
                    got = True
                    break
        if not got:
            print('  the action button did not pick the chair up (own carry %x)' % carry_of(m_own, pl))
            fails.append('%s: pickup did not happen' % label)
            return
        print('  picked up after %.2f s: own %s' % (secs, describe(m_own, e)))
        okc, secs2 = wait_for(lambda: u32(m_oth, (other_chair() or 0) + 0xc4) != 0, 2.5)
        eo = other_chair() or eo
        print('  carry on the other copy: %s (waited %.2f s) -> %s' %
              ('yes' if okc else 'NO', secs2, describe(m_oth, eo)))
        if not okc:
            fails.append('%s: the other copy does not show the carried chair' % label)
        # --- swing -> break
        broke = False
        for i in range(4):
            press_a(pipe_own, 0)
            okb, secs3 = wait_for(lambda: u32(m_own, e + 0xa4) != 0, 1.5)
            if okb:
                broke = True
                break
        if not broke:
            print('  the swing did not break the chair (broken %d, carry %x)' % (u32(m_own, e + 0xa4), carry_of(m_own, pl)))
            fails.append('%s: no break' % label)
            return
        print('  broken after %.2f s: own %s' % (secs3, describe(m_own, e)))
        okb, secs4 = wait_for(lambda: u32(m_oth, (other_chair() or 0) + 0xa4) != 0, 3.0)
        eo = other_chair() or eo
        print('  break on the other copy: %s (waited %.2f s) -> %s' % ('yes' if okb else 'NO', secs4, describe(m_oth, eo)))
        if not okb:
            fails.append('%s: the other copy does not show the broken chair' % label)
        # --- the drop item
        dh, dg = u32(m_own, e + 0x118), u32(m_oth, eo + 0x118)
        if dh or dg:
            same = dh and dg and u32(m_own, dh + 0x10) == u32(m_oth, dg + 0x10) and u32(m_own, dh + 4) == u32(m_oth, dg + 4)
            print('  drop item: own %s id %s at (%.2f,%.2f,%.2f) | other %s id %s at (%.2f,%.2f,%.2f)' % (
                tag(u32(m_own, dh + 0x10)) if dh else '-', tag(u32(m_own, dh + 4)) if dh else '-',
                f32(m_own, dh + 0x6c), f32(m_own, dh + 0x70), f32(m_own, dh + 0x74),
                tag(u32(m_oth, dg + 0x10)) if dg else '-', tag(u32(m_oth, dg + 4)) if dg else '-',
                f32(m_oth, dg + 0x6c), f32(m_oth, dg + 0x70), f32(m_oth, dg + 0x74)))
            if not same:
                fails.append('%s: the drop item differs between the copies' % label)
        else:
            print('  drop item: none (this chair has no itemType attribute)')

    # The TASK 26 "apply path" phase (break a chair while the peer cannot hear) is NOT run any more: every
    # way of making the peer miss the packets also takes its game out of play. `netpause` (both copies)
    # stops the paused copy's own pad from reaching its game at all (net_tick feeds the input ring and
    # returns at its first line), and a receive-only drop (`netdroprx`) makes the game see its partner's
    # controller vanish, which ends its prop sync and its pad handling for the rest of the session
    # (TASK 27 runs 2 and 3). What is left to test - a break by either player reaching the other copy - is
    # what the two phases below do, and the resend path is exercised by every break whose announcement this
    # copy did not simulate itself.
    one_player(None, None, mh, mg, ph, 0, 'player 1 (host)')
    one_player(None, None, mg, mh, pg, 1, 'player 2 (guest)')

    print('\nbreakables: inventory host %d guest %d' % (inv_count(mh), inv_count(mg)))
    print('breakables: game ticks (frames) host %s guest %s' % (frames(ph), frames(pg)))
    print('breakables: sync host  %s' % ph.cmd('sync'))
    print('breakables: sync guest %s' % pg.cmd('sync'))
    if fails:
        print('breakables FAIL:')
        for f in fails:
            print('  - ' + f)
        print('breakables: props host  %s' % ph.cmd('props'))
        print('breakables: props guest %s' % pg.cmd('props'))
        return 1
    print('breakables OK (chairs picked up, swung and broken on both copies; %d chair(s) checked)' % len(used))
    return 0


sys.exit(main())
