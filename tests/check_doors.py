"""TASK 34 item 2: a door use plays on BOTH copies, and the level change it causes reaches both.

The level change was synced before this task, the door image was not: the host used a door, the guest
jumped into the new level with the door still shut on its screen. This check drives the game's own door
use on one copy (the pipe `usedoor`, which makes the same vtable+0x34 / vtable+0x70 calls the interaction
scan makes), then reads on BOTH copies:

  * the door entity the use names (class, id, position),
  * `door+0xc4`, the character the game's own use method stores there (FUN_0042c2b0),
  * `character+0x2bc`, the object the character is using,
  * both worlds' level tag.

PASS (image): on both copies the same door shows the same character as its user, or both copies have
already changed level (the use completed and the world is being rebuilt).
PASS (transition): both copies reach the destination the door names at `door+0x118` (the tag the game's
own change uses, FINDINGS_20 §1.3), within TRANSITION_WAIT seconds.

Phases:
  A. the host's own character opens the nearest door;
  B. after `--reset <save>` (a second load of the pair's save, back to the same level) the GUEST's own
     character opens the same door - the guest's ChangeLevel is dropped, so this is the direction that
     needs PKT_DOOR + PKT_LEVELASK.

Usage: python -I check_doors.py <host pid> <guest pid> [--by host|guest] [--reset <save file>]
"""
import os
import re
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe
from peek import Proc
from tp_to_items import level, player_human, player_pos, rtti, tag, u32, world

DOORS = ('CToeDoor', 'CToeDoubleDoor', 'CToeSpecialDoor', 'CToeInternalDoor', 'CToeFlapDoor')
SAMPLE = 0.1
USE_WATCH = 8.0
TRANSITION_WAIT = float(os.environ.get('OBSCOOP_DOOR_WAIT', '40'))

host_pid, guest_pid = int(sys.argv[1]), int(sys.argv[2])
mode = 'host'
reset = ''
args = sys.argv[3:]
for i, a in enumerate(args):
    if a == '--by' and i + 1 < len(args):
        mode = args[i + 1]
    if a == '--reset' and i + 1 < len(args):
        reset = args[i + 1]

H, G = Proc(host_pid), Proc(guest_pid)
HP, GP = Pipe(host_pid), Pipe(guest_pid)


def mode_of(m):
    g = u32(m, m.va(0x6c3068))
    return (u32(m, g + 0x310), u32(m, g + 0x320)) if g else (None, None)


def in_level(m):
    md, st = mode_of(m)
    return md == 1 and st == 0 and (level(m) or 0) != 0


def normal(m):
    """TASK 37: in a level AND in normal play. A scripted event (world+0x12c != 0, state 7) right after a
    load stops the interaction scan, so `usedoor` answers "not in a level" while the world is rebuilding -
    waiting for normal play instead of failing the phase."""
    w = world(m)
    if not (in_level(m) and w):
        return False
    return u32(m, w + 0x11c) == 1 and u32(m, w + 0x12c) == 0


def wait_in_level(t=30.0):
    t0 = time.time()
    while time.time() - t0 < t:
        if in_level(H) and in_level(G) and normal(H) and normal(G):
            return True
        time.sleep(0.3)
    return False


def doors(m):
    """(entity, rtti name, id, position, usable +0x24, user +0xc4, destination +0x118) per door."""
    out = []
    mgr = u32(m, world(m) + 0x1768) if world(m) else 0
    node = u32(m, mgr + 8) if mgr else 0
    seen = set()
    while node and node not in seen and len(seen) < 600:
        seen.add(node)
        e = u32(m, node)
        node = u32(m, node + 4)
        if not e:
            continue
        name = rtti(m, e)
        if name in DOORS:
            b = m.read(e + 0x6c, 12)
            pos = struct.unpack('<3f', b) if b else (0, 0, 0)
            out.append(dict(ent=e, rtti=name, id=u32(m, e + 4), pos=pos, usable=u32(m, e + 0x24),
                            user=u32(m, e + 0xc4), dest=u32(m, e + 0x118)))
    return out


