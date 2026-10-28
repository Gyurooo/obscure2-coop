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
//
// Attaching the pointer is not enough. Request state 3 (load by name) rewrites the second character
// record's controller tag 2CHC (0x43484332) to MTHC (0x4348544d) in the live progress table *before*
// the world is built (decompile 98986-98989), so the partner is spawned on the shared teammate
// controller (world+0x174c, tag MTHC) - its body is `human+8`. The input controller then points at
// her but she still answers the teammate AI, and the pad of player 2 moves nobody (TASK 13 run 2:
// GIR1 moved 0.0 units on both copies). Point the body at the input controller too, which is what a
// world built for two players looks like (human+8 == *(world+0x1748)+0x764). In a real 2P world this
// is a no-op.
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
	unsigned c2 = ctl + 0x764;         // input controller 2 (an object: vtable +0, character +4, tag +0xc)
	unsigned c2h = c2 + 4;             // the character pointer the mod writes
	unsigned n = rd32(mgr + 4), arr = rd32(mgr + 0xc);
	if (n < 2) return;
	unsigned h2 = rd32(arr + 4);
	if (!h2 || IsBadWritePtr((void *)(uintptr_t)c2h, 4) || IsBadReadPtr((const void *)(uintptr_t)(h2 + 8), 4))
		return;
	if (!rd32(c2h))
		*(DWORD *)(uintptr_t)c2h = h2;   // input controller 2 controls the partner
	unsigned hc = rd32(h2 + 8);          // the controller the partner's body answers
	if (hc && hc != c2 && rd32(hc + 0xc) == 0x4348544d && rd32(c2 + 0xc) == 0x43484332 &&
	    !IsBadWritePtr((void *)(uintptr_t)(h2 + 8), 4)) {
		char who[5], was[5], nowc[5];
		*(DWORD *)(uintptr_t)(h2 + 8) = c2;
		logf("attach: %s answered the teammate controller (%s), now the player 2 input controller (%s)",
			tag4(rd32(h2 + H_TAG), who), tag4(0x4348544d, was), tag4(rd32(c2 + 0xc), nowc));
	}
}

// ---- save-file transfer (host -> guest) --------------------------------------------------------
// The guest builds its world from the same save file the host loaded, so the transfer sends the file the
// host's load named first (o2.sav for the main menu's Load Game, gameN.sav for a pause-menu slot) and then
// Save\game0..9.sav, in 512-byte chunks; the guest writes them and acks each chunk; a chunk that is not
// acked is retransmitted after 250 ms. Several chunks are in flight at once (SAVE_WINDOW): stop-and-wait
// moved one chunk per round trip, so 400 KB took 150 s over a 60 ms relay link and never finished inside
// the test. The ack arrives on the network thread while the frame thread sends, so all of the transfer
// state is guarded by g_save_cs.
//
// Each completed file is announced by name (PKT_SAVES_DONE), so the guest waits for the exact file its
// load needs instead of for all ten. A file the host loads after the join transfer (a second load in one
// session) is queued and sent then (host_save_include).
#define SAVE_RETRY_MS 250
#define SAVE_WINDOW 16
#define SAVE_MAX_FILES 12    // the loaded file plus game0..9.sav
#define SAVE_DONE_MS 200     // PKT_SAVES_DONE has no ack: each notice is repeated a few times
#define SAVE_DONE_REPEAT 4
typedef struct { DWORD off, len, sent_at; int sent, acked; BYTE data[SAVE_CHUNK]; } save_chunk;
typedef struct { char name[32]; DWORD at; int left; } save_done_rep;
static CRITICAL_SECTION g_save_cs;
static char g_save_list[SAVE_MAX_FILES][32];   // host: the files of this transfer, in send order
static int g_save_cnt;
static char g_last_load_name[32];              // host: the file the last load named ("" = a new game)
static DWORD g_save_file, g_save_next;   // the file being sent and the next offset to read
static int g_save_eof;                   // the file's last (short or empty) chunk has been queued
static int g_save_active, g_save_n;      // transfer running; chunks in the window, in send order
static int g_save_done_sent;             // the "all files acked" notice was sent for this welcome
static save_chunk g_save_win[SAVE_WINDOW];
static save_done_rep g_save_done_rep[SAVE_MAX_FILES];
static int g_save_done_n;
// Guest: the files the host's transfer has completed (each is whole on disk), so a real load may use it.
#define SAVE_RCVD_MAX 16
static CRITICAL_SECTION g_rcvd_cs;
static char g_save_rcvd[SAVE_RCVD_MAX][32];
static int g_save_rcvd_n;
static volatile LONG g_saves_done;   // guest: the whole transfer has finished (status line)

// A save file name from the game or the host: a plain name inside Save\ (never a path).
static int save_name_ok(const char *name)
{
	size_t l = name ? strlen(name) : 0;
	return l > 0 && l < 32 && !strchr(name, '\\') && !strchr(name, '/') && !strchr(name, ':') && !strstr(name, "..");
}

// Host: is this file already in the transfer list? (g_save_cs held)
static int save_list_index(const char *name)
{
	for (int i = 0; i < g_save_cnt; i++)
		if (!_stricmp(g_save_list[i], name))
			return i;
	return -1;
}

static int save_list_has(const char *name)
{
	return save_list_index(name) >= 0;
}

static void save_bak_path(char *out, size_t n, const char *name)
{
	char exe[MAX_PATH];
	GetModuleFileNameA(NULL, exe, sizeof exe);
	char *slash = strrchr(exe, '\\');
	if (slash) *slash = 0;
	_snprintf(out, n, "%s\\Save.bak\\%s", exe, name);
}

static void save_path(char *out, size_t n, const char *name)
{
	char exe[MAX_PATH];
	GetModuleFileNameA(NULL, exe, sizeof exe);
	char *slash = strrchr(exe, '\\');
	if (slash) *slash = 0;
	_snprintf(out, n, "%s\\Save\\%s", exe, name);
}

// The game's own save files do NOT live in <exe>\Save: its save manager reads them through Steam
// RemoteStorage, which this mod's proxy maps to <exe>\coop_profile\remote\<name> (obscoop2.c remote_path).
// OBSERVED (TASK 14): `loadsave o2.sav` with the file only in Save\ logged "remote FileExists o2.sav -> 0"
// and the game's open failed; with the file in coop_profile\remote\ it was read. A transferred save must
// land there to be loadable, so the transfer reads/writes that copy and keeps <exe>\Save in step.
static void save_game_path(char *out, size_t n, const char *name)
{
	char exe[MAX_PATH];
	GetModuleFileNameA(NULL, exe, sizeof exe);
	char *slash = strrchr(exe, '\\');
	if (slash) *slash = 0;
	_snprintf(out, n, "%s\\coop_profile\\remote\\%s", exe, name);
}

// The copy of a save that exists (the game's own folder first, then the Save mirror); 0 if neither.
static int save_existing_path(char *out, size_t n, const char *name)
{
	save_game_path(out, n, name);
	if (GetFileAttributesA(out) != INVALID_FILE_ATTRIBUTES)
		return 1;
	save_path(out, n, name);
	return GetFileAttributesA(out) != INVALID_FILE_ATTRIBUTES;
}

// Host: send the saves again from the first file. Called from the welcome path, so a guest that reconnects
// (or missed chunks) gets a clean transfer. The file the host's latest load named goes first: the guest's
// load waits for exactly that file.
static void host_save_begin(void)
{
	EnterCriticalSection(&g_save_cs);
	g_save_cnt = 0;
	if (save_name_ok(g_last_load_name))
		_snprintf(g_save_list[g_save_cnt++], sizeof g_save_list[0], "%s", g_last_load_name);
	for (int i = 0; i < 10 && g_save_cnt < SAVE_MAX_FILES; i++) {
		char name[16];
		_snprintf(name, sizeof name, "game%d.sav", i);
		if (!save_list_has(name))
			_snprintf(g_save_list[g_save_cnt++], sizeof g_save_list[0], "%s", name);
	}
	g_save_active = 1;
	g_save_file = 0;
	g_save_next = 0;
	g_save_eof = 0;
	g_save_n = 0;
	g_save_done_sent = 0;
	g_save_done_n = 0;
	memset(g_save_done_rep, 0, sizeof g_save_done_rep);
	logf("host: save transfer starts (%d file%s, first \"%s\")", g_save_cnt, g_save_cnt == 1 ? "" : "s",
		g_save_cnt ? g_save_list[0] : "");
	LeaveCriticalSection(&g_save_cs);
}

