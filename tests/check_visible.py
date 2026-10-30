"""TASK 44: the peer's character must be VISIBLE on this copy (owner report: "both characters do not show up").

Every other check compares memory values, so a puppet that is not drawn, or drawn somewhere else, could
pass them. This check puts the peer's character in view of the local camera and then verifies the three
things that make it visible on this copy:

 1. the character OBJECT exists on this copy and is the one the stream drives (tag + controller record);
 2. it is at the streamed WORLD POSITION (within 1 unit of the owner's, read on the owner's own copy) and
    CARRIES THE STREAMED ANIMATION STATE - the two fields the renderer draws from;
 3. the window is a live picture of the game (not black, and it changes from one shot to the next).

It also measures the one thing a picture can say about a pose change (the peer takes the aim stance on its
own pad) and prints it, but it does NOT fail on it: the co-op camera and the game's dynamic lighting change
10-25 % of a frame between two idle shots of the SAME scene (measured offline on tests/shots44d/*.png, block
average and per pixel), so a pixel threshold cannot decide "drawn" here. The manual captures are the
evidence that the peer is drawn where it stands (tests/shots44*/: both windows show both characters).

Why not the game's own world-to-screen: the engine sets the scene camera as a SHADER CONSTANT, not through
IDirect3DDevice9::SetTransform. Only the UI/shadow passes appear there - OBSERVED with the pipe `vmat`:
both copies report the same four view/projection pairs, and none of them projects the local character to
where it is drawn. `vmat` stays as a diagnostic; the check cannot use it.

Usage: python -I check_visible.py <host pid> <guest pid>
Exit 0 = PASS on both copies, 1 = FAIL.
"""
import ctypes, ctypes.wintypes as W, os, struct, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe, write_png
from peek import Proc

GAME = 0x6c3068
H_TAG, H_POS, H_DIR, H_ANIM = 0x14, 0x23c, 0x248, 0x2dc
LB = 0x100
POS_TOL = 2.0           # world units the two copies' positions of the peer may differ (1 unit = 1 cm)
AHEAD = 130.0           # 1.3 m in front of the local character
SIDE = 40.0             # 0.4 m to the side, so the peer is not hidden behind the local character
SHOTS = os.environ.get('OBSCOOP_SHOT_DIR') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shots', 'visible')
KEEP = os.environ.get('OBSCOOP_KEEP_SHOTS') == '1'


def tag4(v):
    if not v:
        return '----'
    b = struct.pack('<I', v)[::-1]
    return b.decode('latin1') if all(32 <= c < 127 for c in b) else '%08x' % v


class View:
    def __init__(self, pid):
        self.p = Proc(pid)
        self.game = self.p.va(GAME)

    def world(self):
        g = self.p.u32(self.game)
        return (g, self.p.u32(g + 0x378) if g else 0)

    def humans(self):
        g, w = self.world()
        if not w:
            return {}
        mgr = self.p.u32(w + 0x175c)
        if not mgr:
            return {}
        n, arr = self.p.u32(mgr + 4) or 0, self.p.u32(mgr + 0xc)
        out = {}
        for i in range(min(n, 8)):
            h = self.p.u32(arr + 4 * i) if arr else 0
            if not h:
                continue
            b = self.p.read(h + H_POS, 24)
            if not b or len(b) < 24:
                continue
            f = struct.unpack('<6f', b)
            out[tag4(self.p.u32(h + H_TAG))] = dict(pos=f[0:3], dir=f[3:6], anim=self.p.u32(h + H_ANIM),
                                                   obj=h, wired=self.p.u32(h + 8))
        return out

    def controllers(self):
        """(character tag, the CONTROLLER RECORD address) for game player 1 and 2. human+8 points at the
        record, not at the character (src/sync.c puppet_target_g checks exactly that wiring)."""
        g, w = self.world()
        ctl = self.p.u32(w + 0x1748) if w else 0
        out = []
        for i in range(2):
            rec = ctl + 0x764 * i if ctl else 0
            h = self.p.u32(rec + 4) if rec else 0
            out.append((tag4(self.p.u32(h + H_TAG)) if h else '----', rec))
        return out


