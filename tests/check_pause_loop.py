"""TASK 57/58: the shared pause menu opened and CLOSED from each side, ten times in a row.

The reviewer's run of check_menus.py on TASK 57's build lost the close: the GUEST opened the pause menu,
the HOST pressed START, and both copies stayed in state 5 for the rest of the run (a player who cannot
leave the pause menu cannot play). This check runs the pause steps alone, in the three orders that race:

  A. the GUEST opens the pause menu, the HOST closes it            (the reviewer's failing order)
  B. the HOST opens it, the GUEST closes it
  C. BOTH press START within 100 ms of each other (both open, the guest closes)

Each round must end with both copies in the same state within 1 s. Every step prints, for each copy:
  world+0x11c (current state), world+0x12c (requested state), world+0x180 (the state the pause saved
  when it opened - what FUN_004b2770 leaves to) and the mod's pipe `menu` line (own/peer seq, reqs).

Usage: python -I check_pause_loop.py <host pid> <guest pid> [--rounds N] [--shots <dir>]
Exit: 0 = every round reached the same state on both copies within 1 s (and both end in normal play).
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe, press, shot
from peek import Proc
from tp_to_items import level, tag, u32, world

STATE = 0x11c          # world+0x11c: the current world state (1 normal, 2 inventory, 5 pause)
REQ = 0x12c            # world+0x12c: the requested state (the world update consumes it)
STORE = 0x180          # world+0x180: the state the pause menu saved when it opened

host_pid, guest_pid = int(sys.argv[1]), int(sys.argv[2])
rounds = 10
shots = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shots')
args = sys.argv[3:]
for i, a in enumerate(args):
    if a == '--rounds' and i + 1 < len(args):
        rounds = int(args[i + 1])
    if a == '--shots' and i + 1 < len(args):
        shots = args[i + 1]
os.makedirs(shots, exist_ok=True)

H, G = Proc(host_pid), Proc(guest_pid)
HP, GP = Pipe(host_pid), Pipe(guest_pid)


def menu_state(m):
    w = world(m)
    return u32(m, w + STATE) if w else None


def req_state(m):
    w = world(m)
    return u32(m, w + REQ) if w else 0


def store_state(m):
    w = world(m)
    return u32(m, w + STORE) if w else 0


def coords(m):
    w = world(m)
    return (menu_state(m), req_state(m), store_state(m)) if w else (None, 0, 0)


def stamp():
    return time.strftime('%H:%M:%S') + '.%03d' % (int(time.time() * 1000) % 1000)


def pipe_menu(p):
    return p.cmd('menu')


GAP = 0.35   # after a press both the release has to reach the game and one poll has to see it: two presses
             # closer than this on ONE pad are one continuous hold to the game (and to the mod's edges)


def p_(who, pipe, user, names, hold=0.2):
    print('   %s press %s on the %s pad' % (stamp(), names, who))
    press(pipe, user, names, hold)
    time.sleep(GAP)


def show(label):
    print('   %s %-24s host %s %s | guest %s %s' % (stamp(), label,
          coords(H), pipe_menu(HP), coords(G), pipe_menu(GP)))


def both(pred):
    return pred(H) and pred(G)


def wait_for(pred, secs=1.0, what=''):
    t0 = time.time()
    while time.time() - t0 < secs:
        if pred():
            return time.time() - t0
        time.sleep(0.05)
    return None


def check(ok, what):
    print('   %s: %s' % (what, 'PASS' if ok else 'FAIL'))
    return ok


def in_level(m):
    return menu_state(m) == 1 and (level(m) or 0) != 0


def scene_req(m):
    """world+0x12c non-zero in normal play = a level script is driving the state (FINDINGS_57 §7): a
    menu opened inside a scripted event is closed again by the event, so wait for a quiet window."""
    return req_state(m)


def playable(m):
    return in_level(m) and not scene_req(m)


def press_both_offset(user, names, hold, offset):
    """Press the same key on both copies with a controlled offset (the 'both press START' race)."""
    out = {}

    def go(who, pipe, delay):
        if delay:
            time.sleep(delay)
        out[who] = press(pipe, user, names, hold)

    a = threading.Thread(target=go, args=('host', HP, 0.0))
    b = threading.Thread(target=go, args=('guest', GP, offset))
    a.start()
    b.start()
    a.join()
    b.join()
    return out


# ---- settle: normal play without a level script on both copies (as check_menus.py) -------------------
t0 = time.time()
while time.time() - t0 < 60:
    if playable(H) and playable(G):
        break
    time.sleep(0.2)
if not (in_level(H) and in_level(G)):
    print('NOT IN A LEVEL on both copies (host %s guest %s): check skipped' % (menu_state(H), menu_state(G)))
    sys.exit(1)
STABLE = 6.0
stable_since = None
t0 = time.time()
while time.time() - t0 < 60:
    if playable(H) and playable(G):
        if stable_since is None:
            stable_since = time.time()
        elif time.time() - stable_since >= STABLE:
            break
    else:
        stable_since = None
    time.sleep(0.2)
if stable_since is None or time.time() - stable_since < STABLE:
    print('NOT STABLE: normal play without a scene did not last %.0f s on both copies (host %s scene %s,'
          ' guest %s scene %s)' % (STABLE, menu_state(H), scene_req(H), menu_state(G), scene_req(G)))
    sys.exit(1)

print('== starting in level %s (normal play stable for %.0f s)' % (tag(level(H)), STABLE))
show('before')

results = []


def recover_to_normal(tag_):
    """Bring both copies back to normal play after a failed round, so the next round starts clean."""
    for _ in range(3):
        if both(lambda m: menu_state(m) == 1):
            return True
        if menu_state(H) != 1:
            p_('host', HP, 0, 'START')
        if menu_state(G) != 1:
            p_('guest', GP, 0, 'START')
        wait_for(lambda: both(lambda m: menu_state(m) == 1), 1.5)
    ok = both(lambda m: menu_state(m) == 1)
    if not ok:
        print('   %s: could not leave the menu (host %s guest %s)' % (tag_, menu_state(H), menu_state(G)))
    return ok


def round_(i, kind):
    if not recover_to_normal('round %d start' % (i + 1)):
        return False, 'both copies in normal play before the round'
    ok = True
    if kind == 'guest-open-host-close':
        p_('guest', GP, 0, 'START')
        t = wait_for(lambda: both(lambda m: menu_state(m) == 5), 1.0)
        show('after guest START (open)')
        ok &= check(t is not None, 'the guest opens the pause menu on both within 1 s%s'
                    % ('' if t is None else ' (%.2f s)' % t))
        time.sleep(0.5)
        p_('host', HP, 0, 'START')
        t = wait_for(lambda: both(lambda m: menu_state(m) == 1), 1.0)
        show('after host START (close)')
        ok &= check(t is not None, 'the host closes the pause menu on both within 1 s%s'
                    % ('' if t is None else ' (%.2f s)' % t))
    elif kind == 'host-open-guest-close':
        p_('host', HP, 0, 'START')
        t = wait_for(lambda: both(lambda m: menu_state(m) == 5), 1.0)
        show('after host START (open)')
        ok &= check(t is not None, 'the host opens the pause menu on both within 1 s%s'
                    % ('' if t is None else ' (%.2f s)' % t))
        time.sleep(0.5)
        p_('guest', GP, 0, 'START')
        t = wait_for(lambda: both(lambda m: menu_state(m) == 1), 1.0)
        show('after guest START (close)')
        ok &= check(t is not None, 'the guest closes the pause menu on both within 1 s%s'
                    % ('' if t is None else ' (%.2f s)' % t))
    else:   # both-start
        print('   %s press START on BOTH pads within 100 ms' % stamp())
        press_both_offset(0, 'START', 0.2, 0.08)
        time.sleep(GAP)
        t = wait_for(lambda: both(lambda m: menu_state(m) == 5), 1.0)
        show('after both START (open)')
        ok &= check(t is not None, 'both pressing START within 100 ms pauses both copies within 1 s%s'
                    % ('' if t is None else ' (%.2f s)' % t))
        time.sleep(0.5)
        p_('guest', GP, 0, 'START')
        t = wait_for(lambda: both(lambda m: menu_state(m) == 1), 1.0)
        show('after guest START (close)')
        ok &= check(t is not None, 'the guest closes it again on both within 1 s%s'
                    % ('' if t is None else ' (%.2f s)' % t))
    if not both(lambda m: menu_state(m) == 1):
        print('   after the round: host st %s scene %s | guest st %s scene %s - both copies MUST be in'
              ' state 1 here' % (menu_state(H), scene_req(H), menu_state(G), scene_req(G)))
        ok = False
    return ok, kind


KINDS = ('guest-open-host-close', 'host-open-guest-close', 'both-start')
for i in range(rounds):
    kind = KINDS[i % len(KINDS)]
    print('\n== round %d/%d: %s' % (i + 1, rounds, kind))
    ok, what = round_(i, kind)
    results.append(ok)
    if not ok:
        shot(host_pid, os.path.join(shots, 'pause_loop_host_%02d.png' % (i + 1)))
        shot(guest_pid, os.path.join(shots, 'pause_loop_guest_%02d.png' % (i + 1)))

print('\n== summary')
print('   rounds in the same state on both copies within 1 s: %d/%d' % (sum(1 for r in results if r), len(results)))
show('at the end')
ok = bool(results) and all(results) and both(lambda m: menu_state(m) == 1)
# The state the pause menu saved when it opened must be cleared again once it is closed: a stale +0x180
# is what made a close request land on the wrong state.
stored = (store_state(H), store_state(G))
print('   world+0x180 after the last close: host %s guest %s' % stored)
ok = check(ok, 'every round ended in normal play on both copies within 1 s') and ok
print('pause loop %s (%d rounds)' % ('OK' if ok else 'FAIL', rounds))
sys.exit(0 if ok else 1)