// Host: the game is loading this save file. Remember it (a guest that joins later must load the same file,
// CASE 1) and make sure the guest receives exactly it: it goes first on the next welcome, or it is queued
// and sent right away when the join transfer is already running or finished (a second load, CASE 3).
static void host_save_include(const char *name)
{
	if (!save_name_ok(name))
		return;
	int send_now = 0, fresh = 0;
	EnterCriticalSection(&g_save_cs);
	_snprintf(g_last_load_name, sizeof g_last_load_name, "%s", name);
	int idx = save_list_index(name);
	if (g_peer_ok && idx < 0 && g_save_cnt < SAVE_MAX_FILES) {
		_snprintf(g_save_list[g_save_cnt++], sizeof g_save_list[0], "%s", name);
		idx = g_save_cnt - 1;
		fresh = 1;
	}
	if (g_peer_ok && idx >= 0 && !g_save_active) {
		// The join transfer is over: (re)send this file now. It may be new (a second load naming a file the
		// join transfer never sent) or the guest may have lost it — the load waits for the notice either way.
		g_save_file = (DWORD)idx;
		g_save_next = 0;
		g_save_eof = 0;
		g_save_n = 0;
		g_save_done_sent = 0;
		g_save_active = 1;
		send_now = 1;
	}
	LeaveCriticalSection(&g_save_cs);
	if (send_now)
		logf("host: \"%s\" is %s in the save transfer for the guest", name,
			fresh ? "added" : "sent again");
}

// Host: the host's world no longer comes from a save file (a new game, back to the menu).
static void host_save_forget(void)
{
	EnterCriticalSection(&g_save_cs);
	g_last_load_name[0] = 0;
	LeaveCriticalSection(&g_save_cs);
}

// Host: announce one finished file, or the whole transfer (name NULL), and repeat it: PKT_SAVES_DONE has
// no ack. (g_save_cs held)
static void host_send_saves_done(const char *name)
{
	pkt_saves_done p;
	memset(&p, 0, sizeof p);
	p.all = name ? 0 : 1;
	if (name)
		_snprintf(p.name, sizeof p.name, "%s", name);
	net_send(PKT_SAVES_DONE, &p, (WORD)(sizeof p - sizeof(pkt_hdr)));
	if (g_save_done_n < SAVE_MAX_FILES) {
		save_done_rep *d = &g_save_done_rep[g_save_done_n++];
		_snprintf(d->name, sizeof d->name, "%s", name ? name : "");
		d->at = GetTickCount();
		d->left = SAVE_DONE_REPEAT;
	}
}

static void host_send_saves(void)
{
	EnterCriticalSection(&g_save_cs);
	DWORD now = GetTickCount();
	for (int i = 0; i < g_save_done_n; ) {   // repeat the completion notices the guest may have missed
		save_done_rep *d = &g_save_done_rep[i];
		if (d->left <= 0) {
			memmove(&g_save_done_rep[i], &g_save_done_rep[i + 1], sizeof g_save_done_rep[0] * (g_save_done_n - i - 1));
			g_save_done_n--;
			continue;
		}
		if (now - d->at >= SAVE_DONE_MS) {
			d->at = now;
			d->left--;
			host_send_saves_done(d->name[0] ? d->name : NULL);
		}
		i++;
	}
	if (!g_peer_ok || !g_save_active) {   // the guest is gone; the next welcome starts the transfer again
		g_save_active = 0;
		g_save_n = 0;
		LeaveCriticalSection(&g_save_cs);
		return;
	}
	if (g_save_file >= (DWORD)g_save_cnt) {   // everything was acked (or skipped); wait for the next welcome
		int tell = !g_save_done_sent;
		g_save_done_sent = 1;
		g_save_active = 0;
		g_save_n = 0;
		host_send_saves_done(NULL);
		LeaveCriticalSection(&g_save_cs);
		if (tell)
			logf("host: save transfer finished, the guest may load a transferred save");
		return;
	}
	// Advance over every chunk at the head that was acked. The file is done when a chunk shorter than
	// SAVE_CHUNK (its last one, possibly empty) has been acked.
	while (g_save_n > 0 && g_save_win[0].acked) {
		int end = g_save_win[0].len < SAVE_CHUNK;
		memmove(&g_save_win[0], &g_save_win[1], sizeof g_save_win[0] * (g_save_n - 1));
		g_save_n--;
		if (end) {
			char fin[32];
			_snprintf(fin, sizeof fin, "%s", g_save_list[g_save_file]);
			g_save_file++;
			g_save_next = 0;
			g_save_eof = 0;
			g_save_n = 0;
			host_send_saves_done(fin);
			logf("host: the guest has \"%s\" (%u of %d files)", fin, (unsigned)g_save_file, g_save_cnt);
		}
	}
	while (g_save_n < SAVE_WINDOW && g_save_file < (DWORD)g_save_cnt && !g_save_eof) {
		const char *name = g_save_list[g_save_file];
		char path[MAX_PATH];
		HANDLE f = INVALID_HANDLE_VALUE;
		if (save_existing_path(path, sizeof path, name))
			f = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING, 0, NULL);
		if (f == INVALID_HANDLE_VALUE) {
			if (g_save_n > 0)   // a file cannot vanish in the middle of its window; try again next frame
				break;
			g_save_file++;      // no such save on this host: skip it
			g_save_next = 0;
			g_save_eof = 0;
			continue;
		}
		save_chunk *c = &g_save_win[g_save_n];
		DWORD got = 0;
		SetFilePointer(f, g_save_next, NULL, FILE_BEGIN);
		ReadFile(f, c->data, SAVE_CHUNK, &got, NULL);
		CloseHandle(f);
		c->off = g_save_next;
		c->len = got;
		c->sent = 0;
		c->acked = 0;
		g_save_next += got;
		// A short read is the file's last chunk; a 0-byte chunk at an exact multiple of SAVE_CHUNK says
		// "end of file" so its ack completes the file.
		if (got < SAVE_CHUNK)
			g_save_eof = 1;
		g_save_n++;
	}
	// Send what was never sent; retransmit the rest when its 250 ms are up. The slot exists before the
	// send, so an ack that comes back before sendto() returns cannot be lost.
	for (int i = 0; i < g_save_n; i++) {
		save_chunk *c = &g_save_win[i];
		if (c->acked || (c->sent && now - c->sent_at < SAVE_RETRY_MS))
			continue;
		pkt_save p; memset(&p, 0, sizeof p);
		_snprintf(p.name, sizeof p.name, "%s", g_save_list[g_save_file]);
		p.off = c->off;
		p.len = c->len;
		if (c->len)
			memcpy(p.data, c->data, c->len);
		c->sent = 1;
		c->sent_at = now;
		net_send(PKT_SAVE, &p, (WORD)(sizeof p - sizeof(pkt_hdr)));
	}
	LeaveCriticalSection(&g_save_cs);
}

static void host_on_save_ack(const char *buf, int n)
{
	if (n != (int)sizeof(pkt_save_ack)) return;
	const pkt_save_ack *a = (const pkt_save_ack *)buf;
	char acked[sizeof a->name + 1];
	memcpy(acked, a->name, sizeof a->name);
	acked[sizeof a->name] = 0;
	EnterCriticalSection(&g_save_cs);
	// Mark the chunk it acknowledges; a stale or duplicated ack (wrong file or offset) is ignored.
	if (g_save_active && g_save_file < (DWORD)g_save_cnt) {
		if (!_stricmp(acked, g_save_list[g_save_file]))
			for (int i = 0; i < g_save_n; i++)
				if (g_save_win[i].off == a->off && !g_save_win[i].acked) {
					g_save_win[i].acked = 1;
					break;
				}
	}
	LeaveCriticalSection(&g_save_cs);
}

// Guest: a new session (the host welcomed us), so the host starts its transfer again. Forget what the
// previous one completed; the files are still on disk, but the host's copies may have changed.
static void guest_save_session(void)
{
	EnterCriticalSection(&g_rcvd_cs);
	g_save_rcvd_n = 0;
	LeaveCriticalSection(&g_rcvd_cs);
	InterlockedExchange(&g_saves_done, 0);
}

static int guest_save_complete(const char *name)
{
	int ok = 0;
	EnterCriticalSection(&g_rcvd_cs);
	for (int i = 0; i < g_save_rcvd_n; i++)
		if (!_stricmp(g_save_rcvd[i], name)) { ok = 1; break; }
	LeaveCriticalSection(&g_rcvd_cs);
	return ok;
}

static void guest_on_saves_done(const char *buf, int n)
{
	if (n != (int)sizeof(pkt_saves_done)) return;
	const pkt_saves_done *p = (const pkt_saves_done *)buf;
	if (!memchr(p->name, 0, sizeof p->name)) return;
	if (p->name[0]) {
		if (!save_name_ok(p->name)) return;
		int fresh = !guest_save_complete(p->name);
		if (fresh) {
			EnterCriticalSection(&g_rcvd_cs);
			if (g_save_rcvd_n < SAVE_RCVD_MAX)
				_snprintf(g_save_rcvd[g_save_rcvd_n++], sizeof g_save_rcvd[0], "%s", p->name);
			LeaveCriticalSection(&g_rcvd_cs);
			logf("guest: the host's save transfer has \"%s\" (whole file on disk)", p->name);
		}
	}
	if (p->all && InterlockedExchange(&g_saves_done, 1) == 0)
		logf("guest: the host's save transfer is complete (transferred saves may be loaded)");
}

