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


def s32(v):
    return v - (1 << 32) if v is not None and v >= (1 << 31) else v


def cursors(m):
    """TASK 51/52: (tab, cursor player 1, cursor player 2) of the active inventory tab panel.
    game+0x46c = CMenuInventory, +0x98 tab index, tab panels at +0x84, cursors at +0x138 / +0x13c."""
    g = u32(m, m.va(GAME))
    inv = u32(m, g + 0x46c) if g else 0
    if not inv:
        return (-1, None, None)
    tab = u32(m, inv + 0x98)
    p = u32(m, inv + 0x84 + 4 * tab) if tab < 5 else 0
    if not p:
        return (tab, None, None)
    return (tab, s32(u32(m, p + 0x138)), s32(u32(m, p + 0x13c)))


def human(m, player):
    w = world(m)
    ctl = u32(m, w + 0x1748) if w else 0
    return u32(m, ctl + 4 + 0x764 * player) if ctl else 0


def weapons(m, player):
    """(tag, selected slot, the four slot tags) of one player's character - the equip result."""
    h = human(m, player)
    if not h:
        return None
    slots = []
    for s in range(4):
        wp = u32(m, h + 0x704 + 4 * s)
        slots.append(tag(u32(m, wp + 0x10)) if wp else '----')
    return (tag(u32(m, h + 0x14)), u32(m, h + 0x714), tuple(slots))


def wstate(m):
    return (weapons(m, 0), weapons(m, 1))


def show_w(label):
    print('   %-24s host %s | guest %s' % (label, wstate(H), wstate(G)))
    return wstate(H), wstate(G)


def panel_obj(m):
    g = u32(m, m.va(GAME))
    inv = u32(m, g + 0x46c) if g else 0
    if not inv:
        return 0
    tab = u32(m, inv + 0x98)
    return u32(m, inv + 0x84 + 4 * tab) if tab < 5 else 0


GRID = ('UP', 'DOWN', 'LEFT', 'RIGHT')
GRID_OFF = {'UP': 0xfc, 'DOWN': 0x104, 'LEFT': 0x108, 'RIGHT': 0x100}


def grid(m):
    """TASK 52: the 24 inventory grid cells (panel+0xc0): item tag at +0xec, neighbour index per
    direction at +0xfc/+0x104/+0x108/+0x100 (the four walk functions FUN_00549810/f0/80/60)."""
    p = panel_obj(m)
    if not p:
        return None
    out = []
    for i in range(24):
        it = u32(m, p + 0xc0 + 4 * i)
        if not it:
            return None
        out.append(dict({'tag': u32(m, it + 0xec)},
                        **{d: s32(u32(m, it + GRID_OFF[d])) for d in GRID}))
    return out


def grid_tags(m):
    c = grid(m)
    return tuple(x['tag'] for x in c) if c else None


def path_to(cells, start, goal):
    from collections import deque
    q = deque([(start, [])])
    seen = {start}
    while q:
        cur, path = q.popleft()
        if cur == goal:
            return path
        for d in GRID:
            n = cells[cur][d]
            if n is None or n < 0 or n >= len(cells) or n in seen:
                continue
            seen.add(n)
            q.append((n, path + [d]))
    return None


def go(pad, user, moves):
    for d in moves or ():
        press(pad, user, d, 0.15)
        time.sleep(0.28)


def cursor_cmd(p):
    """The pipe `menu` line's cursor counters: (writes to player 1's cursor, to player 2's)."""
    line = p.cmd('menu')
    i = line.find('cursor writes p1 ')
    if i < 0:
        return None
    parts = line[i + len('cursor writes p1 '):].split()
    return (int(parts[0]), int(parts[2].rstrip(',')))


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
    print('   %-22s host st %s ui %s cur %s | guest st %s ui %s cur %s'
          % (label, menu_state(H), ui_state(H), cursors(H), menu_state(G), ui_state(G), cursors(G)))


def both(pred):
    return pred(H) and pred(G)


def pipe_menu(p):
    return p.cmd('menu')


def check(ok, what):
    print('   %s: %s' % (what, 'PASS' if ok else 'FAIL'))
    return ok


t0 = time.time()
while time.time() - t0 < 60:
    if in_level(H) and in_level(G):
        break
    time.sleep(0.3)
if not (in_level(H) and in_level(G)):
    print('NOT IN A LEVEL on both copies (host %s guest %s): check skipped' % (menu_state(H), menu_state(G)))
    sys.exit(1)

