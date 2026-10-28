"""Pictures of what both copies actually draw, after save 01 loaded and the hands converged.

Usage: python -I shot_pair.py <host pid> <guest pid> [outdir]

Captures each copy's own game window from outside the game (PrintWindow with PW_RENDERFULLCONTENT; if
that comes back blank, a BitBlt of the window's client area from the screen), saves host.png / guest.png
in tests/shots/ and prints:
  * the window state (visible / iconic / size) - the test setup keeps the windows hidden and unfocused,
    so this says whether that is even the situation the owner saw,
  * a numeric difference between the two frames (whole picture and the lower-centre area where the
    characters stand).
Works whether or not the game keeps rendering to a hidden window; no game code is involved.
"""
import ctypes, ctypes.wintypes as W, os, struct, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from peek import Proc
from bot import write_png

OUT = os.path.abspath(sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shots'))
os.makedirs(OUT, exist_ok=True)
h, g = int(sys.argv[1]), int(sys.argv[2])
user32 = ctypes.WinDLL('user32', use_last_error=True)
gdi32 = ctypes.WinDLL('gdi32')

WNDENUMPROC = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
# The window helpers take pointer-sized handles; without argtypes ctypes would pass HWND_TOPMOST (-1) as
# 0x00000000FFFFFFFF and every call would quietly fail.
user32.SetWindowPos.argtypes = [W.HWND, W.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.SetWindowPos.restype = W.BOOL
user32.GetWindowRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.mouse_event.argtypes = [W.DWORD, W.DWORD, W.DWORD, W.DWORD, ctypes.c_size_t]


def window_of(pid):
    """The game's window: the visible top-level window of the process with the largest client area."""
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
    """Client area of hwnd -> (w, h, BGRA bytes, top-down)."""
    r = W.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    w, hh = r.right, r.bottom
    wdc = user32.GetDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(wdc)
    bmp = gdi32.CreateCompatibleBitmap(wdc, w, hh)
    gdi32.SelectObject(mdc, bmp)
    if method == 'print':
        ok = user32.PrintWindow(hwnd, mdc, 3)   # PW_CLIENTONLY | PW_RENDERFULLCONTENT
    else:
        pt = W.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(pt))
        sdc = user32.GetDC(0)
        ok = gdi32.BitBlt(mdc, 0, 0, w, hh, sdc, pt.x, pt.y, 0x00CC0020 | 0x40000000)   # SRCCOPY | CAPTUREBLT
        user32.ReleaseDC(0, sdc)
    bih = BIH(ctypes.sizeof(BIH), w, -hh, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = (ctypes.c_ubyte * (w * hh * 4))()
    gdi32.GetDIBits(mdc, bmp, 0, hh, buf, ctypes.byref(bih), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, wdc)
    return w, hh, bytes(buf), ok


def nonblack(px):
    """Fraction of pixels that are not almost black - a blank PrintWindow looks like a black frame."""
    n = 0
    for i in range(0, len(px), 4 * 97):   # sample every 97th pixel
        if px[i] + px[i + 1] + px[i + 2] > 24:
            n += 1
    return n / (len(px) // (4 * 97))


def capture(pid, name):
    hwnd = window_of(pid)
    if not hwnd:
        raise SystemExit('no window for pid %d' % pid)
    r = W.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    print('%s window %x iconic %d visible %d rect %dx%d at %d,%d foreground %d' % (
        name, hwnd, user32.IsIconic(hwnd), user32.IsWindowVisible(hwnd), r.right - r.left, r.bottom - r.top,
        r.left, r.top, user32.GetForegroundWindow() == hwnd))
    w = hh = None
    px = None
    for attempt in range(4):
        for method in ('print', 'screen'):
            w, hh, px, ok = grab(hwnd, method)
            frac = nonblack(px)
            print('%s: %s -> %dx%d ok %d, non-black %.1f%%' % (name, 'PrintWindow' if method == 'print' else 'screen BitBlt',
                                                               w, hh, ok, frac * 100))
            if frac > 0.01:
                path = os.path.join(OUT, name + '.png')
                write_png(path, w, hh, px)
                print('%s: %s' % (name, path))
                user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002)   # HWND_NOTOPMOST, NOMOVE|NOSIZE
                return w, hh, px
        # A D3D9 window that is covered or unfocused can hand out a black frame. Put it in front (topmost,
        # without moving or resizing it); on the last attempt also click it, because some D3D apps stop
        # presenting while they are not the active window.
        if attempt == 0 or attempt == 1:
            user32.ShowWindow(hwnd, 4)   # SW_SHOWNOACTIVATE
            ok = user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)   # HWND_TOPMOST, NOMOVE|NOSIZE|SHOWWINDOW
            print('%s: topmost %s' % (name, ok))
            time.sleep(1.5)
        elif attempt == 2:
            r = W.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            x, y = (r.left + r.right) // 2, (r.top + r.bottom) // 2
            user32.SetCursorPos(x, y)
            user32.mouse_event(0x0002, 0, 0, 0, 0)   # LEFTDOWN: a real click activates the window
            user32.mouse_event(0x0004, 0, 0, 0, 0)   # LEFTUP
            print('%s: clicked at %d,%d to activate it' % (name, x, y))
            time.sleep(1.5)
    user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002)   # HWND_NOTOPMOST, NOMOVE|NOSIZE
    path = os.path.join(OUT, name + '.png')
    write_png(path, w, hh, px)
    print('%s: %s (still black after 4 tries)' % (name, path))
    return w, hh, px