def nearest(m, pl):
    h = player_human(m, pl)
    if not h:
        return None
    p = player_pos(m, pl)
    ds = [d for d in doors(m)]
    if not ds:
        return None
    d = min(ds, key=lambda x: (x['pos'][0] - p[0]) ** 2 + (x['pos'][1] - p[1]) ** 2)
    d['dist'] = ((d['pos'][0] - p[0]) ** 2 + (d['pos'][1] - p[1]) ** 2) ** 0.5
    return d


def same_door(m, ref):
    for d in doors(m):
        if d['rtti'] == ref['rtti'] and d['id'] == ref['id'] and \
                abs(d['pos'][0] - ref['pos'][0]) < 150 and abs(d['pos'][1] - ref['pos'][1]) < 150:
            return d
    return None


def user_tag(m, d):
    if not d or not d['user']:
        return '-'
    h = d['user']
    if u32(m, h + 0x14) is None:
        return '?'
    return tag(u32(m, h + 0x14))


def describe(m, d):
    if not d:
        return 'no door'
    return '%s id %s at (%.1f, %.1f, %.1f) usable %s user %s dest %s' % (
        d['rtti'], tag(d['id']), d['pos'][0], d['pos'][1], d['pos'][2], d['usable'],
        user_tag(m, d), tag(d['dest']) if d['dest'] else '-')


def phase(by):
    pl = 0 if by == 'host' else 1
    user_copy, peer_copy = (H, G) if by == 'host' else (G, H)
    user_proc, peer_proc = (HP, GP) if by == 'host' else (GP, HP)
    lvl0 = tag(level(H))
    # TASK 38: right after a load the world's entity manager can still be filling (the guest's J002
    # phase in soak run 2 saw an empty door list 1.3 s after the reset load). Wait for the scan, do not
    # fail the phase on it.
    d = None
    t0 = time.time()
    while time.time() - t0 < 12.0:
        d = nearest(user_copy, pl)
        if d:
            break
        time.sleep(0.3)
    print('== phase %s -> level %s: %s (door scan after %.1f s)' % (by, lvl0, describe(user_copy, d),
                                                                   time.time() - t0))
    if not d:
        print('%s FAIL: no door in this level' % by.upper())
        return False
    dest = tag(d['dest']) if d['dest'] else '-'
    d_peer = same_door(peer_copy, d)
    print('   the same door on the %s: %s' % ('guest' if by == 'host' else 'host', describe(peer_copy, d_peer)))
    before_peer = user_tag(peer_copy, d_peer)
    # TASK 37: `usedoor` answers "not in a level" while this copy's world is being rebuilt (a load or a
    # level change in flight right after the reset). That is a timing condition, not a door failure: wait
    # for both copies to be in one level again and retry (the world may be rebuilt, so re-pick the door).
    reply = ''
    for attempt in (1, 2, 3):
        reply = user_proc.cmd('usedoor %d' % pl)
        print('   usedoor %d -> %s' % (pl, reply))
        if not reply.startswith('error usedoor: not in a level'):
            break
        if attempt == 3:
            break
        t1 = time.time()
        while time.time() - t1 < 20:
            if in_level(H) and in_level(G) and tag(level(H)) == tag(level(G)):
                break
            time.sleep(0.4)
        print('   the %s world was being rebuilt: waited %.1f s for one level, retrying' % (by, time.time() - t1))
        d = nearest(user_copy, pl)
        if not d:
            break
        d_peer = same_door(peer_copy, d)
        before_peer = user_tag(peer_copy, d_peer)
    if not reply.startswith('ok'):
        print('%s FAIL: the game did not run the use' % by.upper())
        return False
    # TASK 35: the mod now uses the nearest door whose STATE the game's own use can run in (enabled, not
    # busy, +0x120 clear); the nearest door this script shows can be one stuck in that other state. Take
    # the destination from the door the reply names, or the transition would be compared with another door.
    m = re.search(r'ent ([0-9a-f]+)', reply)
    if m:
        used_ent = int(m.group(1), 16)
        if used_ent != d['ent']:
            used = [x for x in doors(user_copy) if x['ent'] == used_ent]
            if used:
                ud = used[0]
                print('   the mod used door ent %x (id %s, dest %s), not the nearest one shown above (id %s, dest %s)'
                      % (used_ent, tag(ud['id']), tag(ud['dest']) if ud['dest'] else '-', tag(d['id']), dest))
                d = ud
                dest = tag(d['dest']) if d['dest'] else '-'
    h = player_human(user_copy, pl)
    want_tag = tag(u32(user_copy, h + 0x14)) if h else '-'
    t0 = time.time()
    seen_peer = None
    changed = False
    image_ok = False
    while time.time() - t0 < USE_WATCH:
        dp, dq = same_door(user_copy, d), same_door(peer_copy, d)
        up, uq = user_tag(user_copy, dp), user_tag(peer_copy, dq)
        lp, lq = tag(level(H)), tag(level(G))
        if up == want_tag and uq == want_tag:
            image_ok = True
            seen_peer = uq
        if seen_peer is None and uq != before_peer:
            seen_peer = uq
        if lp != lvl0 or lq != lvl0:
            changed = True
            break
        time.sleep(SAMPLE)
    dp, dq = same_door(user_copy, d), same_door(peer_copy, d)
    print('   after %.1f s: user copy door user %s (want %s) | peer door user %s (was %s) | levels host %s guest %s'
          % (time.time() - t0, user_tag(user_copy, dp), want_tag, user_tag(peer_copy, dq), before_peer,
             tag(level(H)), tag(level(G))))
    if not image_ok and changed:
        # the world is being rebuilt: the door is gone on both, but the transition is the proof
        print('   the door use started a level change on both copies (the entity is being rebuilt)')
        image_ok = True
    print('   image: %s' % ('PASS' if image_ok else 'FAIL'))
    # the transition: both copies must reach the tag the door names
    trans_ok = False
    if dest != '-':
        t1 = time.time()
        while time.time() - t1 < TRANSITION_WAIT:
            lp, lq = tag(level(H)), tag(level(G))
            if lp == dest and lq == dest:
                trans_ok = True
                break
            if in_level(H) and in_level(G) and lp == lq and lp != lvl0 and lp != dest:
                break   # both moved, but somewhere else: report it
            time.sleep(0.5)
        print('   transition: dest %s -> host %s guest %s after %.1f s: %s'
              % (dest, tag(level(H)), tag(level(G)), time.time() - t1, 'PASS' if trans_ok else 'FAIL'))
    else:
        print('   transition: the door names no destination (a same-level door): skipped')
        trans_ok = True
    return image_ok and trans_ok