# TASK 52: the level load plays a scripted event (the scene code drives world state 1 <-> 5 for seconds
# after the level appears - obscoop.log "scene: this copy entered a scripted event"). Opening a menu in
# the middle of it gets the menu closed again by the game when the event ends, so start only after
# NORMAL PLAY HAS BEEN STABLE for 6 s on both copies.
STABLE = 6.0
stable_since = None
t0 = time.time()
while time.time() - t0 < 60:
    if in_level(H) and in_level(G):
        if stable_since is None:
            stable_since = time.time()
        elif time.time() - stable_since >= STABLE:
            break
    else:
        stable_since = None
    time.sleep(0.25)
if stable_since is None or time.time() - stable_since < STABLE:
    print('NOT STABLE: normal play did not last %.0f s on both copies (host st %s level %s, guest st %s level %s)'
          % (STABLE, menu_state(H), tag(level(H)), menu_state(G), tag(level(G))))
    sys.exit(1)

lvl = tag(level(H))
print('== starting in level %s (normal play stable for %.0f s)' % (lvl, STABLE))
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

print('\n== 4. two cursors: the host pad moves only cursor 0, the guest pad only cursor 1, on BOTH copies')
start = (cursors(H), cursors(G))
print('   start: host %s | guest %s' % start)
results.append(check(start[0] == start[1] and start[0][0] >= 0,
                     'both copies agree on the tab and both cursors'))


def cursor_move(pad, user, player, what):
    """Press DOWN on one player's pad until that player's cursor moved; returns (before, after)."""
    b = (cursors(H), cursors(G))
    a = b
    for _ in range(4):
        press(pad, user, 'DOWN', 0.2)
        time.sleep(0.5)
        a = (cursors(H), cursors(G))
        if a[0][1 + player] != b[0][1 + player]:
            break
    show('%s DOWN' % what)
    return b, a


b, a = cursor_move(HP, 0, 0, 'host D-pad')
results.append(check(a[0][1] != b[0][1] and a[1][1] != b[1][1],
                     'host D-pad moved cursor 0 on both copies (host %s->%s, guest %s->%s)'
                     % (b[0][1], a[0][1], b[1][1], a[1][1])))
results.append(check(a[0][2] == b[0][2] and a[1][2] == b[1][2],
                     'host D-pad left cursor 1 alone on both copies (host %s, guest %s)'
                     % (a[0][2], a[1][2])))

b, a = cursor_move(GP, 0, 1, 'guest D-pad')   # the guest's own pad is virtual pad 0; the game reads it as user 1
results.append(check(a[0][2] != b[0][2] and a[1][2] != b[1][2],
                     'guest D-pad moved cursor 1 on both copies (host %s->%s, guest %s->%s)'
                     % (b[0][2], a[0][2], b[1][2], a[1][2])))
results.append(check(a[0][1] == b[0][1] and a[1][1] == b[1][1],
                     'guest D-pad left cursor 0 alone on both copies (host %s, guest %s)'
                     % (a[0][1], a[1][1])))

hc, gc = cursor_cmd(HP), cursor_cmd(GP)
print('   pipe cursor writes (player 1, player 2): host %s | guest %s' % (hc, gc))
results.append(check(hc is not None and gc is not None and hc[0] == 0 and gc[1] == 0,
                     'each copy writes only the PEER cursor (own-cursor writes: host p1 %s, guest p2 %s)'
                     % (hc[0] if hc else '?', gc[1] if gc else '?')))

print('\n== 5. a selection by each player lands once on both copies (move a weapon into a hand slot)')
# TASK 52: A on the weapon grid picks the item under the cursor up (panel+0x148), the next A drops it:
# a swap with the cell under the cursor (FUN_0054b2c0 -> FUN_00549a10). Dropping into one of the
# character's hand-slot cells (panel+0xc0 cells 16..19 = player 1, 20..23 = player 2) is the equip; the
# panel writes the cells back to the characters when the inventory closes (FUN_0054beb0 -> FUN_00549f60).
# Reopen first so both cursors are back at the game's start positions (0 and 3, FUN_00549be0).
press(HP, 0, 'BACK', 0.25)
wait_for(lambda: both(lambda m: menu_state(m) == 1), 6.0)
time.sleep(0.5)
press(HP, 0, 'BACK', 0.25)
t = wait_for(lambda: both(lambda m: menu_state(m) == 2), 6.0)
time.sleep(0.5)
show('inventory reopened')
results.append(check(t is not None and cursors(H)[1:] == (0, 3) and cursors(G)[1:] == (0, 3),
                     'reopening resets both cursors to the game start positions 0/3'))

start = show_w('weapons before')
results.append(check(wstate(H) == wstate(G), 'the two copies hold the same weapons before the selection'))
results.append(check(grid_tags(H) is not None and grid_tags(H) == grid_tags(G),
                     'the two copies draw the same 24 grid cells before the selection'))
cells0 = grid_tags(H)


