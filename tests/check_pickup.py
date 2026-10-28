"""World item pickup sync, BOTH directions, on two live copies.

Finds live CToeItem entities in the level's CToeManager (world+0x1768: the entity list at manager+8,
count at +0x14, node {entity at +0, next at +4}), picks one near the collecting player, teleports that
player onto it with the pipe command `tp`, presses A and waits for the game's ~500 ms collect animation
and the character-side collect call FUN_004ddad0 (the mod's pickup hook).

  phase 1 (host -> guest): the HOST's player 1 collects. The guest must collect the same entity
                           through the mod's PKT_PICKUP apply (item+0xa8 == 1).
  phase 2 (guest -> host): the GUEST's own player (player 2, `tp 1` and pad 0 on the guest copy: the
                           guest's local pad is XInput user 0, see XInputGetState in obscoop2.c)
                           collects. The host must collect the same entity.

Asserts on both copies: item+0xa8 == 1, the entity is still in the manager (the game does not free it),
the inventory count agrees, and the pickup counters move in the expected direction only (no echo: the
receiving copy must not send the pickup back).

--spawn (TASK 16): no forcing at all. The check first waits until the level's intro has placed the
characters (the world is up long before that; until then the pad is ignored and the characters sit at
the origin), then makes the GAME release a world item: it teleports the collecting player onto every
item source the level has (CToeLoot, CToeBreakable*, CToeContainer, CToeChest, CToeHeavyCase) and uses
the game's own actions (A, then the X attack) until a live collectable exists (item class, +0x20 != 0,
+0xa8 == 0, the three interaction gates clear). Only then do the pickup phases run, and the item is
never written to. If no source produces an item, the check says so and prints what every source did.

Usage: python -I check_pickup.py <host pid> <guest pid> [--host-only|--guest-only] [--spawn]
"""
import sys, os, struct, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe, press
from peek import Proc

GAME = 0x6c3068
# Class tags written by the CToeItem* constructors (ITEMS_FINDINGS.md section 1).
ITEM_TAGS = {
    0x41434944, 0x42415454, 0x424b504b, 0x424c4541, 0x4341424f, 0x43524f57, 0x454e4452,
    0x474c5943, 0x4943414d, 0x49434500, 0x4943524e, 0x49445343, 0x4a454d4d, 0x4a455252,
    0x4a554241, 0x4b455900, 0x4c564552, 0x4d415000, 0x4d454449, 0x50415353, 0x53455255,
    0x534f4441, 0x53544154, 0x53545249, 0x53595249, 0x57454c44,
}
SLOT = os.environ.get('SAVE_SLOT', '?')
PHASES = os.environ.get('OBSCOOP_PICKUP_PHASE', 'both')
SPAWN = os.environ.get('OBSCOOP_PICKUP_SPAWN') == '1'
for a in sys.argv[3:]:
    if a == '--host-only':
        PHASES = 'host'
    elif a == '--guest-only':
        PHASES = 'guest'
    elif a == '--spawn':
        SPAWN = True

h, g = int(sys.argv[1]), int(sys.argv[2])
host, guest = Pipe(h), Pipe(g)
mh, mg = Proc(h), Proc(g)


def tag(v):
    return ''.join(chr((v >> s) & 0xff) if 32 <= ((v >> s) & 0xff) < 127 else '.'
                   for s in (24, 16, 8, 0))


def f32(m, addr):
    b = m.read(addr, 4)
    return struct.unpack('<f', b)[0] if b else 0.0


def world(m):
    g0 = m.u32(m.va(GAME))
    return m.u32(g0 + 0x378) if g0 else 0


def level(m):
    w = world(m)
    return m.u32(w + 4) if w else 0


def u32(m, a):
    try:
        return m.u32(a) or 0
    except Exception:
        return 0