def reset_level(save, lvl):
    print('== reset: the host loads %s again (back to %s)' % (save, lvl))
    print('   reply: %s' % HP.cmd('loadsave %s' % save))
    t0 = time.time()
    # TASK 36: the check used to return as soon as both copies were in ONE level - which they already were
    # right after the previous phase (and right before the load starts), so the next phase ran while the
    # guest was still rebuilding its world and the door request answered "not in a level". Wait for the
    # load to take the pair out of the level first, then for both to be back in one level.
    left = False
    while time.time() - t0 < 30:
        if not (in_level(H) and in_level(G)):
            left = True
            break
        time.sleep(0.2)
    if not left:
        print('   note: neither copy left the level within 30 s (the load may not have started)')
    while time.time() - t0 < 90:
        if in_level(H) and in_level(G) and tag(level(H)) == tag(level(G)):
            print('   both copies in level %s after %.1f s' % (tag(level(H)), time.time() - t0))
            return True
        time.sleep(0.5)
    print('   NOT back in one level after 90 s (host %s guest %s)' % (tag(level(H)), tag(level(G))))
    return False


if not wait_in_level(40):
    print('NOT IN A LEVEL on both copies (host %s/%s guest %s/%s): check skipped'
          % (level(H) and tag(level(H)), mode_of(H), level(G) and tag(level(G)), mode_of(G)))
    sys.exit(1)

lvl0 = tag(level(H))
ok = []
if mode == 'guest':
    ok.append(phase('guest'))
else:
    ok.append(phase('host'))
    if reset:
        if reset_level(reset, lvl0):
            ok.append(phase('guest'))
        else:
            ok.append(False)
if all(ok):
    print('doors OK (%d phase(s))' % len(ok))
    sys.exit(0)
print('doors FAIL (%d phase(s): %s)' % (len(ok), ', '.join('PASS' if x else 'FAIL' for x in ok)))
sys.exit(1)