static void guest_on_save(const char *buf, int n)
{
	if (n != (int)sizeof(pkt_save)) return;   // a short packet must not make us read past data[]
	const pkt_save *p = (const pkt_save *)buf;
	if (!memchr(p->name, 0, sizeof p->name) || !save_name_ok(p->name)) return;
	if (p->len > SAVE_CHUNK) return;
	// Both copies the game might use: the one its save manager really reads (coop_profile\remote) and the
	// Save mirror the owner's setup and check_savexfer.py look at.
	char paths[2][MAX_PATH];
	save_game_path(paths[0], sizeof paths[0], p->name);
	save_path(paths[1], sizeof paths[1], p->name);
	for (int i = 0; i < 2; i++) {
		char dir[MAX_PATH]; _snprintf(dir, sizeof dir, "%s", paths[i]);
		char *slash = strrchr(dir, '\\'); if (slash) *slash = 0;
		CreateDirectoryA(dir, NULL);
	}
	if (p->off == 0) {
		// First chunk of a file: this may be a re-transfer of a file the guest already has (the host sends the
		// file its load names again). Until the host announces this file complete again, the copy on disk is
		// being rewritten and must not be loaded: forgetting the completion is what makes the guest wait.
		EnterCriticalSection(&g_rcvd_cs);
		for (int i = 0; i < g_save_rcvd_n; i++)
			if (!_stricmp(g_save_rcvd[i], p->name)) {
				memmove(&g_save_rcvd[i], &g_save_rcvd[i + 1], sizeof g_save_rcvd[0] * (g_save_rcvd_n - i - 1));
				g_save_rcvd_n--;
				break;
			}
		LeaveCriticalSection(&g_rcvd_cs);
		// Keep the guest's own copy before the host's version overwrites it. The owner agreed to this;
		// CopyFileA with bFailIfExists never replaces an earlier backup.
		char bak[MAX_PATH], bakdir[MAX_PATH], src[MAX_PATH];
		save_bak_path(bak, sizeof bak, p->name);
		_snprintf(bakdir, sizeof bakdir, "%s", bak);
		char *bs = strrchr(bakdir, '\\'); if (bs) *bs = 0;
		CreateDirectoryA(bakdir, NULL);
		if (save_existing_path(src, sizeof src, p->name) && CopyFileA(src, bak, TRUE))
			logf("guest: kept the guest's own \"%s\" (%s) in Save.bak before the host's copy overwrote it",
				p->name, strstr(src, "coop_profile") ? "the game's save folder" : "Save");
	}
	for (int i = 0; i < 2; i++) {
		HANDLE f = CreateFileA(paths[i], GENERIC_WRITE, FILE_SHARE_READ, NULL, OPEN_ALWAYS, 0, NULL);
		if (f == INVALID_HANDLE_VALUE) {
			if (i == 0) return;   // the game's own copy is the one that matters: not acked, retransmitted
			continue;
		}
		SetFilePointer(f, p->off, NULL, FILE_BEGIN);
		DWORD wrote = 0; WriteFile(f, p->data, p->len, &wrote, NULL); CloseHandle(f);
		if (i == 0 && wrote != p->len)
			return;   // the game's copy is short: not acked, the host retransmits this chunk
	}
	pkt_save_ack a; memset(&a, 0, sizeof a);
	_snprintf(a.name, sizeof a.name, "%s", p->name);
	a.off = p->off;
	net_send(PKT_SAVE_ACK, &a, (WORD)(sizeof a - sizeof(pkt_hdr)));
}

// ---- host: snapshots ---------------------------------------------------------------------------

// ---- host: inventory mirror -------------------------------------------------------------------
// The save's inventory object (world+0x1790, vtable 0x665844) holds a count at +4 and 32-byte entries
// at +8 (entry = obj + 8 + i*0x20; FUN_004b04a0 returns exactly that address). It is not part of the
// character or progress packets, so mirror it when it changes. One entry is 8 dwords: flags, tag, id,
// ammo, then a float at +0x10 that FUN_004b0300 turns into the ammo of a DYNA/FLBG weapon. The old
// packet assumed 16-byte entries and copied only count*16 bytes, which truncated the guest's inventory
// after entry ~22 and left DYNA/FLBA (indices 28/23) with no entry to build from (TASK6_FINDINGS).
#define ITEM_RESEND_MS 1000       // repeat the mirror at this rate: a lost chunk, or a guest whose world is not
                                  // ready yet, still converges (the inventory is a few KB, the cost is small)
static DWORD g_item_last_count, g_item_last_hash;
static DWORD g_item_sent_at;
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
	for (DWORD i = 0; i < count * 8; i++) h = h * 31 + rd32(inv + 8 + i * 4);   // whole 32-byte entries
	if (count == g_item_last_count && h == g_item_last_hash && now - g_item_sent_at < ITEM_RESEND_MS)
		return;   // unchanged and repeated a moment ago
	g_item_last_count = count; g_item_last_hash = h;
	g_item_sent_at = now;
	pkt_item p;
	for (DWORD off = 0; off < count; off += ITEM_CHUNK) {
		DWORD n = count - off < ITEM_CHUNK ? count - off : ITEM_CHUNK;
		const void *src = (const void *)(uintptr_t)(inv + 8 + off * 0x20);
		memset(&p, 0, sizeof p);
		p.level = rd32(w + 4);
		p.off = off; p.count = n; p.total = count;
		if (mem_ok(src, n * 0x20))
			memcpy(p.data, src, n * 0x20);
		net_send(PKT_ITEM, &p, (WORD)(sizeof p - sizeof(pkt_hdr)));
	}
	if (count == 0) {   // an emptied inventory is still a state the guest must take
		memset(&p, 0, sizeof p);
		p.level = rd32(w + 4);
		net_send(PKT_ITEM, &p, (WORD)(sizeof p - sizeof(pkt_hdr)));
	}
}

// The guest assembles the chunks in a shadow copy and writes the inventory only when every chunk of
// one total is present: a lost or late datagram must not leave a half-mirrored inventory (that is what
// hid DYNA/FLBA from weapon_object).
static BYTE g_item_shadow[ITEM_MAX * 0x20];
static unsigned g_item_inv;      // the inventory object the assembly is for
static DWORD g_item_total, g_item_have;   // entries expected, bitmask of chunks received
static int g_item_parts;                  // chunks per total

static void guest_on_item(const char *buf, int n)
{
	if (n != (int)sizeof(pkt_item)) return;   // n is the whole datagram, header included (see net_handle)
	const pkt_item *p = (const pkt_item *)buf;
	unsigned w = world_obj();
	unsigned inv = w ? rd32(w + 0x1790) : 0;
	if (!inv || p->level != rd32(w + 4)) return;
	DWORD total = p->total;
	if (total > ITEM_MAX || p->count > ITEM_CHUNK || p->off % ITEM_CHUNK || p->off + p->count > total)
		return;
	if (inv != g_item_inv) {   // a new world's inventory: drop any partial assembly
		g_item_inv = inv; g_item_total = 0; g_item_have = 0; g_item_parts = 0;
	}
	if (total == 0) {
		*(DWORD *)(uintptr_t)(inv + 4) = 0;
		g_item_total = 0; g_item_have = 0; g_item_parts = 0;
		InterlockedIncrement(&g_item_applied);
		return;
	}
	if (total != g_item_total) {
		g_item_total = total; g_item_have = 0;
		g_item_parts = (int)((total + ITEM_CHUNK - 1) / ITEM_CHUNK);
	}
	if (p->off == 0)   // every send starts here: a repeated first chunk starts a fresh assembly
		g_item_have = 0;
	memcpy(g_item_shadow + p->off * 0x20, p->data, p->count * 0x20);
	g_item_have |= 1u << (p->off / ITEM_CHUNK);
	if (g_item_have != (1u << g_item_parts) - 1)
		return;   // still waiting for a chunk
	if (IsBadWritePtr((void *)(uintptr_t)(inv + 8), total * 0x20))
		return;   // the world went away between the pointer read and now
	memcpy((void *)(uintptr_t)(inv + 8), g_item_shadow, total * 0x20);
	*(DWORD *)(uintptr_t)(inv + 4) = total;
	g_item_total = 0; g_item_have = 0; g_item_parts = 0;
	InterlockedIncrement(&g_item_applied);
}

// ---- world item pickup (both directions) ---------------------------------------------------------
// A placed world item (a CToeItem entity in the level's CToeManager) is collected by a character on one
// copy; the other copy must collect the same entity through the game's own collect method so it
// disappears there too. The item is identified by its class tag (+0x10) and id (+4).
//
// Hook (hooks.c): FUN_004ddad0, the character-side collect call, fires after the ~500 ms pickup
// animation with the target entity in character+0x73c. The hook sends when the item is not collected
// yet. Both roles send: the host's own player and the guest's own player (player 2 on the host copy)
// each collect on their own copy, and the other copy applies. An applied pickup calls the item's
// virtual slot 26 (vtable+0x68, the same call FUN_004ddad0 makes) directly, so it never reaches the
// hook again: no echo. g_pickup_applying is a second guard in case that path ever calls the hook.
static volatile LONG g_pickup_sent, g_pickup_rcv, g_pickup_applied, g_pickup_skipped, g_pickup_missing;
static volatile LONG g_pickup_applying;

