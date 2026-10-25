// Windowed mode for test runs (OBSCOOP_WINDOWED=1): the game's Direct3D 9 device is created in a
// normal captioned window instead of exclusive fullscreen. A fullscreen device is lost and the window is
// minimised when the game loses the foreground, which freezes the game and makes screenshots 160x28.
// Included from obscoop2.c.

#include <d3d9.h>

typedef IDirect3D9 *(WINAPI *Direct3DCreate9_t)(UINT);
typedef HRESULT(STDMETHODCALLTYPE *d3d_create_device_t)(IDirect3D9 *, UINT, D3DDEVTYPE, HWND, DWORD,
	D3DPRESENT_PARAMETERS *, IDirect3DDevice9 **);
typedef HRESULT(STDMETHODCALLTYPE *dev_reset_t)(IDirect3DDevice9 *, D3DPRESENT_PARAMETERS *);

static void frame_tick(void);
static float fabsf_(float v) { return v < 0 ? -v : v; }
float atan2f(float y, float x);
static volatile float g_cam_yaw;           // radians: ground direction of the camera's forward axis (world x, y; z is up)
static volatile LONG g_cam_yaw_valid;
// The game sets several view matrices per frame (UI, map, shadows). The scene camera is the tilted look-down one:
// forward has a small downward z, up points up. Facing of a character after "stick up" matched this forward (observed).
static void cam_yaw_update(void);
static HWND g_game_wnd;   // the game's window, for the title status line
typedef HRESULT(STDMETHODCALLTYPE *dev_present_t)(IDirect3DDevice9 *, const RECT *, const RECT *, HWND, const RGNDATA *);
static dev_present_t real_dev_Present;
typedef HRESULT(STDMETHODCALLTYPE *dev_settransform_t)(IDirect3DDevice9 *, D3DTRANSFORMSTATETYPE, const D3DMATRIX *);
static dev_settransform_t real_dev_SetTransform;
static volatile float g_view[16];        // the last D3DTS_VIEW matrix the game set (row-major, as D3D stores it)
static volatile LONG g_view_sets, g_xf_sets;
static volatile float g_view_first[16];   // the first view matrix set after the last Present (the 3D scene camera)
static volatile LONG g_view_first_seen;
#define NVIEWS 12
static float g_views[NVIEWS][16];          // distinct view matrices seen in the last completed frame
static LONG g_views_n[NVIEWS], g_views_count;
static float g_cur_views[NVIEWS][16];      // being collected in the current frame
static LONG g_cur_n[NVIEWS], g_cur_count;
static Direct3DCreate9_t real_Direct3DCreate9;
static d3d_create_device_t real_d3d_CreateDevice;
static dev_reset_t real_dev_Reset;

static int env_int(const char *name, int def);

static void win_patch_slot(void **slot, void *hook, void **orig)
{
	DWORD old;
	if (*slot == hook)   // Direct3DCreate9 can be called twice, sharing one vtable: never hook our own hook
		return;
	*orig = *slot;
	VirtualProtect(slot, sizeof *slot, PAGE_READWRITE, &old);
	*slot = hook;
	VirtualProtect(slot, sizeof *slot, old, &old);
}

// Puts the game window on the desktop as a captioned window whose client area is the back buffer.
static int win_wanted(void)
{
	static int v = -1;
	char e[8];
	if (v < 0)
		v = GetEnvironmentVariableA("OBSCOOP_WINDOWED", e, sizeof e) && e[0] == '1';
	return v;
}

static void win_adjust(D3DPRESENT_PARAMETERS *pp, HWND focus)
{
	if (!win_wanted())
		return;
	HWND w = pp->hDeviceWindow ? pp->hDeviceWindow : focus;
	UINT bw = pp->BackBufferWidth, bh = pp->BackBufferHeight;
	if (!w || !bw || !bh)
		return;
	if (!pp->Windowed)
		logf("windowed: fullscreen %ux%u -> window", bw, bh);
	pp->Windowed = TRUE;
	pp->FullScreen_RefreshRateInHz = 0;
	DWORD style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_VISIBLE;
	RECT r = { 0, 0, (LONG)bw, (LONG)bh };
	AdjustWindowRect(&r, style, FALSE);
	SetWindowLongA(w, GWL_STYLE, (LONG)style);
	SetWindowPos(w, HWND_NOTOPMOST, env_int("OBSCOOP_WINX", 40), env_int("OBSCOOP_WINY", 40), r.right - r.left, r.bottom - r.top, SWP_FRAMECHANGED | SWP_SHOWWINDOW | SWP_NOACTIVATE);
	ShowWindow(w, SW_SHOWNOACTIVATE);   // also restores a window that was minimised
}