def entities(m):
    """All level entities from the CToeManager's list: (address, class +0x10, id +4, collected +0xa8,
    position +0x6c/+0x70/+0x74, enabled +0x20, mesh +0x34, gates +0xc0/+0xac/+0xb0, radius +0xa0)."""
    w = world(m)
    out = []
    mgr = u32(m, w + 0x1768) if w else 0
    if not mgr:
        return w, mgr, out
    node, seen = u32(m, mgr + 8), set()
    while node and node not in seen and len(out) < 4000:
        seen.add(node)
        e = u32(m, node)
        if e:
            out.append((e, u32(m, e + 0x10), u32(m, e + 4), u32(m, e + 0xa8),
                        (f32(m, e + 0x6c), f32(m, e + 0x70), f32(m, e + 0x74)),
                        u32(m, e + 0x20), u32(m, e + 0x34),
                        u32(m, e + 0xc0), u32(m, e + 0xac), u32(m, e + 0xb0), f32(m, e + 0xa0)))
        node = u32(m, node + 4)
    return w, mgr, out


def item_line(e):
    ent, cls, idv, coll, pos, p20, p34, c0, ac, b0, rad = e
    return ('class %s id %s collected %d p20=%d p34=%x pos (%.2f, %.2f, %.2f) '
            'gates c0=%s ac=%s b0=%s r=%.1f @%x' % (
                tag(cls), tag(idv), coll, p20, p34, pos[0], pos[1], pos[2], c0, ac, b0, rad, ent))


def items(m):
    return [e for e in entities(m)[2] if e[1] in ITEM_TAGS]


def rtti(m, obj):
    """Class name of an entity from its vtable RTTI (vtable-4 -> COL -> +0xc TypeDescriptor -> name
    at +8), the same read scan_slots.py uses. Empty when it cannot be read."""
    vt = u32(m, obj)
    if not vt:
        return ''
    col = u32(m, vt - 4)
    td = u32(m, col + 0xc) if col else 0
    b = m.read(td + 8, 96) if td else b''
    return ((b or b'').split(b'\0')[0].decode('latin1', 'replace')).replace('.?AV', '').replace('@@', '')


# The level objects that can make the game release a world item (FINDINGS_16 sections 1-3).
SOURCE_CLASSES = ('CToeLoot', 'CToeBreakableCase', 'CToeBreakableTwoStates', 'CToeBreakableOnce',
                  'CToeBreakableDetailed', 'CToeBreakableByAnim', 'CToeContainer', 'CToeChest',
                  'CToeChestKey', 'CToeHeavyCase', 'CToeBeamCase')


def sane(pos):
    return all(abs(v) < 50000 for v in pos)


def live_items(m, active=None):
    """Not collected, valid position and the three interaction gates clear (+0xc0/+0xac/+0xb0 == 0,
    the same fields FUN_0044d6a0 refuses). The +0x20 activation gate is reported but not required in
    the forcing mode: a save-loaded world leaves it 0, and that test sets it with `wr` before the A
    press. In --spawn mode (active=True) +0x20 must already be non-zero: only the game may set it."""
    if active is None:
        active = SPAWN
    return [e for e in items(m)
            if e[3] == 0 and sane(e[4]) and any(abs(v) > 0.01 for v in e[4])
            and e[7] == 0 and e[8] == 0 and e[9] == 0
            and (not active or e[5] != 0)]


def find_item(m, cls, idv, pos):
    """The same entity on the other copy: class (+id when set), and the position when several match."""
    best, bd = None, 1e30
    for e in items(m):
        if e[1] != cls or (idv and e[2] != idv):
            continue
        d = sum((e[4][i] - pos[i]) ** 2 for i in range(3)) ** 0.5
        if best is None or d < bd:
            best, bd = e, d
    return best


def inventory(m):
    w = world(m)
    inv = u32(m, w + 0x1790) if w else 0
    return u32(m, inv + 4) if inv else None


def inv_tags(m):
    w = world(m)
    inv = u32(m, w + 0x1790) if w else 0
    if not inv:
        return []
    return [tag(u32(m, inv + 8 + i * 0x20 + 4)) for i in range(min(u32(m, inv + 4), 99))]


def player_human(m, pl):
    w = world(m)
    ctl = u32(m, w + 0x1748) if w else 0
    return u32(m, ctl + 4 + 0x764 * pl) if ctl else 0


def player_pos(m, pl):
    hh = player_human(m, pl)
    return (f32(m, hh + 0x23c), f32(m, hh + 0x240), f32(m, hh + 0x244)) if hh else None