static void pickup_local_collect(unsigned item, unsigned ch)
{
	if (g_pickup_applying || !item || !ch)
		return;
	if (!g_peer_ok)
		return;
	unsigned w = world_obj();
	if (!w || rd32(item + 0xa8) != 0)
		return;
	pkt_pickup p;
	memset(&p, 0, sizeof p);
	p.level = rd32(w + 4);
	p.cls = rd32(item + 0x10);
	p.id = rd32(item + 4);
	p.ch_tag = rd32(ch + H_TAG);
	if (mem_ok((const void *)(uintptr_t)(item + 0x6c), 12))
		memcpy(p.pos, (const void *)(uintptr_t)(item + 0x6c), sizeof p.pos);
	net_send(PKT_PICKUP, &p, (WORD)(sizeof p - sizeof(pkt_hdr)));
	InterlockedIncrement(&g_pickup_sent);
	char c[5], i[5], lv[5], ct[5];
	logf("%s: item pickup sent: class %s id %s at (%.1f, %.1f, %.1f) by %s [level %s]",
		g_role == 2 ? "guest" : "host", tag4(p.cls, c), tag4(p.id, i), p.pos[0], p.pos[1], p.pos[2],
		tag4(p.ch_tag, ct), tag4(p.level, lv));
}

static CRITICAL_SECTION g_pick_cs;
static pkt_pickup g_pick_q[8];
static DWORD g_pick_t[8];
static int g_pick_head, g_pick_tail;

static void peer_on_pickup(const char *buf, int n)
{
	if (n != (int)sizeof(pkt_pickup))
		return;
	EnterCriticalSection(&g_pick_cs);
	if (((g_pick_tail + 1) & 7) != g_pick_head) {
		memcpy(&g_pick_q[g_pick_tail], buf, sizeof(pkt_pickup));
		g_pick_t[g_pick_tail] = GetTickCount();
		g_pick_tail = (g_pick_tail + 1) & 7;
	}
	LeaveCriticalSection(&g_pick_cs);
	InterlockedIncrement(&g_pickup_rcv);
}

// CToeManager::GetEntityByClassAndID (0x45f540, thiscall: manager, class tag, id).
typedef int(__fastcall *find_entity_t)(void *, void *, unsigned, unsigned);
// The item's virtual slot 26 (vtable+0x68): the collect method FUN_004ddad0 calls.
typedef int(__fastcall *item_collect_t)(void *, void *, void *);

static unsigned human_with_tag(unsigned tag)
{
	unsigned hs[MAX_CH];
	int n = world_humans(hs, MAX_CH);
	for (int i = 0; i < n; i++)
		if (rd32(hs[i] + H_TAG) == tag)
			return hs[i];
	unsigned h = player_human(g_role == 2 ? 1 : 0);
	if (h)
		return h;
	return n > 0 ? hs[0] : 0;
}

// The entity the packet names: same class tag and (when the packet has one) the same id. Item ids are
// often 0, so the position decides which of several same-class entities is meant. A collected
// candidate is only used when nothing live matches (then the caller reports "already collected").
static unsigned pickup_find_entity(unsigned mgr, unsigned cls, unsigned id, const float *pp)
{
	unsigned best = 0, best_dead = 0;
	float bd = 1e30f;
	if (!mgr)
		return 0;
	unsigned heads[2] = { rd32(mgr + 8), rd32(mgr + 0x18) };
	for (int h = 0; h < 2; h++) {
		unsigned seen[2] = { 0, 0 };
		int nseen = 0;
		for (unsigned node = heads[h], guard = 0; node && guard < 4000; guard++) {
			int dup = 0;
			for (int s = 0; s < nseen; s++)
				if (seen[s] == node)
					dup = 1;
			if (dup)
				break;
			if (nseen < 2)
				seen[nseen++] = node;
			unsigned e = rd32(node);
			if (e && rd32(e + 0x10) == cls && (!id || rd32(e + 4) == id)) {
				if (rd32(e + 0xa8) != 0) {
					if (!best_dead)
						best_dead = e;
				} else {
					const float *ep = (const float *)(uintptr_t)(e + 0x6c);
					float dx = ep[0] - pp[0], dy = ep[1] - pp[1], dz = ep[2] - pp[2];
					float d = dx * dx + dy * dy + dz * dz;
					if (d < bd) { bd = d; best = e; }
				}
			}
			unsigned nx = rd32(node + 4);
			if (nx == node)
				break;
			node = nx;
		}
	}
	if (best)
		return best;
	if (best_dead)
		return best_dead;
	return (unsigned)(uintptr_t)((find_entity_t)0x45f540)((void *)(uintptr_t)mgr, NULL, cls, id);
}

