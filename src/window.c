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
float sqrtf(float v);
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
// TASK 44: the projection that belongs to each view. The game sets several view/projection pairs per frame
// (scene, map, UI, shadows); the pair that draws the 3D scene is found by self-calibration on the local
// character (see scene_pair). Together they turn a world position into the pixel the GPU draws it at, which
// is how check_visible.py proves the peer's character is drawn where it stands (pipe `screen x y z ref...`).
static volatile float g_proj_last[16];
static volatile LONG g_proj_last_seen;
#define NVIEWS 12
static float g_views[NVIEWS][16];          // distinct view matrices seen in the last completed frame
static LONG g_views_n[NVIEWS], g_views_count;
static float g_cur_views[NVIEWS][16];      // being collected in the current frame
static LONG g_cur_n[NVIEWS], g_cur_count;
static float g_projs[NVIEWS][16];          // the projection set while g_views[k] was current
static LONG g_projs_seen[NVIEWS];
static float g_cur_projs[NVIEWS][16];
static LONG g_cur_projs_seen[NVIEWS];
static int g_cur_view, g_cur_proj_pending;
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
		memcpy((void *)g_view, m, sizeof g_view);
		if (!g_view_first_seen) {   // the pipe `cam` diagnostic shows the first view of the frame
			memcpy((void *)g_view_first, m, sizeof g_view_first);
			g_view_first_seen = 1;
		}
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
			g_cur_n[g_cur_count] = 1;
			g_cur_projs_seen[g_cur_count] = 0;
			k = g_cur_count++;
		}
		g_cur_view = k;          // the projection the game sets next belongs to this view
		g_cur_proj_pending = 1;
		InterlockedIncrement(&g_view_sets);
	}
	if (st == D3DTS_PROJECTION && m) {
		memcpy((void *)g_proj_last, m, sizeof g_proj_last);
		g_proj_last_seen = 1;
		if (g_cur_view >= 0 && g_cur_view < NVIEWS && g_cur_proj_pending) {
			memcpy(g_cur_projs[g_cur_view], m, 64);
			g_cur_projs_seen[g_cur_view] = 1;
			g_cur_proj_pending = 0;
		}
	}
	return real_dev_SetTransform(dev, st, m);
}

// One (view, projection) pair -> client-area pixel. `conv` 0 = the matrices in the order D3D stores them
// (row-major, row vector on the left), 1 = the same arrays read as column-major (a game that hands its own
// column-major matrices to SetTransform). 0 = the point is at/behind the camera plane.
static int proj_with(const float *v, const float *p, float x, float y, float z, int conv, int W, int H,
                     float *sx, float *sy)
{
	float vx, vy, vz, vw, cx, cy, cw;
	if (conv == 0) {
		vx = x * v[0] + y * v[4] + z * v[8] + v[12];
		vy = x * v[1] + y * v[5] + z * v[9] + v[13];
		vz = x * v[2] + y * v[6] + z * v[10] + v[14];
		vw = x * v[3] + y * v[7] + z * v[11] + v[15];
		cx = vx * p[0] + vy * p[4] + vz * p[8] + vw * p[12];
		cy = vx * p[1] + vy * p[5] + vz * p[9] + vw * p[13];
		cw = vx * p[3] + vy * p[7] + vz * p[11] + vw * p[15];
	} else {
		vx = x * v[0] + y * v[1] + z * v[2] + v[3];
		vy = x * v[4] + y * v[5] + z * v[6] + v[7];
		vz = x * v[8] + y * v[9] + z * v[10] + v[11];
		vw = x * v[12] + y * v[13] + z * v[14] + v[15];
		cx = vx * p[0] + vy * p[1] + vz * p[2] + vw * p[3];
		cy = vx * p[4] + vy * p[5] + vz * p[6] + vw * p[7];
		cw = vx * p[12] + vy * p[13] + vz * p[14] + vw * p[15];
	}
	if (cw <= 0.0001f)
		return 0;
	*sx = (cx / cw * 0.5f + 0.5f) * (float)W;
	*sy = (0.5f - cy / cw * 0.5f) * (float)H;
	return 1;
}

