"""World state shared by both copies (TASK 60): the same save file, the same live items, the same
container/pedestal state.

Phases (each prints its own verdict):
  A save      the HOST uses its level's save point (the game's own `CToeSavePoint::use`, through the
              mod's TEST-ONLY pipe `savepoint`; the ten test saves store the save point in its POST-SAVE
              state +0x14 = 3, whose own can-use check wants 0, so the check puts the idle value back),
              then the GUEST uses its save point (the mod turns that into a request the host performs).
              After each, the save file the game wrote must exist on BOTH copies with identical bytes.
  B items     both copies must list the same LIVE world items (class + position). Then one item is made
              live on the HOST only (the `wr` activation write check_pickup.py already uses for these
              saves); the GUEST must show the same item after the host's world packet.
  C container the level H006 (save 08) has three CToePedestal objects. Each is used on the host and then
              on the guest with the game's own use call (pipe `useobj`); both copies must show the same
              state afterwards.

Usage: python -I check_world.py <host pid> <guest pid> [--skip-save] [--skip-items] [--skip-container]
"""
import os, sys, time, glob, struct, hashlib, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe, press
from peek import Proc

GAME = 0x6c3068
ROOT = os.environ.get('OBSCOOP_TEST_ROOT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOST_DIR = os.environ.get('OBSCOOP_HOST_DIR') or os.path.join(ROOT, 'obscure2-test')
GUEST_DIR = os.environ.get('OBSCOOP_GUEST_DIR') or os.path.join(ROOT, 'obscure2-test2')
ITEM_TAGS = {
    0x41434944, 0x42415454, 0x424b504b, 0x424c4541, 0x4341424f, 0x43524f57, 0x454e4452,
    0x474c5943, 0x4943414d, 0x49434500, 0x4943524e, 0x49445343, 0x4a454d4d, 0x4a455252,
    0x4a554241, 0x4b455900, 0x4c564552, 0x4d415000, 0x4d454449, 0x50415353, 0x53455255,
    0x534f4441, 0x53544154, 0x53545249, 0x53595249, 0x57454c44,
}
CONTAINER_TAGS = {0x434f4e54, 0x43484553, 0x43484b45, 0x50454445}   # CONT, CHES, CHKE, PEDE
SYNC_OFF = (0x20, 0xa4, 0xa8, 0xb0, 0xc0, 0xc4, 0x128)
SAVEPT = 0x53415645   # "SAVE"
SKIP = set(a for a in sys.argv[3:])

h, g = int(sys.argv[1]), int(sys.argv[2])
HP, GP = Pipe(h), Pipe(g)
H, G = Proc(h), Proc(g)
fails = []


def tag(v):
    return ''.join(chr((v >> s) & 0xff) if 32 <= ((v >> s) & 0xff) < 127 else '.'
                   for s in (24, 16, 8, 0))


def u32(m, a):
    try:
        return m.u32(a) or 0
    except Exception:
        return 0


def f32(m, a):
    b = m.read(a, 4)
    return struct.unpack('<f', b)[0] if b else 0.0


def game(m):
    return u32(m, m.va(GAME))


def world(m):
    g0 = game(m)
    return u32(m, g0 + 0x378) if g0 else 0


def mode(m):
    return u32(m, game(m) + 0x310)


def level(m):
    w = world(m)
    return u32(m, w + 4) if w else 0


def in_level(m):
    return mode(m) == 1 and world(m) != 0


def walk(m, head):
    out, node, seen = [], head, set()
    while node and node not in seen and len(out) < 4000:
        seen.add(node)
        ent = u32(m, node)
        if ent:
            out.append(ent)
        node = u32(m, node + 4)
    return out


def entities(m):
    w = world(m)
    mgr = u32(m, w + 0x1768) if w else 0
    if not mgr:
        return []
    count = u32(m, mgr + 0x14)
    lists = {o: walk(m, u32(m, mgr + o)) for o in (0, 8, 0x18)}
    best = max(lists, key=lambda o: (len(lists[o]) == count, len(lists[o])))
    return lists[best]


def pos(m, e):
    return (f32(m, e + 0x6c), f32(m, e + 0x70), f32(m, e + 0x74))


def fields(m, e):
    return tuple(u32(m, e + o) for o in SYNC_OFF)


def players(m):
    w = world(m)
    if not w:
        return []
    mg = u32(m, w + 0x175c)
    if not mg:
        return []
    return [u32(m, u32(m, mg + 0xc) + 4 * i) for i in range(min(u32(m, mg + 4), 8))]


def humans(m):
    """This copy's humans by character tag (BOY1/GIR1/...) with their positions; a position that reads
    as garbage (the objects are rebuilt during a load) is left out. A human's position is at +0x23c
    (+0x240/+0x244), the field every other check uses (check_movement.py's H_POS): +0x6c is the
    position of a LEVEL entity (CToe*), not of a character."""
    out = {}
    for h in players(m):
        t, p = tag(u32(m, h + 0x14)), (f32(m, h + 0x23c), f32(m, h + 0x240), f32(m, h + 0x244))
        if t and all(abs(v) < 1e6 for v in p):
            out[t] = p
    return out


def live_items(m):
    """The game's own liveness test: active (+0x20 != 0), not collected (+0xa8 == 0), not broken
    (+0xa4 == 0), and the three interaction gates clear (+0xc0/+0xac/+0xb0)."""
    out = []
    for e in entities(m):
        if u32(m, e + 0x10) not in ITEM_TAGS:
            continue
        if u32(m, e + 0x20) and not u32(m, e + 0xa8) and not u32(m, e + 0xa4) \
                and not u32(m, e + 0xc0) and not u32(m, e + 0xac) and not u32(m, e + 0xb0):
            p = pos(m, e)
            if all(abs(v) < 1e6 for v in p):
                out.append((tag(u32(m, e + 0x10)), tuple(round(v, 1) for v in p), e))
    return out


def find_pt(m, cls, near):
    best, bd = 0, 1e18
    for e in entities(m):
        if u32(m, e + 0x10) != cls:
            continue
        p = pos(m, e)
        d = sum((p[i] - near[i]) ** 2 for i in range(3))
        if d < bd:
            bd, best = d, e
    return best


def find_save_point(m):
    """The level's CToeSavePoint ("SAVE"), nearest to player 1, from ALL THREE of the entity manager's
    lists (mgr+0/+8/+0x18). `entities()` picks one "best" list and can miss the save point after a
    location change: in the soak's J002 -> I100 load it found none although the entity tables were
    rebuilt (host log "world ... in level I100 is settled"), so the save test could not run."""
    w = world(m)
    mgr = u32(m, w + 0x1768) if w else 0
    if not mgr:
        return 0
    near = pos(m, players(m)[0]) if players(m) else (0.0, 0.0, 0.0)
    best, bd = 0, 1e18
    for off in (0, 8, 0x18):
        for e in walk(m, u32(m, mgr + off)):
            if u32(m, e + 0x10) != SAVEPT:
                continue
            p = pos(m, e)
            d = sum((p[i] - near[i]) ** 2 for i in range(3))
            if d < bd:
                bd, best = d, e
    return best


def wait_level(host_lvl, limit=90):
    t0, stable = time.time(), None
    while time.time() - t0 < limit:
        if in_level(H) and in_level(G) and level(H) == level(G) == host_lvl:
            if stable is None:
                stable = time.time()
            elif time.time() - stable >= 2.0:
                print('   both copies in level %s after %.1f s' % (tag(host_lvl), time.time() - t0))
                return True
        else:
            stable = None
        time.sleep(0.5)
    print('   NOT in one level after %d s (host %s/%s guest %s/%s)'
          % (limit, tag(level(H)) if world(H) else '-', mode(H), tag(level(G)) if world(G) else '-', mode(G)))
    return False


def wait_ready(limit=60):
    """The game's own "level ready" on BOTH copies, so a read is of finished characters and not of the
    objects a load is still rebuilding (FINDINGS_61 2.2 read a load half-way): mode 1, world state 1
    (world+0x11c), the same humans present with finite positions, those positions unchanged for 1 s."""
    t0, prev, stable = time.time(), None, None
    hh, gg = {}, {}
    while time.time() - t0 < limit:
        hh, gg = humans(H), humans(G)
        here = in_level(H) and in_level(G) and hh and set(hh) == set(gg) \
            and u32(H, world(H) + 0x11c) == 1 and u32(G, world(G) + 0x11c) == 1
        if here:
            same = prev is not None and set(prev[0]) == set(hh) and \
                all(math.dist(prev[0][t], hh[t]) <= 0.5 for t in hh) and \
                all(math.dist(prev[1][t], gg[t]) <= 0.5 for t in gg)
            if stable is None or not same:
                stable = time.time()
            elif time.time() - stable >= 1.0:
                print('   the level is ready on both copies after %.1f s (mode 1, world state 1, %s)'
                      % (time.time() - t0, '/'.join(sorted(hh))))
                return True
            prev = (hh, gg)
        else:
            prev = stable = None
        time.sleep(0.5)
    print('   the level is NOT ready on both copies after %d s (mode %s/%s, world state %s/%s, humans %s/%s)'
          % (limit, mode(H), mode(G), u32(H, world(H) + 0x11c) if world(H) else '-',
             u32(G, world(G) + 0x11c) if world(G) else '-', sorted(hh), sorted(gg)))
    return False


def walk_away(pipe, m, start, want=12.0):
    """Holds the move stick until this copy has moved `want` units away from `start`, trying the four
    directions in turn. Without a real walk the saved-spot comparison proves nothing (TASK 61's run
    "walked 0.0 units": it read +0x6c, a level-entity field, so even a walking host measured 0)."""
    best = 0.0
    for lx, ly in ((0, 32000), (32000, 0), (-32000, 0), (0, -32000)):
        pipe.cmd('pad 0 0 %d %d' % (lx, ly))
        t0 = time.time()
        while time.time() - t0 < 2.5:
            now = humans(m)
            best = max(best, max((math.dist(start[t], now[t]) for t in start if t in now), default=0.0))
            if best >= want:
                pipe.cmd('pad 0 0 0 0')
                time.sleep(0.5)
                return best
            time.sleep(0.25)
        pipe.cmd('pad 0 0 0 0')
        time.sleep(0.3)
    return best


def save_dirs():
    return [os.path.join(HOST_DIR, 'coop_profile', 'remote'), os.path.join(GUEST_DIR, 'coop_profile', 'remote'),
            os.path.join(HOST_DIR, 'Save'), os.path.join(GUEST_DIR, 'Save')]


def save_snap(d):
    out = {}
    for f in glob.glob(os.path.join(d, '*.sav')):
        try:
            out[os.path.basename(f)] = hashlib.sha256(open(f, 'rb').read()).hexdigest()
        except OSError:
            pass
    return out


def save_times(d):
    out = {}
    for f in glob.glob(os.path.join(d, '*.sav')):
        try:
            out[os.path.basename(f)] = os.stat(f).st_mtime_ns
        except OSError:
            pass
    return out


def dir_snap(d):
    out = {}
    for f in glob.glob(os.path.join(d, '*')):
        if os.path.isfile(f):
            try:
                out[os.path.basename(f)] = hashlib.sha256(open(f, 'rb').read()).hexdigest()
            except OSError:
                pass
    return out


def wait_save(m, name, sha, own_dir, other_dir, limit=30):
    """Waits for the saving copy to hold `sha` for `name`, then for the other copy to hold the same."""
    t0 = time.time()
    while time.time() - t0 < limit:
        if save_snap(own_dir).get(name) == sha:
            break
        time.sleep(0.5)
    if save_snap(own_dir).get(name) != sha:
        return False, 'the saving copy does not hold it'
    t0 = time.time()
    while time.time() - t0 < limit:
        if save_snap(other_dir).get(name) == sha:
            return True, 'both copies hold it'
        time.sleep(0.5)
    return False, 'the other copy has %s' % save_snap(other_dir).get(name, 'no file')


def reset_savepoint(m, pipe, who):
    """Puts this copy's save point in its idle state +0x14 = 0: the value the save point's own can-use
    check wants (FUN_0046e6c0) and the state its own save machine starts from (FUN_0046f330). The ten
    test saves store every save point in the post-save state 3 (FINDINGS_60 2), so a save loaded from
    one of them cannot save again without this. Test-only memory write, never done by the mod."""
    sp = find_save_point(m)
    if not sp:
        print('   %s: no save point in level %s' % (who, tag(level(m))))
        return 0
    if u32(m, sp + 0x14) != 0:
        print('   %s: save point +0x14 = %d (the state the save that made these saves left); setting 0'
              % (who, u32(m, sp + 0x14)))
        pipe.cmd('wr %x 00000000' % (sp + 0x14))
    return sp


def wait_state(m, want, limit):
    """Seconds until this copy's world reaches state `want` (world+0x11c), -1 on timeout."""
    t0 = time.time()
    while time.time() - t0 < limit:
        w = world(m)
        if w and u32(m, w + 0x11c) == want:
            return time.time() - t0
        time.sleep(0.3)
    return -1


def use_savepoint(pipe, m, pl, who):
    """Puts the level's save point in its idle state and makes this copy use it the way the interaction
    scan does (vtable slot 28, through the mod's TEST-ONLY `savepoint` pipe command)."""
    if not reset_savepoint(m, pipe, who):
        return False
    print('   %s: savepoint (player %d) -> %s' % (who, pl + 1, pipe.cmd('savepoint %d' % pl)))
    return True


def panel_save_item(m):
    """(panel, item) of the save panel (game+0x478): the item tagged "SFLO" (0x53464c4f)."""
    g = game(m)
    p = u32(m, g + 0x478) if g else 0
    if not p:
        return 0, 0
    n, arr = u32(m, p + 0x38), u32(m, p + 0x40)
    for i in range(min(n, 12)):
        c = u32(m, arr + 4 * i)
        if u32(m, c + 0x10) == 0x53464c4f:
            return p, c
    return p, 0


def drive_save(pipe, m, who):
    """The rest of the player's own save at a save point, with the game's own UI:
      1. the save point's machine (FUN_0046f330 state 0) waits for pad A -> the animation,
      2. 3 s animation + 3 s -> CLevel::Request_SaveGame -> world+0x11c = 10 and the save panel
         (menus\\save.xmc's SFLO item on game+0x478) shows its slot list after 999 ms,
      3. A picks the highlighted slot (state 2 -> 0x17 = the SPOP confirmation); DOWN + A picks the
         button that saves, which runs FUN_004a25e0 (the game's own SaveGame builder) in state 0x18;
      4. A closes the "save complete" popup (state 0x19), then the panel hides and world state 10 ends.
    A press before the slot list exists, or while a popup is still opening, is dropped; so each press
    waits for the item's own state instead of a fixed clock."""
    if wait_state(m, 11, 10) < 0:
        print('   %s: the save point use did not reach world state 11 (state %s)'
              % (who, u32(m, world(m) + 0x11c) if world(m) else '-'))
        return False
    time.sleep(0.8)
    press(pipe, 0, 'A', 0.25)
    shown = wait_state(m, 10, 25)
    if shown < 0:
        print('   %s: the save panel (world+0x11c = 10) did not open (state %s)'
              % (who, u32(m, world(m) + 0x11c) if world(m) else '-'))
        return False
    print('   %s: the save panel opened %.1f s after the pad A' % (who, shown))
    t0, last = time.time(), 0.0
    st2 = st17 = None
    confirms = ['DOWN', 'UP', 'LEFT', 'RIGHT']
    confirm_at = 0
    next_status = 0.0
    while time.time() - t0 < 70:
        p, c = panel_save_item(m)
        if not p or u32(m, p + 0x10) == 0:
            print('   %s: the save panel closed after %.1f s' % (who, time.time() - t0))
            return True
        st = u32(m, c + 0xe0) if c else -1
        now = time.time()
        if now >= next_status:
            next_status = now + 10.0
            print('   %s: t+%.0f save item state %d, panel on %d, world %d'
                  % (who, now - t0, st, u32(m, p + 0x10), u32(m, world(m) + 0x11c) if world(m) else -1))
        if st != 2:
            st2 = None
        if st != 0x17:
            st17 = None
        if st == 2:
            st2 = st2 or now
            if now - st2 >= 1.0 and now - last > 2.0:
                print('   %s: the slot list is ready (item state 2): pad A' % who)
                press(pipe, 0, 'A', 0.2)
                last = time.time()
        elif st == 0x17:
            # FUN_00553520(0x17) shows the SPOP confirmation (the save item's child at in_ECX[0x33]);
            # the state machine only proceeds once SPOP is closed (child+0x34 == 0) and then reads the
            # button that was picked (child+0xb8). The plain first button does not save: DOWN selects
            # the second one, A activates it (proved solo). The other directions are only a fallback.
            if st17 is None:
                st17 = now
                print('   %s: the save confirmation is up (item state 0x17): pad %s, then A'
                      % (who, confirms[confirm_at % len(confirms)]))
            elif now - st17 >= 2.5 and now - last > 3.0:
                press(pipe, 0, confirms[confirm_at % len(confirms)], 0.2)
                confirm_at += 1
                time.sleep(0.8)
                press(pipe, 0, 'A', 0.2)
                last = time.time()
        elif st == 0x19 and now - last > 2.0:
            # the write is done and the game shows its own "save complete" popup
            # (FUN_00553520(0x19) -> FUN_00546af0(0x8100005, 0x4000006)): A closes it, then the panel
            # hides itself and world state 10 completes.
            print('   %s: the save was written, the completion popup is up (item state 0x19): pad A' % who)
            press(pipe, 0, 'A', 0.2)
            last = time.time()
        time.sleep(0.4)
    print('   %s: the save panel did not close (world state %s)'
          % (who, u32(m, world(m) + 0x11c) if world(m) else '-'))
    return False


def wait_new_save(d, before_hash, before_time, limit=45):
    """Waits for the game to write a slot of folder `d` (its SHA-256 or its mtime changes)."""
    t0 = time.time()
    while time.time() - t0 < limit:
        now, now_t = save_snap(d), save_times(d)
        for k, v in now.items():
            if before_hash.get(k) != v or before_time.get(k) != now_t.get(k):
                return k, v, time.time() - t0
        time.sleep(0.5)
    return None, None, time.time() - t0


def save_phase():
    print('\n== A save: the same file on both copies')
    if level(H) != 0x49313030:
        # The soak's location changes leave the pair in another level (J002): the save test belongs in
        # I100, the level save 01 loads. Its save point is 89 units from the level start, inside the
        # mod's own 400-unit lookup for the `savepoint` command; a check-only entity scan is more lenient
        # than that lookup (in J002 it found a save point the mod could not reach), so the level, not the
        # scan, decides. A save made here also keeps game0.sav an I100 slot for the next session.
        print('   level %s is not I100: loading game0.sav (the pair\'s start slot)' % tag(level(H)))
        print('   loadsave -> %s' % HP.cmd('loadsave game0.sav'))
        if not wait_level(0x49313030):
            print('save: NOT DONE - the level with the save point (I100) did not load')
            fails.append('save')
            return
    sp, t0 = 0, time.time()
    while time.time() - t0 < 30 and not sp:
        sp = find_save_point(H)
        if not sp:
            time.sleep(1.0)
    if not sp:
        print('   level %s has no save point after %.0f s' % (tag(level(H)), time.time() - t0))
        print('save: NOT DONE - the level with the save point did not load')
        fails.append('save')
        return
    dirs = save_dirs()
    names = ['host remote', 'guest remote', 'host Save', 'guest Save']
    b_hash = [save_snap(d) for d in dirs]
    b_time = [save_times(d) for d in dirs]
    b_dir = [dir_snap(d) for d in dirs]
    for i, nm in enumerate(names):
        print('   before %-12s %d files: %s' % (nm, len(b_dir[i]), sorted(b_dir[i])))
    ok = True
    saved = 0
    slot = None
    # 1. the HOST saves at its save point (its own game path; the file goes to the guest)
    if not use_savepoint(HP, H, 0, 'host'):
        ok = False
    elif not drive_save(HP, H, 'host'):
        ok = False
    else:
        name, sha, dt = wait_new_save(dirs[0], b_hash[0], b_time[0])
        if name:
            saved += 1
            slot = name
            print('   the host\'s game wrote %s after %.1f s: sha256 %s' % (name, dt, sha))
            good, why = wait_save(H, name, sha, dirs[0], dirs[1])
            print('   guest remote %s: %s -> sha256 %s' % (name, why, save_snap(dirs[1]).get(name)))
            ok = ok and good
        else:
            print('   the host\'s game did NOT write a save in 45 s (world state %s)'
                  % (u32(H, world(H) + 0x11c) if world(H) else '-'))
    # 2. the GUEST uses its save point: the mod refuses that use on the guest and the HOST performs it
    #    with the game's own use on its copy of the save point, so the host's +0x14 must be idle too.
    print('   -- the guest\'s save point: the host performs that save')
    reset_savepoint(H, HP, 'host')
    g_hash, g_time = save_snap(dirs[0]), save_times(dirs[0])
    if not use_savepoint(GP, G, 1, 'guest'):
        ok = False
    elif not drive_save(HP, H, 'host (asked by the guest)'):
        ok = False
    else:
        name, sha, dt = wait_new_save(dirs[0], g_hash, g_time)
        if name:
            saved += 1
            slot = name
            print('   the host (asked by the guest) wrote %s after %.1f s: sha256 %s' % (name, dt, sha))
            good, why = wait_save(H, name, sha, dirs[0], dirs[1])
            print('   guest remote %s: %s -> sha256 %s' % (name, why, save_snap(dirs[1]).get(name)))
            ok = ok and good
        else:
            print('   no save file was written for the guest\'s request in 45 s (host world state %s)'
                  % (u32(H, world(H) + 0x11c) if world(H) else '-'))
    # 3. only that slot may have changed, and only inside coop_profile\remote (the game's own
    #    ISteamRemoteStorage folder through the mod's proxy; FINDINGS_60 section 2)
    print('   -- what changed in the save folders')
    a_dir = [dir_snap(d) for d in dirs]
    bak = (slot or '') + '.solo.bak'
    for i, nm in enumerate(names):
        changed = sorted(k for k in set(b_dir[i]) | set(a_dir[i]) if b_dir[i].get(k) != a_dir[i].get(k))
        print('   after  %-12s %d files changed: %s' % (nm, len(changed), changed or 'none'))
        if bak in changed:
            # TASK 62: the mod keeps this copy's own save once as <slot>.solo.bak before it replaces
            # bytes that differ (sync.c save_solo_keep, the save push and the join transfer alike).
            print('   %s: %s kept this copy\'s own %s before the save replaced it (sha256 %s)'
                  % (nm, bak, slot, a_dir[i][bak][:16]))
            if b_dir[i].get(slot) and a_dir[i][bak] != b_dir[i][slot]:
                print('   %s: %s is not the copy that was there before the save' % (nm, bak))
                ok = False
        other = [k for k in changed if k != slot and k != bak]
        if other:
            print('   %s changed a file that is not the saved slot: %s' % (nm, other))
            ok = False
        elif i >= 2 and slot in changed:
            # <exe>\Save is the mod's own mirror of what the game reads from coop_profile\remote
            # (sync.c save60_store writes both); the game itself writes only the remote folder.
            print('   %s: %s is the mod\'s mirror of the slot (sync.c save60_store), not a game write'
                  % (nm, slot))
    # The owner's data: the backup must be visible in the guest's own folders (its game save folder and
    # the Save mirror), holding exactly the file the save replaced.
    for i in (1, 3):
        listing = sorted(a_dir[i])
        print('   %-12s listing: %s' % (names[i], listing))
        if bak in a_dir[i]:
            print('   %-12s %s = %s (sha256 %s)'
                  % (names[i], bak, 'the copy that was there before the save'
                     if b_dir[i].get(slot) == a_dir[i][bak]
                     else 'an earlier copy, not the one there before this save', a_dir[i][bak][:16]))
        elif i == 1:
            print('   guest remote: no %s: the guest\'s own save was replaced without a backup' % bak)
            ok = False
    if saved == 0:
        print('save: NOT DONE - no save file was written by the game')
        print('   host save counters:  %s' % [s for s in HP.cmd('sync').split('|') if 'saves sent' in s or 'savept' in s])
        print('   guest save counters: %s' % [s for s in GP.cmd('sync').split('|') if 'saves sent' in s or 'savept' in s])
        print('save FAIL')
        fails.append('save')
        return
    # 4. the next session: both copies load the save they both hold and come up in the same place.
    #    The game's own save at a save point carries NO player position (probe62: walk 74 units away, save
    #    at the save point, load -> exactly the level's own start again; none of the live positions or the
    #    save point's own is anywhere in the 40 KB file), so a load restarts the level from its start, not
    #    from the spot the player stood on. What the next session must show is therefore that BOTH copies
    #    come up in the same place, and that the load really ran (the host is no longer where it walked
    #    to). The distance from the live saved spot is printed as information only.
    print('   -- the next session: both copies load %s' % slot)
    saved_at = humans(H)
    if not saved_at:
        print('   the host reads no human position at the saved spot')
    walked = walk_away(HP, H, saved_at)
    walked_at = humans(H)
    print('   the host walked %.1f units away from the saved spot' % walked)
    if walked <= 10:
        print('   the host did not get away from the saved spot: the reload cannot be told from standing still')
        ok = False
    lv = level(H)
    print('   loadsave -> %s' % HP.cmd('loadsave ' + slot))
    if not wait_level(lv):
        print('   the save did not load on both copies')
        ok = False
    elif not wait_ready():
        print('   the loaded level never became ready on both copies')
        ok = False
    else:
        good = False
        stable = None
        t0 = time.time()
        last_note = t0
        while time.time() - t0 < 45:
            hs, gs = humans(H), humans(G)
            if hs and set(hs) == set(gs) and all(any(abs(v) > 1e-3 for v in p) for p in hs.values()):
                ds = {t: math.dist(hs[t], gs[t]) for t in hs}
                if max(ds.values()) <= 2.5:
                    if stable is None:
                        stable = (hs, time.time())
                    elif time.time() - stable[1] >= 1.5 and \
                            all(math.dist(stable[0][t], hs[t]) <= 0.5 for t in hs):
                        good = True
                        print('   both copies hold %s within %.2f units after %.1f s: %s'
                              % ('/'.join(sorted(ds)), max(ds.values()), time.time() - t0,
                                 {t: round(v, 2) for t, v in sorted(ds.items())}))
                        back = {t: math.dist(saved_at[t], hs[t]) for t in saved_at if t in hs}
                        if back:
                            print('   distance from the live saved spot (the game restores the level '
                                  'start, not that spot): %s'
                                  % {t: round(v, 1) for t, v in sorted(back.items())})
                        off = {t: math.dist(walked_at[t], hs[t]) for t in walked_at if t in hs}
                        if off:
                            print('   the load moved the host %.1f units off the spot it walked to'
                                  % max(off.values()))
                            if max(off.values()) <= 10:
                                print('   the host is still where it walked to: the load did not restart '
                                      'the level')
                                good = False
                        break
                else:
                    stable = None
            else:
                stable = None
            if time.time() - last_note > 10:
                last_note = time.time()
                print('   waiting for both copies to settle: host %s guest %s' % (hs, gs))
            time.sleep(1.0)
        if not good:
            print('   the two copies are NOT in the same place after the load (host %s guest %s)'
                  % (humans(H), humans(G)))
            ok = False
    if ok:
        print('save OK: every save file the game wrote on one copy is byte-identical on the other, and '
              'the file loads into the same place on both')
    else:
        print('save FAIL')
        fails.append('save')


def item_phase():
    print('\n== B items: both copies list the same live world items')
    lh, lg = live_items(H), live_items(G)
    print('   host live items: %s' % ([(c, p) for c, p, _ in lh] or 'none'))
    print('   guest live items: %s' % ([(c, p) for c, p, _ in lg] or 'none'))
    same = [(c, p) for c, p, _ in lh] == [(c, p) for c, p, _ in lg]
    print('   live item lists equal: %s' % same)
    if not same:
        fails.append('items-list')
    # Make one inactive item live on the HOST only; the guest must show it (the host's world packet).
    cand = None
    for e in entities(H):
        if u32(H, e + 0x10) in ITEM_TAGS and u32(H, e + 0x20) == 0 and u32(H, e + 0xa8) == 0:
            cand = e
            break
    if not cand:
        print('   no inactive item entity on the host to activate: propagation not measured')
        return
    print('   host: activate item %s %x (+0x20 = 1, the test write check_pickup.py uses)'
          % (tag(u32(H, cand + 0x10)), cand))
    print('   wr -> %s' % HP.cmd('wr %x 01000000' % (cand + 0x20)))
    cls, p = u32(H, cand + 0x10), pos(H, cand)
    t0, ok = time.time(), False
    while time.time() - t0 < 12:
        for c, q, e in live_items(G):
            if c == tag(cls) and all(abs(q[i] - p[i]) <= 1.0 for i in range(3)):
                ok = True
                print('   guest shows the same live item after %.1f s: %s at %.1f,%.1f,%.1f' % (time.time() - t0, c, *q))
                break
        if ok:
            break
        time.sleep(1.0)
    if not ok:
        print('   guest does NOT show the host\'s live item (live: %s)' % ([(c, q) for c, q, _ in live_items(G)] or 'none'))
        fails.append('items-propagation')
    print('   host worlds: %s' % HP.cmd('worlds').split(':')[0])
    print('   guest worlds: %s' % GP.cmd('worlds').split(':')[0])
    if ok:
        print('items OK: the guest\'s live item set follows the host\'s')


def container_phase():
    print('\n== C containers: the same opened/used state on both copies')
    lvl = level(H)
    fam = [e for e in entities(H) if u32(H, e + 0x10) in CONTAINER_TAGS]
    if not fam:
        print('   level %s has no container-family entity: loading game7.sav (H006, 3 CToePedestal)' % tag(lvl))
        print('   loadsave -> %s' % HP.cmd('loadsave game7.sav'))
        if not wait_level(0x48303036):   # "H006"
            print('container: NOT DONE - the level with the container family did not load')
            fails.append('container-load')
            return
        fam = [e for e in entities(H) if u32(H, e + 0x10) in CONTAINER_TAGS]
    print('   %d container-family entities in level %s' % (len(fam), tag(level(H))))
    ok = True
    cls, p = u32(H, fam[0] + 0x10), pos(H, fam[0])
    for who, pipe, m, pl in (('host', HP, H, 0), ('guest', GP, G, 1)):
        ent = find_pt(m, cls, p)
        if not ent:
            print('   %s: %s at %.1f,%.1f,%.1f is not in this copy\'s entity list' % (who, tag(cls), *p))
            ok = False
            continue
        before_h, before_g = fields(H, find_pt(H, cls, p)), fields(G, find_pt(G, cls, p))
        print('   %s uses %s %x at %.1f,%.1f,%.1f: %s'
              % (who, tag(cls), ent, *p, pipe.cmd('useobj %x %d' % (ent, pl))))
        time.sleep(3.0)
        fh, fg = fields(H, find_pt(H, cls, p) or fam[0]), fields(G, find_pt(G, cls, p) or ent)
        print('   host  fields %s' % (fh,))
        print('   guest fields %s' % (fg,))
        if fh != fg:
            print('   %s: the two copies disagree on the container state' % who)
            ok = False
        elif fh == before_h and fg == before_g:
            print('   (the game\'s own use changed none of the synced fields in this save)')
    # The game action that sets a pedestal's placed flag (+0x128) needs a STAT statuette entity, and no
    # test save has one. The flag is the field the pedestal's own use checks (FUN_00449df0), so flip it on
    # the HOST only and require the guest to follow: that is the A1-9 "opened/used on both" mechanism.
    eh = find_pt(H, cls, p)
    if eh:
        was = u32(H, eh + 0x128)
        print('   host: %s +0x128 = %d -> %d (its "placed" flag; no STAT entity exists in these saves)'
              % (tag(cls), was, 0 if was else 1))
        print('   wr -> %s' % HP.cmd('wr %x %s' % (eh + 0x128, '01000000' if not was else '00000000')))
        want = 0 if was else 1
        t0, seen = time.time(), False
        while time.time() - t0 < 12:
            eg = find_pt(G, cls, p)
            if eg and u32(G, eg + 0x128) == want:
                seen = True
                print('   guest shows %s +0x128 = %d after %.1f s' % (tag(cls), want, time.time() - t0))
                break
            time.sleep(1.0)
        if not seen:
            eg = find_pt(G, cls, p)
            print('   guest does NOT show the host\'s container state (guest %s)'
                  % (('fields %s' % (fields(G, eg),)) if eg else 'has no such entity'))
            ok = False
    if ok:
        print('containers OK: the same state on both copies after each player used them')
    else:
        print('containers FAIL')
        fails.append('containers')


if '--skip-save' not in SKIP:
    save_phase()
if '--skip-items' not in SKIP:
    item_phase()
if '--skip-container' not in SKIP:
    container_phase()

print('\nsummary: fails %s' % (fails or 'none'))
if fails:
    print('check_world: FAIL (%s)' % ', '.join(fails))
    sys.exit(1)
print('check_world: OK')