static void peer_apply_pickups(void)
{
	for (;;) {
		pkt_pickup p;
		EnterCriticalSection(&g_pick_cs);
		if (g_pick_head == g_pick_tail) {
			LeaveCriticalSection(&g_pick_cs);
			return;
		}
		p = g_pick_q[g_pick_head];
		DWORD queued = g_pick_t[g_pick_head];
		LeaveCriticalSection(&g_pick_cs);
		unsigned g = game_obj(), w = world_obj();
		if (GetTickCount() - queued > 10000) {   // never applicable (the level changed): do not block the queue
			EnterCriticalSection(&g_pick_cs);
			g_pick_head = (g_pick_head + 1) & 7;
			LeaveCriticalSection(&g_pick_cs);
			InterlockedIncrement(&g_pickup_missing);
			logf("%s: item pickup class %08x id %08x dropped: not applied within 10 s (level changed?)",
				g_role == 2 ? "guest" : "host", p.cls, p.id);
			continue;
		}
		if (!g || !w || rd32(g + 0x310) != 1 || rd32(g + 0x320) != 0)
			return;   // menu or loading: keep the pickup queued
		if (rd32(w + 4) != p.level)
			return;   // another level: keep it queued (a level change may be in progress)
		EnterCriticalSection(&g_pick_cs);
		g_pick_head = (g_pick_head + 1) & 7;
		LeaveCriticalSection(&g_pick_cs);
		char c[5], i[5], lv[5], ct[5];
		unsigned mgr = rd32(w + 0x1768);
		unsigned ent = pickup_find_entity(mgr, p.cls, p.id, p.pos);
		if (!ent) {
			InterlockedIncrement(&g_pickup_missing);
			logf("%s: item pickup class %s id %s: no entity in level %s (already gone)",
				g_role == 2 ? "guest" : "host", tag4(p.cls, c), tag4(p.id, i), tag4(p.level, lv));
			continue;
		}
		if (rd32(ent + 0xa8) != 0) {
			InterlockedIncrement(&g_pickup_skipped);
			logf("%s: item pickup class %s id %s: already collected",
				g_role == 2 ? "guest" : "host", tag4(p.cls, c), tag4(p.id, i));
			continue;
		}
		unsigned ch = human_with_tag(p.ch_tag);
		void **vt = *(void ***)(uintptr_t)ent;
		if (!ch || !vt || IsBadReadPtr(vt, 27 * sizeof(void *)) || !mem_ok((const void *)(uintptr_t)ent, 0xac)) {
			InterlockedIncrement(&g_pickup_missing);
			logf("%s: item pickup class %s id %s: no character or item vtable",
				g_role == 2 ? "guest" : "host", tag4(p.cls, c), tag4(p.id, i));
			continue;
		}
		InterlockedIncrement(&g_pickup_applying);
		((item_collect_t)vt[26])((void *)(uintptr_t)ent, NULL, (void *)(uintptr_t)ch);   // the game's own collect path
		InterlockedDecrement(&g_pickup_applying);
		InterlockedIncrement(&g_pickup_applied);
		logf("%s: item pickup applied: class %s id %s at level %s by %s (collected=%u)",
			g_role == 2 ? "guest" : "host", tag4(p.cls, c), tag4(p.id, i), tag4(p.level, lv),
			tag4(p.ch_tag, ct), rd32(ent + 0xa8));
	}
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
		c->anim = rd32(hs[i] + 0x2dc);
		c->life = rd32(hs[i] + 0x320);
		for (int s = 0; s < 4; s++) {
			unsigned wp = rd32(hs[i] + 0x704 + 4 * s);   // the live weapon object in slot s
			c->wep[s] = wp ? rd32(wp + 0x10) : 0;        // its tag, 0 = empty slot
		}
		c->wcur = rd32(hs[i] + 0x714);                   // the slot in the hand
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

// ---- guest: the weapons in the characters' hands --------------------------------------------------
// The live weapon state is on the character itself: +0x704 + i*4 is the object in slot i (the object
// carries its 4-character tag at +0x10, 0 = empty slot) and +0x714 is the slot in the hand. None of it is
// in the 0x140-byte record block, so the host sends the four tags per character in ch_state and the guest
// makes its hands match with the game's own functions (HANDS_FINDINGS.md section 2):
//   0x4b0980  __stdcall(tag) -> the world entity carrying a weapon tag
//   0x45cdd0  entity factory, ECX = *(world+0x1768): constructs the class for a tag
//   0x4b0300  ECX = inventory entry, fills the entity from the entry (tag, id, ammo) - what the inventory
//             pass (FUN_004b05a0) does right after the factory
//   0x5544c0  ECX = *(world+0x1768)+0x18, takes the entity: registers it in the world's entity list
//   0x4dc870  the game's equip, ECX = human, takes (weapon object, slot): owner, slot, selected index, show
// The apply runs in the input-update hook (the game's own update), not in the Present hook: the factory
// loads weapon assets, and doing that inside Present stopped the guest dead in the first live attempt.
typedef unsigned(__stdcall *find_weapon_t)(unsigned tag);
typedef void *(__fastcall *new_weapon_t)(void *mgr, void *edx, unsigned tag);
typedef void(__fastcall *fill_weapon_t)(void *entry, void *edx, void *ent);
typedef void(__fastcall *list_weapon_t)(void *list, void *edx, void *ent);
typedef void(__fastcall *ent_call1_t)(void *ent, void *edx, int arg);
typedef int(__fastcall *equip_weapon_t)(void *human, void *edx, void *weapon, int slot);

static int code_ok(unsigned addr, const BYTE *prologue, int len)
{
	return mem_ok((const void *)(uintptr_t)addr, len) && !memcmp((const void *)(uintptr_t)addr, prologue, len);
}

// ---- a real save load through the game's own menu path -------------------------------------------
// The menu's Load is two calls, not one (FINDINGS_12 (a), disassembly 0x5484ef..0x548514):
//   1. the save manager (game+0x3e4) opens the file:  manager->open(name)  = FUN_0053d9b0
//   2. the game is asked to load what it opened:      LoadByName(name)     = FUN_004a1bd0 (state 3)
// The game's own update (FUN_004a5f20 -> FUN_004a5520) then reads the chunks into game+0x318 and builds
// the level itself. Replaying the pair brings a copy that sits at the main menu straight into the save,
// so the guest builds its own world from the same file instead of having the host's world patched into a
// default one (FINDINGS_11: empty hands, 8 vs 43 world entities).
// Both calls must run on the game's thread: the save manager allocates and reads inside the game, and the
// request state machine is not thread-safe. They run from the game update hook (hk_game_update, hooks.c).
#define LOAD_WAIT_MS 10000          // how long a real load may wait for its file (the save transfer may be running)
static CRITICAL_SECTION g_rload_cs;
static volatile LONG g_rload_want;   // 1 = a real load is waiting for the game thread
static char g_rload_name[32];
static char g_rload_src[8];          // "pipe" (host test command) or "host" (a request from the host)
static DWORD g_rload_at;             // when the load was asked for (the wait is measured from it)
static DWORD g_real_load_at;         // guest: when this copy's own real load was issued
static volatile LONG g_real_load_stage;   // guest: 0 none, 1 issued, 2 the world it built is up

// A copy may not load a save the host is still transferring: the file would be half written. The host
// sends PKT_SAVES_DONE when the last chunk of the last save has been acked on the guest.
static int save_file_ready(const char *name)
{
	char path[MAX_PATH];
	if (!name[0])
		return 0;
	if (!save_existing_path(path, sizeof path, name))
		return 0;
	// The guest only loads a file the host's own transfer has completed: its own copy may be stale, and a
	// half-written file would load as garbage. (CASE 2: wait for exactly this file, not for all of them.)
	if (g_role == 2 && !guest_save_complete(name))
		return 0;
	return 1;
}

// Ask the game thread for a real load. Safe from the pipe thread (host test command) and from the frame
// tick (guest: a request from the host); the calls themselves happen in game_load_tick.
static void request_real_load(const char *name, const char *src)
{
	EnterCriticalSection(&g_rload_cs);
	_snprintf(g_rload_name, sizeof g_rload_name, "%s", name ? name : "");
	_snprintf(g_rload_src, sizeof g_rload_src, "%s", src ? src : "");
	g_rload_at = GetTickCount();
	InterlockedExchange(&g_rload_want, 1);
	LeaveCriticalSection(&g_rload_cs);
	logf("%s: real load of \"%.31s\" requested (%s)", g_role == 2 ? "guest" : "host", g_rload_name, g_rload_src);
}

// The save manager's open-by-name (FUN_0053d9b0, thiscall: ECX = manager, one stack argument).
typedef unsigned(__fastcall *save_open_t)(void *mgr, void *edx, const char *name);
typedef void(__fastcall *load_name_t)(void *game, void *edx, unsigned name);

static int game_save_open(unsigned game, const char *name)
{
	static const BYTE p_open[6] = { 0x55, 0x8b, 0xec, 0x6a, 0xff, 0x68 };
	unsigned mgr = game ? rd32(game + 0x3e4) : 0;
	if (!mgr || IsBadReadPtr((const void *)(uintptr_t)mgr, 0x200) || !code_ok(0x53d9b0, p_open, 6))
		return 0;
	return (int)((save_open_t)0x53d9b0)((void *)(uintptr_t)mgr, NULL, name);
}

// Guest: is this the level the guest has just loaded itself? Then a host level request for it must not
// rebuild the world (the file already built it); it is a "verify", not a change.
static int guest_owns_level(unsigned level)
{
	if (!g_real_load_at || (LONG)(GetTickCount() - g_real_load_at) > 25000)
		return 0;
	unsigned w = world_obj();
	return w && rd32(w + 4) == level;
}

static void guest_load_failed(const char *name);   // sync.c: the game refused the file, take a repeat again

// Runs on the game's own thread, every frame, in every mode (main menu included).
static void game_load_tick(unsigned game)
{
	if (!game)
		return;
	{   // the first call proves the hook really runs at the main menu
		static int said;
		if (!said) {
			said = 1;
			logf("%s: game update hook runs (mode %u world %#x)", g_role == 2 ? "guest" : "host",
				rd32(game + 0x310), rd32(game + 0x378));
		}
	}
	if (g_role == 2 && g_real_load_stage == 1 && rd32(game + 0x310) == 1 && rd32(game + 0x320) == 0 &&
	    rd32(game + 0x378)) {
		char lv[5];
		g_real_load_stage = 2;
		logf("guest: the world this copy built from the save itself is up (level %s, %u ms after the load)",
			tag4(rd32(rd32(game + 0x378) + 4), lv), GetTickCount() - g_real_load_at);
	}
	if (!g_rload_want)
		return;
	char name[32], src[8];
	DWORD at;
	EnterCriticalSection(&g_rload_cs);
	memcpy(name, g_rload_name, sizeof name);
	memcpy(src, g_rload_src, sizeof src);
	at = g_rload_at;
	LeaveCriticalSection(&g_rload_cs);
	name[sizeof name - 1] = 0;
	src[sizeof src - 1] = 0;
	DWORD now = GetTickCount();
	if (!save_file_ready(name)) {
		if ((LONG)(now - at) < LOAD_WAIT_MS)
			return;   // still transferring (or not there yet): keep waiting, the request stays pending
		logf("%s: real load of \"%s\" (%s) given up after %u ms: the host's transfer of that file is not complete",
			g_role == 2 ? "guest" : "host", name, src, now - at);
		InterlockedExchange(&g_rload_want, 0);
		return;
	}
	InterlockedExchange(&g_rload_want, 0);
	int opened = game_save_open(game, name);
	logf("%s: real load of \"%s\" (%s): the game's save open %s", g_role == 2 ? "guest" : "host", name, src,
		opened ? "ok" : "FAILED");
	if (!opened) {
		if (g_role == 2 && !strcmp(src, "host"))   // let the host's repeat of the request through again
			guest_load_failed(name);
		return;
	}
	if (g_role == 2) {   // the guest's own load: remember it, so the host's level request does not rebuild
		g_real_load_at = now;
		g_real_load_stage = 1;
	}
	// Call the hooked entry, not the trampoline: on the host this is what forwards REQ_LOAD_NAME to the
	// guest, exactly like a menu load does.
	((load_name_t)0x4a1bd0)((void *)(uintptr_t)game, NULL, (unsigned)(uintptr_t)name);
	logf("%s: real load of \"%s\" issued (mode %u request state %u)", g_role == 2 ? "guest" : "host", name,
		rd32(game + 0x310), rd32(game + 0x320));
}

// A character's weapon object in the world, found or built the way the game's inventory pass builds it.
static unsigned weapon_object(unsigned tag)
{
	static const BYTE p_find[6] = { 0x55, 0x8b, 0xec, 0xa1, 0x68, 0x30 };
	static const BYTE p_new[6] = { 0x55, 0x8b, 0xec, 0x6a, 0xff, 0x68 };
	static const BYTE p_fill[6] = { 0x55, 0x8b, 0xec, 0x8b, 0x01, 0x8b };
	static const BYTE p_add[6] = { 0x55, 0x8b, 0xec, 0x56, 0x57, 0x8b };
	char t[5];
	if (!code_ok(0x4b0980, p_find, 6) || !code_ok(0x45cdd0, p_new, 6) ||
	    !code_ok(0x4b0300, p_fill, 6) || !code_ok(0x5544c0, p_add, 6))
		return 0;
	unsigned obj = ((find_weapon_t)0x4b0980)(tag);
	if (obj)
		return obj;
	unsigned w = world_obj(), mgr = w ? rd32(w + 0x1768) : 0, inv = w ? rd32(w + 0x1790) : 0;
	if (!mgr || !inv)
		return 0;
	unsigned n = rd32(inv + 4), entry = 0;
	if (n > ITEM_MAX)
		n = ITEM_MAX;
	for (unsigned i = 0; i < n && !entry; i++)
		if (rd32(inv + 8 + i * 0x20 + 4) == tag)          // entry: +0 flags, +4 tag, +0xc ammo
			entry = inv + 8 + i * 0x20;
	if (!entry) {
		logf("guest: weapon %s has no object and no inventory entry", tag4(tag, t));
		return 0;
	}
	obj = (unsigned)(uintptr_t)((new_weapon_t)0x45cdd0)((void *)(uintptr_t)mgr, NULL, tag);
	if (!obj || IsBadWritePtr((void *)(uintptr_t)obj, 0x120)) {
		logf("guest: could not make weapon %s", tag4(tag, t));
		return 0;
	}
	unsigned vt = rd32(obj);
	unsigned v8 = vt ? rd32(vt + 8) : 0, v84 = vt ? rd32(vt + 0x84) : 0;
	if (!v8 || !v84 || IsBadReadPtr((const void *)(uintptr_t)v8, 1) || IsBadReadPtr((const void *)(uintptr_t)v84, 1)) {
		logf("guest: weapon %s has no usable vtable", tag4(tag, t));
		return 0;
	}
	*(DWORD *)(uintptr_t)(obj + 0x28) = 0;
	((ent_call1_t)v8)((void *)(uintptr_t)obj, NULL, 0);                  // the game's vtable+8(0)
	((fill_weapon_t)0x4b0300)((void *)(uintptr_t)entry, NULL, (void *)(uintptr_t)obj);   // tag, id, ammo from the inventory
	((ent_call1_t)v84)((void *)(uintptr_t)obj, NULL, 0);                 // the game's vtable+0x84(0)
	*(DWORD *)(uintptr_t)(obj + 0xa8) = 1;
	((list_weapon_t)0x5544c0)((void *)(uintptr_t)(mgr + 0x18), NULL, (void *)(uintptr_t)obj);   // register it
	logf("guest: made weapon %s (object %p) from the inventory entry", tag4(tag, t), (void *)(uintptr_t)obj);
	return obj;
}

static unsigned g_wep_seen[MAX_CH][4], g_wep_seen_cur[MAX_CH];   // guest: what the last apply reported
static DWORD g_wep_at[MAX_CH][4];                                // guest: and when, to retry a failure later

// Makes one character's four live slots and the selected slot match the host's.
static void weapons_for(int k, unsigned h, const ch_state *c)
{
	static const BYTE p_equip[6] = { 0x55, 0x8b, 0xec, 0x83, 0xec, 0x0c };
	unsigned got[4];
	int same = 1;
	if (IsBadReadPtr((const void *)(uintptr_t)h, 0x718))
		return;
	for (int s = 0; s < 4; s++) {
		unsigned wp = rd32(h + 0x704 + 4 * s);
		got[s] = wp ? rd32(wp + 0x10) : 0;
		if (got[s] != c->wep[s])
			same = 0;
	}
	if (same && (c->wcur >= 4 || rd32(h + 0x714) == c->wcur))
		return;   // already like the host
	char t1[5], t2[5];
	DWORD now = GetTickCount();
	for (int s = 0; s < 4; s++) {
		unsigned want = c->wep[s];
		if (!want || want == got[s])
			continue;   // only fill a gap; a slot the host has empty is left alone
		if (g_wep_seen[k][s] == want && (LONG)(now - g_wep_at[k][s]) < 5000)
			continue;   // tried this one just now
		g_wep_seen[k][s] = want;
		g_wep_at[k][s] = now;
		unsigned obj = weapon_object(want);
		if (!obj) {
			logf("guest: %s slot %d needs weapon %s, none in this world", tag4(rd32(h + H_TAG), t1), s, tag4(want, t2));
			continue;
		}
		if (!code_ok(0x4dc870, p_equip, 6))
			return;
		if (!((equip_weapon_t)0x4dc870)((void *)(uintptr_t)h, NULL, (void *)(uintptr_t)obj, s)) {
			logf("guest: %s slot %d weapon %s refused by the game (object %p)", tag4(rd32(h + H_TAG), t1), s,
				tag4(want, t2), (void *)(uintptr_t)obj);
			continue;
		}
		logf("guest: %s slot %d = weapon %s (object %p)", tag4(rd32(h + H_TAG), t1), s, tag4(want, t2),
			(void *)(uintptr_t)obj);
	}
	// Put the host's weapon in the hand and show it, exactly as the game does after restoring a save
	// (FUN_004f1b80: +0x714 = record+0x24, then the weapon's vtable+0xcc).
	if (c->wcur < 4 && rd32(h + 0x714) != c->wcur) {
		unsigned wp = rd32(h + 0x704 + 4 * c->wcur);
		unsigned vt = wp ? rd32(wp) : 0, show = vt ? rd32(vt + 0xcc) : 0;
		if (wp && show && !IsBadReadPtr((const void *)(uintptr_t)show, 1)) {
			*(DWORD *)(uintptr_t)(h + 0x714) = c->wcur;
			if (g_wep_seen_cur[k] != c->wcur) {
				g_wep_seen_cur[k] = c->wcur;
				logf("guest: %s holds weapon %s (slot %d)", tag4(rd32(h + H_TAG), t1), tag4(c->wep[c->wcur], t2), c->wcur);
			}
			((void(__fastcall *)(void *, void *))show)((void *)(uintptr_t)wp, NULL);   // draw it
		}
	}
}

// guest: the snapshot loop asks for a hands sync; the input-update hook (the game's own update) does it.
static LONG g_weap_pending;
static ch_state g_weap_want[MAX_CH];
static int g_weap_want_n;
static int g_weap_said;

static void guest_weapons_frame(void)
{
	if (g_role != 2 || !g_weap_pending)
		return;
	g_weap_pending = 0;
	unsigned g = game_obj();
	if (!g || rd32(g + 0x310) != 1 || rd32(g + 0x320) != 0)
		return;   // not in game or a request is pending
	unsigned hs[MAX_CH];
	int n = world_humans(hs, MAX_CH), wn = g_weap_want_n > MAX_CH ? MAX_CH : g_weap_want_n;
	for (int i = 0; i < wn; i++) {
		for (int k = 0; k < n; k++) {
			if (rd32(hs[k] + H_TAG) != g_weap_want[i].tag)
				continue;
			weapons_for(k, hs[k], &g_weap_want[i]);
			break;
		}
	}
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
			*(DWORD *)(uintptr_t)(hs[k] + 0x2dc) = st.ch[i].anim;   // death/animation state from the host
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
				// A timed error is a real position error at the snapshot's time, so take half of it per
				// snapshot (a quarter left the guest's own character ~v*dt/0.25 units behind the host's
				// copy while walking: TASK 13 measured mean 10.7 units on loopback). Untimed local
				// movement still gets a gentle 10 % so a late clock does not drag the player's character.
				float kk = (!timed && local && !idle) ? 0.1f : 0.5f;
				pos[0] += ex * kk; pos[1] += ey * kk; pos[2] += ez * kk;
				if (timed)
					hist_shift(st.ch[i].tag, st.t_ms, ex * kk, ey * kk, ez * kk);
				InterlockedIncrement(&g_blends);
			}
			InterlockedIncrement(&g_applied);
			break;
		}
	}
	// The hands are synced in the game's own input update, not here in Present (see weapons_for).
	{
		int wn = (int)st.n > MAX_CH ? MAX_CH : (int)st.n;
		for (int i = 0; i < wn; i++)
			g_weap_want[i] = st.ch[i];
		g_weap_want_n = wn;
		g_weap_pending = 1;
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

// TEST ONLY (OBSCOOP_TEST_DELAY_PROGRESS_MS=<ms>): holding the party block back makes the level request win
// the race against it, which is what exercises the guest's "wait for the host party" branch. Off unless set.
static DWORD g_test_prog_hold_ms, g_test_prog_hold_until;
static int g_test_prog_held;

static void test_delay_progress_init(void)
{
	char v[16];
	if (GetEnvironmentVariableA("OBSCOOP_TEST_DELAY_PROGRESS_MS", v, sizeof v))
		g_test_prog_hold_ms = (DWORD)strtoul(v, NULL, 10);
	if (g_test_prog_hold_ms)
		logf("host: TEST OBSCOOP_TEST_DELAY_PROGRESS_MS=%lu: the party block is held back after a level request",
			(unsigned long)g_test_prog_hold_ms);
}

static void test_hold_party(void)
{
	if (!g_test_prog_hold_ms || g_role != 1)
		return;
	g_test_prog_hold_until = GetTickCount() + g_test_prog_hold_ms;
	g_test_prog_held = 1;
	logf("host: TEST holding the party block back for %lu ms (the level request goes now)",
		(unsigned long)g_test_prog_hold_ms);
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
	if (g_test_prog_held && (LONG)(now - g_test_prog_hold_until) < 0)
		return;   // TEST ONLY: no party block yet, the guest has to wait for it
	if (g_test_prog_held) {
		logf("host: TEST delay over after %lu ms, sending the party block",
			(unsigned long)(now - (g_test_prog_hold_until - g_test_prog_hold_ms)));
		g_test_prog_held = 0;
	}
	if (!g_prog_sent_valid || memcmp(g_prog_sent + PROG_CHR_OFF, (const void *)(uintptr_t)(obj + PROG_CHR_OFF), PROG_END - PROG_CHR_OFF)) {
		host_send_region(obj, PROG_CHR_OFF, PROG_END - PROG_CHR_OFF, level);
		memcpy(g_prog_sent + PROG_CHR_OFF, (const void *)(uintptr_t)(obj + PROG_CHR_OFF), PROG_END - PROG_CHR_OFF);
	}
	g_prog_sent_valid = 1;
}

#define REG_Q_SIZE 64   // a level request now waits for the party table, so more progress packets can queue up
static CRITICAL_SECTION g_reg_cs;
static pkt_region g_reg_q[REG_Q_SIZE];
static int g_reg_head, g_reg_tail;

// The host's 8 character records (progress + 0x1b0c) as they arrive in PKT_REGION, one slot per recent level.
// Keying them by level (instead of one "latest" stash) means a reordered packet for the level the guest is
// leaving cannot overwrite the table of the level it is going to, and a table that arrives before its level
// request is still usable (PARTY_FINDINGS 4.8). All of it is written by the UDP thread (guest_on_region) and
// read by the main thread (the level change and the request queue) under g_reg_cs, so a copy is never torn.
#define PARTY_SLOTS 4
static BYTE g_party_tab[PARTY_SLOTS][0x140];
static unsigned g_party_lvl[PARTY_SLOTS];
static int g_party_next;

// Caller holds g_reg_cs.
static int party_slot(unsigned level)
{
	for (int i = 0; i < PARTY_SLOTS; i++)
		if (g_party_lvl[i] == level)
			return i;
	return -1;
}

// Caller holds g_reg_cs.
static void party_store(unsigned level, const BYTE *tab)
{
	int i = party_slot(level);
	if (i < 0) {
		i = g_party_next;
		g_party_next = (g_party_next + 1) % PARTY_SLOTS;
		g_party_lvl[i] = level;
	}
	memcpy(g_party_tab[i], tab, 0x140);
}

static int guest_party_ready(unsigned level)
{
	int ok;
	EnterCriticalSection(&g_reg_cs);
	ok = party_slot(level) >= 0;
	LeaveCriticalSection(&g_reg_cs);
	return ok;
}

static int guest_party_copy(unsigned level, BYTE *out)
{
	int i, ok = 0;
	EnterCriticalSection(&g_reg_cs);
	i = party_slot(level);
	if (i >= 0) {
		memcpy(out, g_party_tab[i], 0x140);
		ok = 1;
	}
	LeaveCriticalSection(&g_reg_cs);
	return ok;
}

static void guest_on_region(const char *buf, int n)
{
	const pkt_region *r = (const pkt_region *)buf;
	int stashed = 0;
	if (n < (int)(sizeof(pkt_hdr) + 12) || r->len > REGION_MAX || (int)(sizeof(pkt_hdr) + 12 + r->len) != n)
		return;
	EnterCriticalSection(&g_reg_cs);
	if (((g_reg_tail + 1) & (REG_Q_SIZE - 1)) != g_reg_head) {
		memcpy(&g_reg_q[g_reg_tail], buf, n);
		g_reg_tail = (g_reg_tail + 1) & (REG_Q_SIZE - 1);
	}
	if (r->off == PROG_CHR_OFF && r->len >= 0x140) {   // the host's party, for the level change (hk_party_table)
		party_store(r->level, r->data);
		stashed = 1;
	}
	LeaveCriticalSection(&g_reg_cs);
	if (stashed) {
		char lv[5], ch[5];
		unsigned first;
		memcpy(&first, r->data, sizeof first);
		logf("guest: host party stored at level %s: first character %s", tag4(r->level, lv), tag4(first, ch));
	}
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
		g_reg_head = (g_reg_head + 1) & (REG_Q_SIZE - 1);
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
// PKT_REQ is one datagram with no ack: a lost level request would leave the guest in the old level for good, so
// a request is repeated every 250 ms for 3.5 s (the guest drops the duplicates) and each repeat is preceded by
// the progress block the party table arrives in. The window covers the guest's wait for that table
// (REQ_LEVEL_PARTY_WAIT in guest_apply_requests).
#define REQ_REPEAT_MS 250
#define REQ_REPEAT_FOR 3500
static DWORD g_req_rep_until, g_req_rep_at, g_req_rep_level, g_req_rep_entry, g_req_rep_flag;
static DWORD g_req_rep_kind;              // REQ_LEVEL or REQ_LOAD_NAME (a load is as important as a level change)
static char g_req_rep_name[32];

static void host_level_request_repeat(unsigned level, unsigned entry, unsigned flag)
{
	DWORD now = GetTickCount();
	g_req_rep_level = level;
	g_req_rep_entry = entry;
	g_req_rep_flag = flag;
	g_req_rep_kind = REQ_LEVEL;
	g_req_rep_until = now + REQ_REPEAT_FOR;
	g_req_rep_at = now;
}

static void host_load_request_repeat(const char *name)
{
	DWORD now = GetTickCount();
	_snprintf(g_req_rep_name, sizeof g_req_rep_name, "%s", name ? name : "");
	g_req_rep_kind = REQ_LOAD_NAME;
	g_req_rep_until = now + REQ_REPEAT_FOR;
	g_req_rep_at = now;
}

static void host_repeat_tick(void)
{
	if (!g_peer_ok || !g_req_rep_until)
		return;
	DWORD now = GetTickCount();
	if ((LONG)(now - g_req_rep_until) >= 0) {   // the repeat window is over
		g_req_rep_until = 0;
		return;
	}
	if (now - g_req_rep_at < REQ_REPEAT_MS)
		return;
	g_req_rep_at = now;
	if (g_req_rep_kind == REQ_LOAD_NAME) {
		net_send_req(REQ_LOAD_NAME, 0, 0, 0, g_req_rep_name);
		InterlockedIncrement(&g_req_sent);
		return;
	}
	host_send_progress(1);   // the party table must reach the guest before the level change it belongs to
	net_send_req(REQ_LEVEL, g_req_rep_level, g_req_rep_entry, g_req_rep_flag, NULL);
	InterlockedIncrement(&g_req_sent);
}

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
		test_hold_party();
		host_send_progress(1);   // the party table must reach the guest before the level change it belongs to
		net_send_req(REQ_LEVEL, lvl, entry, 1, NULL);
		InterlockedIncrement(&g_req_sent);
		host_level_request_repeat(lvl, entry, 1);
		InterlockedIncrement(&g_watch_sent);
	}
}

