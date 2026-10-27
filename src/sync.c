// What the host sends the guest and how the guest applies it (included by obscoop2.c, after net.c and hooks.c).
//
// Layout (build 215294, from the decompile and live reads):
//   game  = *(0x6c3068)             world = *(game + 0x378), level tag at world + 4
//   humans: manager = *(world + 0x175c), count at +4, array of CCharacterHuman* at +0xc
//   human:  +0x14 character tag, +0x23c position (x, y, z), +0x248 facing (x, y, z), +0x220 / +0x278 state ints
//   players: *(world + 0x1748) is an array of 2 controller records (stride 0x764); the first dword of record
//            i is the human player i controls (0 = player 1, 1 = player 2)

float sqrtf(float);   // not <math.h>: its logf clashes with ours
float atan2f(float y, float x);

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

static float g_stat_sum, g_stat_max;   // guest: how far the host's characters were from this copy at each snapshot
static LONG g_stat_n;
static volatile LONG g_snd_states, g_rcv_states, g_applied, g_snaps, g_blends, g_skipped_level, g_timed_corr;
static volatile LONG g_req_applied;
static volatile LONG g_item_applied;

// A save load starts the game with only player 1 attached: the second input controller's character
// pointer is 0, so the partner is AI and the guest's pad controls nothing. Re-attach the second human
// to the second input controller after a load (both copies do this).
static void attach_player2(void)
{
	static DWORD last;
	DWORD now = GetTickCount();
	if (now - last < 500) return;
	last = now;
	unsigned w = world_obj();
	unsigned ctl = w ? rd32(w + 0x1748) : 0;
	unsigned mgr = w ? rd32(w + 0x175c) : 0;
	if (!ctl || !mgr) return;
	unsigned c1 = ctl + 4 + 0x764;
	if (rd32(c1)) return;
	unsigned n = rd32(mgr + 4), arr = rd32(mgr + 0xc);
	if (n < 2) return;
	unsigned h2 = rd32(arr + 4);
	if (h2) *(DWORD *)(uintptr_t)c1 = h2;
}

// ---- host: snapshots ---------------------------------------------------------------------------

// ---- host: inventory mirror -------------------------------------------------------------------
// The save's inventory object (world+0x1790, vtable 0x665844) holds a count at +4 and 16-byte
// entries at +8. It is not part of the character or progress packets, so mirror it when it changes.
static DWORD g_item_last_count, g_item_last_hash;
static void host_send_item(void)
{
	static DWORD last;
	DWORD now = GetTickCount();
	if (now - last < 250) return;
	last = now;
	unsigned w = world_obj();
	unsigned inv = w ? rd32(w + 0x1790) : 0;
	if (!inv) return;
	DWORD count = rd32(inv + 4);
	if (count > ITEM_MAX) count = ITEM_MAX;
	DWORD h = count * 2654435761u;
	for (DWORD i = 0; i < count * 4; i++) h = h * 31 + rd32(inv + 8 + i * 4);
	if (count == g_item_last_count && h == g_item_last_hash) return;
	pkt_item p;
	memset(&p, 0, sizeof p);
	p.level = rd32(w + 4);
	p.count = count;
	for (DWORD i = 0; i < count * 4; i++) p.data[i] = rd32(inv + 8 + i * 4);
	net_send(PKT_ITEM, &p, (WORD)(sizeof p - sizeof(pkt_hdr)));
	g_item_last_count = count; g_item_last_hash = h;
}

static void guest_on_item(const char *buf, int n)
{
	if (n < (int)(sizeof(pkt_item) - sizeof(((pkt_item *)0)->data))) return;
	const pkt_item *p = (const pkt_item *)buf;
	unsigned w = world_obj();
	unsigned inv = w ? rd32(w + 0x1790) : 0;
	if (!inv || p->level != rd32(w + 4)) return;
	DWORD count = p->count; if (count > ITEM_MAX) count = ITEM_MAX;
	for (DWORD i = 0; i < count * 4; i++) *(DWORD *)(uintptr_t)(inv + 8 + i * 4) = p->data[i];
	*(DWORD *)(uintptr_t)(inv + 4) = count;
	InterlockedIncrement(&g_item_applied);
}