def diff(a, b, box=None):
    """Mean absolute difference of two BGRA frames (optionally inside box x0,y0,x1,y1)."""
    (wa, ha, pa), (wb, hb, pb) = a, b
    if (wa, ha) != (wb, hb):
        return None
    x0, y0, x1, y1 = box or (0, 0, wa, ha)
    tot = n = 0
    for y in range(y0, y1):
        base = (y * wa + x0) * 4
        end = (y * wa + x1) * 4
        for i in range(base, end, 4):
            tot += abs(pa[i] - pb[i]) + abs(pa[i + 1] - pb[i + 1]) + abs(pa[i + 2] - pb[i + 2])
            n += 3
    return tot / n if n else None


def world(p):
    go = p.u32(p.va(0x6c3068))
    return p.u32(go + 0x378) if go else 0


def wait_world(ps, secs=60):
    t0 = time.time()
    while time.time() - t0 < secs:
        ws = [world(p) for p in ps]
        if all(ws) and all(p.u32(w + 4) for w, p in zip(ws, ps)):
            return time.time() - t0
        time.sleep(0.5)
    raise SystemExit('no world after %d s: %r' % (secs, [world(p) for p in ps]))


dt = wait_world([Proc(h), Proc(g)])
print('both copies have a world after %.1f s' % dt)
print('waiting 10 s for the hands/level to settle')
time.sleep(10)
# A joining guest raises the local co-op "Player 2 is joining the game" prompt on the host; it pauses the
# picture and covers the characters. Press A on both pads (harmless if no prompt) before the capture.
from bot import Pipe, press
for pid in (h, g):
    p = Pipe(pid)
    print('pid %d: A -> %r' % (pid, press(p, 0, 'A')))
    p.f.close()
    time.sleep(0.5)
time.sleep(2)
A = capture(h, 'host')
B = capture(g, 'guest')
w, hh = A[0], A[1]
box = (w // 4, hh * 45 // 100, w * 3 // 4, hh * 95 // 100)
print('frame %dx%d  mean abs diff whole %.2f  lower-centre (x %d-%d, y %d-%d) %.2f' % (
    w, hh, diff(A, B), box[0], box[2], box[1], box[3], diff(A, B, box)))
print('shots in', OUT)