// Host: a guest just connected. Make it load and go to the level the party is in, then send all of the state.
static void host_welcome_guest(void)
{
	char lname[sizeof g_last_load_name];
	EnterCriticalSection(&g_save_cs);
	memcpy(lname, g_last_load_name, sizeof lname);
	LeaveCriticalSection(&g_save_cs);
	logf("join: sending the current state to the guest (level %c%c%c%c)", (char)(g_last_level >> 24), (char)(g_last_level >> 16),
		(char)(g_last_level >> 8), (char)g_last_level);
	test_hold_party();
	host_send_progress(1);   // the party table has to reach the guest before the level request
	if (lname[0]) {
		// The host is already inside a save it loaded (possibly before this guest existed): the guest must
		// load that file itself, exactly as it would if the load happened now (CASE 1). No REQ_LEVEL: the
		// file builds that world, and a level request would only sit in the guest's queue behind the load.
		logf("join: the host is in a load of \"%s\"; asking the guest to load that file itself", lname);
		net_send_req(REQ_LOAD_NAME, 0, 0, 0, lname);
		InterlockedIncrement(&g_req_sent);
		host_load_request_repeat(lname);
		return;
	}
	// The friend starts their own "New game, Two players" first (that choice decides who controls player 2); the
	// level request waits on the guest until its world exists.
	if (g_last_level) {
		net_send_req(REQ_LEVEL, g_last_level, g_last_entry, g_last_flag, NULL);
		InterlockedIncrement(&g_req_sent);
		host_level_request_repeat(g_last_level, g_last_entry, g_last_flag);
	}
}

