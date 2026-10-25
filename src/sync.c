// What the host sends the guest and how the guest applies it (included by obscoop2.c, after net.c and hooks.c).
//
// Layout (build 215294, from the decompile and live reads):
//   game  = *(0x6c3068)             world = *(game + 0x378), level tag at world + 4
//   humans: manager = *(world + 0x175c), count at +4, array of CCharacterHuman* at +0xc
//   human:  +0x14 character tag, +0x23c position (x, y, z), +0x248 facing (x, y, z), +0x220 / +0x278 state ints
//   players: *(world + 0x1748) is an array of 2 controller records (stride 0x764); the first dword of record
//            i is the human player i controls (0 = player 1, 1 = player 2)

float sqrtf(float);   // not <math.h>: its logf clashes with ours

#define H_TAG 0x14
#define H_POS 0x23c
#define H_DIR 0x248

static int mem_ok(const void *p, size_t n)
{
	return p && !IsBadReadPtr(p, n);
}

static unsigned rd32(unsigned addr)
{
	return mem_ok((const void *)(uintptr_t)addr, 4) ? *(const unsigned *)(uintptr_t)addr : 0;
}

static unsigned game_obj(void) { return rd32(0x6c3068); }
static unsigned world_obj(void) { unsigned g = game_obj(); return g ? rd32(g + 0x378) : 0; }

// Fills out with the characters in the human manager; returns how many.
static int world_humans(unsigned *out, int max)
{
	unsigned w = world_obj();
	if (!w)
		return 0;
	unsigned mg = rd32(w + 0x175c);
	if (!mg)
		return 0;
	unsigned n = rd32(mg + 4), arr = rd32(mg + 0xc);
	if (!arr || n > (unsigned)max)
		n = n > (unsigned)max ? (unsigned)max : n;
	int k = 0;
	for (unsigned i = 0; i < n; i++) {
		unsigned h = rd32(arr + 4 * i);
		if (h && mem_ok((const void *)(uintptr_t)h, 0x300))
			out[k++] = h;
	}
	return k;
}

// The human that player 0 or 1 controls (0 if none).
static unsigned player_human(int player)
{
	unsigned w = world_obj();
	unsigned ctl = w ? rd32(w + 0x1748) : 0;
	return ctl ? rd32(ctl + 4 + 0x764 * player) : 0;
}

static volatile LONG g_snd_states, g_rcv_states, g_applied, g_snaps, g_blends, g_skipped_level;
static volatile LONG g_req_applied;

// ---- host: snapshots ---------------------------------------------------------------------------

static void host_send_state(void)
{
	static DWORD last;
	DWORD now = GetTickCount();
	if (now - last < 16)
		return;
	last = now;
	unsigned hs[MAX_CH];
	int n = world_humans(hs, MAX_CH);
	if (n <= 0)
		return;
	pkt_state p;
	memset(&p, 0, sizeof p);
	p.t_ms = now;
	p.level = rd32(world_obj() + 4);
	p.n = (DWORD)n;
	for (int i = 0; i < n; i++) {
		ch_state *c = &p.ch[i];
		c->tag = rd32(hs[i] + H_TAG);
		memcpy(c->pos, (const void *)(uintptr_t)(hs[i] + H_POS), sizeof c->pos);
		memcpy(c->dir, (const void *)(uintptr_t)(hs[i] + H_DIR), sizeof c->dir);
		c->s220 = rd32(hs[i] + 0x220);
		c->s278 = rd32(hs[i] + 0x278);
	}
	net_send(PKT_STATE, &p, (WORD)(sizeof p - sizeof(pkt_hdr)));
	InterlockedIncrement(&g_snd_states);
}

// ---- guest: snapshots --------------------------------------------------------------------------

static CRITICAL_SECTION g_rx_cs;
static pkt_state g_rx_state;
static volatile LONG g_rx_state_new;

static void guest_on_state(const char *buf, int n)
{
	if (n != (int)sizeof(pkt_state))
		return;
	EnterCriticalSection(&g_rx_cs);
	memcpy(&g_rx_state, buf, sizeof g_rx_state);
	g_rx_state_new = 1;
	LeaveCriticalSection(&g_rx_cs);
	InterlockedIncrement(&g_rcv_states);
}

