"""Window helper for the Obscure II test copy. Usage: python -I win.py <pid> [min|restore|info]"""
import ctypes, ctypes.wintypes as W, sys
u = ctypes.WinDLL('user32')
pid = int(sys.argv[1]); act = sys.argv[2] if len(sys.argv) > 2 else 'info'
WP = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
def cb(h, _):
    p = W.DWORD(); u.GetWindowThreadProcessId(h, ctypes.byref(p))
    b = ctypes.create_unicode_buffer(40); u.GetWindowTextW(h, b, 40)
    if p.value == pid and b.value == 'Obscure2':
        if act == 'min': u.ShowWindow(h, 7)       # SW_SHOWMINNOACTIVE
        if act == 'restore': u.ShowWindow(h, 4)   # SW_SHOWNOACTIVATE
        r = W.RECT(); u.GetWindowRect(h, ctypes.byref(r))
        print('hwnd %x style %x iconic %d size %dx%d foreground %d' % (h, u.GetWindowLongW(h, -16) & 0xffffffff, u.IsIconic(h),
              r.right - r.left, r.bottom - r.top, u.GetForegroundWindow() == h))
    return True
u.EnumWindows(WP(cb), 0)