// TASK 44: the (view, projection) pair that draws the 3D scene, found by self-calibration on the LOCAL
// character (`ref`). NOTE: on the real engine no pair qualifies (the scene camera is not set through
// SetTransform - see screen_cmd); this is the diagnostic that established that.
// The third-person camera does NOT put the character in the middle: it looks over the character, which
// stands in the lower middle of the picture (observed on captured frames: feet at 70-80 % of the frame
// height, body 30-45 % of it). The map/UI/shadow passes fail one of the checks (body span, horizontal
// position, feet above the lower edge), so this picks the scene camera without knowing the pass order.
// Returns -1 = none, else `k*4 + q*2 + conv`.
static int scene_pair(const float *ref, int W, int H, float *err_out, float *span_out)
{
	float mx = 0.5f * (float)W, my = 0.80f * (float)H;
	float best = 1e9f;
	int bidx = -1;
	for (int k = 0; k < g_views_count && k < NVIEWS; k++) {
		const float *v = g_views[k];
		int camlike = fabsf_(v[10]) < 0.9f && fabsf_(v[10]) > 0.05f && fabsf_(v[9]) > 0.5f;
		for (int q = 0; q < 2; q++) {
			const float *p = q == 0 ? (g_projs_seen[k] ? g_projs[k] : (const float *)0)
			                        : (g_proj_last_seen ? (const float *)g_proj_last : (const float *)0);
			if (!p)
				continue;
			for (int conv = 0; conv < 2; conv++) {
				float fx, fy, hx, hy;
				if (!proj_with(v, p, ref[0], ref[1], ref[2], conv, W, H, &fx, &fy))
					continue;
				if (!proj_with(v, p, ref[0], ref[1], ref[2] + 170.0f, conv, W, H, &hx, &hy))
					continue;
				float span = fy - hy;             // positive = the head is drawn above the feet
				if (span < 0.10f * (float)H || span > 0.65f * (float)H)
					continue;                     // a map/UI/thumbnail pass: far too small or far too large
				if (fx < 0.15f * (float)W || fx > 0.85f * (float)W)
					continue;
				if (fy < 0.35f * (float)H || fy > 0.995f * (float)H)
					continue;
				float sc = fabsf_((fx - mx) / (float)W) + fabsf_((fy - my) / (float)H);
				if (!camlike)
					sc += 0.5f;
				if (sc < best) {
					best = sc;
					bidx = k * 4 + q * 2 + conv;
					if (err_out)
						*err_out = sqrtf((fx - mx) * (fx - mx) + (fy - my) * (fy - my));
					if (span_out)
						*span_out = span;
				}
			}
		}
	}
	return bidx;
}

// TASK 44: world position -> client-area pixel of the last completed frame, with the pair scene_pair
// picked on the local character (`ref`). `err` returns how far that pair puts the reference from the
// expected spot (a sanity number for the check), `span` the local body height it implies.
static int world_to_screen(float x, float y, float z, const float *ref, float *sx, float *sy,
                           int *ww, int *hh, float *err, float *span)
{
	if (!g_game_wnd)
		return 0;
	RECT r;
	if (!GetClientRect(g_game_wnd, &r) || r.right <= 0 || r.bottom <= 0)
		return 0;
	int W = r.right, H = r.bottom;
	int bidx = -1;
	if (ref) {
		bidx = scene_pair(ref, W, H, err, span);
	} else {
		for (int k = 0; k < g_views_count && k < NVIEWS && bidx < 0; k++) {
			const float *v = g_views[k];
			if (fabsf_(v[10]) < 0.9f && fabsf_(v[10]) > 0.05f && fabsf_(v[9]) > 0.5f)
				bidx = k * 4 + (g_projs_seen[k] ? 0 : 2);
		}
		if (bidx < 0)
			return 0;
	}
	if (bidx < 0)
		return 0;
	int k = bidx / 4, rest = bidx % 4, q = rest / 2, conv = rest % 2;
	const float *p = q == 0 ? g_projs[k] : (const float *)g_proj_last;
	if (!proj_with(g_views[k], p, x, y, z, conv, W, H, sx, sy))
		return 0;
	*ww = W;
	*hh = H;
	return 1;
}