// Writes the host's position and facing into the guest's copy of a character. The character this PC
// controls (player 2) keeps its own movement unless it is far off; the host's player 1 is pulled in.
static void guest_apply_state(void)
{
	if (!g_rx_state_new)
		return;
	pkt_state st;
	EnterCriticalSection(&g_rx_cs);
	st = g_rx_state;
	g_rx_state_new = 0;
	LeaveCriticalSection(&g_rx_cs);
	unsigned w = world_obj();
	if (!w || rd32(w + 4) != st.level) {
		InterlockedIncrement(&g_skipped_level);
		return;
	}
	unsigned hs[MAX_CH];
	int n = world_humans(hs, MAX_CH);
	unsigned mine = player_human(1);
	for (int i = 0; i < (int)st.n && i < MAX_CH; i++) {
		for (int k = 0; k < n; k++) {
			if (rd32(hs[k] + H_TAG) != st.ch[i].tag)
				continue;
			float *pos = (float *)(uintptr_t)(hs[k] + H_POS), *dir = (float *)(uintptr_t)(hs[k] + H_DIR);
			if (IsBadWritePtr(pos, 12) || IsBadWritePtr(dir, 12))
				break;
			float dx = st.ch[i].pos[0] - pos[0], dy = st.ch[i].pos[1] - pos[1];
			float err = sqrtf(dx * dx + dy * dy);
			int local = hs[k] == mine;
			// This PC's own character (player 2) answers its own pad at once, so it runs ahead of the host's copy while
			// it moves: leave it alone then, pull it in gently once the stick is idle.
			int idle = 1;
			if (local) {
				xstate lp;
				local_pad(g_local_pad, &lp);
				idle = abs(lp.lx) < 4000 && abs(lp.ly) < 4000;
			}
			if (err > (local ? 80.0f : 30.0f)) {   // far off (a door, a cutscene, a respawn): snap
				memcpy(pos, st.ch[i].pos, 12);
				memcpy(dir, st.ch[i].dir, 12);
				InterlockedIncrement(&g_snaps);
			} else if (!local ? err > 1.0f : (idle ? err > 1.5f : err > 15.0f)) {   // close: pull a quarter of the way each snapshot
				float k = (local && !idle) ? 0.1f : 0.25f;
				for (int a = 0; a < 3; a++)
					pos[a] += (st.ch[i].pos[a] - pos[a]) * k;
				InterlockedIncrement(&g_blends);
			}
			InterlockedIncrement(&g_applied);
			break;
		}
	}
}


// ---- NPCs and enemies (the NPC manager at world + 0x1760: same container layout as the humans, same position
// and facing offsets) ---------------------------------------------------------------------------------

static int world_npcs(unsigned *out, int max)
{
	unsigned w = world_obj();
	if (!w)
		return 0;
	unsigned mg = rd32(w + 0x1760);
	if (!mg)
		return 0;
	unsigned n = rd32(mg + 4), arr = rd32(mg + 0xc);
	if (n > (unsigned)max)
		n = (unsigned)max;
	int k = 0;
	for (unsigned i = 0; i < n && arr; i++) {
		unsigned h = rd32(arr + 4 * i);
		if (h && mem_ok((const void *)(uintptr_t)h, 0x300))
			out[k++] = h;
	}
	return k;
}

// Some NPC objects have no character tag at +0x14 (random bytes that differ between copies): then match on class only.
static unsigned tag_key(unsigned t)
{
	for (int i = 0; i < 4; i++) {
		unsigned c = (t >> (8 * i)) & 0xff;
		if (c < 32 || c > 126)
			return 0;
	}
	return t;
}

static volatile LONG g_npc_sent, g_npc_rcv, g_npc_applied, g_npc_snaps, g_npc_blends, g_npc_unmatched;

static void host_send_npcs(void)
{
	static DWORD last;
	DWORD now = GetTickCount();
	if (now - last < 33)
		return;
	last = now;
	unsigned hs[MAX_NPC];
	int n = world_npcs(hs, MAX_NPC);
	if (n <= 0)
		return;
	pkt_npc p;
	memset(&p, 0, sizeof p);
	p.t_ms = now;
	p.level = rd32(world_obj() + 4);
	p.n = (DWORD)n;
	for (int i = 0; i < n; i++) {
		p.npc[i].cls = rd32(hs[i]);
		p.npc[i].tag = tag_key(rd32(hs[i] + H_TAG));
		memcpy(p.npc[i].pos, (const void *)(uintptr_t)(hs[i] + H_POS), 12);
		memcpy(p.npc[i].dir, (const void *)(uintptr_t)(hs[i] + H_DIR), 12);
	}
	net_send(PKT_NPC, &p, (WORD)(sizeof p - sizeof(pkt_hdr)));
	InterlockedIncrement(&g_npc_sent);
}

