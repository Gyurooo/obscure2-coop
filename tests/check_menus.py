"""TASK 36: a menu is a SHARED session state - both screens show it, both pads drive it, either closes it.

Reads the game's own menu state on BOTH copies (`world+0x11c`: 1 = normal play, 5 = the pause menu, 2 = the
live inventory CMenuInventoryLive; `controller+0xa4`: 3 = weapon wheel, 4 = item menu - FINDINGS_36 §2-§4)
and drives the pads of each copy through the mod's pipe:

  1. the host opens the pause menu -> state 5 on BOTH copies;
  2. the guest navigates it (D-pad) and closes it with START -> state 1 on BOTH (the guest's START is the
     mod's pause pulse path);
  3. the host opens the inventory (BACK) -> state 2 on BOTH; the guest moves in it (D-pad) and closes it
     with B -> state 1 on BOTH (B is a plain menu action, so this proves the guest's pad drove the menu
     through the mod's merged input, not through the START special case);
  4. the weapon wheel: the host's D-pad raises controller 1's UI state 3 on BOTH copies; the guest's D-pad
     raises controller 2's on BOTH;
  5. every step prints the `menu` pipe line of both copies (this copy's and the peer's state).

The map and the document panels are `CMenuPanel*` items of the same live-inventory menu (state 2), so they
move under the same merged input; they are not separately reachable from a pad in the test save and are
reported as "same code path, not tested live".

Usage: python -I check_menus.py <host pid> <guest pid> [--shots <dir>]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe, press, shot
from peek import Proc
from tp_to_items import level, tag, u32, world

GAME = 0x6c3068
STATE = 0x11c          # world+0x11c: 1 normal, 2 inventory menu, 5 pause menu (FINDINGS_36 §2)
UI = 0xa4              # controller+0xa4: 3 weapon wheel, 4 item menu (FINDINGS_36 §4)

host_pid, guest_pid = int(sys.argv[1]), int(sys.argv[2])
shots = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shots')
args = sys.argv[3:]
for i, a in enumerate(args):
    if a == '--shots' and i + 1 < len(args):
        shots = args[i + 1]
os.makedirs(shots, exist_ok=True)

H, G = Proc(host_pid), Proc(guest_pid)
HP, GP = Pipe(host_pid), Pipe(guest_pid)


def menu_state(m):
    w = world(m)
    return u32(m, w + STATE) if w else None


def ui_state(m):
    w = world(m)
    ctl = u32(m, w + 0x1748) if w else 0
    if not ctl:
        return (None, None)
    return (u32(m, ctl + UI), u32(m, ctl + 0x764 + UI))


def in_level(m):
    return menu_state(m) == 1 and (level(m) or 0) != 0


def teammate_human(m):
    """TASK 38: the character the game's teammate controller (world+0x174c) is linked to. The mod's
    TASK 35 door fix unlinks player 2's character from it in normal play; TASK 38's guard puts it back
    whenever the copy is not in normal play (a menu, a load, a scripted event), because the game's own
    scripted-event skip reads it and a NULL there crashed the guest."""
    w = world(m)
    if not w:
        return None
    mt = u32(m, w + 0x174c)
    return u32(m, mt + 4) if mt else None


def wait_for(pred, secs=5.0, what=''):
    t0 = time.time()
    while time.time() - t0 < secs:
        if pred():
            return time.time() - t0
        time.sleep(0.1)
    return None


def show(label):
    print('   %-22s host st %s ui %s | guest st %s ui %s' % (label, menu_state(H), ui_state(H),
                                                            menu_state(G), ui_state(G)))


def both(pred):
    return pred(H) and pred(G)


def pipe_menu(p):
    return p.cmd('menu')


def check(ok, what):
    print('   %s: %s' % (what, 'PASS' if ok else 'FAIL'))
    return ok


t0 = time.time()
while time.time() - t0 < 40:
    if in_level(H) and in_level(G):
        break
    time.sleep(0.3)
if not (in_level(H) and in_level(G)):
    print('NOT IN A LEVEL on both copies (host %s guest %s): check skipped' % (menu_state(H), menu_state(G)))
    sys.exit(1)

lvl = tag(level(H))
print('== starting in level %s' % lvl)
show('before')
print('   teammate controller: host %s | guest %s (TASK 38: 0 in normal play, restored while a menu is up)'
      % (teammate_human(H), teammate_human(G)))

results = []

print('\n== 1. the host opens the pause menu (START on the host pad)')
press(HP, 0, 'START', 0.2)
t = wait_for(lambda: both(lambda m: menu_state(m) == 5), 5.0)
show('after host START')
print('   both copies show the pause menu after %s s' % ('%.2f' % t if t is not None else 'NO'))
results.append(check(t is not None, 'pause menu shown on both'))
tg = teammate_human(G)
print('   guest teammate controller -> character %s' % tg)
results.append(check(tg not in (None, 0), 'guest teammate restored while a menu is up (TASK 38 guard)'))
print('   host  menu: %s' % pipe_menu(HP))
print('   guest menu: %s' % pipe_menu(GP))

print('\n== 2. the guest navigates it (D-pad on the guest pad) and closes it (START on the guest pad)')
press(GP, 0, 'DOWN', 0.2)
time.sleep(0.4)
press(GP, 0, 'UP', 0.2)
time.sleep(0.4)
show('after guest D-pad')
results.append(check(both(lambda m: menu_state(m) == 5), 'still open while the guest navigates'))
press(GP, 0, 'START', 0.2)
t = wait_for(lambda: both(lambda m: menu_state(m) == 1), 6.0)
show('after guest START')
print('   both copies left the pause menu after %s s' % ('%.2f' % t if t is not None else 'NO'))
results.append(check(t is not None, 'guest closes the pause menu on both'))

print('\n== 3. the host opens the inventory (BACK: CMenuInventoryLive, state 2)')
press(HP, 0, 'BACK', 0.25)
t = wait_for(lambda: both(lambda m: menu_state(m) == 2), 5.0)
show('after host BACK')
print('   both copies show the inventory after %s s' % ('%.2f' % t if t is not None else 'NO'))
results.append(check(t is not None, 'inventory shown on both'))
print('   host  menu: %s' % pipe_menu(HP))
print('   guest menu: %s' % pipe_menu(GP))

print('\n== 4. the guest moves in the inventory (D-pad) and closes it with B (a plain menu action)')
press(GP, 0, 'DOWN', 0.2)
time.sleep(0.4)
press(GP, 0, 'RIGHT', 0.2)
time.sleep(0.4)
show('after guest D-pad')
results.append(check(both(lambda m: menu_state(m) == 2), 'still open while the guest navigates'))
press(GP, 0, 'B', 0.2)
t = wait_for(lambda: both(lambda m: menu_state(m) == 1), 6.0)
show('after guest B')
print('   both copies left the inventory after %s s' % ('%.2f' % t if t is not None else 'NO'))
results.append(check(t is not None, "guest's B closes the inventory on both (merged input)"))

print('\n== 5. screenshots with the inventory open on both copies')
press(HP, 0, 'BACK', 0.25)
wait_for(lambda: both(lambda m: menu_state(m) == 2), 5.0)
time.sleep(0.8)
show('inventory open')
hp = os.path.join(shots, 'menus_host.png')
gp = os.path.join(shots, 'menus_guest.png')
shot(host_pid, hp)      # the game windows, not the desktop (tests/bot.py)
shot(guest_pid, gp)
print('   host shot: %s' % hp)
print('   guest shot: %s' % gp)
press(HP, 0, 'B', 0.2)
wait_for(lambda: both(lambda m: menu_state(m) == 1), 6.0)
show('after host B')

print('\n== 6. the per-player UI (controller+0xa4) shows on both copies from either pad')
# TASK 43: the wheel and the aim stance are the CHARACTER'S OWN controller state, and the puppet's
# controller does not run on the other copy any more (TASK 42) - the owner now streams the state and the
# other copy makes the game's own HUD calls for that player, so this works again by design.
HP.cmd('pad 0 8')          # the host's D-pad RIGHT held
time.sleep(0.5)
show('host pad RIGHT')
h = ui_state(H)
g = ui_state(G)
results.append(check(h[0] == 3 and g[0] == 3, "host's wheel on both copies (player 1)"))
HP.cmd('pad 0 0')
time.sleep(0.4)
GP.cmd('pad 0 8')          # the guest's D-pad RIGHT held
time.sleep(0.5)
show('guest pad RIGHT')
h = ui_state(H)
g = ui_state(G)
results.append(check(h[1] == 3 and g[1] == 3, "guest's wheel on both copies (player 2)"))
GP.cmd('pad 0 0')
time.sleep(0.4)
show('after release')
results.append(check(both(lambda m: menu_state(m) == 1), 'back to normal play on both'))
# the same per-player UI channel, the aim stance (controller+0xa4 == 1, FINDINGS_36 section 4)
HP.cmd('pad 0 0x100')      # the host's LB held
time.sleep(0.5)
show('host pad LB')
h = ui_state(H)
g = ui_state(G)
results.append(check(h[0] == 1 and g[0] == 1, "host's aim stance (UI 1) on both copies"))
HP.cmd('pad 0 0')
time.sleep(0.3)
GP.cmd('pad 0 0x100')      # the guest's LB held
time.sleep(0.5)
show('guest pad LB')
h = ui_state(H)
g = ui_state(G)
results.append(check(h[1] == 1 and g[1] == 1, "guest's aim stance (UI 1) on both copies"))
GP.cmd('pad 0 0')
time.sleep(0.4)
show('after LB release')
results.append(check(both(lambda m: menu_state(m) == 1), 'still normal play on both'))

print('\n== 7. after the menus: the two copies are in the same state')
show('final')
results.append(check(both(lambda m: menu_state(m) == 1) and tag(level(H)) == tag(level(G)), 'both normal, same level'))
t = wait_for(lambda: teammate_human(G) == 0, 2.0)
print('   guest teammate controller -> character %s' % teammate_human(G))
results.append(check(t is not None, 'guest teammate unlinked again in normal play (the door fix)'))

print('\nmenus %s (%d checks)' % ('OK' if all(results) else 'FAIL', len(results)))
sys.exit(0 if all(results) else 1)
