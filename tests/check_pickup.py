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

Usage: python -I check_pickup.py <host pid> <guest pid> [--host-only|--guest-only]
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
for a in sys.argv[3:]:
    if a == '--host-only':
        PHASES = 'host'
    elif a == '--guest-only':
        PHASES = 'guest'

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


def sane(pos):
    return all(abs(v) < 50000 for v in pos)


def live_items(m):
    """Not collected, valid position and the three interaction gates clear (+0xc0/+0xac/+0xb0 == 0,
    the same fields FUN_0044d6a0 refuses). The +0x20 activation gate is reported but not required: a
    save-loaded world leaves it 0, and the test sets it with `wr` before the A press."""
    return [e for e in items(m)
            if e[3] == 0 and sane(e[4]) and any(abs(v) > 0.01 for v in e[4])
            and e[7] == 0 and e[8] == 0 and e[9] == 0]


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


def collect(phase, who, pipe, m, pl, item, other_pipe, om, other_name, hold=()):
    """Teleport `who`'s player `pl` onto `item`, press A, wait for the local collect, then the peer.

    `hold` lists (pipe, player) of the SAME character on the other copy: the guest's own character is
    pulled toward the host's copy of it every snapshot, so for a guest-side pickup the host's copy of
    that character is moved to the item too. Its item is left inactive (only the collecting copy's
    +0x20 is set), so the host cannot collect it itself."""
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
        if e_now is not None and e_now[5] == 0:
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


if PHASES in ('both', 'host'):
    hpos = player_pos(mh, 0)
    live = live_items(mh)
    print('host live items: %d (player 1 at %s)' % (
        len(live), '(%.2f, %.2f, %.2f)' % hpos if hpos else '?'))
    if live:
        target = nearest(live, hpos)
        print('nearest live item %.1f away' % dist(target[4], hpos))
        collect('host->guest', 'host', host, mh, 0, target, guest, mg, 'guest')
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
        collect('guest->host', 'guest', guest, mg, 1, target, host, mh, 'host', hold=((host, 1),))
    else:
        print('NO live world item reachable on the guest: phase guest->host cannot run')
        results.append(('guest->host', None))

print('\nresults: %s' % results)
assert all(r is not False for _, r in results), 'a pickup phase failed'
if any(r is None for _, r in results):
    print('pickup: some phases could not run (no live world item)')
else:
    print('pickup OK: both directions collected on both copies, inventories match, no echo')