static pkt_npc g_rx_npc;
static volatile LONG g_rx_npc_new;

static void guest_on_npc(const char *buf, int n)
{
	if (n != (int)sizeof(pkt_npc))
		return;
	EnterCriticalSection(&g_rx_cs);
	memcpy(&g_rx_npc, buf, sizeof g_rx_npc);
	g_rx_npc_new = 1;
	LeaveCriticalSection(&g_rx_cs);
	InterlockedIncrement(&g_npc_rcv);
}

// Each host NPC is matched to the nearest unused guest NPC of the same class and tag.
static void guest_apply_npcs(void)
{
	if (!g_rx_npc_new)
		return;
	pkt_npc st;
	EnterCriticalSection(&g_rx_cs);
	st = g_rx_npc;
	g_rx_npc_new = 0;
	LeaveCriticalSection(&g_rx_cs);
	unsigned w = world_obj();
	if (!w || rd32(w + 4) != st.level)
		return;
	unsigned hs[MAX_NPC];
	int n = world_npcs(hs, MAX_NPC);
	unsigned used = 0;
	for (int i = 0; i < (int)st.n && i < MAX_NPC; i++) {
		int best = -1;
		float bd = 1e30f;
		for (int k = 0; k < n; k++) {
			if ((used >> k) & 1 || rd32(hs[k]) != st.npc[i].cls || tag_key(rd32(hs[k] + H_TAG)) != st.npc[i].tag)
				continue;
			const float *p = (const float *)(uintptr_t)(hs[k] + H_POS);
			float dx = p[0] - st.npc[i].pos[0], dy = p[1] - st.npc[i].pos[1], d = dx * dx + dy * dy;
			if (d < bd) { bd = d; best = k; }
		}
		if (best < 0) {
			InterlockedIncrement(&g_npc_unmatched);
			continue;
		}
		used |= 1u << best;
		float *pos = (float *)(uintptr_t)(hs[best] + H_POS), *dir = (float *)(uintptr_t)(hs[best] + H_DIR);
		if (IsBadWritePtr(pos, 12) || IsBadWritePtr(dir, 12))
			continue;
		float err = sqrtf(bd);
		if (err > 30.0f) {
			memcpy(pos, st.npc[i].pos, 12);
			memcpy(dir, st.npc[i].dir, 12);
			InterlockedIncrement(&g_npc_snaps);
		} else if (err > 1.0f) {
			for (int a = 0; a < 3; a++)
				pos[a] += (st.npc[i].pos[a] - pos[a]) * 0.25f;
			InterlockedIncrement(&g_npc_blends);
		}
		InterlockedIncrement(&g_npc_applied);
	}
}

// ---- guest: requests from the host -------------------------------------------------------------

static CRITICAL_SECTION g_req_cs;
static pkt_req g_req_q[8];
static int g_req_head, g_req_tail;

static void guest_on_req(const char *buf, int n)
{
	if (n != (int)sizeof(pkt_req))
		return;
	EnterCriticalSection(&g_req_cs);
	if (((g_req_tail + 1) & 7) != g_req_head) {
		memcpy(&g_req_q[g_req_tail], buf, sizeof(pkt_req));
		g_req_tail = (g_req_tail + 1) & 7;
	}
	LeaveCriticalSection(&g_req_cs);
}