// Pipe `screen <x> <y> <z> [refx refy refz]`: a world-to-screen through the view/projection pairs the
// game hands to SetTransform. TASK 44 DIAGNOSTIC, documented result: the engine's scene camera is a
// SHADER CONSTANT, so what SetTransform sees are only the UI/shadow passes and this does not project the
// scene correctly on either copy (FINDINGS_44 section 1.4). Kept because it is the evidence for that.
static void screen_cmd(const char *args, char *reply, size_t replysz)
{
	float v[6] = { 0, 0, 0, 0, 0, 0 }, sx = 0, sy = 0, err = -1, span = -1;
	int w = 0, h = 0;
	int got = sscanf(args, "%f %f %f %f %f %f", &v[0], &v[1], &v[2], &v[3], &v[4], &v[5]);
	if (got < 3) {
		_snprintf(reply, replysz, "error screen <x> <y> <z> [refx refy refz] (world positions)");
		return;
	}
	if (!world_to_screen(v[0], v[1], v[2], got >= 6 ? v + 3 : 0, &sx, &sy, &w, &h, &err, &span)) {
		_snprintf(reply, replysz, "behind (no camera yet, or the point is at/behind the camera)");
		return;
	}
	if (got >= 6)
		_snprintf(reply, replysz, "ok %.1f %.1f %d %d ref_err %.1f ref_span %.1f", sx, sy, w, h, err, span);
	else
		_snprintf(reply, replysz, "ok %.1f %.1f %d %d", sx, sy, w, h);
}

// Pipe `vmat [k]`: the view/projection pairs of the last frame. Without k a one-line summary of each
// view; with k the full 16+16 floats of that view as hex (diagnostic for the projection above).
static void vmat_cmd(const char *args, char *reply, size_t replysz)
{
	int k = -1;
	if (sscanf(args, "%d", &k) == 1 && k >= 0 && k < g_views_count && k < NVIEWS) {
		const float *p = g_projs_seen[k] ? g_projs[k] : (const float *)g_proj_last;
		int n = _snprintf(reply, replysz, "view %d V", k);
		for (int i = 0; i < 16 && n > 0 && n < (int)replysz - 12; i++) {
			unsigned u;
			memcpy(&u, &g_views[k][i], 4);
			n += _snprintf(reply + n, replysz - n, " %08x", u);
		}
		n += _snprintf(reply + n, replysz - n, " P");
		for (int i = 0; i < 16 && n > 0 && n < (int)replysz - 12; i++) {
			unsigned u;
			memcpy(&u, &p[i], 4);
			n += _snprintf(reply + n, replysz - n, " %08x", u);
		}
		return;
	}
	int n = _snprintf(reply, replysz, "views %ld projlast %ld", (long)g_views_count, (long)g_proj_last_seen);
	for (int v = 0; v < g_views_count && v < 4 && n > 0 && n < (int)replysz - 160; v++) {
		const float *vw = g_views[v];
		const float *p = g_projs_seen[v] ? g_projs[v] : (const float *)g_proj_last;
		n += _snprintf(reply + n, replysz - n, " | %d f %.2f,%.2f,%.2f up %.2f proj %.2f,%.2f,%.2f,%.2f",
			v, vw[2], vw[6], vw[10], vw[9], p[0], p[5], p[10], p[11]);
	}
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
	memcpy(g_projs, g_cur_projs, sizeof g_projs);
	memcpy(g_projs_seen, g_cur_projs_seen, sizeof g_projs_seen);
	g_views_count = g_cur_count;
	g_cur_count = 0;
	g_cur_view = -1;
	g_cur_proj_pending = 0;
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
