"""TASK 26 screenshots: player 1 carries a chair, then breaks it, on both copies.
Usage: python -I shoot_breakables.py <host pid> <guest pid> <outdir>
"""
import ctypes, ctypes.wintypes as W, sys, os, struct, time
TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)
import bot
from peek import Proc

GAME = 0x6c3068
CHAI = 0x43484149


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
    col = u32(m, vt - 4) if vt else 0
    td = u32(m, col + 0xc) if col else 0
    raw = (m.read(td + 8, 160) if td else b'') or b''
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


def d3(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def chairs(m):
    return [e for e in ents(m) if u32(m, e + 0x10) == CHAI or 'CToeChair' in rtti(m, e)]


def wait_for(fn, secs):
    t = time.time()
    while time.time() - t < secs:
        if fn():
            return True, time.time() - t
        time.sleep(0.1)
    return False, time.time() - t


user32 = ctypes.WinDLL('user32', use_last_error=True)
gdi32 = ctypes.WinDLL('gdi32')
user32.SetWindowPos.argtypes = [W.HWND, W.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.SetWindowPos.restype = W.BOOL
WNDENUMPROC = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)


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


def grab(hwnd, method):
    r = W.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    w, hh = r.right, r.bottom
    wdc = user32.GetDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(wdc)
    bmp = gdi32.CreateCompatibleBitmap(wdc, w, hh)
    gdi32.SelectObject(mdc, bmp)
    if method == 'print':
        ok = user32.PrintWindow(hwnd, mdc, 3)
    else:
        pt = W.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(pt))
        sdc = user32.GetDC(0)
        ok = gdi32.BitBlt(mdc, 0, 0, w, hh, sdc, pt.x, pt.y, 0x00CC0020 | 0x40000000)
        user32.ReleaseDC(0, sdc)
    bih = BIH(ctypes.sizeof(BIH), w, -hh, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = (ctypes.c_ubyte * (w * hh * 4))()
    gdi32.GetDIBits(mdc, bmp, 0, hh, buf, ctypes.byref(bih), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, wdc)
    return w, hh, bytes(buf), ok


def nonblack(px):
    n = 0
    for i in range(0, len(px) - 4, 4 * 97):
        if px[i] + px[i + 1] + px[i + 2] > 24:
            n += 1
    return n / max(1, len(px) // (4 * 97))


def shot2(pid, path):
    """Raise the game window and capture it, the same way tests/shot_pair.py does: a D3D9 window that is
    covered, unfocused or minimised hands out black frames until it is in front (and on the last attempt
    clicked). PrintWindow first, the screen's own pixels second."""
    hwnd = window_of(pid)
    if not hwnd:
        print('  no window for pid %d' % pid)
        return
    best = None
    for attempt in range(4):
        for method in ('print', 'screen'):
            w, hh, px, ok = grab(hwnd, method)
            frac = nonblack(px)
            print('  %s: %s try %d %dx%d ok %d non-black %.1f%%' % (
                os.path.basename(path), method, attempt + 1, w, hh, ok, frac * 100))
            if best is None or frac > best[3]:
                best = (w, hh, px, frac)
            if frac > 0.02:
                bot.write_png(path, w, hh, px)
                user32.SetWindowPos(hwnd, W.HWND(-2), 0, 0, 0, 0, 0x0001 | 0x0002)   # NOTOPMOST, NOMOVE|NOSIZE
                return
        if attempt == 0:
            user32.ShowWindow(hwnd, 9)   # SW_RESTORE
            user32.ShowWindow(hwnd, 4)   # SW_SHOWNOACTIVATE
            user32.SetWindowPos(hwnd, W.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
            print('  %s: restored and put in front' % os.path.basename(path))
            time.sleep(1.5)
        elif attempt == 1:
            user32.SetWindowPos(hwnd, W.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
            user32.SetForegroundWindow(hwnd)
            time.sleep(1.5)
        elif attempt == 2:
            r = W.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            x, y = (r.left + r.right) // 2, (r.top + r.bottom) // 2
            user32.SetCursorPos(x, y)
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            print('  %s: clicked at %d,%d to activate it' % (os.path.basename(path), x, y))
            time.sleep(1.5)
    bot.write_png(path, best[0], best[1], best[2])
    print('  %s: still black' % os.path.basename(path))


def main():
    hp, gp, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    os.makedirs(out, exist_ok=True)
    mh, mg = Proc(hp), Proc(gp)
    ph = bot.Pipe(hp)
    t = time.time()
    while time.time() - t < 90 and not (world(mh) and chairs(mh)):
        time.sleep(0.5)
    time.sleep(2)
    usable = [e for e in chairs(mh) if u32(mh, e + 0x24) and not u32(mh, e + 0xa4)]
    print('level %s, usable chairs %d' % (tag(u32(mh, world(mh) + 4)), len(usable)))
    if not usable:
        print('no usable chair: cannot take the pictures')
        return 1
    me = ctl_human(mh, 0)
    e = min(usable, key=lambda x: d3(epos(mh, x), hpos(mh, me)))
    cp = epos(mh, e)
    pp = hpos(mh, me)
    print('chair @%x at (%.1f,%.1f,%.1f), P1 at (%.1f,%.1f,%.1f)' % (e, cp[0], cp[1], cp[2], pp[0], pp[1], pp[2]))
    ok = False
    for radius in (55.0, 75.0, 95.0, 30.0):
        dx, dy = pp[0] - cp[0], pp[1] - cp[1]
        dd = (dx * dx + dy * dy) ** 0.5 or 1.0
        stand = (cp[0] + dx / dd * radius, cp[1] + dy / dd * radius, cp[2])
        r = ph.cmd('tp 0 %.3f %.3f %.3f %.3f %.3f' % (stand[0], stand[1], stand[2], cp[0] - stand[0], cp[1] - stand[1]))
        print('tp r=%.0f -> %s' % (radius, r))
        if r.startswith('ok'):
            ok = True
            break
    if not ok:
        print('tp refused; no pictures')
        return 1
    time.sleep(1.2)
    shot2(hp, os.path.join(out, 'carry_before_host.png'))
    shot2(gp, os.path.join(out, 'carry_before_guest.png'))
    for i in range(3):
        bot.press(ph, 0, 'A')
        got, secs = wait_for(lambda: u32(mh, ctl_human(mh, 0) + 0x2bc) != 0, 1.5)
        if got:
            break
    print('carry: %s after %.1f s (host chair carrier %x, guest chair carrier %x)' % (
        got, secs, u32(mh, e + 0xc4), u32(mg, e + 0xc4)))
    time.sleep(0.6)
    shot2(hp, os.path.join(out, 'carry_host.png'))
    shot2(gp, os.path.join(out, 'carry_guest.png'))
    broke = False
    for i in range(4):
        bot.press(ph, 0, 'A')
        broke, secs2 = wait_for(lambda: u32(mh, e + 0xa4) != 0, 1.6)
        if broke:
            break
    print('break: %s after %.1f s (host broken %d, guest broken %d)' % (
        broke, secs2, u32(mh, e + 0xa4), u32(mg, e + 0xa4)))
    time.sleep(1.0)
    shot2(hp, os.path.join(out, 'broken_host.png'))
    shot2(gp, os.path.join(out, 'broken_guest.png'))
    print('pictures in', out)
    return 0


sys.exit(main())
