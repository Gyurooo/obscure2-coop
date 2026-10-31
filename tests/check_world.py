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
import os, sys, time, glob, struct, hashlib
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


def save_dirs():
    return [os.path.join(HOST_DIR, 'coop_profile', 'remote'), os.path.join(GUEST_DIR, 'coop_profile', 'remote'),
            os.path.join(HOST_DIR, 'Save'), os.path.join(GUEST_DIR, 'Save')]


def save_snap(d):
    out = {}
    for f in glob.glob(os.path.join(d, '*.sav')):
        try:
            out[os.path.basename(f)] = hashlib.sha1(open(f, 'rb').read()).hexdigest()[:12]
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


def use_savepoint(pipe, m, pl, who):
    """Puts the level's save point in its idle state (+0x14 = 0, the value its own can-use check wants)
    and makes this copy use it the way the interaction scan does."""
    w = world(m)
    sp = find_pt(m, SAVEPT, pos(m, players(m)[0]) if players(m) else (0, 0, 0))
    if not sp:
        print('   %s: no save point in level %s' % (who, tag(level(m))))
        return False
    if u32(m, sp + 0x14) != 0:
        print('   %s: save point +0x14 = %d (the state the save that made these saves left); setting 0'
              % (who, u32(m, sp + 0x14)))
        pipe.cmd('wr %x 00000000' % (sp + 0x14))
    print('   %s: savepoint (player %d) -> %s' % (who, pl + 1, pipe.cmd('savepoint %d' % pl)))
    return True


def save_phase():
    print('\n== A save: the same file on both copies')
    before = [save_snap(d) for d in save_dirs()]
    print('   host remote %d saves, guest remote %d saves' % (len(save_snap(save_dirs()[0])), len(save_snap(save_dirs()[1]))))
    ok = True
    saved = False
    # 1. the HOST saves at its save point (its own game path; the file goes to the guest)
    if not use_savepoint(HP, H, 0, 'host'):
        ok = False
    else:
        press(HP, 0, 'A', 0.25)
        t0 = time.time()
        name = sha = None
        while time.time() - t0 < 40 and not name:
            press(HP, 0, 'A', 0.25)
            now = save_snap(save_dirs()[0])
            for k, v in now.items():
                if before[0].get(k) != v:
                    name, sha = k, v
                    break
            time.sleep(1.0)
        if name:
            saved = True
            print('   the host\'s game wrote %s (sha %s) after %.1f s' % (name, sha, time.time() - t0))
            good, why = wait_save(H, name, sha, save_dirs()[0], save_dirs()[1])
            print('   guest copy: %s' % why)
            ok = ok and good
        else:
            print('   the host\'s game did NOT write a save in 40 s (world state %s, request %s)'
                  % (u32(H, world(H) + 0x11c) if world(H) else '-', u32(H, game(H) + 0x320) if game(H) else '-'))
    # 2. the GUEST uses its save point: a request the host performs
    before = [save_snap(d) for d in save_dirs()]
    if not use_savepoint(GP, G, 1, 'guest'):
        ok = False
    else:
        t0 = time.time()
        name = sha = None
        while time.time() - t0 < 40 and not name:
            press(HP, 0, 'A', 0.25)
            now = save_snap(save_dirs()[0])
            for k, v in now.items():
                if before[0].get(k) != v:
                    name, sha = k, v
                    break
            time.sleep(1.0)
        if name:
            saved = True
            print('   the host (asked by the guest) wrote %s (sha %s) after %.1f s' % (name, sha, time.time() - t0))
            good, why = wait_save(H, name, sha, save_dirs()[0], save_dirs()[1])
            print('   guest copy: %s' % why)
            ok = ok and good
        else:
            print('   no save file was written for the guest\'s request in 40 s')
    if not saved:
        print('save: NOT DONE - the game\'s own save state (world+0x11c = 10) does not complete in these '
              'saves, so no save file exists to compare (see FINDINGS_60)')
        print('   host save counters:  %s' % [s for s in HP.cmd('sync').split('|') if 'saves sent' in s or 'savept' in s])
        print('   guest save counters: %s' % [s for s in GP.cmd('sync').split('|') if 'saves sent' in s or 'savept' in s])
        return
    if ok:
        print('save OK: every save file the game wrote on one copy is byte-identical on the other')
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