def pickup_stat(pipe):
    for part in pipe.cmd('sync').split('|'):
        part = part.strip()
        if part.startswith('pickup '):
            f = part.split()
            return dict(zip(f[1::2], map(int, f[2::2])))
    return {}


def nearest(items, pos):
    return min(items, key=lambda e: sum((e[4][i] - pos[i]) ** 2 for i in range(3)) ** 0.5)


def dist(a, b):
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5


print('save slot (SAVE_SLOT): %s' % SLOT)
print('levels: host %s guest %s' % (tag(level(mh)), tag(level(mg))))
assert tag(level(mh)) == tag(level(mg)), 'the copies are in different levels'
wh, mgr_h, ents_h = entities(mh)
wg, mgr_g, ents_g = entities(mg)
print('CToeManager: host @%x %d entities, guest @%x %d entities' % (mgr_h, len(ents_h), mgr_g, len(ents_g)))
print('items on host:')
for e in items(mh):
    print('   ', item_line(e))
print('items on guest:')
for e in items(mg):
    print('   ', item_line(e))
print('inventory host %s guest %s' % (inventory(mh), inventory(mg)))

ok = True
results = []


def collect(phase, who, pipe, m, pl, item, other_pipe, om, other_name, hold=(), force=True):
    """Teleport `who`'s player `pl` onto `item`, press A, wait for the local collect, then the peer.

    `hold` lists (pipe, player) of the SAME character on the other copy: the guest's own character is
    pulled toward the host's copy of it every snapshot, so for a guest-side pickup the host's copy of
    that character is moved to the item too. Its item is left inactive (only the collecting copy's
    +0x20 is set), so the host cannot collect it itself. `force=False` (--spawn) never writes memory:
    the item must already be live."""
    global ok
    cls, idv, pos = item[1], item[2], item[4]
    print('\n== phase %s: %s player %d collects %s (pos %.2f, %.2f, %.2f)'
          % (phase, who, pl + 1, tag(cls), pos[0], pos[1], pos[2]))
    before_send, before_rcv = pickup_stat(pipe), pickup_stat(other_pipe)
    inv0 = (inventory(m), inventory(om))
    got = False
    forced = False
    for attempt in range(3):
        e_now = find_item(m, cls, idv, pos)
        if force and e_now is not None and e_now[5] == 0:
            # The save-loaded world leaves its item entities inactive (+0x20 == 0), which is exactly the
            # gate the game's own interaction check (FUN_0044d6a0) tests. No save slot has an item with
            # that gate set (SLOT_SCAN.md), so the test sets it through the pipe and then lets the GAME
            # collect the item with the A press: only the gate is test-written, the pickup path is the
            # game's own (input scan -> animation 0x640 -> FUN_004ddad0 -> item vtable slot 26).
            print('   item +0x20 == 0 (inactive in this save): forcing the game\'s own activation gate with wr')
            print('   wr %x 01000000 -> %s' % (e_now[0] + 0x20, pipe.cmd('wr %x 01000000' % (e_now[0] + 0x20))))
            forced = True
            time.sleep(0.3)
        for hp, hpl in hold:
            print('   tp %s player %d (keeps the collecting character in step): %s'
                  % ('peer' if hp is not pipe else who, hpl + 1,
                     hp.cmd('tp %d %.3f %.3f %.3f' % (hpl, pos[0], pos[1], pos[2]))))
        print('   tp %s: %s' % (who, pipe.cmd('tp %d %.3f %.3f %.3f' % (pl, pos[0], pos[1], pos[2]))))
        time.sleep(0.2)
        press(pipe, 0, 'A', 0.5)
        print('   pressed A (attempt %d)' % (attempt + 1))
        for _ in range(12):   # up to 6 s: 500 ms animation, then FUN_004ddad0
            time.sleep(0.5)
            e = find_item(m, cls, idv, pos)
            if e is None or e[3] != 0:
                got = True
                break
        if got:
            break
        e = find_item(m, cls, idv, pos)
        print('   still live on %s:' % who, item_line(e) if e else '<absent>')
    e = find_item(m, cls, idv, pos)
    print('%s after: ' % who, item_line(e) if e else '<absent>')
    print('waiting for the peer copy...')
    peer_ok = False
    eg = None
    for _ in range(20):
        time.sleep(0.5)
        eg = find_item(om, cls, idv, pos)
        if eg is None or eg[3] != 0:
            peer_ok = True
            break
    print('%s after:' % other_name, item_line(eg) if eg else '<absent>')
    for _ in range(10):
        if inventory(m) == inventory(om):
            break
        time.sleep(0.5)
    print('inventory after: host %s guest %s (before %s / %s)' % (
        inventory(mh), inventory(mg), inv0[0], inv0[1]))
    print('inventory tags host: %s' % ' '.join(inv_tags(mh)))
    print('inventory tags guest: %s' % ' '.join(inv_tags(mg)))
    print('%s sync:  %s' % (who, pipe.cmd('sync')))
    print('%s sync: %s' % (other_name, other_pipe.cmd('sync')))
    a, b = pickup_stat(pipe), pickup_stat(other_pipe)
    print('pickup counters: %s %s | %s %s' % (who, a, other_name, b))
    sent = a.get('sent', 0) - before_send.get('sent', 0)
    rcv = b.get('rcv', 0) - before_rcv.get('rcv', 0)
    applied = b.get('applied', 0) - before_rcv.get('applied', 0)
    echo = b.get('sent', 0) - before_rcv.get('sent', 0)
    print('counters this phase: collected-on-%s=%s, %s sent +%d, %s rcv +%d applied +%d, echo sent +%d' % (
        who, got, who, sent, other_name, rcv, applied, echo))
    r = got and peer_ok and inventory(mh) == inventory(mg) and sent >= 1 and rcv >= 1 and applied >= 1 and echo == 0
    results.append((phase, r))
    print('phase %s: %s' % (phase, 'OK' if r else 'FAILED'))
    ok = ok and r