def select(player, pad, user, bag_cell, slot_cell):
    cells = grid(H)
    cur = cursors(H)[1 + player]
    path1 = path_to(cells, cur, bag_cell) if cells and cur is not None else None
    path2 = path_to(cells, bag_cell, slot_cell) if cells else None
    print('   player %d: cursor %s -> bag cell %d via %s, then -> hand-slot cell %d via %s'
          % (player + 1, cur, bag_cell, path1, slot_cell, path2))
    if path1 is None or path2 is None:
        results.append(check(False, 'player %d: the grid path to the bag and the hand slot exists' % (player + 1)))
        return
    go(pad, user, path1)
    press(pad, user, 'A', 0.2)      # pick the weapon up
    time.sleep(0.5)
    go(pad, user, path2)
    press(pad, user, 'A', 0.2)      # drop it: swap with the hand-slot cell
    time.sleep(0.8)
    show_w('after player %d move' % (player + 1))


select(0, HP, 0, 0, 16)     # bag cell 0 -> player 1's hand slot 0
select(1, GP, 0, 1, 20)     # bag cell 1 -> player 2's hand slot 0
cells1 = grid_tags(H)
print('   grid host == guest: %s ; changed since the start: %s'
      % (grid_tags(H) == grid_tags(G), cells1 != cells0))
results.append(check(cells1 is not None and cells1 != cells0 and grid_tags(H) == grid_tags(G),
                     'both copies hold the same 24 grid cells after the two moves (the move landed once)'))

press(HP, 0, 'BACK', 0.25)          # close: the panel commits its cells to the characters
t = wait_for(lambda: both(lambda m: menu_state(m) == 1), 6.0)
time.sleep(0.8)
after = show_w('after the close (committed)')
results.append(check(t is not None and wstate(H) == wstate(G),
                     'after the close both copies hold the same weapons'))
results.append(check(after[0] != start[0] and after[1] != start[1],
                     'the selection changed the committed hand slots of both players'))

press(HP, 0, 'BACK', 0.25)          # reopen for the screenshots and the close/open checks
wait_for(lambda: both(lambda m: menu_state(m) == 2), 6.0)
show('inventory open again')

print('\n== 6. screenshots of both windows: the two cursors on different cells')
cells = grid(H)
p1 = path_to(cells, cursors(H)[1], 3) if cells else None
p2 = path_to(cells, cursors(H)[2], 6) if cells else None
go(HP, 0, p1)
go(GP, 0, p2)
time.sleep(0.8)
show('before the shots')
print('   host cursor 0 on cell %s, guest cursor 1 on cell %s (cells 3 and 6 hold a weapon)'
      % (cursors(H)[1], cursors(H)[2]))
results.append(check(cursors(H) == cursors(G) and cursors(H)[1] != cursors(H)[2],
                     'the two cursors are on different cells and both copies agree'))
hp = os.path.join(shots, 'menus_host.png')
gp = os.path.join(shots, 'menus_guest.png')
shot(host_pid, hp)      # the game windows, not the desktop (tests/bot.py)
shot(guest_pid, gp)
print('   host shot: %s' % hp)
print('   guest shot: %s' % gp)

print('\n== 7. close and open from each side')
for who, pad, user in (('guest', GP, 0), ('host', HP, 0)):
    press(pad, user, 'BACK', 0.25)
    t = wait_for(lambda: both(lambda m: menu_state(m) == 1), 6.0)
    show('after %s BACK (close)' % who)
    results.append(check(t is not None, "the %s's BACK closes the inventory on both copies" % who))
    time.sleep(0.5)
    press(pad, user, 'BACK', 0.25)
    t = wait_for(lambda: both(lambda m: menu_state(m) == 2), 6.0)
    show('after %s BACK (open)' % who)
    results.append(check(t is not None, "the %s's BACK opens the inventory on both copies" % who))
    time.sleep(0.5)
press(HP, 0, 'BACK', 0.25)
t = wait_for(lambda: both(lambda m: menu_state(m) == 1), 6.0)
results.append(check(t is not None, 'back to normal play for the per-player UI checks'))

print('\n== 8. the per-player UI (controller+0xa4) shows on both copies from either pad')
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

print('\n== 9. after the menus: the two copies are in the same state')
show('final')
results.append(check(both(lambda m: menu_state(m) == 1) and tag(level(H)) == tag(level(G)), 'both normal, same level'))
t = wait_for(lambda: teammate_human(G) == 0, 2.0)
print('   guest teammate controller -> character %s' % teammate_human(G))
results.append(check(t is not None, 'guest teammate unlinked again in normal play (the door fix)'))

print('\nmenus %s (%d checks)' % ('OK' if all(results) else 'FAIL', len(results)))
sys.exit(0 if all(results) else 1)