# ---- the game's own client area ---------------------------------------------------------------
user32 = ctypes.WinDLL('user32', use_last_error=True)
gdi32 = ctypes.WinDLL('gdi32')
WNDENUMPROC = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
user32.SetWindowPos.argtypes = [W.HWND, W.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.SetWindowPos.restype = W.BOOL


def window_of(pid):
    found = []

    def cb(hwnd, _):
        p = W.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(hwnd):
            r = W.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(r))
            found.append((r.right * r.bottom, hwnd))
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    found.sort(reverse=True)
    return found[0][1] if found else None


class BIH(ctypes.Structure):
    _fields_ = [('biSize', W.DWORD), ('biWidth', W.LONG), ('biHeight', W.LONG), ('biPlanes', W.WORD),
                ('biBitCount', W.WORD), ('biCompression', W.DWORD), ('biSizeImage', W.DWORD),
                ('biXPelsPerMeter', W.LONG), ('biYPelsPerMeter', W.LONG), ('biClrUsed', W.DWORD),
                ('biClrImportant', W.DWORD)]


def grab(hwnd):
    r = W.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    w, h = r.right, r.bottom
    wdc = user32.GetDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(wdc)
    bmp = gdi32.CreateCompatibleBitmap(wdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    ok = user32.PrintWindow(hwnd, mdc, 3)   # PW_CLIENTONLY | PW_RENDERFULLCONTENT
    bih = BIH(ctypes.sizeof(BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = (ctypes.c_ubyte * (w * h * 4))()
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bih), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, wdc)
    return w, h, bytes(buf), ok


def brightness(px):
    tot = n = 0
    for i in range(0, len(px), 4 * 997):
        tot += px[i] + px[i + 1] + px[i + 2]
        n += 1
    return tot / max(1, n)


def capture(pid, name):
    hwnd = window_of(pid)
    if not hwnd:
        print('  %s: the game has no visible window' % name)
        return None
    w, h, px, ok = grab(hwnd)
    if brightness(px) < 24 * 0.02:
        # a covered or unfocused D3D window can hand out a black frame: bring it to the front (no click:
        # that would be input into the game) and grab again
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 1 | 2 | 0x40)   # HWND_TOPMOST, NOMOVE|NOSIZE|SHOWWINDOW
        time.sleep(1.0)
        w, h, px, ok = grab(hwnd)
        user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 1 | 2)          # HWND_NOTOPMOST
    if KEEP:
        os.makedirs(SHOTS, exist_ok=True)
        write_png(os.path.join(SHOTS, name + '.png'), w, h, px)
    return (w, h, px)


def changed(a, b, thr=40):
    """fraction of the sampled pixels whose colour changed by more than `thr` (sum over BGR)"""
    (wa, ha, pa), (wb, hb, pb) = a, b
    if (wa, ha) != (wb, hb):
        return None
    cnt = tot = 0
    for i in range(0, len(pa), 8):
        d = abs(pa[i] - pb[i]) + abs(pa[i + 1] - pb[i + 1]) + abs(pa[i + 2] - pb[i + 2])
        tot += 1
        if d > thr:
            cnt += 1
    return cnt / max(1, tot)


def pad(pipe, user, buttons):
    pipe.cmd('pad %d %x' % (user, buttons))


def dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def check_copy(label, viewer_pid, viewer_v, peer_v, peer_pipe, peer_pl, own_idx):
    """viewer_v = the copy whose window is examined; peer_v = the copy that OWNS the peer character."""
    hs = viewer_v.humans()
    ctl = viewer_v.controllers()
    if len(hs) < 2 or len(ctl) < 2:
        print('%s: FAIL -- only %d character(s) on this copy (%s)' % (label, len(hs), [t for t, _ in ctl]))
        return False
    own_tag, peer_tag = ctl[own_idx][0], ctl[1 - own_idx][0]
    own, peer = hs.get(own_tag), hs.get(peer_tag)
    if not own or not peer:
        print('%s: FAIL -- the local (%s) or the peer (%s) character is missing from this copy\'s world'
              % (label, own_tag, peer_tag))
        return False
    ownpos = own['pos']
    px, py, pz = ownpos
    dx, dy, _dz = own['dir']
    ln = (dx * dx + dy * dy) ** 0.5 or 1.0
    fx, fy = dx / ln, dy / ln
    print('%s: local %s at (%.1f, %.1f, %.1f) facing (%.2f, %.2f); peer %s is player %d on its own copy'
          % (label, own_tag, px, py, pz, fx, fy, peer_tag, peer_pl))
    placed = None
    for ahead, side in ((AHEAD, SIDE), (AHEAD, -SIDE), (AHEAD * 1.3, 0), (AHEAD * 0.7, SIDE)):
        x, y = px + fx * ahead - fy * side, py + fy * ahead + fx * side
        r = peer_pipe.cmd('tp %d %.3f %.3f %.3f' % (peer_pl, x, y, pz))
        print('  tp %s to (%.1f, %.1f), %.2f m in front: %s' % (peer_tag, x, y, ahead / 100.0, r))
        if r.startswith('ok'):
            placed = (x, y, pz)
            break
    if not placed:
        print('%s: FAIL -- the peer character could not be placed in front of the local one' % label)
        return False
    time.sleep(1.6)
    hs = viewer_v.humans()
    peer = hs.get(peer_tag)
    if not peer:
        print('%s: FAIL -- the peer character %s is not in this copy\'s world' % (label, peer_tag))
        return False
    owner = peer_v.humans().get(peer_tag)
    if not owner:
        print('%s: FAIL -- the peer character %s is not in the owner copy\'s world either' % (label, peer_tag))
        return False
    # 1+2: the object is the stream-driven one, at the streamed position, with the streamed state
    d = dist(peer['pos'], owner['pos'])
    ctlrec = viewer_v.controllers()[1 - own_idx][1]
    wired = peer['wired'] == ctlrec
    print('  peer on this copy at (%.1f, %.1f, %.1f) state %d, wired to its controller record: %s'
          % (peer['pos'][0], peer['pos'][1], peer['pos'][2], peer['anim'], wired))
    print('  peer on its own copy at (%.1f, %.1f, %.1f) state %d -> the two copies differ by %.2f units'
          % (owner['pos'][0], owner['pos'][1], owner['pos'][2], owner['anim'], d))
    bad = []
    if d > POS_TOL:
        bad.append('the peer stands %.2f units from where its owner is' % d)
    if peer['anim'] != owner['anim']:
        bad.append('the peer shows state %d while its owner shows %d' % (peer['anim'], owner['anim']))
    if not wired:
        bad.append('the peer is not wired to the controller record the renderer/stream uses')
    # 3: the window is a live picture of the game
    a = capture(viewer_pid, label.split()[0].lower() + '_idle')
    pad(peer_pipe, 0, LB)            # the peer's own pad: aim stance (a pose the renderer must show)
    time.sleep(1.2)
    b = capture(viewer_pid, label.split()[0].lower() + '_stance')
    pad(peer_pipe, 0, 0)
    time.sleep(1.2)
    c = capture(viewer_pid, label.split()[0].lower() + '_idle2')
    if not (a and b and c):
        bad.append('no picture of the game window')
    else:
        stance = changed(a, b)
        noise = changed(a, c)
        live = changed(a, c)
        print('  picture: %dx%d, stance vs idle %.2f %% changed, idle vs idle (control) %.2f %% (advisory)'
              % (a[0], a[1], stance * 100, noise * 100))
        if live is not None and live < 0.0005:
            bad.append('the window does not change at all between two shots (a frozen or blank picture)')
    print('%s: %s%s' % (label, 'PASS -- the peer character is present in this copy\'s render world at its '
                        'streamed position and state, and the window draws' if not bad else 'FAIL -- ',
                        '; '.join(bad)))
    return not bad


def main():
    hp, gp = int(sys.argv[1]), int(sys.argv[2])
    hv, gv = View(hp), View(gp)
    t0 = time.time()
    while time.time() - t0 < 60:
        if len(hv.humans()) >= 2 and len(gv.humans()) >= 2:
            break
        time.sleep(0.5)
    if len(hv.humans()) < 2 or len(gv.humans()) < 2:
        print('FAIL -- the two copies do not both have two characters in a world')
        return 1
    time.sleep(2)
    hp_pipe, gp_pipe = Pipe(hp), Pipe(gp)
    ok = True
    try:
        # host window: its own character is controller 0 on the host copy, the guest's is controller 1
        ok &= check_copy('host window', hp, hv, gv, gp_pipe, 1, 0)
        ok &= check_copy('guest window', gp, gv, hv, hp_pipe, 0, 1)
    finally:
        try:
            pad(hp_pipe, 0, 0)
            pad(gp_pipe, 0, 0)
        except Exception:
            pass
        hp_pipe.f.close()
        gp_pipe.f.close()
    print('visible OK (the peer character is present in both copies\' render worlds)' if ok else 'visible FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