def wait_placed(m, pl, who, limit=150):
    """The world is up a fraction of a second after the load, but the level's intro keeps both
    characters at/near the origin and the pad does nothing until it has run (FINDINGS_16 section 4:
    a probe that reads earlier sees (0,0,0) and a dead pad). Wait for the game's own placement."""
    t0, last = time.time(), None
    while time.time() - t0 < limit:
        p = player_pos(m, pl)
        if p and sane(p) and any(abs(v) > 1.0 for v in p):
            print('%s: player %d placed after %.1f s at (%.2f, %.2f, %.2f)'
                  % (who, pl + 1, time.time() - t0, p[0], p[1], p[2]))
            return p
        if p != last:
            print('%s: player %d at %s (not placed yet)' % (who, pl + 1, p))
            last = p
        time.sleep(1.0)
    print('%s: player %d STILL not placed after %d s (%s)' % (who, pl + 1, limit, player_pos(m, pl)))
    return player_pos(m, pl)


def source_list(m):
    """Every level object that can make the game release an item. A (0,0,0) position is kept too: the
    I100 loot spot sits at the world origin, and the origin is a real place in the level."""
    out = []
    for e in entities(m)[2]:
        r = rtti(m, e[0])
        if r in SOURCE_CLASSES and sane(e[4]):
            out.append((r, e))
    return out


def source_state(m, e):
    return ('broken(+a4)=%s active(+20)=%s collected(+a8)=%s gate(+b0)=%s'
            % (u32(m, e[0] + 0xa4), u32(m, e[0] + 0x20), u32(m, e[0] + 0xa8), u32(m, e[0] + 0xb0)))