// Camera: the view matrix the game gives Direct3D. Stick directions are relative to the camera, so a copy whose camera
// differs from the other's must turn the other's stick into its own camera frame (see sync.c).
static HRESULT STDMETHODCALLTYPE hk_dev_SetTransform(IDirect3DDevice9 *dev, D3DTRANSFORMSTATETYPE st, const D3DMATRIX *m)
{
	InterlockedIncrement(&g_xf_sets);
	if (st == D3DTS_VIEW && m) {
		if (!g_view_first_seen) {
			memcpy((void *)g_view_first, m, sizeof g_view_first);
			g_view_first_seen = 1;
		}
		memcpy((void *)g_view, m, sizeof g_view);
		{
			const float *f = (const float *)m;
			int k;
			for (k = 0; k < g_cur_count; k++) {
				int same = 1;
				for (int i = 0; i < 16; i++)
					if (fabsf_(f[i] - g_cur_views[k][i]) > 0.0005f)
						same = 0;
				if (same) {
					g_cur_n[k]++;
					break;
				}
			}
			if (k == g_cur_count && g_cur_count < NVIEWS) {
				memcpy(g_cur_views[g_cur_count], f, 64);
				g_cur_n[g_cur_count++] = 1;
			}
		}
		InterlockedIncrement(&g_view_sets);
	}
	return real_dev_SetTransform(dev, st, m);
}

static void cam_yaw_update(void)
{
	for (int k = 0; k < g_views_count; k++) {
		const float *v = g_views[k];
		float fx = v[2], fy = v[6], fz = v[10];   // forward = third column of the D3D view matrix (rows are v[0..], v[4..], v[8..])
		float uz = v[9];                           // up.z
		if (fabsf_(fz) < 0.9f && fabsf_(fz) > 0.05f && fabsf_(uz) > 0.5f && fabsf_(fx) + fabsf_(fy) > 0.1f) {
			g_cam_yaw = atan2f(fy, fx);
			g_cam_yaw_valid = 1;
			return;
		}
	}
}

// Once per frame on the game's render thread, which is also its main thread.
static HRESULT STDMETHODCALLTYPE hk_dev_Present(IDirect3DDevice9 *dev, const RECT *a, const RECT *b, HWND w, const RGNDATA *r)
{
	frame_tick();
	g_view_first_seen = 0;
	memcpy(g_views, g_cur_views, sizeof g_views);
	memcpy(g_views_n, g_cur_n, sizeof g_views_n);
	g_views_count = g_cur_count;
	g_cur_count = 0;
	cam_yaw_update();
	return real_dev_Present(dev, a, b, w, r);
}

static HRESULT STDMETHODCALLTYPE hk_dev_Reset(IDirect3DDevice9 *dev, D3DPRESENT_PARAMETERS *pp)
{
	if (pp)
		win_adjust(pp, NULL);
	return real_dev_Reset(dev, pp);
}

static HRESULT STDMETHODCALLTYPE hk_d3d_CreateDevice(IDirect3D9 *d3d, UINT adapter, D3DDEVTYPE type, HWND focus,
	DWORD flags, D3DPRESENT_PARAMETERS *pp, IDirect3DDevice9 **out)
{
	if (pp)
		logf("windowed: CreateDevice in: %ux%u windowed %d fmt %d refresh %u focus %p devwnd %p flags 0x%lx", pp->BackBufferWidth,
			pp->BackBufferHeight, (int)pp->Windowed, (int)pp->BackBufferFormat, pp->FullScreen_RefreshRateInHz, (void *)focus,
			(void *)pp->hDeviceWindow, (unsigned long)flags);
	if (pp)
		win_adjust(pp, focus);
	g_game_wnd = (pp && pp->hDeviceWindow) ? pp->hDeviceWindow : focus;
	HRESULT hr = real_d3d_CreateDevice(d3d, adapter, type, focus, flags, pp, out);
	logf("windowed: CreateDevice %ux%u -> 0x%08lx", pp ? pp->BackBufferWidth : 0, pp ? pp->BackBufferHeight : 0, (unsigned long)hr);
	if (SUCCEEDED(hr) && out && *out)
		win_patch_slot(&(*(void ***)*out)[16], (void *)hk_dev_Reset, (void **)&real_dev_Reset);
	if (SUCCEEDED(hr) && out && *out)
		win_patch_slot(&(*(void ***)*out)[17], (void *)hk_dev_Present, (void **)&real_dev_Present);
	if (SUCCEEDED(hr) && out && *out)
		win_patch_slot(&(*(void ***)*out)[44], (void *)hk_dev_SetTransform, (void **)&real_dev_SetTransform);
	return hr;
}

static IDirect3D9 *WINAPI hk_Direct3DCreate9(UINT sdk)
{
	IDirect3D9 *d3d = real_Direct3DCreate9(sdk);
	logf("windowed: Direct3DCreate9(%u) -> %p", sdk, (void *)d3d);
	if (d3d)
		win_patch_slot(&(*(void ***)d3d)[16], (void *)hk_d3d_CreateDevice, (void **)&real_d3d_CreateDevice);
	return d3d;
}