static void host_send_state(void)
{
	static DWORD last;
	DWORD now = GetTickCount();
	if (now - last < 16)
		return;
	last = now;
	attach_player2();
	host_send_item();
	unsigned hs[MAX_CH];
	int n = world_humans(hs, MAX_CH);
	if (n <= 0)
		return;
	pkt_state p;
	memset(&p, 0, sizeof p);
	p.t_ms = now_ms();
	p.level = rd32(world_obj() + 4);
	p.n = (DWORD)n;
	memset(&p.hpad, 0, sizeof p.hpad);
	pad_read(0, &p.hpad);   // the host's own controller is the guest's player 1
	p.yaw = g_cam_yaw;
	p.yaw_valid = (DWORD)g_cam_yaw_valid;
	for (int i = 0; i < n; i++) {
		ch_state *c = &p.ch[i];
		c->tag = rd32(hs[i] + H_TAG);
		memcpy(c->pos, (const void *)(uintptr_t)(hs[i] + H_POS), sizeof c->pos);
		memcpy(c->dir, (const void *)(uintptr_t)(hs[i] + H_DIR), sizeof c->dir);
		c->s220 = rd32(hs[i] + 0x220);
		c->s278 = rd32(hs[i] + 0x278);
		c->life = rd32(hs[i] + 0x320);
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
	// The snapshot repeats the host's pad: if a HOSTPAD packet is lost, player 1 on this copy would keep
	// its old input and the position corrections would drag it (seen as gliding). Only a newer stamp wins.
	const pkt_state *st = (const pkt_state *)buf;
	if ((LONG)(st->t_ms - g_last_pad_t) >= 0) {
		g_last_pad_t = st->t_ms;
		g_netpad = st->hpad;
		g_netpad_tick = GetTickCount();
		ring_push(&g_ring_p1, st->t_ms, &st->hpad);
		if (st->yaw_valid) { g_peer_yaw = st->yaw; g_peer_yaw_valid = 1; }
	}
	EnterCriticalSection(&g_rx_cs);
	memcpy(&g_rx_state, buf, sizeof g_rx_state);
	g_rx_state_new = 1;
	LeaveCriticalSection(&g_rx_cs);
	InterlockedIncrement(&g_rcv_states);
}


// ---- guest: where the characters were, to compare a snapshot with the right moment -----------------------------------
// A snapshot says where the host's character was at host time T. The guest's character is now further along its path,
// so comparing the two directly would pull it backwards by speed x delay. Compare against the guest's own position at
// T instead (history, interpolated) and move the current position by that error.
#define HH 192
typedef struct { DWORD t; float pos[3]; } hpos;
static DWORD g_hist_tag[MAX_CH];
static hpos g_hist[MAX_CH][HH];
static int g_hist_head[MAX_CH], g_hist_n[MAX_CH];

static int hist_slot(DWORD tag)
{
	for (int i = 0; i < MAX_CH; i++)
		if (g_hist_tag[i] == tag)
			return i;
	for (int i = 0; i < MAX_CH; i++)
		if (!g_hist_tag[i]) {
			g_hist_tag[i] = tag;
			return i;
		}
	return -1;
}

static void guest_record_history(void)
{
	if (!g_clock_valid)
		return;
	unsigned hs[MAX_CH];
	int n = world_humans(hs, MAX_CH);
	DWORD t = timeline_now();
	for (int k = 0; k < n; k++) {
		int sl = hist_slot(rd32(hs[k] + H_TAG));
		if (sl < 0)
			continue;
		int last = (g_hist_head[sl] + HH - 1) % HH;
		if (g_hist_n[sl] && (int)(t - g_hist[sl][last].t) < 6)
			continue;
		hpos *e = &g_hist[sl][g_hist_head[sl]];
		e->t = t;
		memcpy(e->pos, (const void *)(uintptr_t)(hs[k] + H_POS), 12);
		g_hist_head[sl] = (g_hist_head[sl] + 1) % HH;
		if (g_hist_n[sl] < HH)
			g_hist_n[sl]++;
	}
}

// A correction moves the character's path from time t onward: shift the history entries after t the same way, or the next
// snapshot would see the same error again and correct it again.
static void hist_shift(DWORD tag, DWORD t, float cx, float cy, float cz)
{
	int sl = hist_slot(tag);
	if (sl < 0)
		return;
	for (int k = 0; k < g_hist_n[sl]; k++) {
		hpos *e = &g_hist[sl][(g_hist_head[sl] + HH - 1 - k) % HH];
		if ((int)(e->t - t) <= 0)
			break;
		e->pos[0] += cx; e->pos[1] += cy; e->pos[2] += cz;
	}
}

// The guest's own position of this character at host time t (interpolated); 0 if the history does not cover t.
static int hist_at(DWORD tag, DWORD t, float *out)
{
	int sl = hist_slot(tag);
	if (sl < 0 || g_hist_n[sl] < 2)
		return 0;
	for (int k = 0; k < g_hist_n[sl] - 1; k++) {
		int i = (g_hist_head[sl] + HH - 1 - k) % HH, j = (i + HH - 1) % HH;   // i newer than j
		if ((int)(g_hist[sl][j].t - t) <= 0 && (int)(t - g_hist[sl][i].t) <= 0) {
			float span = (float)(int)(g_hist[sl][i].t - g_hist[sl][j].t);
			float a = span > 0 ? (float)(int)(t - g_hist[sl][j].t) / span : 1.0f;
			for (int c = 0; c < 3; c++)
				out[c] = g_hist[sl][j].pos[c] + (g_hist[sl][i].pos[c] - g_hist[sl][j].pos[c]) * a;
			return 1;
		}
	}
	return 0;
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
			*(DWORD *)(uintptr_t)(hs[k] + 0x320) = st.ch[i].life;   // health from the host
			// the error is measured against where this copy's character was at the snapshot's time
			float ref[3] = { pos[0], pos[1], pos[2] };
			int timed = g_clock_valid && hist_at(st.ch[i].tag, st.t_ms, ref);
			if (timed)
				InterlockedIncrement(&g_timed_corr);
			float ex = st.ch[i].pos[0] - ref[0], ey = st.ch[i].pos[1] - ref[1], ez = st.ch[i].pos[2] - ref[2];
			float err = sqrtf(ex * ex + ey * ey);
			// This PC's own character (player 2) answers its own pad, so it runs ahead of the host's copy while it
			// moves: leave it alone then, pull it in gently once the stick is idle.
			int local = hs[k] == mine;
			int idle = 1;
			if (local) {
				xstate lp;
				local_pad(g_local_pad, &lp);
				idle = abs(lp.lx) < 4000 && abs(lp.ly) < 4000;
			}
			{
				static int dbg = -1, dn;
				if (dbg < 0) { char v[8]; dbg = GetEnvironmentVariableA("OBSCOOP_DEBUG_SYNC", v, sizeof v) ? 1 : 0; }
				if (dbg && !local && err > 8.0f && (dn++ % 8) == 0 && dn < 4000)
					logf("corr tag %08x timed %d err %.1f e=(%.1f,%.1f) own_now=(%.1f,%.1f) ref=(%.1f,%.1f) host=(%.1f,%.1f) dT %d", st.ch[i].tag, timed, err, ex, ey,
						pos[0], pos[1], ref[0], ref[1], st.ch[i].pos[0], st.ch[i].pos[1], (int)(timeline_now() - st.t_ms));
			}
			if (!local) {
				g_stat_sum += err; g_stat_n++;
				if (err > g_stat_max) g_stat_max = err;
			}
			float big = timed ? 30.0f : (local ? 80.0f : 30.0f);
			if (err > big) {   // far off (a door, a cutscene, a respawn): move by the whole error
				pos[0] += ex; pos[1] += ey; pos[2] += ez;
				if (timed)
					hist_shift(st.ch[i].tag, st.t_ms, ex, ey, ez);
				memcpy(dir, st.ch[i].dir, 12);
				InterlockedIncrement(&g_snaps);
			} else if (!local ? err > (timed ? 0.6f : 1.0f) : (timed ? err > 0.6f : (idle ? err > 1.5f : err > 15.0f))) {
				float kk = (!timed && local && !idle) ? 0.1f : 0.25f;
				pos[0] += ex * kk; pos[1] += ey * kk; pos[2] += ez * kk;
				if (timed)
					hist_shift(st.ch[i].tag, st.t_ms, ex * kk, ey * kk, ez * kk);
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


// ---- progress object (story and world state) -----------------------------------------------------
// The live progress object is *(game + 0x318) (game + 0x31c is a copy kept for saving). Observed layout:
//   +0x810 pointer (never copied)   +0x814 count, +0x818.. entries of 12 bytes {entity id, state, extra}: the
//   persistent state of doors and other entities (the story flags)   +0x1b0c.. table of 8 characters   +0x1c4c level
//   +0x1c50.. counters   +0x1c68 chapter   +0x1cb8.. more state   up to +0x1cd4.
// The host sends the parts that changed; the guest writes them in once its world is the same level.
#define PROG_ENT_OFF 0x814
#define PROG_CHR_OFF 0x1b0c
#define PROG_END 0x1cd4

static BYTE g_prog_sent[PROG_END];
static volatile LONG g_prog_sent_valid, g_prog_chunks_sent, g_prog_chunks_rcv, g_prog_chunks_applied;

static void host_send_region(unsigned obj, unsigned off, unsigned len, unsigned level)
{
	pkt_region r;
	memset(&r, 0, sizeof r);
	r.level = level; r.off = off; r.len = len;
	memcpy(r.data, (const void *)(uintptr_t)(obj + off), len);
	net_send(PKT_REGION, &r, (WORD)(12 + len));
	InterlockedIncrement(&g_prog_chunks_sent);
}

static void host_send_progress(int force)
{
	static DWORD last;
	DWORD now = GetTickCount();
	if (!force && now - last < 250)
		return;
	last = now;
	unsigned g = game_obj();
	unsigned obj = g ? rd32(g + 0x318) : 0;
	unsigned w = world_obj();
	if (!obj || !w || !mem_ok((const void *)(uintptr_t)obj, PROG_END))
		return;
	unsigned level = rd32(w + 4);
	unsigned count = rd32(obj + PROG_ENT_OFF);
	if (count > 380)
		count = 380;
	unsigned ent_end = 0x818 + 12 * count;
	if (force)
		g_prog_sent_valid = 0;
	for (unsigned off = PROG_ENT_OFF; off < ent_end; off += REGION_MAX) {
		unsigned len = ent_end - off < REGION_MAX ? ent_end - off : REGION_MAX;
		if (!g_prog_sent_valid || memcmp(g_prog_sent + off, (const void *)(uintptr_t)(obj + off), len)) {
			host_send_region(obj, off, len, level);
			memcpy(g_prog_sent + off, (const void *)(uintptr_t)(obj + off), len);
		}
	}
	if (!g_prog_sent_valid || memcmp(g_prog_sent + PROG_CHR_OFF, (const void *)(uintptr_t)(obj + PROG_CHR_OFF), PROG_END - PROG_CHR_OFF)) {
		host_send_region(obj, PROG_CHR_OFF, PROG_END - PROG_CHR_OFF, level);
		memcpy(g_prog_sent + PROG_CHR_OFF, (const void *)(uintptr_t)(obj + PROG_CHR_OFF), PROG_END - PROG_CHR_OFF);
	}
	g_prog_sent_valid = 1;
}

static CRITICAL_SECTION g_reg_cs;
static pkt_region g_reg_q[16];
static int g_reg_head, g_reg_tail;

static void guest_on_region(const char *buf, int n)
{
	const pkt_region *r = (const pkt_region *)buf;
	if (n < (int)(sizeof(pkt_hdr) + 12) || r->len > REGION_MAX || (int)(sizeof(pkt_hdr) + 12 + r->len) != n)
		return;
	EnterCriticalSection(&g_reg_cs);
	if (((g_reg_tail + 1) & 15) != g_reg_head) {
		memcpy(&g_reg_q[g_reg_tail], buf, n);
		g_reg_tail = (g_reg_tail + 1) & 15;
	}
	LeaveCriticalSection(&g_reg_cs);
	InterlockedIncrement(&g_prog_chunks_rcv);
}

// Writes queued regions into the guest's progress object once the world is the same level as the host's.
static void guest_apply_regions(void)
{
	for (;;) {
		pkt_region r;
		EnterCriticalSection(&g_reg_cs);
		if (g_reg_head == g_reg_tail) {
			LeaveCriticalSection(&g_reg_cs);
			return;
		}
		r = g_reg_q[g_reg_head];
		LeaveCriticalSection(&g_reg_cs);
		unsigned g = game_obj(), w = world_obj();
		if (!g || !w || rd32(g + 0x310) != 1 || rd32(g + 0x320) != 0 || rd32(w + 4) != r.level)
			return;   // keep it queued: the guest is still loading, or in another level
		EnterCriticalSection(&g_reg_cs);
		g_reg_head = (g_reg_head + 1) & 15;
		LeaveCriticalSection(&g_reg_cs);
		unsigned obj = rd32(g + 0x318);
		if (!obj || r.off < PROG_ENT_OFF || r.off + r.len > PROG_END || IsBadWritePtr((void *)(uintptr_t)(obj + r.off), r.len))
			continue;
		memcpy((void *)(uintptr_t)(obj + r.off), r.data, r.len);
		InterlockedIncrement(&g_prog_chunks_applied);
	}
}


// Host: the level can also change without a ChangeLevel request (loading a save, a new game). Announce those too,
// with the arrival door id of the character that player 1's controller record names.
static volatile LONG g_watch_sent;
static void host_watch_level(void)
{
	unsigned g = game_obj(), w = world_obj();
	if (!g || !w || rd32(g + 0x310) != 1 || rd32(g + 0x320) != 0)
		return;
	unsigned lvl = rd32(w + 4);
	if (!lvl)
		return;
	if (!g_last_level) {   // first level of this game: the guest starts there too
		g_last_level = lvl;
		return;
	}
	if (lvl == g_last_level)
		return;
	unsigned obj = rd32(g + 0x318), entry = g_last_entry;
	if (obj) {
		for (int i = 0; i < 8; i++) {
			unsigned rec = obj + 0x1b0c + i * 0x28;
			if (rd32(rec + 0xc) == 0x43484331) {   // "CHC1": the character player 1 controls
				entry = rd32(rec + 8);
				break;
			}
		}
	}
	logf("host: level is now %c%c%c%c without a ChangeLevel request (load or new game), telling the guest (entry %u)",
		(char)(lvl >> 24), (char)(lvl >> 16), (char)(lvl >> 8), (char)lvl, entry);
	g_last_level = lvl;
	g_last_entry = entry;
	if (g_peer_ok) {
		net_send_req(REQ_LEVEL, lvl, entry, 1, NULL);
		InterlockedIncrement(&g_req_sent);
		InterlockedIncrement(&g_watch_sent);
	}
}

// Host: a guest just connected. Make it load and go to the level the party is in, then send all of the state.
static void host_welcome_guest(void)
{
	logf("join: sending the current state to the guest (level %c%c%c%c)", (char)(g_last_level >> 24), (char)(g_last_level >> 16),
		(char)(g_last_level >> 8), (char)g_last_level);
	// The friend starts their own "New game, Two players" first (that choice decides who controls player 2); the
	// level request waits on the guest until its world exists.
	if (g_last_level)
		net_send_req(REQ_LEVEL, g_last_level, g_last_entry, g_last_flag, NULL);
	host_send_progress(1);
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
		if (r.kind == REQ_LEVEL) {   // a joining guest may still be loading: keep the request until its world exists
			unsigned g0 = game_obj();
			if (!g0 || rd32(g0 + 0x310) != 1 || rd32(g0 + 0x320) != 0 || !world_obj()) {
				LeaveCriticalSection(&g_req_cs);
				return;
			}
		}
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


// Debug (OBSCOOP_DEBUG_SYNC): how each copy's player 1 actually moves versus the stick that was fed in.
static void guest_debug_p1(void)
{
	static int dbg = -1;
	static DWORD last;
	static float prev[3], prevh[3];
	static DWORD prev_t;
	if (dbg < 0) { char v[8]; dbg = GetEnvironmentVariableA("OBSCOOP_DEBUG_SYNC", v, sizeof v) ? 1 : 0; }
	if (!dbg || !g_clock_valid)
		return;
	DWORD now = GetTickCount();
	if (now - last < 150)
		return;
	last = now;
	unsigned hs[MAX_CH];
	int n = world_humans(hs, MAX_CH);
	unsigned p1 = player_human(0);
	for (int k = 0; k < n; k++) {
		if (hs[k] != p1)
			continue;
		const float *pos = (const float *)(uintptr_t)(hs[k] + H_POS);
		float dx = pos[0] - prev[0], dy = pos[1] - prev[1];
		float sp = sqrtf(dx * dx + dy * dy);
		xstate raw = g_netpad, fed;
		memset(&fed, 0, sizeof fed);
		ring_get(&g_ring_p1, timeline_now() - (DWORD)g_delay_ms, &fed);
		xstate rm = fed;
		remap_if_known(&rm);
		if (sp > 3.0f)
			logf("p1dbg own move angle %.0f deg (%.0f u) | stick raw (%d,%d) ring (%d,%d) remapped (%d,%d) | yaw peer %.0f own %.0f | camera valid own %ld peer %ld",
				atan2f(dy, dx) * 57.2958f, sp, raw.lx, raw.ly, fed.lx, fed.ly, rm.lx, rm.ly, g_peer_yaw * 57.2958f, g_cam_yaw * 57.2958f,
				g_cam_yaw_valid, g_peer_yaw_valid);
		memcpy(prev, pos, 12);
		(void)prevh; (void)prev_t;
	}
}

// ---- frame tick (Present hook, main thread) --------------------------------------------------------

static void sync_init(void)
{
	InitializeCriticalSection(&g_reg_cs);
	InitializeCriticalSection(&g_rx_cs);
	InitializeCriticalSection(&g_req_cs);
}

static void frame_tick(void)
{
	if (!g_role)
		return;
	{
		static DWORD last_title;
		DWORD now = GetTickCount();
		if (g_game_wnd && now - last_title >= 500) {
			char line[96], title[160];
			last_title = now;
			net_status_line(line, sizeof line);
			_snprintf(title, sizeof title, "Obscure 2 - %s", line);
			SetWindowTextA(g_game_wnd, title);
		}
	}
	net_frame();
	if (!g_peer_ok)
		return;
	{   // every 10 s: a line the testers can send along with the log
		static DWORD last_stat;
		DWORD now = GetTickCount();
		if (now - last_stat >= 10000) {
			last_stat = now;
			if (g_role == 2)
				logf("sync stats: host characters off by mean %.1f max %.1f units over %ld snapshots (%ld snaps, %ld blends); rtt %ld ms, "
					"clock %s, input delay %s %ld ms, camera yaw own %.0f peer %.0f (valid %ld/%ld)",
					g_stat_n ? g_stat_sum / g_stat_n : 0.0f, g_stat_max, g_stat_n, g_snaps, g_blends, g_net_rtt_ms, g_clock_valid ? "synced" : "unknown",
					g_delay_on ? "on" : "off", g_delay_ms, g_cam_yaw * 57.2958f, g_peer_yaw * 57.2958f, g_cam_yaw_valid, g_peer_yaw_valid);
			else
				logf("sync stats: sent %ld snapshots, %ld requests; guest rtt %.0f ms; camera yaw own %.0f peer %.0f (valid %ld/%ld)", g_snd_states, g_req_sent,
					g_guest_rtt, g_cam_yaw * 57.2958f, g_peer_yaw * 57.2958f, g_cam_yaw_valid, g_peer_yaw_valid);
			g_stat_sum = 0; g_stat_max = 0; g_stat_n = 0;
		}
	}
	if (g_role == 1) {
		if (g_join_pending) {
			g_join_pending = 0;
			host_welcome_guest();
		}
		host_watch_level();
		host_send_state();
		host_send_npcs();
		host_send_progress(0);
	} else {
		attach_player2();
		guest_apply_requests();
		guest_apply_regions();
		guest_apply_state();
		guest_apply_npcs();
		guest_follow_own_player();
		guest_record_history();
		guest_debug_p1();
	}
}

static void sync_status(char *reply, size_t replysz)
{
	_snprintf(reply, replysz, "sync role %s sent %ld recv %ld applied %ld snaps %ld blends %ld skipped_level %ld timed %ld req_sent %ld req_applied %ld",
		g_role == 1 ? "host" : g_role == 2 ? "guest" : "off", g_snd_states, g_rcv_states, g_applied, g_snaps, g_blends,
		g_skipped_level, g_timed_corr, g_req_sent, g_req_applied);
	size_t l = strlen(reply);
	if (l < replysz)
		_snprintf(reply + l, replysz - l, " | prog sent %ld rcv %ld applied %ld | npc sent %ld rcv %ld applied %ld snaps %ld blends %ld unmatched %ld | cam sets %ld", g_prog_chunks_sent, g_prog_chunks_rcv, g_prog_chunks_applied, g_npc_sent, g_npc_rcv,
			g_npc_applied, g_npc_snaps, g_npc_blends, g_npc_unmatched, g_cam_sets);
}