// Runs on the main thread (frame hook): the game's state machine is not thread-safe.
static void guest_apply_requests(void)
{
	for (;;) {
		pkt_req r;
		EnterCriticalSection(&g_req_cs);
		if (g_req_head == g_req_tail) {
			LeaveCriticalSection(&g_req_cs);
			return;
		}
		r = g_req_q[g_req_head];
		g_req_head = (g_req_head + 1) & 7;
		LeaveCriticalSection(&g_req_cs);
		unsigned g = game_obj();
		if (!g)
			continue;
		r.name[sizeof r.name - 1] = 0;
		// A load the guest already started itself (its menu gets the host's pad presses too) must not run twice.
		if ((r.kind == REQ_LOAD_PROGRESS || r.kind == REQ_LOAD_NAME) && (rd32(g + 0x310) == 1 || rd32(g + 0x320) != 0)) {
			logf("guest: host load request ignored (already in game or loading, mode %u state %u)", rd32(g + 0x310), rd32(g + 0x320));
			continue;
		}
		g_apply_host_req = 1;
		switch (r.kind) {
		case REQ_LEVEL:
			logf("guest: host ChangeLevel %c%c%c%c entry %u flag %u", (char)(r.a >> 24), (char)(r.a >> 16), (char)(r.a >> 8),
				(char)r.a, r.b, r.c);
			if (g_change_level)
				g_change_level((void *)(uintptr_t)g, NULL, r.a, r.b, r.c);
			break;
		case REQ_LOAD_PROGRESS:
			logf("guest: host LoadProgress %u", r.a);
			if (g_load_progress)
				g_load_progress((void *)(uintptr_t)g, NULL, r.a);
			break;
		case REQ_LOAD_NAME:
			logf("guest: host LoadByName \"%s\"", r.name);
			if (g_load_name)
				g_load_name((void *)(uintptr_t)g, NULL, (unsigned)(uintptr_t)r.name);
			break;
		case REQ_TO_MENU:
			logf("guest: host ToMenu");
			if (g_to_menu)
				g_to_menu((void *)(uintptr_t)g, NULL);
			break;
		}
		g_apply_host_req = 0;
		InterlockedIncrement(&g_req_applied);
	}
}


// ---- independent camera (guest) ----------------------------------------------------------------------
// The camera manager is world + 0x1764; *(manager + 0x17c) is the character the camera follows (player 1 by
// default). FUN_00530960(character) is its set-target method (thiscall, one argument; it blends to the new
// target and returns at once if it is the current one). The guest follows its own character, the host keeps
// player 1. OBSCOOP_CAMERA=shared turns it off.
static volatile LONG g_cam_sets;

static void guest_follow_own_player(void)
{
	static int mode = -1;
	if (mode < 0) {
		char v[16];
		mode = !(GetEnvironmentVariableA("OBSCOOP_CAMERA", v, sizeof v) && !_stricmp(v, "shared"));
		logf("camera: guest %s", mode ? "follows its own player (player 2)" : "shares the host's camera target");
	}
	if (!mode)
		return;
	unsigned w = world_obj();
	unsigned cam = w ? rd32(w + 0x1764) : 0;
	unsigned me = player_human(1);
	if (!cam || !me || rd32(cam + 0x17c) == me || rd32(game_obj() + 0x310) != 1)
		return;
	((void(__fastcall *)(void *, void *, unsigned))0x530960)((void *)(uintptr_t)cam, NULL, me);
	InterlockedIncrement(&g_cam_sets);
}

// ---- frame tick (Present hook, main thread) --------------------------------------------------------

static void sync_init(void)
{
	InitializeCriticalSection(&g_rx_cs);
	InitializeCriticalSection(&g_req_cs);
}

static void frame_tick(void)
{
	if (!g_role)
		return;
	net_frame();
	if (!g_peer_ok)
		return;
	if (g_role == 1) {
		host_send_state();
		host_send_npcs();
	} else {
		guest_apply_requests();
		guest_apply_state();
		guest_apply_npcs();
		guest_follow_own_player();
	}
}

static void sync_status(char *reply, size_t replysz)
{
	_snprintf(reply, replysz, "sync role %s sent %ld recv %ld applied %ld snaps %ld blends %ld skipped_level %ld req_sent %ld req_applied %ld",
		g_role == 1 ? "host" : g_role == 2 ? "guest" : "off", g_snd_states, g_rcv_states, g_applied, g_snaps, g_blends,
		g_skipped_level, g_req_sent, g_req_applied);
	size_t l = strlen(reply);
	if (l < replysz)
		_snprintf(reply + l, replysz - l, " | npc sent %ld rcv %ld applied %ld snaps %ld blends %ld unmatched %ld | cam sets %ld", g_npc_sent, g_npc_rcv,
			g_npc_applied, g_npc_snaps, g_npc_blends, g_npc_unmatched, g_cam_sets);
}