// ---- guest: requests from the host -------------------------------------------------------------

static CRITICAL_SECTION g_req_cs;
static pkt_req g_req_q[8];
static DWORD g_req_seen[8];   // when each queued request was first seen (the party wait is measured from it)
static int g_req_head, g_req_tail;
static DWORD g_lvl_req_done_a, g_lvl_req_done_b, g_lvl_req_done_at;   // the last level request this copy applied
#define REQ_LEVEL_PARTY_WAIT 3000   // how long a level request may wait for the host's party table
#define REQ_LEVEL_DONE_MS 4500      // the host repeats a level request for REQ_REPEAT_FOR: ignore the copies longer
#define REQ_LOAD_DONE_MS 4500       // the same for a load request (the host repeats it too)
static unsigned g_lvl_defer_level;  // the level request currently waiting for the host party (0 = none)
static DWORD g_ln_done_at;          // the last load request this copy took
static char g_ln_done_name[sizeof(((pkt_req *)0)->name)];

// The game refused to open the file this load named (a half-written file, or a name it does not accept).
// Forget the "already taken" mark, so the host's repeat of the same request is executed again instead of
// being dropped as a duplicate for REQ_LOAD_DONE_MS.
static void guest_load_failed(const char *name)
{
	EnterCriticalSection(&g_req_cs);
	if (!strncmp(g_ln_done_name, name, sizeof g_ln_done_name))
		g_ln_done_at = 0;
	LeaveCriticalSection(&g_req_cs);
}