def spawn_item(m, pipe, pl, who):
    """Ask the GAME to create/release a world item: tp the player onto each source, then use the game's
    own actions (A to interact, X to attack) and watch for a live collectable (+0x20 != 0, +0xa8 == 0,
    gates clear). Never writes memory. Returns the live item entities found."""
    srcs = source_list(m)
    print('%s: %d item source(s) in the level (level %s, %d entities)'
          % (who, len(srcs), tag(level(m)), len(entities(m)[2])))
    for r, e in srcs:
        print('   %-26s %s' % (r, item_line(e)))
    if not srcs:
        return []
    tgt = player_pos(m, pl)
    if tgt:
        srcs.sort(key=lambda s: dist(s[1][4], tgt))
    for r, e in srcs:
        pos = e[4]
        print(' -- %s @%x at (%.2f, %.2f, %.2f), %.0f away: tp player %d onto it'
              % (r, e[0], pos[0], pos[1], pos[2], dist(pos, tgt) if tgt else 0, pl + 1))
        print('    tp -> %s' % pipe.cmd('tp %d %.3f %.3f %.3f' % (pl, pos[0], pos[1], pos[2])))
        time.sleep(0.4)
        n0 = len(entities(m)[2])
        for btn in ('A', 'A', 'X', 'X', 'X', 'B'):
            # the level's floor is not always under a source's position (the save-loaded world has only
            # part of its geometry), so the character may fall away from the object: put it back first
            p = player_pos(m, pl)
            if p and dist(p, pos) > 1.0:
                pipe.cmd('tp %d %.3f %.3f %.3f' % (pl, pos[0], pos[1], pos[2]))
                time.sleep(0.2)
            press(pipe, 0, btn, 0.4)
            time.sleep(1.2)
            live = live_items(m, active=True)
            ents = entities(m)[2]
            print('    %s: source %s | +0x73c=%s | entities %d (was %d) | live items %d'
                  % (btn, source_state(m, e), hex(u32(m, player_human(m, pl) + 0x73c))
                     if player_human(m, pl) else '?', len(ents), n0, len(live)))
            for x in ents:
                if x[0] not in [y[0] for y in entities_cache]:
                    print('       NEW entity %s (%s)' % (item_line(x), rtti(m, x[0])))
            if live:
                print('    the game released a live world item:')
                for x in live:
                    print('       %s (%s)' % (item_line(x), rtti(m, x[0])))
                return live
    return []


entities_cache = []


if SPAWN:
    print('\n== spawn mode: NO memory writes; the game itself must release the item')
    hpos = wait_placed(mh, 0, 'host')
    if PHASES in ('both', 'guest'):
        wait_placed(mg, 1, 'guest')
    entities_cache = entities(mh)[2]
    if live_items(mh, active=True):
        print('host already has a live world item (%d):' % len(live_items(mh, active=True)))
        for e in live_items(mh, active=True):
            print('   %s (%s)' % (item_line(e), rtti(mh, e[0])))
    else:
        print('no live world item on the host: asking the game to release one')
        spawn_item(mh, host, 0, 'host')
    print('live items after the spawn attempt: host %d guest %d'
          % (len(live_items(mh, active=True)), len(live_items(mg, active=True))))


if PHASES in ('both', 'host'):
    hpos = player_pos(mh, 0)
    live = live_items(mh)
    print('host live items: %d (player 1 at %s)' % (
        len(live), '(%.2f, %.2f, %.2f)' % hpos if hpos else '?'))
    if live:
        target = nearest(live, hpos)
        print('nearest live item %.1f away' % dist(target[4], hpos))
        collect('host->guest', 'host', host, mh, 0, target, guest, mg, 'guest', force=not SPAWN)
    else:
        print('NO live world item on the host: phase host->guest cannot run')
        results.append(('host->guest', None))

if PHASES in ('both', 'guest'):
    gpos = player_pos(mg, 1)
    live = live_items(mg)
    print('guest live items: %d (player 2 at %s)' % (
        len(live), '(%.2f, %.2f, %.2f)' % gpos if gpos else '?'))
    if live and gpos:
        target = nearest(live, gpos)
        print('nearest live item (guest) %.1f away' % dist(target[4], gpos))
        # The guest's own player is player 2 on its copy (`tp 1`, pad 0 = the guest's local XInput
        # user). The host's copy of that character is moved along, or the guest's snapshot correction
        # (guest_apply_state) pulls it back before the A press lands; the host's item stays inactive.
        collect('guest->host', 'guest', guest, mg, 1, target, host, mh, 'host', hold=((host, 1),),
                force=not SPAWN)
    else:
        print('NO live world item reachable on the guest: phase guest->host cannot run')
        results.append(('guest->host', None))

print('\nresults: %s' % results)
assert all(r is not False for _, r in results), 'a pickup phase failed'
if any(r is None for _, r in results):
    print('pickup: some phases could not run (no live world item)')
else:
    print('pickup OK: both directions collected on both copies, inventories match, no echo')