static void guest_on_req(const char *buf, int n)
{
	if (n != (int)sizeof(pkt_req))
		return;
	const pkt_req *r = (const pkt_req *)buf;
	DWORD now = GetTickCount();
	EnterCriticalSection(&g_req_cs);
	if (r->kind == REQ_LEVEL) {
		// The host repeats a level request because PKT_REQ is not reliable: skip the copies (one already
		// waiting in the queue, or one applied a moment ago) so the guest changes level once.
		if (g_lvl_req_done_at && r->a == g_lvl_req_done_a && r->b == g_lvl_req_done_b &&
		    now - g_lvl_req_done_at < REQ_LEVEL_DONE_MS) {
			LeaveCriticalSection(&g_req_cs);
			return;
		}
		for (int i = g_req_head; i != g_req_tail; i = (i + 1) & 7)
			if (g_req_q[i].kind == REQ_LEVEL && g_req_q[i].a == r->a && g_req_q[i].b == r->b) {
				LeaveCriticalSection(&g_req_cs);
				return;
			}
	}
	if (r->kind == REQ_LOAD_NAME) {   // repeated like a level request: one real load per name
		if (g_ln_done_at && !strncmp(r->name, g_ln_done_name, sizeof g_ln_done_name) &&
		    now - g_ln_done_at < REQ_LOAD_DONE_MS) {
			LeaveCriticalSection(&g_req_cs);
			return;
		}
		for (int i = g_req_head; i != g_req_tail; i = (i + 1) & 7)
			if (g_req_q[i].kind == REQ_LOAD_NAME && !strncmp(g_req_q[i].name, r->name, sizeof g_req_q[i].name)) {
				LeaveCriticalSection(&g_req_cs);
				return;
			}
	}
	if (((g_req_tail + 1) & 7) != g_req_head) {
		memcpy(&g_req_q[g_req_tail], buf, sizeof(pkt_req));
		g_req_seen[g_req_tail] = now;
		g_req_tail = (g_req_tail + 1) & 7;
	}
	LeaveCriticalSection(&g_req_cs);
}

// Runs on the main thread (frame hook): the game's state machine is not thread-safe.
static void guest_apply_requests(void)
{
	int looked_at = 0;
	for (;;) {
		pkt_req r;
		DWORD seen = 0, waited = 0;
		int party_missing = 0;
		EnterCriticalSection(&g_req_cs);
		if (g_req_head == g_req_tail) {
			LeaveCriticalSection(&g_req_cs);
			return;
		}
		if (looked_at++ >= 8) {   // a deferred level request was moved to the tail: stop after one pass
			LeaveCriticalSection(&g_req_cs);
			return;
		}
		r = g_req_q[g_req_head];
		seen = g_req_seen[g_req_head];
		if (r.kind == REQ_LEVEL) {   // a joining guest may still be loading: keep the request until its world exists
			unsigned g0 = game_obj();
			if (!g0 || rd32(g0 + 0x310) != 1 || rd32(g0 + 0x320) != 0 || !world_obj()) {
				g_req_seen[g_req_head] = GetTickCount();   // the party wait starts when the guest can act
				LeaveCriticalSection(&g_req_cs);
				return;
			}
			waited = GetTickCount() - seen;
			// The world is rebuilt from the progress character table during state 4, so the host's party
			// (PKT_REGION) has to be here first or the guest spawns its own and a late table never reaches
			// the rebuilt world (PARTY_FINDINGS 4.8). Wait for it, but not forever.
			if (g_role == 2 && !guest_party_ready(r.a)) {
				if (waited < REQ_LEVEL_PARTY_WAIT) {
					// Keep it queued so the stash can still arrive. Move it behind the other kinds so
					// they are not blocked by the wait; if it is the only request, leave it at the head.
					int only_one = ((g_req_head + 1) & 7) == g_req_tail;
					if (!only_one) {
						g_req_head = (g_req_head + 1) & 7;
						g_req_q[g_req_tail] = r;
						g_req_seen[g_req_tail] = seen;
						g_req_tail = (g_req_tail + 1) & 7;
					}
					LeaveCriticalSection(&g_req_cs);
					if (g_lvl_defer_level != r.a) {
						char lv[5];
						g_lvl_defer_level = r.a;
						logf("guest: level request %s deferred waiting for the party (up to %d ms)",
							tag4(r.a, lv), REQ_LEVEL_PARTY_WAIT);
					}
					if (only_one)
						return;
					continue;
				}
				party_missing = 1;   // the fallback is the old behaviour: change level with our own party
			}
		}
		g_req_head = (g_req_head + 1) & 7;
		if (r.kind == REQ_LEVEL) {   // remember it: the host's repeats of this one are dropped
			g_lvl_req_done_a = r.a;
			g_lvl_req_done_b = r.b;
			g_lvl_req_done_at = GetTickCount();
		}
		LeaveCriticalSection(&g_req_cs);
		if (r.kind == REQ_LEVEL && g_lvl_defer_level == r.a) {
			char lv[5];
			g_lvl_defer_level = 0;
			if (party_missing)
				logf("guest: level request %s released after %u ms: no host party for it, the guest keeps its own",
					tag4(r.a, lv), waited);
			else
				logf("guest: level request %s released after %u ms: host party arrived", tag4(r.a, lv), waited);
		}
		if (r.kind == REQ_LEVEL && g_role == 2 && guest_owns_level(r.a)) {
			// This copy loaded the same save itself a moment ago and built that level from the file;
			// the host's level request for it only has to verify, not rebuild (FINDINGS_12 (c)).
			char lv[5];
			logf("guest: host ChangeLevel %s dropped: this copy loaded that save itself %u ms ago",
				tag4(r.a, lv), GetTickCount() - g_real_load_at);
			continue;
		}
		unsigned g = game_obj();
		if (!g)
			continue;
		r.name[sizeof r.name - 1] = 0;
		// The host's load must apply even when the guest is already in its own game: this is what
		// makes the guest load the host's save automatically and keeps parties/items in step.
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
			logf("guest: host LoadByName \"%s\" (world %s)", r.name, world_obj() ? "exists" : "none");
			// Always the game's own menu load (the save manager opens the file, then LoadByName). A bare
			// LoadByName is state 3 without that open: it re-reads whatever chunks the manager still holds
			// (FINDINGS_12 (b)), which fits neither a guest at the main menu nor a guest already in a level
			// that must follow a second load in the same session (CASE 3).
			g_ln_done_at = GetTickCount();
			_snprintf(g_ln_done_name, sizeof g_ln_done_name, "%.63s", r.name);
			request_real_load(r.name, "host");
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
	test_delay_progress_init();
	InitializeCriticalSection(&g_reg_cs);
	InitializeCriticalSection(&g_rx_cs);
	InitializeCriticalSection(&g_req_cs);
	InitializeCriticalSection(&g_save_cs);
	InitializeCriticalSection(&g_rcvd_cs);
	InitializeCriticalSection(&g_rload_cs);
	InitializeCriticalSection(&g_pick_cs);
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
		host_repeat_tick();
		host_send_saves();
		host_send_state();
		host_send_npcs();
		host_send_progress(0);
		peer_apply_pickups();
	} else {
		attach_player2();
		guest_apply_requests();
		guest_apply_regions();
		guest_apply_state();
		guest_apply_npcs();
		peer_apply_pickups();
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
	l = strlen(reply);
	if (l < replysz)
		_snprintf(reply + l, replysz - l, " | saves_done %ld | real load stage %ld at %lu | pickup sent %ld rcv %ld applied %ld already %ld missing %ld",
			(long)g_saves_done, (long)g_real_load_stage, (unsigned long)g_real_load_at,
			g_pickup_sent, g_pickup_rcv, g_pickup_applied, g_pickup_skipped, g_pickup_missing);
}
