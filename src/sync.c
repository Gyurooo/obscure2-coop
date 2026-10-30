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

// TASK 35: a vtable slot may only be called when it points inside the game's own image. An entity a level
// change freed keeps its memory readable (and the heap reuses it), so IsBadReadPtr is not enough: with a
// stale prop the guest's game thread tried to EXECUTE 0x44754000, heap data read as a vtable slot, and the
// game's SEH swallowed the fault and then spun forever (the "frozen with a static image" hang).
static DWORD g_exe_base, g_exe_size;   // filled on first use (virt_exe_base/size query the PE)
static int code_in_exe(DWORD f)
{
	if (!g_exe_base) {
		g_exe_base = virt_exe_base();
		g_exe_size = virt_exe_size();
	}
	return g_exe_base && f >= g_exe_base && f < g_exe_base + g_exe_size;
}

// TASK 40: a class vtable is a static address in the game's image. `code_in_exe` answers "may I jump
// here", which is not the same question: after a world rebuild a freed object's first dword can be a
// heap pointer (the guest's prop mesh read 0x169eb798) whose slot 33 happened to hold an exe address,
// and the call ran an unrelated game function with the dead object as `this` (the crash of
// claude_verify_39_soak2.log). Before dereferencing a vtable, require the vtable ITSELF in the image.
static int image_ptr(DWORD p)
{
	if (!g_exe_base) {
		g_exe_base = virt_exe_base();
		g_exe_size = virt_exe_size();
	}
	return g_exe_base && p >= g_exe_base && p < g_exe_base + g_exe_size;
}

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

// TASK 30: the world's scripted-event state (defined with the rest of the scene code further down).
#define INV_ENERGY 0xc88   // inventory (world+0x1790) + 0xc88: the battery/energy float Cslh_EnergySet writes
static volatile LONG g_scene_sent, g_scene_rcv, g_scene_skips, g_scene_left, g_scene_stuck, g_scene_missed, g_energy_sets;
static int scene_local_cinematic(void);
static void scene_tick(void);
static int door_animation_running(void);   // TASK 34: a local door use is still animating
static void door_probe_arm(unsigned ent);  // TASK 43: watch what the game's own door transition does

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

// ---- TASK 40: the world generation every entity table is keyed on ---------------------------------
// The game rebuilds its world object on every level change AND on every save load, and it fills the
// new world over several frames. The guest log of claude_verify_39_soak2.log shows it: while the copy
// loaded game3.sav INTO J002 (an unchanged level tag) the prop table grew 11 -> 19 entities in one
// 150 ms scan, and the world was "up" only 41 ms later. The world POINTER cannot tell two worlds
// apart either - the heap hands the same address back for the rebuilt world (the same-address rebuild
// TASK 39 §3.8 found for doors). So every table is keyed on a GENERATION:
//   * it changes when this copy leaves normal play (menu, load, level request, no world),
//   * when the world object or its level tag changes,
//   * and when the set of live level entities changes at all (a build adds/removes entities).
// A table is only built when the same entity set has been seen for WORLD_SETTLE_MS, and only used
// inside the generation it was built in.
#define WORLD_SETTLE_MS 150
static DWORD g_world_gen = 1;     // the live generation (never 0: 0 means "no table may be used")
static unsigned g_world_w;        // the world object last seen
static DWORD g_world_level;       // ... its level tag
static DWORD g_world_sig;         // signature of the entity manager's lists
static DWORD g_world_sig_at;      // when that signature was first seen
static int g_world_stable;        // 1 = the same signature for WORLD_SETTLE_MS
static int g_world_changes;       // signature changes seen in this world (the safety valve below)

// A cheap signature of the level's entity set: both lists of the manager (mgr+8 = the level's own
// entities, mgr+0x18 = the objects the world build adds), hashed by entity pointer + count.
static DWORD world_entity_sig(unsigned w)
{
	unsigned mgr = rd32(w + 0x1768);
	if (!mgr)
		return 0;
	DWORD h = 0;   // order-independent: only the SET of entities matters, not their list order
	unsigned n = 0;
	for (int l = 0; l < 2; l++) {
		unsigned node = rd32(mgr + (l ? 0x18 : 8));
		unsigned seen[2] = { 0, 0 };
		int nseen = 0;
		for (unsigned guard = 0; node && guard < 4000; guard++) {
			int dup = 0;
			for (int s = 0; s < nseen; s++)
				if (seen[s] == node)
					dup = 1;
			if (dup)
				break;
			if (nseen < 2)
				seen[nseen++] = node;
			unsigned e = rd32(node);
			h ^= e ? e : 0x9e3779b9u;
			h = (h << 5) | (h >> 27);   // rotate, still order-independent per element
			n++;
			unsigned nx = rd32(node + 4);
			if (nx == node)
				break;
			node = nx;
		}
	}
	return (h ^ (n * 2654435761u)) | 1;   // never 0
}

// 1 = the entity is one of THIS world's live level entities (either list of the manager). TASK 40:
// the strongest identity a cached pointer can have - a block the game freed is removed from the lists
// before it is freed, and its old fields can still look valid.
static int world_has_entity(unsigned ent)
{
	unsigned w = world_obj();
	unsigned mgr = w ? rd32(w + 0x1768) : 0;
	if (!mgr || !ent)
		return 0;
	for (int l = 0; l < 2; l++) {
		unsigned node = rd32(mgr + (l ? 0x18 : 8));
		unsigned seen[2] = { 0, 0 };
		int nseen = 0;
		for (unsigned guard = 0; node && guard < 4000; guard++) {
			int dup = 0;
			for (int s = 0; s < nseen; s++)
				if (seen[s] == node)
					dup = 1;
			if (dup)
				break;
			if (nseen < 2)
				seen[nseen++] = node;
			if (rd32(node) == ent)
				return 1;
			unsigned nx = rd32(node + 4);
			if (nx == node)
				break;
			node = nx;
		}
	}
	return 0;
}

// mode 1 + world state 1 + no pending request, in a level: the state a table may be built in.
static int world_playable(unsigned *wo, unsigned *go)
{
	unsigned g = game_obj();
	unsigned w = g ? rd32(g + 0x378) : 0;
	if (!g || !w || rd32(g + 0x310) != 1 || rd32(g + 0x320) != 0 || !rd32(w + 4))
		return 0;
	if (wo)
		*wo = w;
	if (go)
		*go = g;
	return 1;
}

// 1 = the entity tables may be built and called through (a playable, settled world).
static int world_ready(void)
{
	return g_world_gen && g_world_stable;
}

// Called once per frame before every table tick (frame_tick).
static void world_gen_tick(void)
{
	unsigned w = 0, g = 0;
	DWORD now = GetTickCount();
	if (!world_playable(&w, &g)) {
		if (g_world_stable || g_world_w) {
			g_world_gen++;
			g_world_stable = 0;
			g_world_w = 0;
			g_world_level = 0;
			g_world_sig = 0;
			g_world_sig_at = 0;
		}
		return;
	}
	DWORD level = rd32(w + 4);
	DWORD sig = world_entity_sig(w);
	if (w != g_world_w || level != g_world_level || sig != g_world_sig) {
		// a new world, or the set of entities in this one changed (a build in progress): every table
		// built before this moment belongs to an older generation and may not be called through
		if (w != g_world_w || level != g_world_level)
			g_world_changes = 0;
		else
			g_world_changes++;
		g_world_gen++;
		g_world_w = w;
		g_world_level = level;
		g_world_sig = sig;
		g_world_sig_at = now;
		g_world_stable = 0;
		// Safety valve: a level whose entity set keeps changing (a script that spawns or frees a
		// prop every few frames) must not leave the tables unusable for ever. After a second of
		// changes in an unchanged world this copy accepts the set it sees now.
		if (g_world_changes > 60) {
			g_world_stable = 1;
			g_world_changes = 0;
			logf("%s: the entity set of world %x keeps changing: using it as it is",
				g_role == 2 ? "guest" : "host", w);
		}
		return;
	}
	if (!g_world_stable && now - g_world_sig_at >= WORLD_SETTLE_MS) {
		g_world_stable = 1;
		char lv[5];
		logf("%s: world %x in level %s is settled: the entity tables are rebuilt from it",
			g_role == 2 ? "guest" : "host", w, tag4(level, lv));
	}
}


static float g_stat_sum, g_stat_max;   // guest: how far the host's characters were from this copy at each snapshot
static LONG g_stat_n;
static volatile LONG g_snd_states, g_rcv_states, g_applied, g_snaps, g_blends, g_skipped_level, g_timed_corr;
static volatile LONG g_req_applied;
static volatile LONG g_item_applied;
// Game ticks this copy has run. `sync` prints it: a copy whose game thread stopped (a hang in the game's
// own update, a modal dialog) stops counting while its network thread and pipe keep answering, which is
// otherwise invisible to a test that only reads memory.
static volatile LONG g_frames;

// TASK 37: transitions are ordered. Every transition the host announces gets the next sequence number;
// a repeat of the same transition carries the same number, so the guest can tell a repeat (same seq) from
// an older transition (lower seq, dropped) and from a newer one (higher seq, replaces what is queued).
static DWORD g_trans_seq;   // the newest transition sequence this host has announced (pkt_state.host_seq)
static DWORD host_trans_next(void)
{
	return ++g_trans_seq;
}

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
// TASK 35: a world built from a one-player save keeps its partner on the TEAMMATE controller
// (world+0x174c), and attach_player2 above points player 2's input controller at that same character.
// The game's "stop what the other character is doing" sweep (FUN_0042ad70, decompile 24796-24820) takes
// the teammate controller's character when one is linked - and the door use (FUN_0042c2b0) runs that
// sweep in the middle of its own use, after it stored itself in character+0x2bc. With the partner linked
// there, the sweep stops the very door it is being used on (door+0xc4 = 0), and the door use then reads
// 0x220 through the null character: an access violation at Obscure2.exe+0x2c51b that the game's own SEH
// swallows and then spins on forever (the guest "froze with a static image").
// A real two-player world has no teammate; unlink the controllers' character from it. One character, so
// this is a single pointer write, and attach_player2 repeats it because the game re-links it after a load.
//
// TASK 38: the game itself reads that pointer when it LEAVES a scripted event. In the world update's
// state-7 branch (the noe scene / scripted event, world+0x12c == 7; decompile 110439-110480) a skip key
// runs
//     manager->vtable[0x1c]( *(world+0x174c + 4), world+0x1748 + 0x764 )
// which is FUN_004f16a0: it writes human+8 = &controller2 and then virtual-calls controller2. With the
// teammate human unlinked (0) that is a write to address 8: the guest's FATAL EXCEPTION at
// Obscure2.exe+0xf16a9 in the TASK 37 soak, right after a load and the level's scripted event (the scene's
// skip pressed by the mod or by the player). So the unlink is only kept while this copy is in NORMAL PLAY;
// in a load, a menu, a scripted event or a transition the pointer is put back before the game's update
// runs, and the game's own attach uses a real character. See teammate_game_guard.
static unsigned g_teammate_h;      // the character the unlink took off the teammate controller
static unsigned g_teammate_world;  // ... in this world object (a rebuilt world is the game's own business)
static volatile LONG g_teammate_restores;

static int teammate_unlink(unsigned ch)
{
	unsigned w = world_obj();
	unsigned mt = w ? rd32(w + 0x174c) : 0;
	if (!mt || !ch)
		return 0;
	unsigned p = mt + 4;
	if (IsBadReadPtr((const void *)(uintptr_t)p, 4) || IsBadWritePtr((void *)(uintptr_t)p, 4))
		return 0;
	if (rd32(p) != ch)
		return 0;
	*(DWORD *)(uintptr_t)p = 0;
	g_teammate_h = ch;
	g_teammate_world = w;
	{
		static DWORD logged_tag;
		char c[5];
		unsigned tag = rd32(ch + H_TAG);
		if (logged_tag != tag) {
			logged_tag = tag;
			logf("teammate controller: unlinked %s (it is player 2's own character; the game's door use "
			     "stops the teammate's action and would stop the door it is using)", tag4(tag, c));
		}
	}
	return 1;
}

// TASK 38: put the teammate character back while this copy is NOT in normal play, so the game's own
// code (the scripted-event skip, the enter-normal-play attach, a menu) always finds a real character
// there, and take it off again as soon as the copy is back in normal play (where the door fix needs it
// gone). Called from hk_game_update around the game's own update, which is where the world update runs.
//
// "Normal play" is deliberately narrow: in a level (mode 1) and in world state 1. Nothing else counts.
//
// TASK 39: a pending world REQUEST (world+0x12c) is NOT part of it. That field is the game's own request
// queue, OBSERVED in the world update FUN_004b4cb0: 1/2/3/4/9 = a state change, 5 = a menu, 6 = a
// change-level by tag, 7 = a scripted event, 8 = a screenshot, 0xa = a save, 0xb = ..., 0xc = the
// ChangeLevel request (FUN_004b2a20 writes level/entry/flag there, 0x13c/0x138/0x130), 0xd, 0x10, 0x11.
// The world is still the SAME playable world while such a request is queued - the door use that just
// started its ChangeLevel is the prime example - and the game's "stop the other character" sweep
// (FUN_0042ad70) can still run in it. TASK 38 counted the request as "not playable" and put the teammate
// character back for those frames; that re-enabled exactly the TASK 35 door freeze (the sweep picks the
// teammate, sees the door it is using, stops it). The states that really need a character there are the
// ones the game's own code reads it in: a menu (2/5), a scripted event (7) and a transition (9/0xc/...).
static int world_normal_play(unsigned g)
{
	unsigned w = g ? rd32(g + 0x378) : 0;
	if (!g || !w || IsBadReadPtr((const void *)(uintptr_t)(w + 0x11c), 4))
		return 0;
	return rd32(g + 0x310) == 1 && rd32(w + 0x11c) == 1;
}

// TASK 39: the character the guard is about to put back must still belong to the CURRENT world. A world
// object is freed and rebuilt by every level change and the heap can hand the new world the same address
// (the only test TASK 38 had was `w == g_teammate_world`), so without this a stale character pointer from
// the previous level could be written into the new world's teammate controller - a dead pointer that the
// game's sweep and its scripted-event skip would then call through.
static int world_has_human(unsigned h)
{
	unsigned hs[MAX_CH];
	int n = world_humans(hs, MAX_CH);
	for (int i = 0; i < n; i++)
		if (hs[i] == h)
			return 1;
	return 0;
}

// TASK 39 (diagnostic): every write the guard family makes, with the three fields that decide it. Only
// with OBSCOOP_DEBUG_TEAMMATE=1: the soak logs are 20 KB per run and a line per write would swamp them.
static int teammate_debug(void)
{
	static int dbg = -1;
	if (dbg < 0) {
		char v[8];
		dbg = GetEnvironmentVariableA("OBSCOOP_DEBUG_TEAMMATE", v, sizeof v) ? 1 : 0;
	}
	return dbg;
}

static void teammate_note(const char *what, unsigned g, unsigned cur, unsigned put)
{
	if (!teammate_debug())
		return;
	unsigned w = g ? rd32(g + 0x378) : 0;
	logf("%s: teammate %x -> %x (mode %u state %u req %u world %x/%x)", what, cur, put,
	     g ? rd32(g + 0x310) : 0, w ? rd32(w + 0x11c) : 0, w ? rd32(w + 0x12c) : 0, w, g_teammate_world);
}

static void teammate_game_guard(unsigned g, int before_update)
{
	if (!g_teammate_h)
		return;
	unsigned w = g ? rd32(g + 0x378) : 0;
	if (!w || w != g_teammate_world) {
		// The world was rebuilt: its teammate pointer is the game's own (and possibly a new character).
		g_teammate_h = 0;
		return;
	}
	unsigned mt = rd32(w + 0x174c), p = mt + 4;
	if (!mt || IsBadReadPtr((const void *)(uintptr_t)p, 4) || IsBadWritePtr((void *)(uintptr_t)p, 4)) {
		g_teammate_h = 0;
		return;
	}
	unsigned cur = rd32(p);
	if (before_update) {
		if (!world_normal_play(g) && cur == 0 && world_has_human(g_teammate_h)) {
			teammate_note("guard: restore before the update", g, cur, g_teammate_h);
			*(DWORD *)(uintptr_t)p = g_teammate_h;
			InterlockedIncrement(&g_teammate_restores);
		}
	} else if (world_normal_play(g) && cur == g_teammate_h) {
		teammate_note("guard: unlink after the update", g, cur, 0);
		*(DWORD *)(uintptr_t)p = 0;   // normal play again: the game's teammate sweep must not see it
	}
}

// TASK 38: remember the partner as the teammate controller's character even when the pointer is already
// 0 (the game may have cleared it, or the world came up without one), so the guard knows whom to put back
// while this copy is not in normal play. Restores it at once when the copy is not in normal play.
static void teammate_want(unsigned ch)
{
	unsigned w = world_obj();
	unsigned mt = w ? rd32(w + 0x174c) : 0;
	if (!mt || !ch)
		return;
	unsigned p = mt + 4;
	if (IsBadReadPtr((const void *)(uintptr_t)p, 4) || IsBadWritePtr((void *)(uintptr_t)p, 4))
		return;
	unsigned cur = rd32(p);
	if (cur == 0 || cur == ch) {
		g_teammate_h = ch;
		g_teammate_world = w;
	}
	if (cur == 0 && world_has_human(ch)) {
		teammate_note("attach_player2: restore", game_obj(), cur, ch);
		*(DWORD *)(uintptr_t)p = ch;
		InterlockedIncrement(&g_teammate_restores);
	}
}

// TASK 45 (test switch): OBSCOOP_NO_TEAMMATE=1 leaves the world the game built itself alone - no
// attach_player2, no teammate_unlink - so a test can see what the game's OWN player-2 join does.
static int no_teammate(void)
{
	static int v = -1;
	if (v < 0) {
		char b[8];
		v = GetEnvironmentVariableA("OBSCOOP_NO_TEAMMATE", b, sizeof b) != 0;
	}
	return v;
}

static void attach_player2(void)
{
	static DWORD last;
	DWORD now = GetTickCount();
	if (no_teammate())
		return;
	if (now - last < 500) return;
	last = now;
	unsigned w = world_obj();
	unsigned ctl = w ? rd32(w + 0x1748) : 0;
	unsigned mgr = w ? rd32(w + 0x175c) : 0;
	if (!ctl || !mgr) return;	unsigned c2 = ctl + 0x764;         // input controller 2 (an object: vtable +0, character +4, tag +0xc)
	unsigned c2h = c2 + 4;             // the character pointer the mod writes
	unsigned n = rd32(mgr + 4), arr = rd32(mgr + 0xc);
	if (n < 2) return;
	// TASK 28: the partner is the first human that player 1 does NOT control. The old code took manager
	// entry 1, which is the same character when the save's controller 1 record names the second entry
	// (I015: the old party order is BOY1, BOY2 but player 1 drives BOY2) - player 2 then controlled
	// player 1's character and the guest had no character of its own.
	unsigned h1 = rd32(ctl + 4);
	unsigned h2 = 0;
	for (unsigned i = 0; i < n && i < 8; i++) {
		unsigned h = rd32(arr + 4 * i);
		if (h && h != h1) { h2 = h; break; }
	}
	if (!h2) h2 = rd32(arr + 4);
	if (!h2 || IsBadWritePtr((void *)(uintptr_t)c2h, 4) || IsBadReadPtr((const void *)(uintptr_t)(h2 + 8), 4))
		return;
	// TASK 38: only while this copy is in normal play. In a menu / a load / a scripted event the guard
	// (teammate_game_guard) has put the character back for the game's own code - do not take it away here
	// in the middle of such a frame; the next normal-play frame re-nulls it.
	unsigned g = game_obj();
	if (g && world_normal_play(g))
		teammate_unlink(h2);   // TASK 35: a 2P world has no teammate; see the comment above teammate_unlink
	else
		teammate_want(h2);     // not playable here: the game needs a character there (TASK 38)
	unsigned cur = rd32(c2h);
	if (!cur || cur == h1)
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
// TASK 25: when this process already received a file from the host, a reconnect is not a new session:
// the host is told it needs no transfer (the hello's need_saves) and nothing is forgotten here, so a
// load that waits for a transferred file still finds it.
static void guest_save_session(void)
{
	if (g_save_rcvd_n > 0) {
		logf("net: reconnect; the save files from the host are still current (%d file%s)", g_save_rcvd_n,
			g_save_rcvd_n == 1 ? "" : "s");
		return;
	}
	EnterCriticalSection(&g_rcvd_cs);
	g_save_rcvd_n = 0;
	LeaveCriticalSection(&g_rcvd_cs);
	InterlockedExchange(&g_saves_done, 0);
}

// Host side of the same rule (called from net.c's hello): does the guest still need the save files?
static int guest_need_saves(void)
{
	return g_save_rcvd_n == 0;
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
	// Both copies simulate BOTH characters, and a live world item in reach of a character is collected
	// automatically by the interaction scan (no button). So the same character collects the same item on
	// both copies in the same instant; without this guard each copy would also send its own pickup, and
	// each would receive the peer's for an item it had already collected ("already collected" on both
	// sides, one redundant packet each way). Announce only the pickups of the character this copy drives:
	// host owns player 1, guest owns player 2 (its local pad is XInput user 0 = player 2).
	{
		unsigned own = player_human(g_role == 2 ? 1 : 0);
		if (own && ch != own)
			return;
	}
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
		if (!world_ready())
			return;   // TASK 40: the level's entities are still being built/rebuilt
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
		if (!ch || !vt || !image_ptr((DWORD)(uintptr_t)vt) || IsBadReadPtr(vt, 27 * sizeof(void *)) ||
		    !code_in_exe((DWORD)(uintptr_t)vt[26]) || !mem_ok((const void *)(uintptr_t)ent, 0xac)) {
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

// ---- breakable / carryable level props (TASK 26) --------------------------------------------------
// A CToeChair (class tag CHAI) is picked up with the action button, carried in the aim pose and broken by
// the next press: the game sets character+0x2bc = the object and object+0xc4 = the character (vtable slot
// 28, FUN_00411f80), and the second press calls the object's slot 25 (FUN_00412140), which sets the broken
// flag +0xa4, hides the mesh and enables the drop item entity the object holds (+0x118; one entity, or
// one of the four candidates at +0x168..+0x174 chosen with the party's supply counts and RNG).
// The CToeBreakable* / CToeHeavyCase props (BKCS, BKDT, BKON, BKMA, BKBA, BK2S, HCAS) break when hit and
// carry no drop in these saves (FINDINGS_16: their item_closed is 0).
//
// Both copies simulate both players, so a pickup or a break normally happens on both at once. What the
// other copy cannot re-simulate is an action it missed (a dropped pad packet, a pause, a teleport) and the
// drop a break chose. So: the owner of a character announces what it carries (host: player 1, guest:
// player 2, the same ownership PKT_CHAR uses), and both copies announce a break with the drop they
// enabled - the host's announcement decides the drop on both (the host owns world state). Applying uses
// the game's own methods: object slot 28 (attach), slot 29 (detach), slot 25 (break), and the item's
// slots 34/32/33 (place, enable, show) exactly as FUN_00412140 calls them.
#define PROP_MAX 48
#define PROP_ATTACH_CHAIR 0x411f80u   // CToeChair vtable slot 28 (FUN_00411f80): attach to a character
static volatile LONG g_prop_sent, g_prop_rcv, g_prop_applied, g_prop_broken, g_prop_missing, g_prop_drop;

// The classes a break is mirrored for. The tag is the class tag at entity+0x10 (see the constructors):
// CHAI CToeChair, BKCS CToeBreakableCase, BKDT CToeBreakableDetailed, BKON CToeBreakableOnce,
// BKMA CToeBreakableManikin, BKBA CToeBreakableByAnim, BK2S CToeBreakableTwoStates, HCAS CToeHeavyCase.
static int prop_class_tag(unsigned t)
{
	switch (t) {
	case 0x43484149: case 0x424b4353: case 0x424b4454: case 0x424b4f4e:
	case 0x424b4d41: case 0x424b4241: case 0x424b3253: case 0x48434153:
		return 1;
	}
	return 0;
}

// The item classes (ITEMS_FINDINGS section 1) - only used to sanity-check a drop pointer.
static int prop_item_tag(unsigned t)
{
	static const unsigned tags[] = {
		0x41434944, 0x42415454, 0x424b504b, 0x424c4541, 0x4341424f, 0x43524f57, 0x454e4452,
		0x474c5943, 0x4943414d, 0x49434500, 0x4943524e, 0x49445343, 0x4a454d4d, 0x4a455252,
		0x4a554241, 0x4b455900, 0x4c564552, 0x4d415000, 0x4d454449, 0x50415353, 0x53455255,
		0x534f4441, 0x53544154, 0x53545249, 0x53595249, 0x57454c44
	};
	for (unsigned i = 0; i < sizeof tags / sizeof tags[0]; i++)
		if (tags[i] == t)
			return 1;
	return 0;
}

typedef struct { unsigned ent; DWORD cls, id, broken, vt; unsigned carrier, drop; } prop_slot;
static void prop_defer_break(unsigned ent, DWORD dcls, DWORD did, const float *dpos, int host_word);
static void prop_apply_break(unsigned ent, DWORD dcls, DWORD did, const float *dpos, int host_word);
static void prop_align_drop(unsigned ent, DWORD dcls, DWORD did, const float *dpos, int host_word);

static prop_slot g_props[PROP_MAX];
static int g_prop_n;
static DWORD g_prop_level;                 // the level the table was built in
static unsigned g_prop_world;              // ... and the world object it was scanned from (TASK 39)
static DWORD g_prop_gen;                   // ... and the world generation it belongs to (TASK 40)
// The level the previous scan belongs to: the first scan of a level records its already-broken props
// without announcing them (they are the level's state, not a break this copy performed).
static DWORD g_prev_level;
static float g_prop_pos[PROP_MAX][3];
static unsigned char g_prop_listed[PROP_MAX];   // 1 = the manager's lists hold this prop right now

// A prop pointer is only used when the object is still alive and still the class it was: an entity that
// was rebuilt (level change) or freed must never be called through.
// TASK 40: the class vtable at ent+0 is checked too. A freed block the heap has reused holds another
// object (or heap data) there; the tag at +0x10 alone survived long enough in the crash of
// claude_verify_39_soak2.log for the mod to call the prop's "mesh" pointer.
static int prop_alive(unsigned e, DWORD cls, DWORD vt)
{
	if (!e || e <= 0x10000 || IsBadReadPtr((void *)(uintptr_t)e, 0x120) || rd32(e + 0x10) != cls)
		return 0;
	if (vt && rd32(e) != vt)
		return 0;
	return 1;
}

// The live fields of the prop in slot `i` (the same offsets the packet names: class +0x10, id +4,
// broken +0xa4, carrier +0xc4, drop +0x118, position +0x6c).
static void prop_refresh(int i)
{
	unsigned e = g_props[i].ent;
	g_props[i].cls = rd32(e + 0x10);
	g_props[i].id = rd32(e + 4);
	g_props[i].vt = rd32(e);   // TASK 40: the class vtable is the identity a reused block cannot fake
	g_props[i].broken = rd32(e + 0xa4);
	g_props[i].carrier = rd32(e + 0xc4);
	g_props[i].drop = rd32(e + 0x118);
	const float *ep = (const float *)(uintptr_t)(e + 0x6c);
	g_prop_pos[i][0] = ep[0];
	g_prop_pos[i][1] = ep[1];
	g_prop_pos[i][2] = ep[2];
}

// Rebuilds the prop table from the manager's two lists (mgr+8 = the level's own entities, mgr+0x18 = the
// objects the world build adds; pickup_find_entity walks both for the same reason). Cheap enough to run
// 6-7 times a second (a level has < 60 entities); a pointer is never kept across a level change.
//
// TASK 27: a prop that the lists do not show right now is KEPT (as long as it is alive and still the same
// class) instead of being dropped. The break/carry packets name a prop by class + position, and a carried
// chair's position is wherever the hand is: while the chair is out of the table the peer's next packet can
// only match the nearest *other* chair that is still listed.
static void prop_scan(unsigned w, DWORD level)
{
	unsigned mgr = rd32(w + 0x1768);
	int was_n = g_prop_n;
	// TASK 40: the old entries may only be carried over inside the SAME world generation. After a
	// rebuild they name entities of the world the game just freed.
	int same_world = (g_prop_gen == g_world_gen && g_prop_world == w);
	prop_slot old[PROP_MAX];
	memcpy(old, g_props, sizeof(prop_slot) * (size_t)g_prop_n);
	g_prop_n = 0;
	g_prop_level = level;
	g_prop_world = w;
	g_prop_gen = g_world_gen;
	if (mgr)
		for (int h = 0; h < 2; h++) {
			unsigned head = rd32(mgr + (h == 0 ? 8 : 0x18));
			unsigned node_seen[3] = { 0, 0, 0 };
			int nseen = 0;
			for (unsigned node = head, guard = 0; node && guard < 4000; guard++) {
				int dup = 0;
				for (int s = 0; s < nseen; s++)
					if (node_seen[s] == node)
						dup = 1;
				if (dup)
					break;   // a node seen before: the list loops, stop (node_seen keeps the last few)
				if (nseen < 3)
					node_seen[nseen++] = node;
				unsigned e = rd32(node);
				unsigned nx = rd32(node + 4);
				int have = 0;
				for (int k = 0; k < g_prop_n; k++)
					if (g_props[k].ent == e)
						have = 1;
				if (e && e > 0x10000 && !have && prop_class_tag(rd32(e + 0x10)) && g_prop_n < PROP_MAX) {
					int i = g_prop_n++;
					g_props[i].ent = e;
					g_prop_listed[i] = 1;
					prop_refresh(i);
				}
				if (nx == node)
					break;
				node = nx;
			}
		}
	if (same_world)   // same level + same world: keep the props the lists left out (carried, re-parented)
		for (int i = 0; i < was_n && g_prop_n < PROP_MAX; i++) {
			int have = 0;
			for (int k = 0; k < g_prop_n; k++)
				if (g_props[k].ent == old[i].ent)
					have = 1;
			if (have || !prop_alive(old[i].ent, old[i].cls, old[i].vt))
				continue;
			int n = g_prop_n++;
			g_props[n].ent = old[i].ent;
			g_prop_listed[n] = 0;
			prop_refresh(n);
		}
	// A prop whose broken flag the game cleared again (the 20 s respawn of FUN_00413c00) is worth a line:
	// the copies must end up the same way here too. TASK 40: only inside the same world - after a
	// rebuild the heap can hand the same address to a different prop ("went back to whole" in the
	// guest log of claude_verify_39_soak2.log was exactly that false positive).
	if (same_world)
		for (int i = 0; i < g_prop_n; i++) {
			for (int j = 0; j < was_n; j++)
				if (old[j].ent == g_props[i].ent) {
					if (old[j].broken && !g_props[i].broken) {
						char c[5], i4[5];
						logf("%s: prop went back to whole: %s id %s ent %x (the game respawned it)",
							g_role == 2 ? "guest" : "host", tag4(g_props[i].cls, c), tag4(g_props[i].id, i4),
							g_props[i].ent);
					}
					break;
				}
		}
	if (g_prop_n != was_n || level != g_prev_level) {
		char lv[5];
		logf("%s: prop table: %d breakable/carryable entit%s in level %s", g_role == 2 ? "guest" : "host",
			g_prop_n, g_prop_n == 1 ? "y" : "ies", tag4(level, lv));
	}
}

// The prop a packet names: same class tag, and (when the packet has one) the same id; the nearest to the
// announced position decides among same-class entities (chair ids are often 0). Every candidate is checked
// against the live object, so a pointer kept from an earlier scan can never be called on a dead object.
static unsigned prop_find(DWORD cls, DWORD id, const float *pp)
{
	unsigned best = 0;
	float bd = 400.0f * 400.0f;   // a prop further away than this is not the one the packet means
	for (int i = 0; i < g_prop_n; i++) {
		prop_slot *p = &g_props[i];
		if (p->cls != cls || (id && p->id != id) || !prop_alive(p->ent, cls, p->vt))
			continue;
		float dx = g_prop_pos[i][0] - pp[0], dy = g_prop_pos[i][1] - pp[1], dz = g_prop_pos[i][2] - pp[2];
		float d = dx * dx + dy * dy + dz * dz;
		if (d < bd) { bd = d; best = p->ent; }
	}
	return best;
}

// The CHAI-like object a character holds (character+0x2bc), when it is of the class the packet names. A
// carried prop is identified exactly by this, not by a position that moves with the hand.
static unsigned prop_held_chair(unsigned ch, DWORD cls)
{
	if (!ch || IsBadReadPtr((void *)(uintptr_t)(ch + 0x2bc), 4))
		return 0;
	unsigned cur = rd32(ch + 0x2bc);
	if (!prop_alive(cur, cls, 0) || cur == ch)
		return 0;
	return cur;
}

// 1 when a character of this world holds the prop in its hand (TASK 27: a carried prop leaves the
// manager's lists, so world_has_entity cannot see it).
static int prop_held_anywhere(unsigned ent)
{
	if (!ent)
		return 0;
	unsigned hs[MAX_CH];
	int n = world_humans(hs, MAX_CH);
	for (int i = 0; i < n; i++)
		if (rd32(hs[i] + 0x2bc) == ent)
			return 1;
	return 0;
}

// The item entity at +0x118 (the one the break enabled) or, when it is 0, none.
static unsigned prop_drop_of(unsigned ent)
{
	unsigned d = rd32(ent + 0x118);
	if (d && !IsBadReadPtr((void *)(uintptr_t)d, 0xac) && prop_item_tag(rd32(d + 0x10)) && rd32(d + 0xa8) == 0)
		return d;
	return 0;
}

// The candidate item entity of a chair the packet names (class tag, id).
static unsigned prop_candidate(unsigned ent, DWORD cls, DWORD id)
{
	unsigned cand[5];
	for (int i = 0; i < 4; i++)
		cand[i] = rd32(ent + 0x168 + 4 * i);
	cand[4] = rd32(ent + 0x118);
	for (int i = 0; i < 5; i++) {
		unsigned c = cand[i];
		if (!c || IsBadReadPtr((void *)(uintptr_t)c, 0xac))
			continue;
		if (rd32(c + 0x10) == cls && (!id || rd32(c + 4) == id))
			return c;
	}
	return 0;
}

// The game's own "show this item in the world" (FUN_00412140): project the position, clear the collected
// flag, then the item's vtable slots 34 (place), 32 (enable) and 33 (show).
static void prop_item_enable(unsigned item, const float *pp)
{
	void **vt = *(void ***)(uintptr_t)item;
	if (!vt || !image_ptr((DWORD)(uintptr_t)vt) || IsBadReadPtr(vt, 35 * sizeof(void *)) ||
	    !mem_ok((const void *)(uintptr_t)(item + 0xa8), 4))
		return;
	if (!code_in_exe((DWORD)(uintptr_t)vt[34]) || !code_in_exe((DWORD)(uintptr_t)vt[32]) ||
	    !code_in_exe((DWORD)(uintptr_t)vt[33]))
		return;   // TASK 35: a stale object's slots can hold heap data
	*(DWORD *)(uintptr_t)(item + 0xa8) = 0;
	((void(__fastcall *)(void *, void *, const float *))vt[34])((void *)(uintptr_t)item, NULL, pp);
	((void(__fastcall *)(void *, void *, int))vt[32])((void *)(uintptr_t)item, NULL, 1);
	((void(__fastcall *)(void *, void *, int))vt[33])((void *)(uintptr_t)item, NULL, 1);
}

static void prop_item_hide(unsigned item)
{
	void **vt = *(void ***)(uintptr_t)item;
	if (vt && image_ptr((DWORD)(uintptr_t)vt) && !IsBadReadPtr(vt, 34 * sizeof(void *)) &&
	    code_in_exe((DWORD)(uintptr_t)vt[33]))
		((void(__fastcall *)(void *, void *, int))vt[33])((void *)(uintptr_t)item, NULL, 0);
}

// Make this copy show the same drop entity as the announcement. `host_word` = the announcement came from
// the host, whose drop wins; a guest announcement only fills in a drop this copy did not produce.
static void prop_align_drop(unsigned ent, DWORD dcls, DWORD did, const float *dpos, int host_word)
{
	unsigned local = prop_drop_of(ent);
	if (!host_word && local)
		return;
	if (!dcls) {
		if (local && host_word) {
			prop_item_hide(local);
			InterlockedIncrement(&g_prop_drop);
			logf("%s: prop break: hiding a local drop the host did not produce", g_role == 2 ? "guest" : "host");
		}
		return;
	}
	if (local && rd32(local + 0x10) == dcls && (!did || rd32(local + 4) == did))
		return;   // already the same item
	unsigned want = prop_candidate(ent, dcls, did);
	if (!want)
		return;
	if (local)
		prop_item_hide(local);
	prop_item_enable(want, dpos);
	InterlockedIncrement(&g_prop_drop);
	char a[5], b[5];
	logf("%s: prop drop aligned to %s id %s (was %s)", g_role == 2 ? "guest" : "host",
		tag4(dcls, a), tag4(did, b), local ? "another item" : "none");
}

// A break this copy applied from a packet is not its own news. Echoing it back is harmless in itself, but
// an echo of a mis-matched break hides the real one, and an echo of the peer's break fights its own state
// resend, so the entities applied here are remembered and not announced again for a moment.
static unsigned g_applied_ent[8];
static DWORD g_applied_at[8];
static int g_applied_next;

static void prop_mark_applied(unsigned ent)
{
	g_applied_ent[g_applied_next] = ent;
	g_applied_at[g_applied_next] = GetTickCount();
	g_applied_next = (g_applied_next + 1) & 7;
}

static int prop_applied_here(unsigned ent, DWORD within)
{
	DWORD now = GetTickCount();
	for (int i = 0; i < 8; i++)
		if (g_applied_ent[i] == ent && now - g_applied_at[i] < within)
			return 1;
	return 0;
}

// The state a break leaves behind, written directly instead of running FUN_00412140. That routine also
// spawns the splinter effect, plays the sound and releases the chair's collision object; calling it from
// the frame hook is what TASK 26 already reported as "hung the host in an early run", and in TASK 27 the
// guest's game stopped updating at the exact tick it applied the host's break while its network thread
// kept logging. What a break means for the player and for the sync is its state:
//   +0xa4 = 1 (broken: can-interact refuses, the save records it),
//   +0x24 = 0 (not usable - what the game's own break leaves),
//   +0x12c = 0 (the respawn timer FUN_00413c00 counts up to 20000),
//   the mesh hidden through its own vtable slot 33 (the break's `(*(+0x84))(0)`),
//   the collision object's slot 17 (`(+0x44)(0)`, the call the attach already makes) disabled.
// The drop item entity is enabled by prop_align_drop with the item's own slots 34/32/33, as before.
static int prop_break_state(unsigned ent)
{
	if (!ent || IsBadReadPtr((void *)(uintptr_t)ent, 0x130))
		return 0;
	unsigned mesh = rd32(ent + 0x34);
	if (mesh && !IsBadReadPtr((void *)(uintptr_t)mesh, 8)) {
		void **mvt = *(void ***)(uintptr_t)mesh;
		// TASK 40: the vtable itself must be an image address. In claude_verify_39_soak2.log the mesh
		// of a prop that the rebuilt world had replaced held a heap pointer here, its slot 33 a code
		// address by chance, and the call ran an unrelated game function on the dead object.
		if (mvt && image_ptr((DWORD)(uintptr_t)mvt) && !IsBadReadPtr(mvt, 34 * sizeof(void *)) &&
		    code_in_exe((DWORD)(uintptr_t)mvt[33]))
			((void(__fastcall *)(void *, void *, int))mvt[33])((void *)(uintptr_t)mesh, NULL, 0);
	}
	unsigned col = rd32(ent + 0x68);
	if (col && !IsBadReadPtr((void *)(uintptr_t)col, 8)) {
		void **cvt = *(void ***)(uintptr_t)col;
		if (cvt && image_ptr((DWORD)(uintptr_t)cvt) && !IsBadReadPtr(cvt, 18 * sizeof(void *)) &&
		    code_in_exe((DWORD)(uintptr_t)cvt[17]))
			((void(__fastcall *)(void *, void *, int))cvt[17])((void *)(uintptr_t)col, NULL, 0);
	}
	*(DWORD *)(uintptr_t)(ent + 0x24) = 0;
	*(DWORD *)(uintptr_t)(ent + 0x12c) = 0;
	*(DWORD *)(uintptr_t)(ent + 0xa4) = 1;
	return 1;
}

static void prop_apply_break(unsigned ent, DWORD dcls, DWORD did, const float *dpos, int host_word)
{
	// TASK 40: never touch an entity that is not one of this world's live entities (or in a hand)
	if (!ent || IsBadReadPtr((void *)(uintptr_t)ent, 0x120) ||
	    (!world_has_entity(ent) && !prop_held_anywhere(ent))) {
		InterlockedIncrement(&g_prop_missing);
		logf("%s: prop break (deferred): ent %x is not in this world any more: not applied",
			g_role == 2 ? "guest" : "host", ent);
		return;
	}
	// A prop the other copy broke and this one also broke (the normal case) is already flagged: nothing to
	// do, and no log line - the host repeats its state once a second.
	if (!rd32(ent + 0xa4)) {
		const float *ep = (const float *)(uintptr_t)(ent + 0x6c);
		char c[5], i[5];
		if (prop_break_state(ent)) {
			prop_mark_applied(ent);
			InterlockedIncrement(&g_prop_broken);
			logf("%s: prop break applied: %s id %s ent %x at (%.1f,%.1f,%.1f) -> broken now %u",
				g_role == 2 ? "guest" : "host", tag4(rd32(ent + 0x10), c), tag4(rd32(ent + 4), i), ent,
				ep[0], ep[1], ep[2], rd32(ent + 0xa4));
		}
	}
	prop_align_drop(ent, dcls, did, dpos, host_word);
}

// The character with exactly this tag (human_with_tag falls back to the local player, which is right for a
// pickup but not for attaching a prop to a named character).
static unsigned human_exact(unsigned tag)
{
	unsigned hs[MAX_CH];
	int n = world_humans(hs, MAX_CH);
	for (int i = 0; i < n; i++)
		if (rd32(hs[i] + H_TAG) == tag)
			return hs[i];
	return 0;
}

// Carry: attach the prop to that character (slot 28) or detach what it holds (slot 29), the game's own
// methods. `ent` 0 = the character holds nothing.
// TASK 27: a BROKEN prop is never detached. The game keeps a broken chair linked in the hand on purpose
// (FUN_00411f80/FUN_00412010 do not touch +0xa4), so the owner's "nothing carried" heartbeat must not keep
// calling the game's detach on it every 500 ms - that is a game call we simply do not need.
static void prop_apply_carry(unsigned ch, unsigned ent)
{
	if (!ch || IsBadReadPtr((void *)(uintptr_t)(ch + 0x2bc), 4)) {
		if (ent)
			logf("%s: prop carry applied: no usable character (ent %x)", g_role == 2 ? "guest" : "host", ent);
		return;
	}
	unsigned cur = rd32(ch + 0x2bc);
	if (cur == ent)
		return;
	if (cur && !IsBadReadPtr((void *)(uintptr_t)cur, 0xcc)) {
		if (rd32(cur + 0xa4))
			return;   // a broken chair stays where the break left it
		void **vt = *(void ***)(uintptr_t)cur;
		if (vt && image_ptr((DWORD)(uintptr_t)vt) && !IsBadReadPtr(vt, 30 * sizeof(void *)) &&
		    vt[28] == (void *)(uintptr_t)PROP_ATTACH_CHAIR && code_in_exe((DWORD)(uintptr_t)vt[29]))
			((void(__fastcall *)(void *, void *))vt[29])((void *)(uintptr_t)cur, NULL);   // detach
	}
	if (ent) {
		void **vt = *(void ***)(uintptr_t)ent;
		if (vt && image_ptr((DWORD)(uintptr_t)vt) && !IsBadReadPtr(vt, 29 * sizeof(void *)) &&
		    vt[28] == (void *)(uintptr_t)PROP_ATTACH_CHAIR)
			((void(__fastcall *)(void *, void *, void *))vt[28])((void *)(uintptr_t)ent, NULL, (void *)(uintptr_t)ch);
	}
	char c[5], i[5];
	logf("%s: prop carry applied: %s id %s -> %s", g_role == 2 ? "guest" : "host",
		ent ? tag4(rd32(ent + 0x10), c) : "-----", ent ? tag4(rd32(ent + 4), i) : "----",
		tag4(rd32(ch + H_TAG), c));
}

// Queue of announcements (filled on the network thread, applied on the game thread, like pickups).
static CRITICAL_SECTION g_prop_cs;
static pkt_prop g_prop_q[8];
static DWORD g_prop_q_tick[8];
static int g_prop_head, g_prop_tail;

static void peer_on_prop(const char *buf, int n)
{
	if (n != (int)sizeof(pkt_prop))
		return;
	EnterCriticalSection(&g_prop_cs);
	if (((g_prop_tail + 1) & 7) != g_prop_head) {
		memcpy(&g_prop_q[g_prop_tail], buf, sizeof(pkt_prop));
		g_prop_q_tick[g_prop_tail] = GetTickCount();
		g_prop_tail = (g_prop_tail + 1) & 7;
	}
	LeaveCriticalSection(&g_prop_cs);
	InterlockedIncrement(&g_prop_rcv);
}

// Applies one prop packet on the game thread. 1 = done with it (applied, or it was not this copy's
// business); 0 = the prop it names is not in the table yet - the caller retries, because the table is
// rebuilt every 150 ms and a prop can be missing from one scan.
static int prop_apply_packet(const pkt_prop *pp)
{
	int host_word = g_role == 2;   // the packet came from the host
	unsigned ch = pp->ch_tag ? human_exact(pp->ch_tag) : 0;
	unsigned ent = 0;
	if (pp->kind == 3 && ch) {
		ent = prop_held_chair(ch, pp->cls);   // a carried prop is named exactly by the hand it is in
		if (ent && pp->id && rd32(ent + 4) != pp->id)
			ent = 0;
	}
	if (!ent)
		ent = prop_find(pp->cls, pp->id, pp->pos);
	if (pp->kind == 1 || pp->kind == 2) {
		if (!ch && pp->ch_tag) {
			InterlockedIncrement(&g_prop_missing);
			char ct[5];
			logf("%s: prop carry packet: no character %s here",
				g_role == 2 ? "guest" : "host", tag4(pp->ch_tag, ct));
			return 1;
		}
		if (!ent && pp->kind == 1)
			return 0;   // the prop is not in the table yet: try again after the next scan
		if (pp->kind == 1) {
			char c[5], i4[5], ct[5];
			const float *ep = (const float *)(uintptr_t)(ent + 0x6c);
			logf("%s: prop carry packet: prop %s id %s -> ent %x (%.1f,%.1f,%.1f), character %s %x (holds %x)",
				g_role == 2 ? "guest" : "host", tag4(pp->cls, c), tag4(pp->id, i4), ent, ep[0], ep[1], ep[2],
				tag4(pp->ch_tag, ct), ch, ch ? rd32(ch + 0x2bc) : 0);
		}
		prop_apply_carry(ch, pp->kind == 1 ? ent : 0);
		InterlockedIncrement(&g_prop_applied);
		return 1;
	}
	if (pp->kind != 3)
		return 1;
	if (!ent) {
		// keep the retry cheap: the announcement arrives three times and the host repeats its state
		// once a second, so a prop that never shows up is reported, not waited for forever
		return 0;
	}
	// Do not break it this instant: this copy usually performs the same break itself within a frame, and
	// a second call to the game's break while its own action runs is not safe. Wait 350 ms; if the prop
	// is still whole then, this copy really missed the action.
	{
		char c[5], i4[5], ct[5];
		const float *ep = (const float *)(uintptr_t)(ent + 0x6c);
		logf("%s: prop break packet: %s id %s -> ent %x (%.1f,%.1f,%.1f) carrier %s broken %u",
			g_role == 2 ? "guest" : "host", tag4(pp->cls, c), tag4(pp->id, i4), ent, ep[0], ep[1], ep[2],
			pp->ch_tag ? tag4(pp->ch_tag, ct) : "none", rd32(ent + 0xa4));
	}
	prop_defer_break(ent, pp->drop_cls, pp->drop_id, pp->drop_pos, host_word);
	InterlockedIncrement(&g_prop_applied);
	return 1;
}

// A packet whose prop was not in the table is retried a few times before it is counted as missing.
typedef struct { pkt_prop p; DWORD at; int tries; } prop_retry;
static prop_retry g_retry[4];

static void prop_retry_add(const pkt_prop *p)
{
	int slot = -1;
	for (int i = 0; i < 4; i++)
		if (!g_retry[i].at || (LONG)(GetTickCount() - g_retry[i].at) > 3000) { slot = i; break; }
	if (slot < 0) {   // no free slot: reuse the one that has been waiting longest
		slot = 0;
		for (int i = 1; i < 4; i++)
			if ((LONG)(g_retry[i].at - g_retry[slot].at) < 0)
				slot = i;
		InterlockedIncrement(&g_prop_missing);
	}
	memset(&g_retry[slot], 0, sizeof g_retry[slot]);
	g_retry[slot].p = *p;
	g_retry[slot].at = GetTickCount() + 120;
}

static void prop_retry_tick(void)
{
	DWORD now = GetTickCount();
	for (int i = 0; i < 4; i++) {
		if (!g_retry[i].at || (LONG)(now - g_retry[i].at) < 0)
			continue;
		if (prop_apply_packet(&g_retry[i].p)) {
			g_retry[i].at = 0;
			continue;
		}
		if (++g_retry[i].tries > 8) {
			g_retry[i].at = 0;
			InterlockedIncrement(&g_prop_missing);
			logf("%s: prop %s never turned up in this level (announced %d times)",
				g_role == 2 ? "guest" : "host", g_retry[i].p.kind == 3 ? "break" : "carry",
				g_retry[i].tries);
			continue;
		}
		g_retry[i].at = now + 150;
	}
}

static void peer_apply_props(void)
{
	for (;;) {
		pkt_prop p;
		EnterCriticalSection(&g_prop_cs);
		if (g_prop_head == g_prop_tail) {
			LeaveCriticalSection(&g_prop_cs);
			return;
		}
		p = g_prop_q[g_prop_head];
		DWORD queued = g_prop_q_tick[g_prop_head];
		LeaveCriticalSection(&g_prop_cs);
		unsigned g = game_obj(), w = world_obj();
		if (GetTickCount() - queued > 10000) {
			EnterCriticalSection(&g_prop_cs);
			g_prop_head = (g_prop_head + 1) & 7;
			LeaveCriticalSection(&g_prop_cs);
			InterlockedIncrement(&g_prop_missing);
			continue;
		}
		if (!g || !w || rd32(g + 0x310) != 1 || rd32(g + 0x320) != 0)
			return;   // menu or loading: keep it queued
		if (!world_ready() || g_prop_gen != g_world_gen)
			return;   // TASK 40: the world is being built/rebuilt: keep it queued, never apply on a half table
		if (rd32(w + 4) != p.level)
			return;   // another level: keep it queued
		EnterCriticalSection(&g_prop_cs);
		g_prop_head = (g_prop_head + 1) & 7;
		LeaveCriticalSection(&g_prop_cs);
		if (g_prop_gen != g_world_gen || rd32(w + 4) != g_prop_level)
			prop_scan(w, rd32(w + 4));   // a level change since the last scan
		if (!prop_apply_packet(&p))
			prop_retry_add(&p);
	}
}

// Host: once a second, send every broken prop and the drop it enabled. The three-times announcement covers
// a lost packet; this covers a lost burst and a link pause, and it is what brings a reconnected guest back
// to the host's world state. The guest applies it through the same break path as an announcement.
static void host_send_prop_state(DWORD level)
{
	static DWORD last;
	DWORD now = GetTickCount();
	if (now - last < 1000)
		return;
	last = now;
	pkt_props p;
	memset(&p, 0, sizeof p);
	p.level = level;
	for (int i = 0; i < g_prop_n && p.n < PROP_STATE_MAX; i++) {
		if (!g_props[i].broken)
			continue;
		unsigned drop = prop_drop_of(g_props[i].ent);
		prop_state *e = &p.e[p.n++];
		e->cls = g_props[i].cls;
		e->id = g_props[i].id;
		e->drop_cls = drop ? rd32(drop + 0x10) : 0;
		e->drop_id = drop ? rd32(drop + 4) : 0;
		memcpy(e->pos, g_prop_pos[i], sizeof e->pos);
		if (drop && mem_ok((const void *)(uintptr_t)(drop + 0x6c), 12))
			memcpy(e->drop_pos, (const void *)(uintptr_t)(drop + 0x6c), sizeof e->drop_pos);
	}
	if (!p.n)
		return;
	net_send(PKT_PROPS, &p, (WORD)(sizeof p - sizeof(pkt_hdr)));
	InterlockedIncrement(&g_prop_sent);
}

// Guest: the host's prop state. Applied in the frame tick (this runs on the network thread), so it only
// stores the newest packet.
static pkt_props g_rx_props;
static volatile LONG g_rx_props_new;
static void guest_on_props(const char *buf, int n)
{
	if (n < (int)(sizeof(pkt_props) - sizeof(g_rx_props.e) + sizeof(prop_state)))
		return;
	const pkt_props *p = (const pkt_props *)buf;
	if (p->n > PROP_STATE_MAX)
		return;
	EnterCriticalSection(&g_prop_cs);
	memcpy(&g_rx_props, buf, n);
	g_rx_props_new = 1;
	LeaveCriticalSection(&g_prop_cs);
	InterlockedIncrement(&g_prop_rcv);
}

static void guest_apply_prop_state(void)
{
	if (g_role != 2 || !g_rx_props_new)
		return;
	if (!world_ready() || g_prop_gen != g_world_gen)
		return;   // TASK 40: keep the newest packet until the world is settled and the table is ours
	pkt_props p;
	EnterCriticalSection(&g_prop_cs);
	memcpy(&p, &g_rx_props, sizeof p);
	g_rx_props_new = 0;
	LeaveCriticalSection(&g_prop_cs);
	unsigned w = world_obj();
	if (!w || rd32(w + 4) != p.level || rd32(w + 4) != g_prop_level)
		return;
	for (DWORD i = 0; i < p.n; i++) {
		unsigned ent = prop_find(p.e[i].cls, p.e[i].id, p.e[i].pos);
		if (!ent)
			continue;
		prop_apply_break(ent, p.e[i].drop_cls, p.e[i].drop_id, p.e[i].drop_pos, 1);
		InterlockedIncrement(&g_prop_applied);
	}
}

// A break announcement that is not applied at once (see peer_apply_props): after the delay the prop is
// broken only if this copy's own game still has it whole.
typedef struct { unsigned ent; DWORD at, dcls, did, cls, id, vt; float dpos[3]; int host_word; } prop_pending;
static prop_pending g_pend[8];
static int g_pend_n;

static void prop_defer_break(unsigned ent, DWORD dcls, DWORD did, const float *dpos, int host_word)
{
	for (int i = 0; i < g_pend_n; i++)
		if (g_pend[i].ent == ent) {   // a repeat of the same announcement: keep the first deadline
			return;
		}
	if (g_pend_n >= 8)
		return;
	prop_pending *p = &g_pend[g_pend_n++];
	p->ent = ent;
	p->at = GetTickCount() + 350;
	p->dcls = dcls;
	p->did = did;
	p->host_word = host_word;
	memcpy(p->dpos, dpos, sizeof p->dpos);
	// TASK 35: the entity is a pointer into the world, and the deadline is 350 ms away - a level change
	// in between frees it. Remember what it was, so the apply below cannot run on a reused heap block.
	p->cls = (ent && !IsBadReadPtr((void *)(uintptr_t)ent, 0x20)) ? rd32(ent + 0x10) : 0;
	p->id = p->cls ? rd32(ent + 4) : 0;
	p->vt = p->cls ? rd32(ent) : 0;   // TASK 40: and the class vtable (a reused block has another)
}

// A level change frees every entity the pending list names (TASK 35).
static void prop_pending_flush(void)
{
	g_pend_n = 0;
}

static void prop_tick_pending(void)
{
	DWORD now = GetTickCount();
	for (int i = 0; i < g_pend_n; ) {
		if ((LONG)(now - g_pend[i].at) < 0) {
			i++;
			continue;
		}
		prop_pending p = g_pend[i];
		g_pend[i] = g_pend[--g_pend_n];
		if (!p.ent || !p.cls || !prop_alive(p.ent, p.cls, p.vt) || (p.id && rd32(p.ent + 4) != p.id)) {
			logf("%s: prop break: the entity is gone (the world was rebuilt): not applied", g_role == 2 ? "guest" : "host");
			continue;
		}
		if (!rd32(p.ent + 0xa4)) {   // still whole: this copy missed the action
			prop_apply_break(p.ent, p.dcls, p.did, p.dpos, p.host_word);
		} else {
			// TASK 35: the deferred break found the prop already broken here. That is the normal case (this
			// copy broke it too) and stays quiet; a break that only ever lands here is what a failed
			// guest->host break looks like, so say it once per prop.
			static unsigned logged[4];
			static int next_log;
			int seen = 0;
			for (int z = 0; z < 4; z++)
				if (logged[z] == p.ent) seen = 1;
			if (!seen) {
				logged[next_log] = p.ent;
				next_log = (next_log + 1) & 3;
				char c[5];
				logf("%s: prop break (deferred) found %s ent %x already broken here: nothing to apply",
					g_role == 2 ? "guest" : "host", tag4(p.cls, c), p.ent);
			}
			prop_align_drop(p.ent, p.dcls, p.did, p.dpos, p.host_word);
		}
	}
}

// The prop this character holds (only a chair-like object: slot 28 is the chair attach, which keeps
// character+0x2bc from ever being mistaken for a controller the game points it at during a pickup).
static unsigned prop_held_by(unsigned ch)
{
	unsigned cur = rd32(ch + 0x2bc);
	if (!cur || IsBadReadPtr((void *)(uintptr_t)cur, 0xcc))
		return 0;
	void **vt = *(void ***)(uintptr_t)cur;
	if (!vt || !image_ptr((DWORD)(uintptr_t)vt) || IsBadReadPtr(vt, 29 * sizeof(void *)) ||
	    vt[28] != (void *)(uintptr_t)PROP_ATTACH_CHAIR)
		return 0;
	if (rd32(cur + 0xa4))
		return 0;   // a broken chair stays linked (the game keeps it in hand): it is not "carried"
	return cur;
}

// Break announcements wait here and are repeated: UDP is not reliable and a break is rare, so three
// copies over ~160 ms cost nothing and survive a lost packet.
typedef struct { DWORD cls, id, drop_cls, drop_id, ch_tag; float pos[3], drop_pos[3]; DWORD next_send; int left; } prop_rep;
static prop_rep g_rep[8];
static int g_rep_n;
static DWORD g_prop_scan_at;

static void prop_announce_break(int i, DWORD now)
{
	unsigned drop = prop_drop_of(g_props[i].ent);
	prop_rep *r = 0;
	for (int k = 0; k < g_rep_n; k++)   // a finished announcement's slot is free again
		if (g_rep[k].left <= 0) { r = &g_rep[k]; break; }
	if (!r && g_rep_n < 8)
		r = &g_rep[g_rep_n++];
	if (!r)
		r = &g_rep[0];
	{
		memset(r, 0, sizeof *r);
		r->cls = g_props[i].cls;
		r->id = g_props[i].id;
		// The character that was holding it (a broken chair stays linked in the hand): the peer identifies
		// a carried prop by the hand it is in, which survives any position drift. 0 when it lies on the floor.
		// TASK 35: prop_alive() tests the CLASS tag at +0x10, which is a character's own tag (GIR1), so the
		// test was always false and every announcement went out with ch_tag 0 - the peer could then only
		// match by position. Validate the carrier as a character instead.
		r->ch_tag = (g_props[i].carrier && g_props[i].carrier > 0x10000 &&
		             !IsBadReadPtr((const void *)(uintptr_t)g_props[i].carrier, 0x330))
		                ? rd32(g_props[i].carrier + H_TAG) : 0;
		r->drop_cls = drop ? rd32(drop + 0x10) : 0;
		r->drop_id = drop ? rd32(drop + 4) : 0;
		memcpy(r->pos, g_prop_pos[i], sizeof r->pos);
		if (drop && mem_ok((const void *)(uintptr_t)(drop + 0x6c), 12))
			memcpy(r->drop_pos, (const void *)(uintptr_t)(drop + 0x6c), sizeof r->drop_pos);
		r->next_send = now;
		r->left = 3;
	}
	char c[5], i4[5], dc[5];
	logf("%s: prop broken here: %s id %s ent %x at (%.1f,%.1f,%.1f) carrier %s drop %s",
		g_role == 2 ? "guest" : "host", tag4(g_props[i].cls, c), tag4(g_props[i].id, i4), g_props[i].ent,
		g_prop_pos[i][0], g_prop_pos[i][1], g_prop_pos[i][2],
		g_props[i].carrier ? tag4(rd32(g_props[i].carrier + H_TAG), dc) : "none",
		drop ? tag4(rd32(drop + 0x10), c) : "none");
}

static void prop_tick(void)
{
	if (!g_role || !g_peer_ok)
		return;
	unsigned w = world_obj();
	unsigned g = game_obj();
	if (!w || !g || rd32(g + 0x310) != 1 || rd32(g + 0x320) != 0)
		return;
	// TASK 40: nothing of this table is used while the world is not settled. The game builds a new
	// world over several frames (the guest log of claude_verify_39_soak2.log: the table grew 11 -> 19
	// entities while game3.sav loaded into J002); a table built in that window names entities the game
	// replaces a frame later. The peer's announcements stay in their queue meanwhile.
	if (!world_ready()) {
		g_prop_n = 0;
		prop_pending_flush();
		return;
	}
	DWORD level = rd32(w + 4);
	DWORD now = GetTickCount();
	// TASK 39/40: the table is keyed on the WORLD and its GENERATION, not on the level tag. A save load
	// of the level this copy is already in (the soak loads game3.sav while it is in J002) rebuilds the
	// world under an unchanged level tag, and every entity pointer in the table then points into freed
	// memory: the guest died in prop_tick that way (run_s39_soak3.log, Obscure2.exe+0x184fc7).
	if (g_prop_gen != g_world_gen || w != g_prop_world || level != g_prop_level) {
		prop_scan(w, level);
		prop_pending_flush();   // TASK 35: no entity pointer survives the rebuild
	}
	peer_apply_props();
	prop_tick_pending();
	prop_retry_tick();
	if (g_role == 1)
		host_send_prop_state(level);
	else
		guest_apply_prop_state();

	// 1. the character this copy owns: announce what it carries (on change, plus a slow heartbeat so a
	// lost packet cannot leave the copies different). Host owns player 1, guest player 2 (PKT_CHAR).
	{
		static unsigned last_carry;
		static DWORD last_level, last_send;
		unsigned me = player_human(g_role == 2 ? 1 : 0);
		unsigned held = me ? prop_held_by(me) : 0;
		if (me && (held != last_carry || level != last_level || now - last_send > 500)) {
			pkt_prop p;
			memset(&p, 0, sizeof p);
			p.kind = held ? 1 : 2;
			p.level = level;
			p.ch_tag = rd32(me + H_TAG);
			if (held) {
				p.cls = rd32(held + 0x10);
				p.id = rd32(held + 4);
				if (mem_ok((const void *)(uintptr_t)(held + 0x6c), 12))
					memcpy(p.pos, (const void *)(uintptr_t)(held + 0x6c), sizeof p.pos);
			}
			net_send(PKT_PROP, &p, (WORD)(sizeof p - sizeof(pkt_hdr)));
			InterlockedIncrement(&g_prop_sent);
			last_carry = held;
			last_level = level;
			last_send = now;
			if (held) {
				char c[5], i4[5], ct[5];
				logf("%s: prop carry sent: %s id %s by %s", g_role == 2 ? "guest" : "host",
					tag4(rd32(held + 0x10), c), tag4(rd32(held + 4), i4), tag4(rd32(me + H_TAG), ct));
			}
		}
	}

	// 2. a prop that just became broken on this copy: announce it with the drop it enabled.
	if (now - g_prop_scan_at >= 150) {
		g_prop_scan_at = now;
		unsigned old_ent[PROP_MAX];
		DWORD old_broken[PROP_MAX];
		int old_n = g_prop_n;
		for (int i = 0; i < g_prop_n; i++) {
			old_ent[i] = g_props[i].ent;
			old_broken[i] = g_props[i].broken;
		}
		prop_scan(w, level);
		if (level != g_prev_level) {
			// the first scan of a level: everything already broken is the level's own state, and an
			// announcement still queued from the old level is no longer this copy's news
			g_rep_n = 0;
			g_prev_level = level;
		} else {
			for (int i = 0; i < g_prop_n; i++) {
				if (!g_props[i].broken)
					continue;
				if (prop_applied_here(g_props[i].ent, 2500))
					continue;   // this copy applied it from the peer: not its own news
				int was_broken = 0;
				for (int j = 0; j < old_n; j++)
					if (old_ent[j] == g_props[i].ent) {
						was_broken = old_broken[j] != 0;
						break;
					}
				if (!was_broken)
					prop_announce_break(i, now);
			}
		}
	}
	for (int i = 0; i < g_rep_n; i++) {
		prop_rep *r = &g_rep[i];
		if (r->left <= 0 || (LONG)(now - r->next_send) < 0)
			continue;
		pkt_prop p;
		memset(&p, 0, sizeof p);
		p.kind = 3;
		p.level = level;
		p.cls = r->cls;
		p.id = r->id;
		p.ch_tag = r->ch_tag;
		memcpy(p.pos, r->pos, sizeof p.pos);
		p.drop_cls = r->drop_cls;
		p.drop_id = r->drop_id;
		memcpy(p.drop_pos, r->drop_pos, sizeof p.drop_pos);
		net_send(PKT_PROP, &p, (WORD)(sizeof p - sizeof(pkt_hdr)));
		InterlockedIncrement(&g_prop_sent);
		r->left--;
		r->next_send = now + 80;
	}
}

// Test/diagnostic only (pipe `props`): this copy's prop table - index, entity, class, id, broken flag,
// carrier, position and whether the manager's lists hold it right now. It reads only the table, so it
// cannot fault while the game thread rebuilds it.
static void props_dump(char *reply, size_t replysz)
{
	size_t l = 0;
	l += (size_t)_snprintf(reply + l, replysz - l, "props %d in level %08lx:", g_prop_n, (unsigned long)g_prop_level);
	for (int i = 0; i < g_prop_n && i < 20 && l + 110 < replysz; i++) {
		char c[5], i4[5];
		l += (size_t)_snprintf(reply + l, replysz - l, " #%d %x %s/%s %s%s b%u c%x (%.1f,%.1f,%.1f)", i,
			g_props[i].ent, tag4(g_props[i].cls, c), tag4(g_props[i].id, i4),
			g_prop_listed[i] ? "" : "unlisted ", g_props[i].broken ? "BROKEN" : "whole",
			(unsigned)g_props[i].broken, (unsigned)g_props[i].carrier,
			g_prop_pos[i][0], g_prop_pos[i][1], g_prop_pos[i][2]);
	}
}

// ---- character abilities on level objects (TASK 28) ------------------------------------------------
//
// The aptitude objects are level entities: CToeLockPick (LCKP, Stan), CToeHeavyCase (HCAS, Sven/Kenny),
// CToeDiscLock (DISL, Mei), CToeDocument (DOC., Amy), CToeDarkAura* (Shannon). An ability does not change
// the synced inventory or the progress block alone: the game changes THE OBJECT (the lock is used up, the
// case slides) and the door the object belongs to. The owner of the acting character announces the action
// (kind 1) and, when the object's state/position changes, exactly those fields (kind 2). The other copy
// writes a field only where its own value still equals the sender's "before", so an unrelated local change
// is not overwritten. The mini-game itself is never run on the peer. Watched: the aptitude objects and the
// doors near them (a picked lock / absorbed aura opens its door).
#define APT_MAX 12
static const unsigned APT_OFF[APT_FIELDS] = { 0x20, 0x24, 0xa8, 0x120, 0x124, 0x128, 0x184, 0x1ec, 0x1f0, 0x150 };

typedef struct { unsigned ent; DWORD cls, id, vt; DWORD v[APT_FIELDS]; float pos[3]; } apt_slot;
static apt_slot g_apts[APT_MAX];
static int g_apt_n;
static DWORD g_apt_level, g_apt_scan_at;
static unsigned g_apt_world;
static DWORD g_apt_gen;   // TASK 40: the world generation the table belongs to
static volatile LONG g_apt_sent, g_apt_rcv, g_apt_applied, g_apt_actions;

static int apt_class(DWORD t)
{
	return t == 0x4c434b50 /*LCKP*/ || t == 0x48434153 /*HCAS*/ || t == 0x4449534c /*DISL*/ ||
	       t == 0x444f432e /*DOC.*/ || t == 0x44415552 /*DAUR*/ || t == 0x44415531 /*DAU1*/ ||
	       t == 0x44415532 /*DAU2*/ || t == 0x44415533 /*DAU3*/;
}

static int door_class(DWORD t)
{
	return t == 0x444f5248 /*DORH*/ || t == 0x444f444f /*DODO*/ || t == 0x494e444f /*INDO*/;
}

static void apt_read(apt_slot *a)
{
	for (int i = 0; i < APT_FIELDS; i++)
		a->v[i] = rd32(a->ent + APT_OFF[i]);
	a->vt = rd32(a->ent);   // TASK 40: the class vtable is part of the identity (cf. prop_refresh)
	if (mem_ok((const void *)(uintptr_t)(a->ent + 0x6c), 12))
		memcpy(a->pos, (const void *)(uintptr_t)(a->ent + 0x6c), sizeof a->pos);
}

static float adist(const float *a, const float *b)
{
	float dx = a[0] - b[0], dy = a[1] - b[1], dz = a[2] - b[2];
	return sqrtf(dx * dx + dy * dy + dz * dz);
}

// Rebuilds the watched table from the level entity list: aptitude objects, plus the doors near one.
static void apt_scan(unsigned w, DWORD level)
{
	int was_n = g_apt_n;
	DWORD old_level = g_apt_level;
	// TASK 40: compare against the previous table only inside the same world generation
	int same_world = (g_apt_gen == g_world_gen && g_apt_world == w && level == old_level);
	apt_slot old[APT_MAX];
	memcpy(old, g_apts, sizeof(apt_slot) * (size_t)g_apt_n);
	g_apt_n = 0;
	g_apt_level = level;
	g_apt_world = w;
	g_apt_gen = g_world_gen;
	unsigned mgr = rd32(w + 0x1768);
	unsigned node = mgr ? rd32(mgr + 8) : 0;
	unsigned seen[600];
	int nseen = 0;
	while (node && nseen < 600) {
		int dup = 0;
		for (int k = 0; k < nseen; k++)
			if (seen[k] == node) { dup = 1; break; }
		if (dup)
			break;
		seen[nseen++] = node;
		unsigned e = rd32(node), cls = e ? rd32(e + 0x10) : 0;
		if (e && e > 0x10000 && !IsBadReadPtr((void *)(uintptr_t)e, 0x200) && apt_class(cls) && g_apt_n < APT_MAX) {
			apt_slot *a = &g_apts[g_apt_n++];
			memset(a, 0, sizeof *a);
			a->ent = e;
			a->cls = cls;
			a->id = rd32(e + 4);
			apt_read(a);
		}
		node = rd32(node + 4);
	}
	// doors near an aptitude object (the door a picked lock / absorbed aura belongs to)
	int apts = g_apt_n;
	for (int pass = 0; pass < apts && g_apt_n < APT_MAX; pass++) {
		unsigned head = mgr ? rd32(mgr + 8) : 0;
		nseen = 0;
		while (head && nseen < 600) {
			int dup = 0;
			for (int k = 0; k < nseen; k++)
				if (seen[k] == head) { dup = 1; break; }
			if (dup)
				break;
			seen[nseen++] = head;
			unsigned e = rd32(head), cls = e ? rd32(e + 0x10) : 0;
			head = rd32(head + 4);
			if (!e || e <= 0x10000 || !door_class(cls) || IsBadReadPtr((void *)(uintptr_t)e, 0x200))
				continue;
			int have = 0;
			for (int k = 0; k < g_apt_n; k++)
				if (g_apts[k].ent == e) { have = 1; break; }
			if (have || g_apt_n >= APT_MAX)
				continue;
			float p[3];
			if (!mem_ok((const void *)(uintptr_t)(e + 0x6c), 12))
				continue;
			memcpy(p, (const void *)(uintptr_t)(e + 0x6c), sizeof p);
			if (adist(p, g_apts[pass].pos) > 400.0f)
				continue;
			apt_slot *a = &g_apts[g_apt_n++];
			memset(a, 0, sizeof *a);
			a->ent = e;
			a->cls = cls;
			a->id = rd32(e + 4);
			apt_read(a);
		}
	}
	if (g_apt_n != was_n || level != old_level)
		logf("%s: ability objects: %d watched entit%s in level %x", g_role == 2 ? "guest" : "host",
		     g_apt_n, g_apt_n == 1 ? "y" : "ies", level);
	if (same_world)   // same level + world: compare and announce what changed on this copy
		for (int i = 0; i < g_apt_n; i++) {
			apt_slot *a = &g_apts[i];
			for (int j = 0; j < was_n; j++) {
				if (old[j].ent != a->ent)
					continue;
				int fdiff = 0;
				for (int f = 0; f < APT_FIELDS; f++)
					if (old[j].v[f] != a->v[f])
						fdiff = 1;
				int pdiff = adist(old[j].pos, a->pos) > 0.5f;
				if ((fdiff || pdiff) && !prop_applied_here(a->ent, 2500)) {
					pkt_apt p;
					memset(&p, 0, sizeof p);
					p.kind = 2;
					p.level = level;
					p.cls = a->cls;
					p.id = a->id;
					memcpy(p.before, old[j].pos, sizeof p.before);
					memcpy(p.pos, a->pos, sizeof p.pos);
					for (int f = 0; f < APT_FIELDS; f++) {
						p.old[f] = old[j].v[f];
						p.now[f] = a->v[f];
					}
					net_send(PKT_APT, &p, (WORD)(sizeof p - sizeof(pkt_hdr)));
					InterlockedIncrement(&g_apt_sent);
					char c[5];
					logf("%s: ability result sent: %s id %s ent %x fields %d move %.1f",
					     g_role == 2 ? "guest" : "host", tag4(a->cls, c), tag4(a->id, c), a->ent, fdiff,
					     adist(old[j].pos, a->pos));
				}
				break;
			}
		}
}

// A result this copy applied from the peer must not be announced back.
static void apt_apply_packet(const pkt_apt *p)
{
	int best = -1;
	float bd = 400.0f * 400.0f;
	for (int i = 0; i < g_apt_n; i++) {
		apt_slot *a = &g_apts[i];
		if (a->cls != p->cls || (p->id && a->id && a->id != p->id))
			continue;
		float dx = a->pos[0] - p->before[0], dy = a->pos[1] - p->before[1], dz = a->pos[2] - p->before[2];
		float d = dx * dx + dy * dy + dz * dz;
		if (d < bd) { bd = d; best = i; }
	}
	unsigned ent = best >= 0 ? g_apts[best].ent : 0;
	// TASK 40: the slot's entity is re-checked against the identity the scan recorded (class vtable,
	// class tag, id) right before the writes - the table can be a world rebuild old.
	if (best < 0 || !ent || rd32(ent) != g_apts[best].vt || rd32(ent + 0x10) != g_apts[best].cls ||
	    (p->id && g_apts[best].id && rd32(ent + 4) != g_apts[best].id) || !world_has_entity(ent) ||
	    IsBadWritePtr((void *)(uintptr_t)ent, 0x200)) {
		InterlockedIncrement(&g_apt_rcv);
		return;
	}
	int wrote = 0;
	for (int f = 0; f < APT_FIELDS; f++) {
		unsigned off = APT_OFF[f];
		if (p->old[f] == p->now[f])
			continue;
		if (rd32(ent + off) == p->old[f]) {
			*(DWORD *)(uintptr_t)(ent + off) = p->now[f];
			wrote++;
		}
	}
	float np[3];
	memcpy(np, (const void *)(uintptr_t)(ent + 0x6c), sizeof np);
	if (adist(np, p->before) <= 5.0f && adist(np, p->pos) > 0.1f) {
		memcpy((void *)(uintptr_t)(ent + 0x6c), p->pos, sizeof p->pos);
		wrote++;
	}
	prop_mark_applied(ent);
	InterlockedIncrement(&g_apt_applied);
	char c[5];
	logf("%s: ability result applied: %s id %s ent %x (%d writes)", g_role == 2 ? "guest" : "host",
	     tag4(p->cls, c), tag4(p->id, c), ent, wrote);
}

static CRITICAL_SECTION g_aptq_cs;
static pkt_apt g_aptq[16];
static int g_aptq_head, g_aptq_tail;

static void peer_on_apt(const char *buf, int n)
{
	if (n != (int)sizeof(pkt_apt))
		return;
	EnterCriticalSection(&g_aptq_cs);
	if (((g_aptq_tail + 1) & 15) != g_aptq_head) {
		memcpy(&g_aptq[g_aptq_tail], buf, sizeof(pkt_apt));
		g_aptq_tail = (g_aptq_tail + 1) & 15;
	}
	LeaveCriticalSection(&g_aptq_cs);
	InterlockedIncrement(&g_apt_rcv);
}

static void apt_tick(void)
{
	if (!g_role)
		return;
	unsigned w = world_obj(), g = game_obj();
	if (!w || !g || rd32(g + 0x310) != 1 || rd32(g + 0x320) != 0)
		return;
	// TASK 40: same rule as the prop table - no scan and no game call while the world is being built
	if (!world_ready()) {
		g_apt_n = 0;
		return;
	}
	DWORD level = rd32(w + 4);
	// apply what the peer announced (on the game thread)
	for (;;) {
		pkt_apt p;
		EnterCriticalSection(&g_aptq_cs);
		if (g_aptq_head == g_aptq_tail) {
			LeaveCriticalSection(&g_aptq_cs);
			break;
		}
		p = g_aptq[g_aptq_head];
		g_aptq_head = (g_aptq_head + 1) & 15;
		LeaveCriticalSection(&g_aptq_cs);
		if (p.level == level) {
			if (p.kind == 2) {
				apt_apply_packet(&p);
			} else {
				char c[5], ch[5];
				logf("%s: the peer's character %s started the ability on %s id %s (its animation follows)",
				     g_role == 2 ? "guest" : "host", tag4(p.ch_tag, ch), tag4(p.cls, c), tag4(p.id, c));
			}
		}
	}
	DWORD now = GetTickCount();
	if (now - g_apt_scan_at >= 150) {
		g_apt_scan_at = now;
		apt_scan(w, level);
	}
	// kind 1: the character this copy owns just started an ability on an aptitude object
	unsigned me = player_human(g_role == 2 ? 1 : 0);
	unsigned act = me ? rd32(me + 0x2bc) : 0;
	static unsigned last_act;
	if (act != last_act) {
		last_act = act;
		if (act && !IsBadReadPtr((void *)(uintptr_t)act, 0x200) && apt_class(rd32(act + 0x10))) {
			pkt_apt p;
			memset(&p, 0, sizeof p);
			p.kind = 1;
			p.level = level;
			p.ch_tag = rd32(me + H_TAG);
			p.cls = rd32(act + 0x10);
			p.id = rd32(act + 4);
			if (mem_ok((const void *)(uintptr_t)(act + 0x6c), 12))
				memcpy(p.pos, (const void *)(uintptr_t)(act + 0x6c), sizeof p.pos);
			net_send(PKT_APT, &p, (WORD)(sizeof p - sizeof(pkt_hdr)));
			InterlockedIncrement(&g_apt_actions);
			char c[5], ch[5];
			logf("%s: ability started here: %s id %s by %s", g_role == 2 ? "guest" : "host",
			     tag4(p.cls, c), tag4(p.id, c), tag4(p.ch_tag, ch));
		}
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
	// TASK 37: the host's authoritative state for the guest's self-heal: the level the party is in (the
	// last transition the host performed or announced), its entry, and whether this copy is in the middle
	// of a transition right now (game+0x320 != 0 or the world is being rebuilt).
	p.host_level = p.level ? p.level : g_last_level;   // the level the host is actually in, else its last announced one
	p.host_entry = g_last_entry;
	p.host_seq = g_trans_seq;
	{
		unsigned go = game_obj();
		p.host_busy = (g_last_level && (rd32(go + 0x320) != 0 || !go)) ? 1u : 0u;
	}
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
		{   // TASK 35: make the life the snapshot carries visible (a life change that does not arrive is
			// otherwise invisible on both sides).
			static struct { DWORD tag, val; } ll[8];
			int slot = -1;
			for (int z = 0; z < 8; z++)
				if (ll[z].tag == c->tag) { slot = z; break; }
			for (int z = 0; z < 8 && slot < 0; z++)
				if (!ll[z].tag) slot = z;
			if (slot >= 0 && ll[slot].val != c->life) {
				float v;
				memcpy(&v, &c->life, 4);
				ll[slot].tag = c->tag;
				ll[slot].val = c->life;
				char t[5];
				logf("host: life %s is %.1f (sent in the snapshot)", tag4(c->tag, t), v);
			}
		}
		for (int s = 0; s < 4; s++) {
			unsigned wp = rd32(hs[i] + 0x704 + 4 * s);   // the live weapon object in slot s
			c->wep[s] = wp ? rd32(wp + 0x10) : 0;        // its tag, 0 = empty slot
		}
		c->wcur = rd32(hs[i] + 0x714);                   // the slot in the hand
	}
	// TASK 30: the battery/energy a story event sets (Cslh_EnergySet -> inventory+0xc88) is host-owned.
	unsigned inv = rd32(world_obj() + 0x1790);
	if (inv && !IsBadReadPtr((const void *)(uintptr_t)(inv + INV_ENERGY), 4)) {
		memcpy(&p.energy, (const void *)(uintptr_t)(inv + INV_ENERGY), 4);
		p.energy_valid = 1;
	}
	net_send(PKT_STATE, &p, (WORD)(sizeof p - sizeof(pkt_hdr)));
	InterlockedIncrement(&g_snd_states);
}

// ---- guest: snapshots --------------------------------------------------------------------------

static CRITICAL_SECTION g_rx_cs;
static pkt_state g_rx_state;
static volatile LONG g_rx_state_new;

// ---- TASK 42: the peer's character is a PUPPET -----------------------------------------------------
// The old model re-simulated BOTH characters on both copies from streamed pads (with an input delay) and
// corrected the remote one with position snapshots. On a real Steam link that was unplayable: the remote
// character slid without a walk animation (a pad that arrives late is not the input the owner's copy
// ran) and the two games disagreed about where it was - which is what froze/crashed the game's own code
// (FINDINGS_41 section 1, the owner's playtest).
//
// The puppet model: each copy simulates only its own character. The peer's character is played back from
// a stream: position, facing, velocity, the owner's speed (character+0x278, the value the game's own
// movement state machine uses to pick idle/walk/run) and the game state (character+0x2dc, the id the
// whole game switches on - FINDINGS_42 section 1). The state is applied through the GAME'S OWN SETTER,
// the human's vtable slot 18 (0x4e3ed0 - it plays the animation clip that belongs to the state and
// stores the id in +0x2dc), so walking, running, the aim stance, an attack, a climb and a death play
// their real animation. A raw write of +0x2dc (the old code) changes the value but plays no clip.
//
// Playback is an interpolation buffer ~100 ms behind the newest sample; the delay adapts to the measured
// arrival jitter (the Steam link delivers in bursts, FINDINGS_41 section 3). The buffer is filled on the
// network thread and read on the game thread; both run under g_pb_cs.
#define PBUF 32             // samples kept (a 16 ms stream: half a second of history)
#define PUP_DELAY_MIN 55.0f
#define PUP_DELAY_MAX 220.0f
#define PUP_EXTRAP_MAX 120  // ms of dead reckoning past the newest sample
typedef struct { DWORD t; float pos[3], dir[3], vel[3]; DWORD speed, anim, ui, wsel;
                 float intent[3]; DWORD wanted, ev_seq, ev_val[4], gait; } psample;

static CRITICAL_SECTION g_pb_cs;
static psample g_pb[PBUF];        // sorted by t, oldest first
static int g_pb_n;
static DWORD g_pb_tag;            // the character tag the stream belongs to
static DWORD g_pb_level;          // ... and the level it says it is in
static float g_pb_delay = 90.0f;  // playback delay (ms), adaptive
static float g_pb_age = -1.0f;    // running mean of the arrival age
static float g_pb_dev = 10.0f;    // running mean of |age - mean|
static DWORD g_pb_anim_done;      // the state id last handed to the game's setter (game thread)
static DWORD g_pb_anim_tag;       // ... for this character
static volatile LONG g_char_rcv, g_char_sent, g_char_applied, g_char_skipped, g_char_snaps, g_char_blends;
static volatile LONG g_pb_under, g_pb_extrap, g_pb_anim_sets, g_pb_anim_diff, g_pb_nosample, g_pb_anim_ok;
static volatile LONG g_pb_err_n;
static volatile float g_pb_err_sum, g_pb_err_max;
static volatile LONG g_pb_writes;

// A character's state setter: the game's own animation/state function (CCharacterHuman vtable slot 18,
// 0x4e3ed0 -> __thiscall(void *character, unsigned state)).
typedef void(__fastcall *char_state_t)(void *, void *, unsigned);

static void peer_on_char(const char *buf, int n)
{
	if (n != (int)sizeof(pkt_char))
		return;
	const pkt_char *p = (const pkt_char *)buf;
	EnterCriticalSection(&g_pb_cs);
	if (g_pb_tag != p->me.tag) {   // another character (a respawn, a rebuilt party): the old history is not its own
		char t[5], l[5];
		g_pb_tag = p->me.tag;
		g_pb_n = 0;
		g_pb_age = -1.0f;
		logf("puppet: the peer streams %s in level %s", tag4(p->me.tag, t), tag4(p->level, l));
	}
	g_pb_level = p->level;
	int i = g_pb_n;
	if (i >= PBUF) {   // full: drop the oldest
		memmove(&g_pb[0], &g_pb[1], sizeof(psample) * (PBUF - 1));
		i = PBUF - 1;
	}
	psample *s = &g_pb[i];
	memset(s, 0, sizeof *s);
	s->t = p->t_ms;
	memcpy(s->pos, p->me.pos, 12);
	memcpy(s->dir, p->me.dir, 12);
	memcpy(s->vel, p->vel, 12);
	s->speed = p->speed;
	s->anim = p->me.anim;
	s->ui = p->ui;
	s->wsel = p->wsel;
	memcpy(s->intent, p->intent, sizeof s->intent);
	s->wanted = p->wanted;
	s->ev_seq = p->ev_seq;
	memcpy(s->ev_val, p->ev_val, sizeof s->ev_val);
	s->gait = p->gait;
	g_pb_n = i + 1;
	while (i > 0 && (LONG)(g_pb[i - 1].t - g_pb[i].t) > 0) {   // out of order (jitter)
		psample tmp = g_pb[i - 1];
		g_pb[i - 1] = g_pb[i];
		g_pb[i] = tmp;
		i--;
	}
	{   // the playback delay: mean arrival age + twice its deviation + a margin, bounded, slowly adapted
		LONG age = (LONG)(timeline_now() - p->t_ms);
		if (age < -500) age = -500;
		if (age > 500) age = 500;
		if (g_pb_age < -400.0f)
			g_pb_age = (float)age;
		else
			g_pb_age += ((float)age - g_pb_age) * 0.1f;
		float d = (float)age - g_pb_age;
		if (d < 0) d = -d;
		g_pb_dev += (d - g_pb_dev) * 0.1f;
		float want = g_pb_age + 2.0f * g_pb_dev + 30.0f;
		if (want < PUP_DELAY_MIN) want = PUP_DELAY_MIN;
		if (want > PUP_DELAY_MAX) want = PUP_DELAY_MAX;
		g_pb_delay += (want - g_pb_delay) * 0.05f;
	}
	LeaveCriticalSection(&g_pb_cs);
	InterlockedIncrement(&g_char_rcv);
}

// The pose to show now: the buffer interpolated at (now - delay). 0 = no sample yet.
static int puppet_pose(psample *out)
{
	if (!g_pb_tag)
		return 0;
	DWORD tp;
	EnterCriticalSection(&g_pb_cs);
	int n = g_pb_n;
	if (n < 1) {
		LeaveCriticalSection(&g_pb_cs);
		return 0;
	}
	tp = timeline_now() - (DWORD)g_pb_delay;
	*out = g_pb[n - 1];
	if ((LONG)(tp - g_pb[n - 1].t) >= 0) {   // past the newest sample: dead reckon along the last step
		psample *a = &g_pb[n - 1], *b = n > 1 ? &g_pb[n - 2] : 0;
		LONG age = (LONG)(tp - a->t);
		if (age > PUP_EXTRAP_MAX) age = PUP_EXTRAP_MAX;
		if (b && age > 0 && (LONG)(a->t - b->t) > 0) {
			float k = (float)age / (float)(int)(a->t - b->t);
			if (k > 1.5f) k = 1.5f;
			for (int c = 0; c < 3; c++)
				out->pos[c] = a->pos[c] + (a->pos[c] - b->pos[c]) * k;
			InterlockedIncrement(&g_pb_extrap);
		}
	} else if ((LONG)(tp - g_pb[0].t) < 0) {   // older than the history: the oldest sample
		*out = g_pb[0];
		InterlockedIncrement(&g_pb_under);
	} else {
		for (int i = n - 1; i > 0; i--) {
			if ((LONG)(tp - g_pb[i - 1].t) >= 0) {
				psample *a = &g_pb[i], *b = &g_pb[i - 1];
				LONG span = (LONG)(a->t - b->t);
				float k = span > 0 ? (float)(LONG)(tp - b->t) / (float)span : 1.0f;
				float dx = b->dir[0] + (a->dir[0] - b->dir[0]) * k;
				float dy = b->dir[1] + (a->dir[1] - b->dir[1]) * k;
				float dz = b->dir[2] + (a->dir[2] - b->dir[2]) * k;
				float l = sqrtf(dx * dx + dy * dy + dz * dz);
				*out = *a;
				out->anim = b->anim;   // the state the owner was in at the playback instant
				out->speed = b->speed;
				out->ui = b->ui;       // TASK 43: the per-player UI the owner had then
				out->wsel = b->wsel;
				memcpy(out->intent, b->intent, sizeof out->intent);   // TASK 46: the intent then too
				out->ev_seq = b->ev_seq;                              // ... and the state changes then
				memcpy(out->ev_val, b->ev_val, sizeof out->ev_val);
				out->gait = b->gait;
				for (int c = 0; c < 3; c++) {
					out->pos[c] = b->pos[c] + (a->pos[c] - b->pos[c]) * k;
					out->vel[c] = b->vel[c] + (a->vel[c] - b->vel[c]) * k;
				}
				if (l > 1e-4f) {
					out->dir[0] = dx / l;
					out->dir[1] = dy / l;
					out->dir[2] = dz / l;
				}
				break;
			}
		}
	}
	LeaveCriticalSection(&g_pb_cs);
	return 1;
}

// TASK 43: WHY the puppet was not driven. TASK 42 left five coherence guards in puppet_target() and one
// dropout in the D phase ("the puppet stopped being driven and the game moved it itself", FINDINGS_42
// section 8) with no way to tell which one fired. One counter per guard, reset by the 10 s stats line, plus
// a WINDOW counter: if any guard rejects for longer than PUP_REJ_LOG_MS while the stream and the game are
// live, one log line names the guard and the duration. A single rejected frame (a level change in flight)
// is normal and stays silent.
#define PUP_GUARDS 12
enum {
	PG_NO_LINK = 0, PG_NO_GAME, PG_MODE, PG_NO_WORLD, PG_WSTATE, PG_LEVEL, PG_NO_CTL, PG_NO_CHAR,
	PG_UNWRITABLE, PG_TAG, PG_WIRING, PG_ANIM
};
static volatile LONG g_pup_rej[PUP_GUARDS];
static const char *const g_pup_guard_name[PUP_GUARDS] = {
	"no link/stream", "no game object", "game mode", "no world", "world state", "level",
	"no controller table", "no character", "unwritable character", "character tag", "controller wiring",
	"animation system"
};

// The character the peer drives here (0 = none). The role decides which local slot it is: the host's own
// pad drives player 1, so the guest's character is player 2; on the guest it is the other way round.
static unsigned puppet_target_g(int *guard)
{
#define PUP_REJECT(gid) do { InterlockedIncrement(&g_pup_rej[(gid)]); if (guard) *guard = (gid); return 0; } while (0)
	if (!g_role || !g_peer_ok || !g_pb_tag)
		PUP_REJECT(PG_NO_LINK);
	// This runs from the per-character and per-controller hooks, i.e. on frames where a world is being
	// built or torn down: every pointer is checked before it is dereferenced.
	unsigned g = game_obj();
	if (!g || !mem_ok((const void *)(uintptr_t)g, 0x380))
		PUP_REJECT(PG_NO_GAME);
	if (rd32(g + 0x310) != 1)
		PUP_REJECT(PG_MODE);
	unsigned w = rd32(g + 0x378);
	if (!w || !mem_ok((const void *)(uintptr_t)w, 0x1800))
		PUP_REJECT(PG_NO_WORLD);
	if (rd32(w + 0x11c) != 1)
		PUP_REJECT(PG_WSTATE);   // a menu, a load, a scripted event: the game's own code owns both characters
	if (g_pb_level && rd32(w + 4) != g_pb_level)
		PUP_REJECT(PG_LEVEL);   // the stream is from another level (the level change is still in flight)
	unsigned ctl = rd32(w + 0x1748);
	if (!ctl || !mem_ok((const void *)(uintptr_t)ctl, 0x764 * 2))
		PUP_REJECT(PG_NO_CTL);
	unsigned ctlrec = ctl + 0x764 * (g_role == 1 ? 1 : 0);
	unsigned ch = rd32(ctlrec + 4);
	if (!ch || !mem_ok((const void *)(uintptr_t)ch, 0x330))
		PUP_REJECT(PG_NO_CHAR);
	if (IsBadWritePtr((void *)(uintptr_t)(ch + H_POS), 12))
		PUP_REJECT(PG_UNWRITABLE);
	if (rd32(ch + H_TAG) != g_pb_tag)
		PUP_REJECT(PG_TAG);   // the local world's character is not the one streamed (a rebuild in progress)
	// The character must be WIRED to that controller record (human+8 is the controller the body answers,
	// see check_movement's wiring dump). A world that is being rebuilt has characters allocated but not
	// yet attached; driving one of those (the state setter walks the animation list at +0x210 and the
	// objects at +0x2bc) is how a level change would crash this copy.
	if (rd32(ch + 8) != ctlrec)
		PUP_REJECT(PG_WIRING);
	if (!rd32(ch + 0x210) || !rd32(ch + 0x30c))
		PUP_REJECT(PG_ANIM);   // no animation system yet
	if (guard) *guard = -1;
	return ch;
#undef PUP_REJECT
}

// The identity of the peer's character WITHOUT the pose/state guards: the tag the peer streams decides it.
// The controller and the movement state machine are gated on this, because a guard that fails for a
// moment must never hand the character back to the game's own input (that is the TASK 42 dropout: the
// refused puppet was walked by the game's controller). Writing the pose still needs puppet_target().
static unsigned puppet_identity(void)
{
	unsigned g = game_obj();
	if (!g_role || !g_peer_ok || !g_pb_tag || !g || !mem_ok((const void *)(uintptr_t)g, 0x380))
		return 0;
	unsigned w = rd32(g + 0x378);
	if (!w || !mem_ok((const void *)(uintptr_t)w, 0x1800))
		return 0;
	unsigned ctl = rd32(w + 0x1748);
	if (!ctl || !mem_ok((const void *)(uintptr_t)ctl, 0x764 * 2))
		return 0;
	unsigned ctlrec = ctl + 0x764 * (g_role == 1 ? 1 : 0);
	unsigned ch = rd32(ctlrec + 4);
	if (!ch || !mem_ok((const void *)(uintptr_t)ch, 0x330))
		return 0;
	if (rd32(ch + H_TAG) != g_pb_tag)
		return 0;
	return ch;
}

// Is any guard rejecting a live character right now? The window tracker turns "the puppet was not driven
// for a while" into one log line with the guard's name and the duration.
#define PUP_REJ_LOG_MS 800
static int g_pup_rej_guard = -1;
static int g_pup_rej_logged;
static DWORD g_pup_rej_since;
static DWORD g_pup_drive_since;   // last time the puppet WAS drivable

static unsigned puppet_target(void)
{
	int gi = -1;
	unsigned ch = puppet_target_g(&gi);
	DWORD now = GetTickCount();
	if (gi >= 0) {
		if (g_pup_rej_guard != gi) {
			g_pup_rej_guard = gi;
			g_pup_rej_since = now;
		} else if (now - g_pup_rej_since >= PUP_REJ_LOG_MS && g_pup_drive_since &&
		           (LONG)(now - g_pup_drive_since) < 60000) {
			// log once per window: the first call after the window opened logs, later ones do not
			if (!g_pup_rej_logged) {
				g_pup_rej_logged = 1;
				logf("puppet: the peer's character is NOT driven for %lu ms (guard: %s)", (unsigned long)(now - g_pup_rej_since),
				     g_pup_guard_name[gi]);
			}
		}
	} else {
		if (g_pup_rej_guard >= 0 && g_pup_rej_logged) {
			logf("puppet: driving the peer's character again after %lu ms (was: %s)", (unsigned long)(GetTickCount() - g_pup_rej_since),
			     g_pup_guard_name[g_pup_rej_guard]);
		}
		g_pup_rej_guard = -1;
		g_pup_rej_logged = 0;
		g_pup_drive_since = now;
	}
	return ch;
}

// TASK 45: the position has THREE copies in the game, not one, and the game's own update reads the other
// two every frame:
//   * human+0x23c - the position the renderer/model matrix uses (what TASK 42 wrote);
//   * human+0x27c - the MOVE TARGET. FUN_004de4f0 (the human update) measures pos-target and, when the
//     character has a target and "can move there" (slot 0x38), calls the character's own SetPosition
//     (slot 0x10) with the TARGET - every frame. On a puppet nothing ever wrote the target, so the update
//     walked it back to the level origin (guest) or the spawn point (host) each frame and `puppet_finish`
//     put the pose back - the "drift" of FINDINGS_44 section 2;
//   * human+0x30c -> +0xcc - the COLLISION BODY (CCharacterImpactManager; its vtable slot 7 = 0x449bd0 is
//     `lea eax,[ecx+0xcc]`). Only the game's own SetPosition moves it (slot 3 of the body), and only the
//     movement state machine calls SetPosition for a real player - so on a puppet the body stayed where
//     the character was BUILT (observed: (0,0,z) on the guest, the spawn point on the host), i.e. in
//     another sector/room than the drawn model. That is the stale body of FINDINGS_44 section 2.2.
// Fix: write the move target with the pose and move the character through the game's OWN SetPosition
// (CCharacterHuman vtable slot 4 = FUN_004c6880: it writes +0x23c, moves the collision body, tells the
// kinematic object at +0x124 and +0x314, and copies the body position back when the body is active).
// `move` = 0 only in puppet_finish, where the platform/collision calls of a second SetPosition in the same
// frame are not needed: there the plain fields are enough (the body is already on the pose).
typedef void(__fastcall *char_setpos_t)(void *, void *, float *);
static volatile LONG g_pb_moves;

static void puppet_body(unsigned ch, const float *p, int move)
{
	float q[3] = { p[0], p[1], p[2] };
	if (!IsBadWritePtr((void *)(uintptr_t)(ch + 0x27c), 12))
		memcpy((void *)(uintptr_t)(ch + 0x27c), q, 12);
	if (!move)
		return;
	unsigned vt = rd32(ch), fn = vt ? rd32(vt + 0x10) : 0;
	if (fn && code_in_exe(fn)) {   // __thiscall(this, float *position)
		((char_setpos_t)fn)((void *)(uintptr_t)ch, NULL, q);
		InterlockedIncrement(&g_pb_moves);
	}
}

// Position, facing, velocity and the owner's speed: the four fields the game's own movement code reads.
static void puppet_write(unsigned ch, const psample *s, int move)
{
	float *pos = (float *)(uintptr_t)(ch + H_POS), *dir = (float *)(uintptr_t)(ch + H_DIR);
	float *vel = (float *)(uintptr_t)(ch + 0x294);
	if (IsBadWritePtr(pos, 12) || IsBadWritePtr(dir, 12) || IsBadWritePtr(vel, 12))
		return;
	puppet_body(ch, s->pos, move);
	for (int c = 0; c < 3; c++) {
		pos[c] = s->pos[c];
		dir[c] = s->dir[c];
		vel[c] = s->vel[c];
	}
	if (!IsBadWritePtr((void *)(uintptr_t)(ch + 0x278), 4))
		*(DWORD *)(uintptr_t)(ch + 0x278) = s->speed;   // the speed the walk/run decision uses
	// TASK 46: the MOVE DIRECTION, written the way the owner's input controller writes it (vtable slot
	// 0x60 = FUN_004c6bd0 stores it in +0x288/0x28c/0x290 when +0x2c4 == 0, decompile 121046). Without
	// it the game's own movement state machine (and with it the lower-body animation layer +0x224) sees
	// whatever the character was built with - measured on HEAD: the puppet kept the idle facing while the
	// owner turned (FINDINGS_46 section 2).
	if (rd32(ch + 0x2c4) == 0 && !IsBadWritePtr((void *)(uintptr_t)(ch + 0x288), 12)) {
		float *it = (float *)(uintptr_t)(ch + 0x288);
		for (int c = 0; c < 3; c++)
			it[c] = s->intent[c];
	}
	// The swing state (200 = 0xc8) makes the game's OWN code read its attack target,
	// human+0x824[human+0x820], and dereference it:
	//   0x4dd243  mov 0x820(esi),edx / mov 0x824(esi,edx,4),eax / 0x4dd250 cmp 0,0x64(eax)
	//   0x4e811e  mov 0x820(esi),ecx / mov 0x824(esi,ecx,4),edx / 0x4e812b cmp ebx,0x64(edx)
	// Only the attacker's own controller fills that list (the aim/attack search FUN_004e0750); on a
	// puppet it is null and the copy crashed twice in it (FINDINGS_42 section 5). Point the slot at the
	// character itself - a valid object - so the read is harmless on the copy that only plays the clip.
	if (rd32(ch + 0x2dc) == 200) {
		DWORD idx = rd32(ch + 0x820);
		if (idx > 7) {
			idx = 0;
			*(DWORD *)(uintptr_t)(ch + 0x820) = 0;
		}
		unsigned slot = ch + 0x824 + idx * 4;
		if (!IsBadWritePtr((void *)(uintptr_t)slot, 4) && !rd32(slot))
			*(DWORD *)(uintptr_t)slot = ch;
	}
	InterlockedIncrement(&g_pb_writes);
}

// The state: through the game's own setter, and only when it changes (the setter restarts the clip).
static void puppet_anim(unsigned ch, DWORD st)
{
	DWORD tag = rd32(ch + H_TAG);
	if (g_pb_anim_tag != tag) {
		g_pb_anim_tag = tag;
		g_pb_anim_done = rd32(ch + 0x2dc);
	}
	if (st == g_pb_anim_done)
		return;
	unsigned vt = rd32(ch), fn = vt ? rd32(vt + 0x48) : 0;
	if (!fn || !code_in_exe(fn)) {
		*(DWORD *)(uintptr_t)(ch + 0x2dc) = st;   // fallback: the value at least
		g_pb_anim_done = st;
		return;
	}
	((char_state_t)fn)((void *)(uintptr_t)ch, NULL, st);
	g_pb_anim_done = st;
	InterlockedIncrement(&g_pb_anim_sets);
}

// TASK 46: the LOWER-BODY animation layer in the states the movement machine may not run on the puppet
// (the aim stance: its machine path is the action path TASK 42 gated). The machine changes that layer
// exactly like this (decompile 142194..142199): when the gait index character+0x2e0 differs, it stops the
// old layer clip (vtable slot 0x6c = FUN_004c7620) and plays the new one (vtable slot 0x4c =
// FUN_004e7420, which writes the new index into +0x224). The gait itself is FUN_004da570's answer from
// the intent AND the AIM TARGET (+0x750, FUN_004db0e0) - the aim target is not streamed, so the owner's
// gait index is (measured on HEAD: the owner's +0x224 is LWAF/LWAL in the aim stance, the puppet's LPAU).
typedef void(__fastcall *char_stop_t)(void *, void *, DWORD, int);
typedef void(__fastcall *char_gait_t)(void *, void *, DWORD);
static volatile LONG g_pb_gaits;
static int puppet_aim(DWORD st);   // below: the aim-stance family

static void puppet_gait(unsigned ch, const psample *s)
{
	DWORD st = rd32(ch + 0x2dc);
	if (!puppet_aim(st) || s->gait > 4 || IsBadWritePtr((void *)(uintptr_t)(ch + 0x2e0), 4))
		return;
	unsigned vt = rd32(ch), stop = vt ? rd32(vt + 0x6c) : 0, set = vt ? rd32(vt + 0x4c) : 0;
	if (rd32(ch + 0x2e0) != s->gait) {   // the gait changed: stop the old layer clip, as the machine does
		unsigned tab = rd32(ch + 0x210), idx = rd32(ch + 0x224);
		if (stop && code_in_exe(stop) && tab && idx < 0x1000)
			((char_stop_t)stop)((void *)(uintptr_t)ch, NULL, rd32(tab + idx * 0x28 + 0xc), -1);
		InterlockedIncrement(&g_pb_gaits);
	}
	// FUN_004c74e0 returns early when the clip is already playing, so this is idempotent per frame - and
	// it repairs a layer the state setter had pointed at a different clip.
	if (set && code_in_exe(set))
		((char_gait_t)set)((void *)(uintptr_t)ch, NULL, s->gait);
}

// ---- TASK 46: the owner's state changes as EVENTS (Obscure 1 `host_record_wanted`) -----------------
// A swing, an item use or a climb start can last less than one 16 ms stream interval, so streaming the
// current state alone loses it and the receiver never plays that clip. Each copy records every CHANGE of
// its own character's state (+0x2dc) with a sequence number BEFORE its update (the value the game is
// about to consume, Obscure 1 sync.c ~1728), streams the last four with every PKT_CHAR, and the receiver
// replays the ones it missed, one per update, in order (Obscure 1 sync.c ~1745).
#define EV_KEEP 4
typedef struct { volatile LONG seq; DWORD val[EV_KEEP]; } evring;   // val[seq & (EV_KEEP-1)] = the change seq
static evring g_ev_host;        // this copy's own character: what this copy records and sends
static DWORD g_ev_last_tag, g_ev_last_val;
static DWORD g_ev_tag, g_ev_applied;   // receiver: the character, and the last sequence number replayed
static volatile LONG g_ev_rec, g_ev_rep;

static void host_record_state(DWORD tag, DWORD st)
{
	if (tag != g_ev_last_tag) {   // another character (a respawn, a rebuilt party): start its own history
		g_ev_last_tag = tag;
		g_ev_last_val = st;
		return;
	}
	if (st == g_ev_last_val)
		return;
	LONG n = InterlockedIncrement(&g_ev_host.seq);
	g_ev_host.val[n & (EV_KEEP - 1)] = st;
	g_ev_last_val = st;
	InterlockedIncrement(&g_ev_rec);
}

// The states a puppet may run. Locomotion is the game's own movement-machine set (0 idle, 1 walk, 2 run,
// 4 sprint - decompile 142018..142075); the action states are the ones the state setter FUN_004e3ed0 has
// explicit cases for and a human reaches in normal play (aim 100/0x65/0x66/0xc9, swing 200, charged 300,
// the combat family 500/600/700, the interaction family 0x12d/0x12e/0x12f, death 5). Anything else keeps
// the state the puppet already has and is named once in the log (Obscure 1 `puppet_state_ok`).
static int puppet_state_ok(DWORD st)
{
	switch (st) {
	case 0: case 1: case 2: case 4:              // idle, walk, run, sprint
	case 5:                                      // death
	case 100: case 0x65: case 0x66: case 0xc9:   // aim stance and its variants
	case 200: case 300:                          // swing, charged/special attack
	case 500: case 600: case 700:                // the combat/stance family of the setter
	case 0x12d: case 0x12e: case 0x12f:          // use/interaction family (FINDINGS_29 section 2)
		return 1;
	}
	static DWORD logged[32];
	for (int i = 0; i < 32; i++) {
		if (logged[i] == st)
			return 0;
		if (!logged[i]) {
			logged[i] = st;
			logf("puppet: state %lu is not on the safe list (the puppet holds its pose)", (unsigned long)st);
			return 0;
		}
	}
	return 0;
}

// The locomotion states: the ones where the game's own movement/state machine may run on the puppet. The
// machine's action paths need local context this copy does not have (the swing reads the attack target
// list +0x820/+0x824, FINDINGS_44 section 3), so those keep TASK 42's gate.
static int puppet_locomotion(DWORD st)
{
	return st == 0 || st == 1 || st == 2 || st == 4;
}

// The aim-stance family: the owner keeps walking/strafing while the upper body aims, and its LOWER-BODY
// layer then follows the direction (+0x224 = LWAF/LWAL/LWAB - measured on HEAD). That layer is the only
// thing this copy has to drive itself in these states (puppet_gait); the state and the upper clip stay
// with the game's own setter (puppet_anim) and the movement machine stays gated, as TASK 42 left it.
static int puppet_aim(DWORD st)
{
	return st == 100 || st == 0x65 || st == 0x66;
}

// Which state the owner is in at the playback instant, replaying a state change that arrived since the
// last update (one per update, in order). A state outside the safe list keeps the puppet where it is.
static DWORD puppet_wanted(unsigned ch, const psample *s)
{
	DWORD tag = rd32(ch + H_TAG);
	if (tag != g_ev_tag) {   // another character: start from now, do not replay history
		g_ev_tag = tag;
		g_ev_applied = s->ev_seq;
	}
	DWORD want = s->anim;    // the state at the playback instant (TASK 42's value)
	if (s->ev_seq != g_ev_applied && (LONG)(s->ev_seq - g_ev_applied) < 64) {
		DWORD next = g_ev_applied + 1;
		if ((LONG)(s->ev_seq - next) >= EV_KEEP)   // more than four behind: skip to the oldest still known
			next = s->ev_seq - (EV_KEEP - 1);
		want = s->ev_val[next & (EV_KEEP - 1)];
		g_ev_applied = next;
		InterlockedIncrement(&g_ev_rep);
	}
	if (!puppet_state_ok(want))
		return rd32(ch + 0x2dc);   // hold: not a state a puppet may run
	return want;
}

// Called before the game's own character update for every human: is this the puppet, and if so put it in
// the pose/state the owner has. Returns 1 when the update must be completed by puppet_finish.
static void puppet_ui(unsigned ch, const psample *s);
static int puppet_prepare(unsigned ch)
{
	if (ch != puppet_target())
		return 0;
	psample s;
	if (!puppet_pose(&s)) {
		InterlockedIncrement(&g_pb_nosample);
		return 0;
	}
	DWORD want = puppet_wanted(ch, &s);
	DWORD cur = rd32(ch + 0x2dc);
	if (puppet_locomotion(want) && puppet_locomotion(cur)) {
		// TASK 46: a locomotion state is the MOVEMENT MACHINE's job. Its request field +0x2e8 gets the
		// owner's state; the machine (let through by hk_char_move) picks the gait from the streamed speed
		// and drives the lower-body animation layer +0x224 from the streamed intent direction. Calling the
		// state setter here too would race the machine's own transition.
		if (!IsBadWritePtr((void *)(uintptr_t)(ch + 0x2e8), 4))
			*(DWORD *)(uintptr_t)(ch + 0x2e8) = want;
	} else {
		// an action state (the aim stance included - its machine path is the one TASK 42 gated), or the
		// way back from one: the game's own state setter
		puppet_anim(ch, want);
		puppet_gait(ch, &s);   // ... and its lower-body layer follows the owner's gait
	}
	puppet_write(ch, &s, 1);   // TASK 45: through SetPosition, so the collision body follows
	puppet_ui(ch, &s);
	return 1;
}

// TASK 43: the owner's per-player UI on the other copy. The weapon wheel and the item menu are the
// CHARACTER'S OWN controller state (controller+0xa4 = 3 / 4, FINDINGS_36 section 4) and the controller
// update (FUN_004cf940) ends by publishing them to the HUD:
//     FUN_00552360(character, ui == 3);      // the weapon wheel of that player
//     FUN_00551b70(character, world+0x1790, ui == 4);   // the shared item panel, arbitrated by the game
// (decompile 126846/126847). The puppet's controller does not run any more (TASK 42), so the owner
// streams the state and this copy makes the same two game calls for the puppet's character: the wheel
// panel is per player (HUD+0x88 / +0x8c) and the game itself arbitrates the shared item panel (HUD+0x90).
// The selected weapon slot (character+0x714, the wheel's selection) is mirrored as the plain int it is.
typedef void(__fastcall *hud_wheel_t)(void *, void *, void *, int);
typedef void(__fastcall *hud_items_t)(void *, void *, void *, unsigned, int);
static DWORD g_puppet_ui_done_tag, g_puppet_ui_done;
static volatile LONG g_puppet_ui_sets;

static void puppet_ui(unsigned ch, const psample *s)
{
	unsigned ctl = rd32(ch + 8);
	if (!ctl || IsBadWritePtr((void *)(uintptr_t)(ctl + 0xa4), 4))
		return;
	unsigned want = s->ui & 7;
	if (!IsBadWritePtr((void *)(uintptr_t)(ch + 0x714), 4) && s->wsel < 8)
		*(DWORD *)(uintptr_t)(ch + 0x714) = s->wsel;   // the wheel's selection (a plain int)
	if (rd32(ctl + 0xa4) != want)
		*(DWORD *)(uintptr_t)(ctl + 0xa4) = want;
	// The two HUD calls, only when the state changes (the panel keeps its state between frames). ECX is the
	// HUD manager (game+0x470: +0x88 / +0x8c are the two players' wheel panels and +0x90 the shared item
	// panel - FUN_00552440 reads the same object, decompile 206560), the character is the first argument,
	// exactly as FUN_004cf940 calls them (126846/126847).
	DWORD tag = rd32(ch + H_TAG);
	if (g_puppet_ui_done_tag == tag && g_puppet_ui_done == want)
		return;
	unsigned g = game_obj();
	unsigned hud = g && mem_ok((const void *)(uintptr_t)(g + 0x470), 4) ? rd32(g + 0x470) : 0;
	if (!hud) {   // the world keeps the same object (world+0x17a0 = game+0x470, decompile 109388)
		unsigned w = world_obj();
		hud = w && mem_ok((const void *)(uintptr_t)(w + 0x17a0), 4) ? rd32(w + 0x17a0) : 0;
	}
	if (!hud || IsBadReadPtr((const void *)(uintptr_t)hud, 0x94) || !code_in_exe(0x552360) || !code_in_exe(0x551b70))
		return;
	unsigned w = world_obj();
	unsigned inv = w ? rd32(w + 0x1790) : 0;
	((hud_wheel_t)0x552360)((void *)(uintptr_t)hud, NULL, (void *)(uintptr_t)ch, want == 3);
	((hud_items_t)0x551b70)((void *)(uintptr_t)hud, NULL, (void *)(uintptr_t)ch, inv, want == 4);
	g_puppet_ui_done_tag = tag;
	g_puppet_ui_done = want;
	InterlockedIncrement(&g_puppet_ui_sets);
}

// Called after the game's own character update: the update may have moved the puppet or changed its
// state. The owner's values win; the state field is put back WITHOUT the setter (the clip that is
// playing is the right one - the setter would restart it every frame).
static void puppet_finish(unsigned ch)
{
	psample s;
	if (!puppet_pose(&s))
		return;
	float *pos = (float *)(uintptr_t)(ch + H_POS);
	float dx = s.pos[0] - pos[0], dy = s.pos[1] - pos[1], dz = s.pos[2] - pos[2];
	float err = sqrtf(dx * dx + dy * dy + dz * dz);
	g_pb_err_sum += err;
	if (err > g_pb_err_max) g_pb_err_max = err;
	InterlockedIncrement(&g_pb_err_n);
	if (err > 1.0f) {
		// TASK 44 diagnostic: WHAT the game's own update did to the puppet between our write of the pose
		// and this point. Once a second, so a link that makes the game drag the character is visible in
		// the log without swamping it.
		static DWORD last_drift;
		DWORD now = GetTickCount();
		if (now - last_drift >= 1000) {
			char tg[5];
			float *vel = (float *)(uintptr_t)(ch + 0x294);
			last_drift = now;
			float sl0 = 0, sl1 = 0, sl2 = 0, pt0 = 0, pt1 = 0, pt2 = 0;
			int ns;
			EnterCriticalSection(&g_pb_cs);
			ns = g_pb_n;
			if (ns > 0) {
				const psample *L = &g_pb[ns - 1];
				sl0 = L->pos[0]; sl1 = L->pos[1]; sl2 = L->pos[2];
				if (ns > 1) {
					const psample *P = &g_pb[ns - 2];
					pt0 = P->pos[0]; pt1 = P->pos[1]; pt2 = P->pos[2];
				}
			}
			LeaveCriticalSection(&g_pb_cs);
			// TASK 45: the COLLISION BODY (human+0x30c, position +0xcc) next to the pose, so a log shows
			// whether the body follows the streamed position (it did not before this task: it stayed at
			// the place the character was built).
			unsigned imp = rd32(ch + 0x30c), ib = imp && mem_ok((const void *)(uintptr_t)imp, 0x100) ? imp : 0;
			float bx = 0, by = 0, bz = 0;
			if (ib) {
				bx = *(float *)(uintptr_t)(ib + 0xcc);
				by = *(float *)(uintptr_t)(ib + 0xd0);
				bz = *(float *)(uintptr_t)(ib + 0xd4);
			}
			logf("puppet drift %s: %.2f units; pose %.1f,%.1f,%.1f char %.1f,%.1f,%.1f body %.1f,%.1f,%.1f"
			     " state %u vel %.1f,%.1f,%.1f | buffered %d newest %.1f,%.1f,%.1f prev %.1f,%.1f,%.1f",
			     tag4(rd32(ch + H_TAG), tg), err, s.pos[0], s.pos[1], s.pos[2], pos[0], pos[1], pos[2],
			     bx, by, bz, rd32(ch + 0x2dc), vel[0], vel[1], vel[2], ns, sl0, sl1, sl2, pt0, pt1, pt2);
		}
	}
	if (err > 0.05f)
		InterlockedIncrement(&g_char_snaps);
	puppet_write(ch, &s, 0);
	if (!IsBadWritePtr((void *)(uintptr_t)(ch + 0x2dc), 4)) {
		if (puppet_locomotion(s.anim)) {
			// TASK 46: the movement machine owns the locomotion states on the puppet (it picks the gait
			// from the streamed speed); leave the state it chose.
		} else if (rd32(ch + 0x2dc) == s.anim) {
			InterlockedIncrement(&g_pb_anim_ok);
		} else {
			*(DWORD *)(uintptr_t)(ch + 0x2dc) = s.anim;   // the game's own update moved it: the owner wins
			InterlockedIncrement(&g_pb_anim_diff);
		}
	}
	InterlockedIncrement(&g_char_applied);
}

// Is this character the peer's puppet for the purpose of the CONTROLLER gate? Structural conditions only:
// the tag the peer streams, the game mode and the world state (normal play). The pose guards (level,
// controller wiring, animation system) are deliberately NOT part of it - when one of them fails for a
// moment, the character must stay gated, not be handed back to the game's own input, which walks it (that
// is the TASK 42 D-phase dropout: the refused puppet was driven by the game's controller).
static int puppet_active(unsigned ch)
{
	if (!ch || ch != puppet_identity())
		return 0;
	unsigned g = game_obj();
	if (!g || !mem_ok((const void *)(uintptr_t)g, 0x380) || rd32(g + 0x310) != 1)
		return 0;
	unsigned w = rd32(g + 0x378);
	if (!w || !mem_ok((const void *)(uintptr_t)w, 0x1800) || rd32(w + 0x11c) != 1)
		return 0;
	return 1;
}

// Is this character the puppet (used by the input hook to leave its controller alone)?
static int puppet_is(unsigned ch)
{
	return puppet_active(ch);
}

// TASK 46: may the game's own movement/state machine run for this character this frame? Only in the
// locomotion states - the machine's action paths need local context this copy does not have (the swing
// reads the attack target list +0x820/+0x824, FINDINGS_44 section 3). Elsewhere TASK 42's gate stays.
static int puppet_move_ok(unsigned ch)
{
	return ch && puppet_locomotion(rd32(ch + 0x2dc));
}

// TASK 46: is this the character THIS copy owns (the one it streams, see char_send_local)? Its state
// changes are what the peer replays - the host side of Obscure 1's `host_record_wanted`.
static int own_char(unsigned ch)
{
	return g_role && ch && ch == player_human(g_role == 1 ? 0 : 1);
}

// ---- each copy streams the character its own pad drives -------------------------------------------
// TASK 42: 16 ms = 60 Hz, called from the transport thread (net.c net_tick), so the rate does not depend
// on the frame rate; the receiver interpolates it.
static void char_send_local(void)
{
	if (!g_role || !g_peer_ok)
		return;
	if (scene_local_cinematic())
		return;   // TASK 30: in a scripted event the script owns this character; do not stream it as pad-driven
	static DWORD last;
	DWORD now = GetTickCount();
	if (now - last < 16)
		return;
	last = now;
	unsigned w = world_obj();
	unsigned me = player_human(g_role == 1 ? 0 : 1);
	if (!w || !me || IsBadReadPtr((const void *)(uintptr_t)me, 0x330))
		return;
	pkt_char p;
	memset(&p, 0, sizeof p);
	p.t_ms = timeline_now();
	p.level = rd32(w + 4);
	p.me.tag = rd32(me + H_TAG);
	memcpy(p.me.pos, (const void *)(uintptr_t)(me + H_POS), 12);
	memcpy(p.me.dir, (const void *)(uintptr_t)(me + H_DIR), 12);
	memcpy(p.vel, (const void *)(uintptr_t)(me + 0x294), 12);
	p.speed = rd32(me + 0x278);
	p.me.anim = rd32(me + 0x2dc);
	p.me.life = rd32(me + 0x320);
	// TASK 46: the move intent (character+0x288, written by the owner's input controller through vtable
	// slot 0x60) and the owner's state-change events. The receiver writes the intent into the puppet and
	// lets the game's own movement machine run, so the gait and the lower-body layer follow the owner.
	memcpy(p.intent, (const void *)(uintptr_t)(me + 0x288), sizeof p.intent);
	p.wanted = rd32(me + 0x2dc);
	p.gait = rd32(me + 0x2e0);
	p.ev_seq = (DWORD)g_ev_host.seq;
	for (int i = 0; i < EV_KEEP; i++)
		p.ev_val[i] = g_ev_host.val[i];
	// TASK 43: the owner's per-player UI (the wheel / item menu / aim state) and the selected slot, so the
	// other copy shows what this player is doing (the puppet's own controller no longer runs there).
	{
		unsigned ctl = rd32(me + 8);
		p.ui = ctl && mem_ok((const void *)(uintptr_t)(ctl + 0xa4), 4) ? rd32(ctl + 0xa4) : 0;
		p.wsel = rd32(me + 0x714);
	}
	net_send(PKT_CHAR, &p, (WORD)(sizeof p - sizeof(pkt_hdr)));
	InterlockedIncrement(&g_char_sent);
}


// ---- guest: the host's authoritative level (TASK 37) --------------------------------------------
// The split case this task fixes: the host announced a transition its game did not perform (the door
// line 0.7 s before a pipe load: the load's world was never built on the host), or two transitions
// raced and the two games applied them in a different order - so the copies ended in different levels
// and nothing compared them again. The host streams the level the party is in (pkt_state.host_level /
// host_entry / host_busy / host_seq); if this copy is in another level for LVL_HEAL_MS while BOTH
// copies are idle, it performs the host's level change through the same ChangeLevel call the
// late-join path uses (guest_level_heal, near frame_tick).
static volatile LONG g_host_lvl, g_host_entry, g_host_busy, g_host_seq;
static volatile DWORD g_host_lvl_at;
static DWORD g_lvl_mismatch_since;
static int g_heal_tries;                     // heals without the copies agreeing (a bounded retry)
static volatile LONG g_heals;                // levels re-converged because the host was in another one
#define LVL_HEAL_MS 3000                     // the mismatch must persist this long with both copies idle
#define LVL_HEAL_FRESH_MS 1000               // the host's statement must be this recent

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
	// TASK 37: the host's authoritative level, for the guest's self-heal (guest_level_heal, game thread).
	if (st->host_level) {
		g_host_lvl = (LONG)st->host_level;
		g_host_entry = (LONG)st->host_entry;
		g_host_busy = (LONG)st->host_busy;
		g_host_seq = (LONG)st->host_seq;
		g_host_lvl_at = GetTickCount();
	}
	InterlockedIncrement(&g_rcv_states);
}


// ---- guest: where the characters were, to compare a snapshot with the right moment -----------------------------------
// A snapshot says where the host's character was at host time T. The guest's character is now further along its path,
// so comparing the two directly would pull it backwards by speed x delay. Compare against the guest's own position at
// T instead (history, interpolated) and move the current position by that error.
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

// TASK 37: a transition is never started on top of one that is still in flight. A load is a transition
// too (it rebuilds the world), so it waits until the game has no request pending and the level it holds
// has been stable for LOAD_SETTLE_MS. Without this the game can apply a load and a change-level of its own
// in either order - the copies then end in different levels (the soak's door 0.7 s before a pipe load).
#define LOAD_SETTLE_MS 700
static DWORD g_game_busy_at, g_level_seen_at, g_level_seen_tag;

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
	{   // TASK 37: wait for this copy's own game to be idle and settled (see LOAD_SETTLE_MS above) -
		// but only INSIDE a level. At the main menu game+0x320 holds the menu request state (9), which is
		// normal there; gating on it would hold a joining guest's load at the menu.
		if (rd32(game + 0x310) == 1) {
			DWORD req = rd32(game + 0x320);
			unsigned gw = rd32(game + 0x378), gl = gw ? rd32(gw + 4) : 0;
			if (req)
				g_game_busy_at = now;
			if (gl && gl != g_level_seen_tag) {
				g_level_seen_tag = gl;
				g_level_seen_at = now;
			}
			int busy = req || (g_game_busy_at && now - g_game_busy_at < LOAD_SETTLE_MS) ||
			           (g_level_seen_at && now - g_level_seen_at < LOAD_SETTLE_MS);
			if (busy) {
				static DWORD logged;
				if ((LONG)(now - at) < LOAD_WAIT_MS) {
					if (!logged || now - logged > 2000) {
						logged = now;
						logf("%s: real load of \"%s\" (%s) waits for this copy's transition to finish (state %u, %u ms since the level %08x)",
							g_role == 2 ? "guest" : "host", name, src, req,
							(unsigned)(g_level_seen_at ? now - g_level_seen_at : 0), (unsigned)g_level_seen_tag);
					}
					return;   // keep the request pending
				}
				logf("%s: real load of \"%s\" (%s) given up after %u ms: this copy never became idle",
					g_role == 2 ? "guest" : "host", name, src, now - at);
				InterlockedExchange(&g_rload_want, 0);
				if (g_role == 2 && !strcmp(src, "host"))
					guest_load_failed(name);   // TASK 37: let the host's repeat be applied again
				return;
			}
		}
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
		if (wp && vt && image_ptr(vt) && show && !IsBadReadPtr((const void *)(uintptr_t)show, 1) && code_in_exe(show)) {
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
	// TASK 30: the battery/energy the host's copy has (a story EnergySet, or the usual drain) is host-owned.
	if (st.energy_valid) {
		unsigned inv = rd32(w + 0x1790);
		if (inv && !IsBadWritePtr((void *)(uintptr_t)(inv + INV_ENERGY), 4)) {
			float cur;
			memcpy(&cur, (const void *)(uintptr_t)(inv + INV_ENERGY), 4);
			float d = cur - st.energy;
			if (d > 0.01f || d < -0.01f) {
				memcpy((void *)(uintptr_t)(inv + INV_ENERGY), &st.energy, 4);
				InterlockedIncrement(&g_energy_sets);
			}
		}
	}
	for (int i = 0; i < (int)st.n && i < MAX_CH; i++) {
		for (int k = 0; k < n; k++) {
			if (rd32(hs[k] + H_TAG) != st.ch[i].tag)
				continue;
			float *pos = (float *)(uintptr_t)(hs[k] + H_POS), *dir = (float *)(uintptr_t)(hs[k] + H_DIR);
			if (IsBadWritePtr(pos, 12) || IsBadWritePtr(dir, 12))
				break;
			// TASK 35: a life change that does not arrive used to be invisible. These two lines make it
			// visible: one when the host's value differs from this copy's (the write below), one when the
			// game takes the value back afterwards (something else owns life on this copy).
			{
				static struct { DWORD tag, wrote, at; } lw[8];
				float local;
				memcpy(&local, (const void *)(uintptr_t)(hs[k] + 0x320), 4);
				float incoming;
				memcpy(&incoming, &st.ch[i].life, 4);
				int slot = -1;
				for (int z = 0; z < 8; z++)
					if (lw[z].tag == st.ch[i].tag) { slot = z; break; }
				for (int z = 0; z < 8 && slot < 0; z++)
					if (!lw[z].tag) slot = z;
				if (slot >= 0) {
					DWORD nowm = GetTickCount();
					float was;
					memcpy(&was, &lw[slot].wrote, 4);
					if (lw[slot].tag && lw[slot].at && nowm - lw[slot].at < 3000 &&
					    (local - was > 0.5f || local - was < -0.5f) && (local - incoming > 0.5f || local - incoming < -0.5f)) {
						char c[5];
						logf("guest: %s life came back to %.1f after the host's %.1f: the game owns it here",
						     tag4(st.ch[i].tag, c), local, was);
					}
					if (local - incoming > 0.5f || local - incoming < -0.5f) {
						if (!lw[slot].at || nowm - lw[slot].at > 1000 || lw[slot].wrote != st.ch[i].life) {
							char c[5];
							logf("guest: writing the host's life for %s: local %.1f -> %.1f", tag4(st.ch[i].tag, c),
							     local, incoming);
						}
						lw[slot].tag = st.ch[i].tag;
						lw[slot].wrote = st.ch[i].life;
						lw[slot].at = nowm;
					}
				}
			}
			*(DWORD *)(uintptr_t)(hs[k] + 0x320) = st.ch[i].life;   // health stays host-owned (damage is applied there)
			// TASK 42: no position, facing or animation correction here any more. Each copy owns its own
			// character and the peer's character is a puppet driven by PKT_CHAR (see the puppet block
			// above); a snapshot is one link delay old, and pulling a character towards it is exactly the
			// correction that made the remote character slide and the two games disagree.
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
static volatile LONG g_npc_life, g_npc_dead, g_npc_state;   // TASK 21: life writes, deaths, state writes on the guest

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
		p.npc[i].life = rd32(hs[i] + 0x320);   // TASK 21: the host owns the enemy's life
		p.npc[i].state = rd32(hs[i] + 0x2dc);  // ... and its AI/death state
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
		// TASK 21: the host owns enemy life and death. Apply only the *difference* through the game's own
		// life method (character vtable slot 9 = +0x24, the method CharacterSetLife uses), so a hit both
		// copies simulated nets one subtraction (the difference is then 0) and crossing 0 runs the game's
		// own death path (FUN_004f5bf0 -> state 3). The host's death state (+0x2dc) is copied with it.
		// TASK 23 test switch: the pipe command `npclife 0` turns this off, so a run can show whether the
		// copies drift apart without it (the position part above stays on either way).
		if (g_npc_life_on) {
			float *gl = (float *)(uintptr_t)(hs[best] + 0x320);
			DWORD *gst = (DWORD *)(uintptr_t)(hs[best] + 0x2dc);
			if (!IsBadWritePtr(gl, 4) && !IsBadWritePtr(gst, 4)) {
				float hl = *(const float *)&st.npc[i].life;
				float dlt = hl - *gl;
				if (dlt > 0.01f || dlt < -0.01f) {
					void **vt = *(void ***)(uintptr_t)hs[best];
					if (vt && image_ptr((DWORD)(uintptr_t)vt) && vt[9] && !IsBadCodePtr((FARPROC)vt[9])) {
						((void(__thiscall *)(void *, float))vt[9])((void *)(uintptr_t)hs[best], hl - *gl);
						InterlockedIncrement(&g_npc_life);
						if (hl <= 0.0f)
							InterlockedIncrement(&g_npc_dead);
					}
				}
				if (hl <= 0.0f && *gst != st.npc[i].state) {
					*gst = st.npc[i].state;   // same death/animation state on both copies
					InterlockedIncrement(&g_npc_state);
				}
			}
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
static DWORD g_req_rep_seq;               // TASK 37: the transition sequence this repeat belongs to

static void host_level_request_repeat(unsigned level, unsigned entry, unsigned flag, DWORD seq)
{
	DWORD now = GetTickCount();
	g_req_rep_level = level;
	g_req_rep_entry = entry;
	g_req_rep_flag = flag;
	g_req_rep_kind = REQ_LEVEL;
	g_req_rep_seq = seq;
	g_req_rep_until = now + REQ_REPEAT_FOR;
	g_req_rep_at = now;
}

static void host_load_request_repeat(const char *name, DWORD seq)
{
	DWORD now = GetTickCount();
	_snprintf(g_req_rep_name, sizeof g_req_rep_name, "%s", name ? name : "");
	g_req_rep_kind = REQ_LOAD_NAME;
	g_req_rep_seq = seq;
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
		net_send_req(REQ_LOAD_NAME, 0, 0, 0, g_req_rep_name, g_req_rep_seq);
		InterlockedIncrement(&g_req_sent);
		return;
	}
	host_send_progress(1);   // the party table must reach the guest before the level change it belongs to
	net_send_req(REQ_LEVEL, g_req_rep_level, g_req_rep_entry, g_req_rep_flag, NULL, g_req_rep_seq);
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
		DWORD seq = host_trans_next();
		net_send_req(REQ_LEVEL, lvl, entry, 1, NULL, seq);
		InterlockedIncrement(&g_req_sent);
		host_level_request_repeat(lvl, entry, 1, seq);
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
	// TASK 25: the guest was already in our level when the link dropped - a reconnect, not a join. There is
	// nothing to load or change: the progress block above and the state stream bring it back in step, and a
	// level/load request here would rebuild the world (and lose the characters' positions) for nothing.
	if (g_hello_in_level && g_hello_level && g_hello_level == g_last_level) {
		char lv[5];
		logf("join: the guest is already in level %s: resuming without a level or save request", tag4(g_hello_level, lv));
		return;
	}
	if (lname[0]) {
		// The host is already inside a save it loaded (possibly before this guest existed): the guest must
		// load that file itself, exactly as it would if the load happened now (CASE 1). No REQ_LEVEL: the
		// file builds that world, and a level request would only sit in the guest's queue behind the load.
		logf("join: the host is in a load of \"%s\"; asking the guest to load that file itself", lname);
		DWORD seq = host_trans_next();
		net_send_req(REQ_LOAD_NAME, 0, 0, 0, lname, seq);
		InterlockedIncrement(&g_req_sent);
		host_load_request_repeat(lname, seq);
		return;
	}
	// The friend starts their own "New game, Two players" first (that choice decides who controls player 2); the
	// level request waits on the guest until its world exists.
	if (g_last_level) {
		DWORD seq = host_trans_next();
		net_send_req(REQ_LEVEL, g_last_level, g_last_entry, g_last_flag, NULL, seq);
		InterlockedIncrement(&g_req_sent);
		host_level_request_repeat(g_last_level, g_last_entry, g_last_flag, seq);
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
// TASK 37: transitions are ordered by the host's sequence number. g_trans_applied is the newest one this
// copy has performed, g_trans_queued the newest one waiting; an older request is never applied (it would
// undo a newer transition), and a newer request cancels the older ones still queued.
static DWORD g_trans_applied, g_trans_queued;
static DWORD g_ln_seq;                // the sequence of the load request this copy took (for a retry)
static volatile LONG g_trans_stale;   // requests dropped because a newer transition exists

static int req_is_transition(DWORD kind)
{
	return kind == REQ_LEVEL || kind == REQ_LOAD_NAME || kind == REQ_LOAD_PROGRESS;
}

// The game refused to open the file this load named (a half-written file, or a name it does not accept).
// Forget the "already taken" mark, so the host's repeat of the same request is executed again instead of
// being dropped as a duplicate for REQ_LOAD_DONE_MS.
static void guest_load_failed(const char *name)
{
	EnterCriticalSection(&g_req_cs);
	if (!strncmp(g_ln_done_name, name, sizeof g_ln_done_name))
		g_ln_done_at = 0;
	// TASK 37: the sequence ordering must not swallow the retry. This load was marked as the newest applied
	// transition when it was taken; step the marks back to just below it, so the host's repeat of the same
	// request (same seq) is accepted and tried again instead of being dropped as a duplicate.
	if (g_ln_seq) {
		if (g_trans_applied == g_ln_seq)
			g_trans_applied = g_ln_seq - 1;
		if (g_trans_queued == g_ln_seq)
			g_trans_queued = g_ln_seq - 1;
	}
	LeaveCriticalSection(&g_req_cs);
}

static void guest_on_req(const char *buf, int n)
{
	if (n != (int)sizeof(pkt_req))
		return;
	const pkt_req *r = (const pkt_req *)buf;
	DWORD now = GetTickCount();
	EnterCriticalSection(&g_req_cs);
	if (r->seq && req_is_transition(r->kind)) {
		// TASK 37: only the newest transition counts. A repeat of the one already applied or queued is a
		// duplicate; one OLDER than either would undo a newer transition and is dropped; a NEWER one cancels
		// whatever older transitions are still queued, so nothing is ever applied half.
		if (g_trans_applied && r->seq + 16 < g_trans_applied) {
			// The host's counter is far below ours: it was restarted (the host's game relaunched and
			// reconnected to this guest). Start counting again instead of dropping everything.
			logf("guest: the host's transition counter restarted (%lu < %lu): counting from its values again",
			     (unsigned long)r->seq, (unsigned long)g_trans_applied);
			g_trans_applied = g_trans_queued = 0;
		}
		if (r->seq <= g_trans_applied || r->seq <= g_trans_queued) {
			LeaveCriticalSection(&g_req_cs);
			InterlockedIncrement(&g_trans_stale);
			return;
		}
		for (int i = g_req_head; i != g_req_tail; i = (i + 1) & 7) {
			if (req_is_transition(g_req_q[i].kind) && g_req_q[i].seq < r->seq) {
				char lv[5], nm[sizeof g_req_q[i].name];
				DWORD k = g_req_q[i].kind, lvl = g_req_q[i].a, old = g_req_q[i].seq;
				memcpy(nm, g_req_q[i].name, sizeof nm);
				nm[sizeof nm - 1] = 0;
				g_req_q[i].kind = 0;   // cancelled: a newer transition replaces it (skipped in apply)
				logf("guest: transition %lu (%s %s) cancelled: transition %lu is newer", (unsigned long)old,
				     k == REQ_LEVEL ? "level" : k == REQ_LOAD_NAME ? "load" : "progress",
				     k == REQ_LEVEL ? tag4(lvl, lv) : nm, (unsigned long)r->seq);
			}
		}
		g_trans_queued = r->seq;
	}
	if (r->kind == REQ_LEVEL) {
		// The host repeats a level request because PKT_REQ is not reliable: skip the copies (one already
		// waiting in the queue, or one applied a moment ago) so the guest changes level once.
		if (g_lvl_req_done_at && !r->seq && r->a == g_lvl_req_done_a && r->b == g_lvl_req_done_b &&
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
		if (g_ln_done_at && !r->seq && !strncmp(r->name, g_ln_done_name, sizeof g_ln_done_name) &&
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
		if (r.kind == 0) {   // TASK 37: cancelled by a newer transition
			g_req_head = (g_req_head + 1) & 7;
			LeaveCriticalSection(&g_req_cs);
			continue;
		}
		if (r.kind == REQ_LEVEL) {   // a joining guest may still be loading: keep the request until its world exists
			unsigned g0 = game_obj();
			if (!g0 || rd32(g0 + 0x310) != 1 || rd32(g0 + 0x320) != 0 || !world_obj()) {
				g_req_seen[g_req_head] = GetTickCount();   // the party wait starts when the guest can act
				LeaveCriticalSection(&g_req_cs);
				return;
			}
			waited = GetTickCount() - seen;
			// TASK 34: this copy's own door animation is still running (it reaches its ChangeLevel when it
			// ends, which clears the flag). Rebuilding the world now would cut the animation the owner saw
			// cut when the host's request arrived first. Keep the request queued; the door guard is short.
			if (g_role == 2 && door_animation_running()) {
				static DWORD logged;
				LeaveCriticalSection(&g_req_cs);
				if (!logged || GetTickCount() - logged > 3000) {
					logged = GetTickCount();
					char lv[5];
					logf("guest: level request %s held until this copy's door animation ends", tag4(r.a, lv));
				}
				return;
			}
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
		if (r.seq && req_is_transition(r.kind) && r.seq > g_trans_applied)
			g_trans_applied = r.seq;   // TASK 37: an older transition can never be applied after this one
		if (r.kind == REQ_LOAD_NAME)
			g_ln_seq = r.seq;          // TASK 37: the seq this load owns, so a failure can re-open it
		if (r.kind == REQ_LEVEL) {   // remember it: the host's repeats of this one are dropped
			g_lvl_req_done_a = r.a;
			g_lvl_req_done_b = r.b;
			g_lvl_req_done_at = GetTickCount();
			// TASK 34: the rebuilt world may ask "player 2 is joining"; accept it on this copy too (the
			// pulse is added to both served pads in XInputGetState for 150 ms, 4.5 s from now).
			g_accept_at = GetTickCount() + 4500;
			g_accept_until = g_accept_at + 150;
			logf("join dialog: auto-accept pulse in 4.5 s (this copy's pads)");
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
	if (scene_local_cinematic())
		return;   // TASK 30: a scripted event owns the camera on this copy; do not pull it to the player
	((void(__fastcall *)(void *, void *, unsigned))0x530960)((void *)(uintptr_t)cam, NULL, me);
	InterlockedIncrement(&g_cam_sets);
}


// ---- scripted events: cutscenes, FMV/kine, scripted camera, dialogs (TASK 30) ------------------------
// The world keeps a scripted-event state machine (FINDINGS_30 §2): world+0x11c is the level state
// (1 normal, 5 pause menu, 6 cinematic presentation, 0x11 game over) and world+0x12c the scene playback
// kind (0 none, 6 kine, 7, 8 noe scene, 0xd). A cutscene, an FMV, a scripted camera and a story scene all
// go through these two fields, and every one of them ends with the same LOCAL input: the skip (ESCAPE,
// START or A). The mod therefore never writes them. It mirrors them across the link (PKT_SCENE) and, when
// the peer's copy has left a scene this copy is still in, presses the game's own skip here, so the game's
// own exit path (and its cleanup) always runs. Decided policy: either player may skip; a skip by either
// player skips on both.
#define W_STATE 0x11c
#define W_SCENE 0x12c
#define W_FLAGS 0x130
#define W_SA 0x138
#define W_SB 0x13c
#define W_SD 0x118
#define W_NAME 0x140   // a noe scene's name string (FUN_004b2890 copies it here)

static DWORD g_scene_enter_tick;
static DWORD g_leave_seq;      // this copy's leaves of a scripted event (sent as pkt_scene.leave_seq)
static DWORD g_leave_t0;       // when this copy last left a scripted event
// TASK 34: no skip within this window after the world was rebuilt. A level change tears the world down
// and builds a new one; pressing the cinematic skip (ESCAPE) while the game is still settling opens the
// pause menu instead of skipping, which is the guest's "it pauses by itself when we change location".
static DWORD g_scene_guard_until;
static DWORD g_scene_guard_level;

// TASK 31: the leave is an event, not a state to compare. The leaving copy repeats it for a few seconds
// (and only while the peer still reports a scripted event at the same level), the receiver arms a pending
// skip the moment it arrives and keeps it while its own scene has not left, and the skip ladder is
// repeated - the game can ignore the first press, and a receiver may still be loading into the scene.
#define SCENE_LEAVE_RESEND_MS 8000   // how long a leave is repeated while the peer is still in a scene
#define SCENE_PEND_MS 10000          // how long a received leave stays armed here
#define SCENE_SKIP_TRIES 3           // skip ladders per received leave
#define SCENE_SKIP_GAP_MS 1200       // pause between two ladders
#define SCENE_PAD_PULSE_MS 160       // TASK 48: one short A press (the game polls the pad every frame)

typedef struct { DWORD t_ms, level, state, scene, flags, a, b, d, name4, cine; DWORD tick; } scene_info;

// 1 when a state pair means "a scripted event is being presented on this copy". The pause menu (5) and
// the game-over state (0x11) are local states, not scripted events: pausing must not stop or skip the peer.
// TASK 34: a level load leaves world+0x12c holding the previous scene kind while world+0x11c is 0/4, so a
// loading copy used to count as "in a cutscene". Only a level state of 6 (cinematic presentation) or a
// scene kind inside a normal level (state 1) is a real cutscene; anything else is logged but never skipped.
// TASK 48: state 8 is the game's own "found scene" presentation of a picked-up item (a noe scene:
// world+0x140 holds its name, "fs_MEDI" for a medikit - OBSERVED). The level script starts it on BOTH
// copies when an item is collected, it stops the world (the local pad no longer moves the character and a
// frozen picture), and a player leaves it with A on a pad (OBSERVED: host pad A 8 -> 1, guest pad A
// 8 -> 1). It is a shared presentation like a cutscene, so it is mirrored and left together.
static int scene_cinematic(unsigned state, unsigned scene)
{
	if (state == 6 || state == 8)
		return 1;
	return state == 1 && scene != 0;
}

// TASK 34: the game is in a level and no level/load request is pending. A skip is never pressed outside it.
static int scene_in_level_now(void)
{
	unsigned g = game_obj();
	if (!g || rd32(g + 0x310) != 1 || rd32(g + 0x320) != 0)
		return 0;
	unsigned w = world_obj();
	return w && rd32(w + 4) != 0;
}


static void scene_read(scene_info *s)
{
	memset(s, 0, sizeof *s);
	s->tick = GetTickCount();
	unsigned w = world_obj();
	if (!w || IsBadReadPtr((const void *)(uintptr_t)w, W_NAME + 4))
		return;
	s->level = rd32(w + 4);
	s->state = rd32(w + W_STATE);
	s->scene = rd32(w + W_SCENE);
	s->flags = rd32(w + W_FLAGS);
	s->a = rd32(w + W_SA);
	s->b = rd32(w + W_SB);
	s->d = rd32(w + W_SD);
	s->name4 = rd32(w + W_NAME);   // the noe scene's name, 4 bytes ("POSI" etc.): the scene's identity there
	s->cine = (DWORD)scene_cinematic(s->state, s->scene);
}

static int scene_local_cinematic(void)
{
	unsigned w = world_obj();
	if (!w || IsBadReadPtr((const void *)(uintptr_t)w, W_SD + 4))
		return 0;
	return scene_cinematic(rd32(w + W_STATE), rd32(w + W_SCENE));
}

// ---- the peer's copy ------------------------------------------------------------------------------
static CRITICAL_SECTION g_scene_cs;
static scene_info g_peer_scene;
static volatile LONG g_peer_scene_valid;
static DWORD g_peer_last_leave_seq;   // the peer's leave counter this copy has already seen

// TASK 31: "the peer left its scripted event" is armed on the RX thread the moment that packet arrives,
// so a game-thread check a frame later cannot miss it, and it survives until this copy is out too (or
// until the peer is in a scene again / the peer is gone). TASK 30 compared the two copies' scene ids
// instead and dropped the skip when they differed - which they do run to run, because a kine leaves a
// different leftover in world+0x140 on each copy (that was the unreliable part).
static volatile LONG g_pend_active;
static volatile LONG g_pend_gen;      // one per received leave: restarts the skip-attempt counter
static DWORD g_pend_at, g_pend_level, g_pend_a;

// TASK 34: true only for a real cutscene this copy may be asked to leave. A pending skip is carried out
// only through this test, so a skip can never be pressed during a load, in a menu or right after a level
// change (the cases that opened the pause menu and crashed the guest).
static int scene_skippable(void)
{
	scene_info s;
	scene_read(&s);
	if (!s.cine || !s.level)
		return 0;
	if (!scene_in_level_now())
		return 0;
	if ((LONG)(GetTickCount() - g_scene_guard_until) < 0)
		return 0;
	return 1;
}

static void scene_pending_arm(DWORD level, DWORD a, DWORD seq, const char *why)
{
	char lt[8];
	g_pend_level = level;
	g_pend_a = a;
	g_pend_at = GetTickCount();
	g_pend_active = 1;
	InterlockedIncrement(&g_pend_gen);
	logf("scene: %s (peer level %s, id %#x, leave %lu): pending skip armed", why, tag4(level, lt), a,
			(unsigned long)seq);
}

static void peer_on_scene(const char *buf, int n)
{
	const pkt_scene *p = (const pkt_scene *)buf;
	if (n != (int)sizeof *p)
		return;
	DWORD now = GetTickCount();
	int had, was_cine, seq_edge, cine_edge;
	EnterCriticalSection(&g_scene_cs);
	had = g_peer_scene_valid != 0;
	was_cine = had && g_peer_scene.cine != 0;
	// Two ways to see a leave: the peer's leave counter moved (works even when every "in a scene" packet
	// was lost), or its cine flag fell (works with a peer that only streams states).
	seq_edge = had && p->leave_seq != g_peer_last_leave_seq;
	cine_edge = had && was_cine && p->cine == 0;
	g_peer_scene.t_ms = p->t_ms;
	g_peer_scene.level = p->level;
	g_peer_scene.state = p->state;
	g_peer_scene.scene = p->scene;
	g_peer_scene.flags = p->flags;
	g_peer_scene.a = p->a;
	g_peer_scene.b = p->b;
	g_peer_scene.d = p->d;
	g_peer_scene.name4 = p->name4;
	g_peer_scene.cine = p->cine;
	g_peer_scene.tick = now;
	g_peer_last_leave_seq = p->leave_seq;
	g_peer_scene_valid = 1;
	LeaveCriticalSection(&g_scene_cs);
	if (seq_edge || cine_edge)
		scene_pending_arm(p->level, p->a, p->leave_seq, "the peer left a scripted event");
	else if (g_pend_active && p->cine == 0 && p->leave_seq != 0 && p->level == g_pend_level)
		g_pend_at = now;   // the peer is still repeating that leave: keep the pending alive for it
	InterlockedIncrement(&g_scene_rcv);
}

static void scene_send(void)
{
	static DWORD last, sent_state = ~0u, sent_scene = ~0u, sent_a = ~0u;
	static int sent_cine = -1;              // -1: nothing reported yet
	DWORD now = GetTickCount();
	scene_info s;
	scene_read(&s);
	if (!s.level)
		return;
	int cine = s.cine != 0;
	int entered = cine && sent_cine == 0, left = !cine && sent_cine == 1;
	if (sent_cine < 0)
		entered = cine;                 // the first report is not a leave, but "we are in it" is worth a line
	if (left) {
		g_leave_seq++;
		g_leave_t0 = now;
	}
	// Repeat the state while this copy is in a scene, and keep repeating the leave: for a short while
	// unconditionally (the peer may still be loading into its copy of the event) and for longer while the
	// peer still reports a scripted event at this level. One lost packet must not leave the peer behind.
	int peer_in_scene = 0;
	EnterCriticalSection(&g_scene_cs);
	if (g_peer_scene_valid)
		peer_in_scene = g_peer_scene.cine != 0 && g_peer_scene.level == s.level;
	LeaveCriticalSection(&g_scene_cs);
	int changed = s.state != sent_state || s.scene != sent_scene || s.a != sent_a || (unsigned)cine != (unsigned)sent_cine;
	DWORD since_leave = now - g_leave_t0;
	int repeat = cine || since_leave < 1500 || (peer_in_scene && since_leave < SCENE_LEAVE_RESEND_MS);
	if (!changed && (!repeat || now - last < 250))
		return;
	last = now;
	if (entered) {
		char lt[8];
		logf("scene: this copy entered a scripted event (world state %u, scene %u, id %#x, level %s)", s.state, s.scene,
			s.a, tag4(s.level, lt));
		g_scene_enter_tick = now;
	}
	if (left) {
		char lt[8];
		logf("scene: this copy left the scripted event (world state %u, scene %u, level %s) after %u ms; "
			"repeating it until the peer leaves too (leave %lu)", s.state, s.scene, tag4(s.level, lt),
			(unsigned)(now - g_scene_enter_tick), (unsigned long)g_leave_seq);
	}
	pkt_scene p;
	memset(&p, 0, sizeof p);
	p.t_ms = timeline_now();
	p.level = s.level;
	p.state = s.state;
	p.scene = s.scene;
	p.flags = s.flags;
	p.a = s.a;
	p.b = s.b;
	p.d = s.d;
	p.name4 = s.name4;
	p.cine = cine;
	p.leave_seq = g_leave_seq;
	net_send(PKT_SCENE, &p, (WORD)(sizeof p - sizeof(pkt_hdr)));
	InterlockedIncrement(&g_scene_sent);
	sent_state = s.state; sent_scene = s.scene; sent_cine = cine; sent_a = s.a;
}

// ---- the skip ---------------------------------------------------------------------------------------
// Pressed only while this copy is in a real cutscene (scene_skippable). ESCAPE is what the game's own
// cinematic takes (OBSERVED, FINDINGS_30 §5). TASK 34: START and A are NOT tried any more - START is the
// pause key and A the action key, and a skip that lands one frame after the cutscene ended opened the
// guest's pause menu on every location change (the owner's "it pauses by itself"). One short press, held
// ~140 ms, and the release as soon as the copy is out of the scene.
static int g_skip_step;
static DWORD g_skip_t0;
static DWORD g_skip_retry_at;             // a failed ladder: do not start the next one before this tick
static int g_skip_tries;                  // ladders started for the current received leave
static LONG g_skip_gen;                   // the leave (g_pend_gen) those tries belong to

// The keyboard path needs BOTH: g_vkeys feeds the polled key state (DirectInput GetDeviceState, which is
// what the cinematic's own input check reads) and keyq_push feeds the buffered records (menus). The pipe
// `key` command sets both, which is why an ESCAPE sent by a test works; only pushing the queue does not
// move the polled state at all (TASK 30: the first live run's forwarded skip never took because of this).
static void scene_key(int down)
{
	g_vkeys[0x01] = (BYTE)(down ? 1 : 0);
	keyq_push(0x01, down);
}

static void scene_skip_release(void)
{
	scene_key(0);
}

static void scene_skip_begin(const char *why)
{
	if (g_skip_step)
		return;
	DWORD now = GetTickCount();
	LONG gen = g_pend_gen;
	if (g_skip_gen != gen) {   // a new leave: the old attempts do not count against it
		g_skip_gen = gen;
		g_skip_tries = 0;
		g_skip_retry_at = 0;
	}
	if ((LONG)(g_skip_retry_at - now) > 0 || g_skip_tries >= SCENE_SKIP_TRIES)
		return;
	if (!scene_skippable())   // not a real cutscene on this copy: never press a menu/action key here
		return;
	g_skip_tries++;
	scene_info s;
	scene_read(&s);
	{
		char lt[8];
		logf("scene: %s (world state %u, scene %u, id %#x, level %s): pressing the game's own skip here "
			"(attempt %d of %d)", why, s.state, s.scene, s.a, tag4(s.level, lt), g_skip_tries, SCENE_SKIP_TRIES);
	}
	g_skip_step = 1;
	g_skip_t0 = now;
	if (s.state == 8)
		// TASK 48: the found-scene presentation of a pickup ends with A on a pad (OBSERVED), not with the
		// cinematic's ESCAPE. A short pad pulse is the same path the menu corrections already use; it also
		// leaves the keyboard state alone, so it can never open the pause menu.
		menu_pulse_start(0, 0x1000, 0, SCENE_PAD_PULSE_MS);
	else
		scene_key(1);   // ESCAPE down
	InterlockedIncrement(&g_scene_skips);
}

static void scene_skip_frame(void)
{
	if (!g_skip_step)
		return;
	DWORD el = GetTickCount() - g_skip_t0;
	if (!scene_skippable()) {
		// Out of the scene (or the game entered a load / menu): release at once. ESCAPE held into the
		// next state is the pause key, so this release is what keeps a location change from pausing.
		scene_skip_release();
		logf("scene: skip released after %lu ms (the copy is no longer in a scripted event)", (unsigned long)el);
		InterlockedIncrement(&g_scene_left);
		g_skip_step = 0;
		return;
	}
	if (g_skip_step == 1 && el >= 140) { scene_skip_release(); g_skip_step = 2; }
	if (g_skip_step == 2 && el >= 1800) {
		scene_skip_release();
		scene_info s;
		scene_read(&s);
		logf("scene: still in the scripted event after skip attempt %d (world state %u)", g_skip_tries, s.state);
		InterlockedIncrement(&g_scene_stuck);
		g_skip_step = 0;
		g_skip_retry_at = GetTickCount() + SCENE_SKIP_GAP_MS;   // the game may ignore the first press
	}
}

// TASK 34: after the world is rebuilt nothing may press a skip for a moment. Called once per frame from
// scene_tick, both roles: a level tag change (a door, a loading zone, a load) starts the guard.
static void scene_level_guard(void)
{
	unsigned w = world_obj();
	DWORD lvl = 0;
	if (w && !IsBadReadPtr((const void *)(uintptr_t)w, 8))
		lvl = rd32(w + 4);
	DWORD now = GetTickCount();
	if (lvl != g_scene_guard_level) {
		if (g_scene_guard_level) {
			g_scene_guard_until = now + 4000;
			g_pend_active = 0;   // a leave from before the rebuild does not apply to the new world
		}
		g_scene_guard_level = lvl;
	}
	if (!scene_in_level_now() && g_skip_step) {
		scene_skip_release();
		g_skip_step = 0;
	}
}

// Game thread, both roles: mirror this copy's state and leave a scene the peer has already left.
static void scene_tick(void)
{
	scene_level_guard();
	scene_send();
	scene_skip_frame();
	scene_info peer;
	int have;
	EnterCriticalSection(&g_scene_cs);
	peer = g_peer_scene;
	have = g_peer_scene_valid;
	LeaveCriticalSection(&g_scene_cs);
	if (!have)
		return;
	scene_info me;
	scene_read(&me);
	DWORD now = GetTickCount();
	if (!me.cine) {
		// A pending skip is only for a scripted event this copy is in (or is still loading into): once this
		// copy is out of one the peer's leave has either been carried out here or does not apply here, and
		// keeping it would skip the NEXT scene as well (both copies leave together in the normal case).
		if (g_pend_active && me.level && now - g_pend_at > 500)
			g_pend_active = 0;
		if (peer.cine && me.level && peer.level == me.level) {
			static DWORD logged_a, logged_n;
			if (logged_a != peer.a || logged_n != peer.name4) {
				logged_a = peer.a;
				logged_n = peer.name4;
				InterlockedIncrement(&g_scene_missed);
				logf("scene: the peer is in a scripted event (state %u, scene %u, id %#x) and this copy is not",
						peer.state, peer.scene, peer.a);
			}
		}
		return;
	}
	if (!g_pend_active)
		return;   // nothing says the peer left an event: never skip one it simply did not see
	if (peer.cine) {
		g_pend_active = 0;   // the peer is in a scripted event again: its leave has been overtaken
		return;
	}
	if (g_pend_level && peer.level && me.level && g_pend_level != me.level) {
		g_pend_active = 0;   // a different level: not the same event
		return;
	}
	if (now - g_pend_at > SCENE_PEND_MS) {
		g_pend_active = 0;   // too old to be this scene's leave
		return;
	}
	if (!scene_skippable()) {
		// The pending skip stays armed while this copy is not (yet) in a skippable cutscene, but nothing is
		// pressed: a load, a menu or a fresh level must never receive the cinematic key.
		return;
	}
	scene_skip_begin("the peer's copy has left the scripted event and this copy is still in it");
}


// ---- doors and level transitions (TASK 34) ----------------------------------------------------------
// The level change was synced, the door use was not: the owner saw the guest jump into the new level with
// the door still shut on its screen, and the guest's own door use was swallowed by hk_change_level (its
// ChangeLevel is dropped: the host decides). Both come from the same gap - the game's own door path
// (FUN_0042c2b0, door vtable+0x70; the interaction scan calls +0x34 then +0x70, FINDINGS_19 §1.3) runs
// only where the pad that pressed A is simulated. PKT_DOOR carries the used entity (class vtable address,
// id, position, character), so the other copy runs the same path on its own entity.
//
// Which entity? The game marks what a character is using: FUN_0042c2b0 writes the door into
// character+0x2bc and the character into door+0xc4. Watching our own character's +0x2bc catches every
// door family that goes through this path (a single door, a double door, an internal/special door)
// without guessing class tags from a 4-byte hash, and it fires once per use because the value stays set
// while the use runs.
//
// Transitions without a door object (a loading zone) have no use to replay: their walk-in is the synced
// movement, and the level change itself is covered by the guest's ChangeLevel ask below.
#define DOOR_MAX 48
#define DOOR_SCAN_MAX 600
typedef struct { unsigned ent; DWORD cls, id; float pos[3]; DWORD tag; } door_slot;
static door_slot g_doors[DOOR_MAX];
static int g_door_n;
static DWORD g_door_level, g_door_scan_at, g_door_scanned;
static unsigned g_door_world;
static DWORD g_door_gen;                 // TASK 40: the world generation the table belongs to
static unsigned g_door_prev;             // the last +0x2bc seen on this copy's own character
static unsigned g_door_echo_ent;         // a door use this copy applied from the peer: do not echo it
static DWORD g_door_echo_until;
static unsigned g_door_use_ent;          // the last door use this copy started
static DWORD g_door_use_at;
static volatile LONG g_door_sent, g_door_rcv, g_door_applied, g_door_missed, g_door_queued;
static CRITICAL_SECTION g_door_cs;
static pkt_door g_door_q[4];
static int g_door_qh, g_door_qt;

// A level change the guest's own game asked for (hk_change_level dropped it). It is asked of the host
// after REQ_ASK_DELAY_MS, so the host's own copy of the same door use gets to do it first; the ask is
// repeated for a moment (PKT_LEVELASK has no ack) and dropped when the level actually changes.
#define ASK_DELAY_MS 800
#define ASK_REPEAT_MS 1000
#define ASK_GIVE_UP_MS 8000
static DWORD g_ask_t0, g_ask_level, g_ask_entry, g_ask_flag, g_ask_sent_at;
static volatile LONG g_ask_pending, g_ask_sent;
static DWORD g_ask_logged_level, g_ask_log_at;
static int g_ask_calls;

// Only the door classes measured before (door_class: DORH CToeDoor, DODO CToeDoubleDoor, INDO
// CToeInternalDoor). A tag that is not listed is never called through: the log names it once, so a door
// family this list misses shows up as "use target XXXX is not a door" instead of a wrong call.
static int door_known(DWORD tag)
{
	return door_class(tag);
}

static void door_scan(unsigned w, DWORD level)
{
	g_door_n = 0;
	g_door_level = level;
	g_door_world = w;
	g_door_gen = g_world_gen;
	g_door_scan_at = GetTickCount();
	g_door_scanned = level;
	g_door_prev = 0;
	unsigned mgr = w ? rd32(w + 0x1768) : 0;
	unsigned node = mgr ? rd32(mgr + 8) : 0;
	unsigned seen[DOOR_SCAN_MAX];
	int nseen = 0;
	while (node && nseen < DOOR_SCAN_MAX && g_door_n < DOOR_MAX) {
		int dup = 0;
		for (int k = 0; k < nseen; k++)
			if (seen[k] == node) { dup = 1; break; }
		if (dup)
			break;
		seen[nseen++] = node;
		unsigned e = rd32(node);
		node = rd32(node + 4);
		if (!e || e <= 0x10000 || IsBadReadPtr((void *)(uintptr_t)e, 0x150))
			continue;
		DWORD tag = rd32(e + 0x10);
		if (!door_known(tag))
			continue;
		door_slot *d = &g_doors[g_door_n++];
		memset(d, 0, sizeof *d);
		d->ent = e;
		d->tag = tag;
		d->cls = rd32(e);       // the class vtable: the same address on both copies (same exe build)
		d->id = rd32(e + 4);
		if (!IsBadReadPtr((const void *)(uintptr_t)(e + 0x6c), 12))
			memcpy(d->pos, (const void *)(uintptr_t)(e + 0x6c), sizeof d->pos);
	}
	logf("%s: door objects: %d watched in level %x", g_role == 2 ? "guest" : "host", g_door_n, (unsigned)level);
}

static void door_ensure(void)
{
	unsigned w = world_obj();
	if (!w)
		return;
	DWORD lvl = rd32(w + 4);
	if (!lvl)
		return;
	// TASK 40: a door table built while the game fills a new world names entities that are replaced a
	// frame later. No table at all until the world has settled; it is rebuilt from then on.
	if (!world_ready()) {
		g_door_n = 0;
		g_door_gen = 0;
		return;
	}
	if (g_door_gen != g_world_gen || w != g_door_world || lvl != g_door_level ||
	    (!g_door_n && g_door_scanned != lvl))
		door_scan(w, lvl);
}

// Game thread: our own character started a door use -> tell the peer (once per use).
static void door_watch(void)
{
	if (!g_peer_ok || g_role == 0)
		return;
	unsigned w = world_obj();
	if (!w || !rd32(w + 4) || rd32(w + 4) != g_door_level || w != g_door_world || g_door_gen != g_world_gen)
		return;   // door_ensure (door_tick) rebuilds the table first
	unsigned h = player_human(g_role == 2 ? 1 : 0);
	if (!h || IsBadReadPtr((const void *)(uintptr_t)(h + 0x2bc), 4))
		return;
	unsigned cur = rd32(h + 0x2bc);
	if (cur == g_door_prev)
		return;
	g_door_prev = cur;
	if (!cur || cur <= 0x10000 || IsBadReadPtr((const void *)(uintptr_t)cur, 0x150))
		return;
	DWORD tag = rd32(cur + 0x10);
	if (!door_known(tag)) {
		static DWORD logged_tag;
		static int logged_n;
		if (logged_tag != tag && logged_n < 12) {   // a save point, a lock, a lever: not a door
			logged_tag = tag;
			logged_n++;
			char c[5];
			logf("%s: use target %s is not a door: not forwarded as a door use", g_role == 2 ? "guest" : "host",
			     tag4(tag, c));
		}
		return;
	}
	g_door_use_ent = cur;
	g_door_use_at = GetTickCount();
	pkt_door p;
	memset(&p, 0, sizeof p);
	p.kind = 1;
	p.level = rd32(w + 4);
	p.ch_tag = rd32(h + H_TAG);
	p.cls = rd32(cur);
	p.id = rd32(cur + 4);
	if (!IsBadReadPtr((const void *)(uintptr_t)(cur + 0x6c), 12))
		memcpy(p.pos, (const void *)(uintptr_t)(cur + 0x6c), sizeof p.pos);
	net_send(PKT_DOOR, &p, (WORD)(sizeof p - sizeof(pkt_hdr)));
	InterlockedIncrement(&g_door_sent);
	door_probe_arm(cur);
	{
		char c[5], i4[5];
		logf("%s: used door %s id %s at level %x (ent %x): telling the peer", g_role == 2 ? "guest" : "host",
		     tag4(tag, c), tag4(p.id, i4), (unsigned)p.level, cur);
	}
}

// UDP thread: queue the peer's door use for the game thread (the game's state machine is not thread-safe).
static void peer_on_door(const char *buf, int n)
{
	const pkt_door *p = (const pkt_door *)buf;
	if (n != (int)sizeof *p || p->kind != 1)
		return;
	EnterCriticalSection(&g_door_cs);
	if (((g_door_qt + 1) & 3) != g_door_qh) {
		memcpy(&g_door_q[g_door_qt], p, sizeof *p);
		g_door_qt = (g_door_qt + 1) & 3;
		InterlockedIncrement(&g_door_queued);
	}
	LeaveCriticalSection(&g_door_cs);
	InterlockedIncrement(&g_door_rcv);
}

// Game thread: replay the peer's door use through the game's own path on this copy's entity.
static void door_apply(const pkt_door *p)
{
	DWORD base = virt_exe_base(), size = virt_exe_size();
	if (p->kind != 1)
		return;
	unsigned w = world_obj();
	if (!w || !g_peer_ok || rd32(w + 4) != p->level)
		return;   // not in that level (yet): nothing here to replay it on
	if (w != g_door_world || rd32(w + 4) != g_door_level || g_door_gen != g_world_gen)
		door_scan(w, rd32(w + 4));
	door_slot *best = 0;
	float bd = 200.0f;
	for (int i = 0; i < g_door_n; i++) {
		door_slot *d = &g_doors[i];
		if (d->cls != p->cls || (p->id && d->id != p->id))
			continue;
		float dd = adist(d->pos, p->pos);
		if (dd < bd) { bd = dd; best = d; }
	}
	if (!best) {
		InterlockedIncrement(&g_door_missed);
		char c[5], i4[5];
		logf("%s: the peer used door %s id %s at level %x: no such door on this copy", g_role == 2 ? "guest" : "host",
		     tag4((DWORD)p->cls, c), tag4(p->id, i4), (unsigned)p->level);
		return;
	}
	// Pointer validation tied to the level generation: the entity must still be that exact object (class
	// vtable, class tag, id) and its two use entries must still be inside the exe image. A door rebuilt by
	// a level change or freed by the game is never called through.
	unsigned e = best->ent;
	if (!e || IsBadReadPtr((void *)(uintptr_t)e, 0x150) || rd32(e + 0x10) != best->tag || rd32(e) != best->cls ||
	    rd32(e + 4) != best->id || !world_has_entity(e)) {
		InterlockedIncrement(&g_door_missed);
		return;
	}
	DWORD vt = rd32(e);
	if (!vt || !image_ptr(vt) || IsBadReadPtr((void *)(uintptr_t)vt, 0x74))
		return;
	DWORD f34 = rd32(vt + 0x34), f70 = rd32(vt + 0x70);
	if (f34 < base || f34 >= base + size || f70 < base || f70 >= base + size) {
		char c[5];
		logf("%s: door %s (ent %x) has no usable use entries: not replayed", g_role == 2 ? "guest" : "host",
		     tag4(best->tag, c), e);
		return;
	}
	if (!rd32(e + 0x24)) {   // the game's own gate (FUN_0042a480 returns 0 when +0x24 is 0)
		char c[5];
		logf("%s: door %s (ent %x) is disabled here (+0x24 = 0): use not replayed",
		     g_role == 2 ? "guest" : "host", tag4(best->tag, c), e);
		return;
	}
	unsigned h = 0;
	unsigned hs[MAX_CH];
	int n = world_humans(hs, MAX_CH);
	for (int i = 0; i < n; i++)
		if (rd32(hs[i] + H_TAG) == p->ch_tag) { h = hs[i]; break; }
	if (!h) {
		InterlockedIncrement(&g_door_missed);
		return;
	}
	// Both copies simulate both characters from pads, so this copy's own scan may already have run the
	// use (the door stores the user at +0xc4, the character the object it is using at +0x2bc). Running it
	// again would restart the animation: recognise it and leave it alone.
	if (rd32(e + 0xc4) == h || rd32(h + 0x2bc) == e) {
		g_door_echo_ent = e;
		g_door_echo_until = GetTickCount() + 2500;
		InterlockedIncrement(&g_door_applied);
		door_probe_arm(e);
		char c[5];
		logf("%s: door %s (ent %x) was already used by %s here: not replayed", g_role == 2 ? "guest" : "host",
		     tag4(best->tag, c), e, tag4(p->ch_tag, c));
		return;
	}
	// FUN_0042a480 takes (type, character) and FUN_0042c2b0 takes (character): the interaction scan calls
	// `(door->vtable+0x34)(type, character)` then `(door->vtable+0x70)(character)` (decompile 128210-128245).
	// Passing only the type made the check read a garbage character pointer (it crashed at Obscure2+0x2a4c2).
	// TASK 35: the game's own gate comes first. FUN_0042a480 returns 0 when the character is further than
	// 80 units from the door, is not facing it, the door is disabled (+0x24 = 0) or already in use
	// (+0xb8 != 0); the scan does not call the use then, so neither do we - the use without the gate left
	// the door half entered. And the teammate controller must not point at this character: the use runs
	// FUN_0042ad70, which would stop the door it is using (see teammate_unlink).
	teammate_unlink(h);
	hang_phase("in the peer door replay: the game's gate (vtable+0x34)");
	int ok_use = (int)((int(__fastcall *)(void *, void *, unsigned, void *))f34)((void *)(uintptr_t)e, NULL, 1,
		(void *)(uintptr_t)h);
	hang_phase("in the peer door replay: the game's use (vtable+0x70)");
	if (!ok_use) {
		InterlockedIncrement(&g_door_missed);
		char c[5], t[5];
		logf("%s: door %s (ent %x) refused by the game's own check for character %s (too far / not facing / "
		     "door busy): use not replayed", g_role == 2 ? "guest" : "host", tag4(best->tag, c), e,
		     tag4(p->ch_tag, t));
		return;
	}
	((void(__fastcall *)(void *, void *, void *))f70)((void *)(uintptr_t)e, NULL, (void *)(uintptr_t)h);
	g_door_echo_ent = e;
	g_door_echo_until = GetTickCount() + 2500;
	InterlockedIncrement(&g_door_applied);
	door_probe_arm(e);
	{
		char c[5], i4[5], t[5];
		logf("%s: door %s id %s use replayed on ent %x for character %s", g_role == 2 ? "guest" : "host",
		     tag4(best->tag, c), tag4(p->id, i4), e, tag4(p->ch_tag, t));
	}
}

static void door_apply_tick(void)
{
	pkt_door p;
	// TASK 40: the peer's use stays queued while this copy's world is being built or rebuilt
	if (!world_ready())
		return;
	for (;;) {
		EnterCriticalSection(&g_door_cs);
		if (g_door_qh == g_door_qt) {
			LeaveCriticalSection(&g_door_cs);
			return;
		}
		p = g_door_q[g_door_qh];
		g_door_qh = (g_door_qh + 1) & 3;
		LeaveCriticalSection(&g_door_cs);
		door_apply(&p);
	}
}

// hk_change_level (guest): the game asked for a level change this copy must not perform. Log it once per
// burst (the game's door script calls it every frame while it waits - 1334 lines in the owner's log) and
// remember it for the ask below. Called on the game thread.
static void guest_note_own_level(unsigned level, unsigned entry, unsigned flag)
{
	DWORD now = GetTickCount();
	if (level != g_ask_logged_level || now - g_ask_log_at > 2000) {
		if (g_ask_calls)
			logf("guest: own ChangeLevel %c%c%c%c dropped (the host decides); %d calls in %lu ms",
			     (char)(level >> 24), (char)(level >> 16), (char)(level >> 8), (char)level, g_ask_calls,
			     (unsigned long)(now - g_ask_log_at));
		else
			logf("guest: own ChangeLevel %c%c%c%c dropped (the host decides)", (char)(level >> 24),
			     (char)(level >> 16), (char)(level >> 8), (char)level);
		g_ask_logged_level = level;
		g_ask_log_at = now;
		g_ask_calls = 0;
	}
	g_ask_calls++;
	g_door_use_at = 0;   // the door animation is over: the world may be rebuilt by the level request now
	if (!g_ask_pending || level != g_ask_level) {
		g_ask_level = level;
		g_ask_entry = entry;
		g_ask_flag = flag;
		g_ask_t0 = now;
		g_ask_sent_at = 0;
		g_ask_pending = 1;
	}
}

// Guest, game thread: ask the host for the level change the guest's own game wanted.
static void level_ask_tick(void)
{
	if (g_role != 2 || !g_ask_pending || !g_peer_ok)
		return;
	DWORD now = GetTickCount();
	if (now - g_ask_t0 < ASK_DELAY_MS)
		return;   // the host's own copy of the same door use gets to do the change first
	unsigned w = world_obj();
	if (w && rd32(w + 4) == g_ask_level) {   // the host's request arrived and this copy changed level
		g_ask_pending = 0;
		return;
	}
	if (now - g_ask_t0 > ASK_GIVE_UP_MS) {
		g_ask_pending = 0;
		return;
	}
	if (g_ask_sent_at && now - g_ask_sent_at < ASK_REPEAT_MS)
		return;
	g_ask_sent_at = now;
	pkt_levelask a;
	memset(&a, 0, sizeof a);
	a.kind = 1;
	a.level = g_ask_level;
	a.entry = g_ask_entry;
	a.flag = g_ask_flag;
	net_send(PKT_LEVELASK, &a, (WORD)(sizeof a - sizeof(pkt_hdr)));
	InterlockedIncrement(&g_ask_sent);
	logf("guest: asking the host for ChangeLevel %c%c%c%c entry %u flag %u", (char)(a.level >> 24),
	     (char)(a.level >> 16), (char)(a.level >> 8), (char)a.level, (unsigned)a.entry, (unsigned)a.flag);
}

// Host, UDP thread: the guest's ask, applied on the game thread.
static volatile LONG g_levelask_pending;
static DWORD g_levelask_level, g_levelask_entry, g_levelask_flag;
static DWORD g_levelask_at;   // TASK 37: when the ask started waiting for this copy's own transition

static void host_on_levelask(const char *buf, int n)
{
	const pkt_levelask *a = (const pkt_levelask *)buf;
	if (n != (int)sizeof *a || g_role != 1 || a->kind != 1)
		return;
	g_levelask_level = a->level;
	g_levelask_entry = a->entry;
	g_levelask_flag = a->flag;
	g_levelask_at = 0;
	g_levelask_pending = 1;
}

static void host_levelask_tick(void)
{
	if (g_role != 1 || !g_levelask_pending || !g_peer_ok)
		return;
	DWORD now = GetTickCount();
	if (!g_levelask_at)
		g_levelask_at = now;
	if (host_apply_guest_level(g_levelask_level, g_levelask_entry, g_levelask_flag)) {
		g_levelask_pending = 0;
		g_levelask_at = 0;
		return;
	}
	// TASK 37: this copy has a transition of its own in flight. The ask stays pending until that one is
	// over (a transition is never applied half on top of another), but not forever.
	if (now - g_levelask_at > ASK_GIVE_UP_MS) {
		char lv[5];
		g_levelask_pending = 0;
		g_levelask_at = 0;
		logf("host: the guest's ask for %s is dropped: this copy stayed busy for %d ms",
		     tag4(g_levelask_level, lv), ASK_GIVE_UP_MS);
	}
}

// TEST ONLY (pipe `usedoor <0|1>`): run the game's own door use on the nearest door to that player, the
// same two calls the interaction scan makes. The test saves' doors do not open from a pad press in these
// loaded worlds (FINDINGS_19 §2.4: the scan's gate is not satisfied), so this is how a live check drives
// the door path the mod mirrors. It runs on the game thread (the pipe thread must not call the game).
#define DOORU_IDLE 0
#define DOORU_QUEUED 1
#define DOORU_DONE 2
#define DOORU_PLACED 3
#define DOORU_WAIT_MS 15000
#define DOORU_SETTLE_MS 400
#define DOORU_MAX_DOORS 3
static volatile LONG g_dooru_state, g_dooru_verdict;
static int g_dooru_player;
static DWORD g_dooru_at;
static unsigned g_dooru_ent;   // TASK 35: the chosen door by ENTITY (g_doors is rebuilt on a level change)
static float g_dooru_door_pos[3];
static float g_dooru_anchor[3], g_dooru_face[3];   // the door's interaction anchor and normal
static int g_dooru_tries;
static char g_dooru_msg[200];
// TASK 36: candidate doors and placement spots. A refusal is retried on the same door from another spot,
// and a door whose use runs but does not take the user (its +0x120 lock branch) is left for the next door.
static unsigned g_dooru_doors[DOORU_MAX_DOORS];
static int g_dooru_ndoors, g_dooru_di, g_dooru_spot;
static DWORD g_dooru_req_at;   // TASK 39: when the pipe queued this request (a rebuild is waited out)
// TASK 39: how many times this request had to re-pick because the world was rebuilt under it (bounded, so
// a world that keeps rebuilding ends in the 15 s pipe answer instead of a loop).
#define DOORU_MAX_STALE 8
static int g_dooru_stale;

// The places a use is attempted from, as (depth along the door's own normal, sideways offset). The game's
// check (FUN_0042a480) wants the character within 80 units of the door's anchor (+0x10c) and its forward
// along +0x13c, so every spot keeps both. TASK 36: the Z now comes from the ANCHOR - the old placement
// kept the character's own Z, and the check's distance is 3-D, so a character on a ramp or another floor
// stayed 113 units away while the 2-D placement looked right (measured in J001, five retries, same value).
static const float g_dooru_spots[][2] = {
	{ 55.0f, 0.0f }, { 40.0f, 0.0f }, { 68.0f, 0.0f }, { 25.0f, 0.0f },
	{ -45.0f, 0.0f }, { 0.0f, 45.0f }, { 0.0f, -45.0f },
};
#define DOORU_NSPOTS ((int)(sizeof g_dooru_spots / sizeof g_dooru_spots[0]))

// The slot of the chosen door in the CURRENT table (0 when it is gone: a level change rebuilt the world).
static door_slot *dooru_slot(void)
{
	for (int i = 0; i < g_door_n; i++)
		if (g_doors[i].ent == g_dooru_ent)
			return &g_doors[i];
	return 0;
}

// The state FUN_0042c2b0 needs for its normal use path: enabled (+0x24), not in use (+0xb8) and +0x120 = 0
// (the other branch only plays the "cannot use" sound and clears the user). TASK 35: the test door picker
// used to take the nearest door whatever its state - in I100 that is a door whose +0x120 is set, so the
// use ran but never took the character as its user.
static int dooru_usable(unsigned e)
{
	if (!e || IsBadReadPtr((void *)(uintptr_t)e, 0x150))
		return 0;
	if (!door_known(rd32(e + 0x10)))
		return 0;
	if (!rd32(e + 0x24) || rd32(e + 0xb8) || rd32(e + 0x120))
		return 0;
	return 1;
}

// Step 2: the character has had a few frames to settle at the door: run the use now. Returns 1 when the
// game ran the use, 0 when its own check refused it (the caller places the character again).
static int door_use_run(unsigned h, door_slot *best, float bd)
{
	DWORD base = virt_exe_base(), size = virt_exe_size();
	unsigned e = best->ent;
	// TASK 39: the same identity check door_apply makes. The slot comes from a scan that can be up to a
	// level change old, and a freed entity's memory is reusable by the heap (TASK 35 §3.2 measured a vtable
	// slot holding heap data and the game thread executing 0x44754000): the entity must still be that
	// exact object - class vtable, class tag, id - before its two use entries are called through.
	if (!e || IsBadReadPtr((void *)(uintptr_t)e, 0x150) || rd32(e) != best->cls || rd32(e + 0x10) != best->tag ||
	    (best->id && rd32(e + 4) != best->id) || !world_has_entity(e)) {
		// TASK 39: the slot was rebuilt under the 400 ms settle (a level change landed between the pick and
		// the use). That is not a failed use: the caller picks again from the CURRENT table.
		_snprintf(g_dooru_msg, sizeof g_dooru_msg, "error usedoor: door %x is gone from this world", e);
		return 3;
	}
	DWORD vt = rd32(e);
	DWORD f34 = (vt && image_ptr(vt) && !IsBadReadPtr((void *)(uintptr_t)vt, 0x74)) ? rd32(vt + 0x34) : 0;
	DWORD f70 = f34 ? rd32(vt + 0x70) : 0;
	char c[5];
	if (!f34 || f34 < base || f34 >= base + size || f70 < base || f70 >= base + size) {
		_snprintf(g_dooru_msg, sizeof g_dooru_msg, "error usedoor: door %x has no usable use entries", e);
		return 1;
	}
	// TASK 35: the settle can have turned the character (the game's own idle/animation code owns the
	// facing): face the door again the instant before the check, the way the placement did.
	if (g_dooru_face[0] || g_dooru_face[1] || g_dooru_face[2]) {
		float nf[3] = { g_dooru_face[0], g_dooru_face[1], 0.0f };
		if (!IsBadWritePtr((void *)(uintptr_t)(h + H_DIR), 12))
			memcpy((void *)(uintptr_t)(h + H_DIR), nf, 12);
	}
	// FUN_0042a480(type, character) then FUN_0042c2b0(character): the scan's own two calls (decompile
	// 128210-128245). The first argument is the interaction type (1 = the front pass). The check's answer is
	// the scan's gate: 0 = not usable from here (TASK 35), and the use must not run then.
	teammate_unlink(h);
	// TASK 39: name the two game calls in the watchdog's `last mod step`, so a stall report says WHICH of
	// them the game thread never came back from (the TASK 38 report only said "in door_tick (guest)").
	if (teammate_debug()) {
		unsigned mt = world_obj() ? rd32(world_obj() + 0x174c) : 0;
		teammate_note("door use: the game's gate (vtable+0x34) runs with the teammate", game_obj(), mt ? rd32(mt + 4) : 0, h);
	}
	hang_phase("in the game's door gate (vtable+0x34)");
	int ok_use = (int)((int(__fastcall *)(void *, void *, unsigned, void *))f34)((void *)(uintptr_t)e, NULL, 1,
		(void *)(uintptr_t)h);
	hang_phase("in the game's door use (vtable+0x70)");
	if (!ok_use) {
		// The gate has four inputs; log all of them, so a refusal is never a guess.
		float cd[3] = { 0, 0, 0 }, fw[3] = { 0, 0, 0 };
		if (!IsBadReadPtr((const void *)(uintptr_t)(h + H_POS), 24))
			memcpy(cd, (const void *)(uintptr_t)(h + H_POS), 12);
		if (!IsBadReadPtr((const void *)(uintptr_t)(h + H_DIR), 12))
			memcpy(fw, (const void *)(uintptr_t)(h + H_DIR), 12);
		float dot = fw[0] * g_dooru_face[0] + fw[1] * g_dooru_face[1] + fw[2] * g_dooru_face[2];
		float dx = cd[0] - g_dooru_anchor[0], dy = cd[1] - g_dooru_anchor[1], dz = cd[2] - g_dooru_anchor[2];
		_snprintf(g_dooru_msg, sizeof g_dooru_msg,
		          "error usedoor: the game's own check refused the use (%.1f units from the anchor, facing dot %.2f, "
		          "enabled %u busy %u user %x)", sqrtf(dx * dx + dy * dy + dz * dz), dot,
		          (unsigned)(e && !IsBadReadPtr((void *)(uintptr_t)(e + 0x24), 8) ? rd32(e + 0x24) : 0),
		          (unsigned)(e && !IsBadReadPtr((void *)(uintptr_t)(e + 0xb8), 8) ? rd32(e + 0xb8) : 0),
		          (unsigned)(e && !IsBadReadPtr((void *)(uintptr_t)(e + 0xc4), 4) ? rd32(e + 0xc4) : 0));
		logf("usedoor: %s", g_dooru_msg);
		return 0;
	}
	((void(__fastcall *)(void *, void *, void *))f70)((void *)(uintptr_t)e, NULL, (void *)(uintptr_t)h);
	g_door_prev = 0;   // the watch sees this use as its own and announces it to the peer
	InterlockedIncrement(&g_dooru_verdict);
	door_probe_arm(e);
	// TASK 36: FUN_0042c2b0 has an early branch (door+0x120 != 0) that only plays the "cannot use" sound and
	// clears the user, so a use can pass the gate and still do nothing. The use is only proven by the state
	// it leaves: door+0xc4 = the character and character+0x2bc = the door.
	if (!IsBadReadPtr((void *)(uintptr_t)e, 0x150) && rd32(e + 0xc4) == h) {
		_snprintf(g_dooru_msg, sizeof g_dooru_msg,
		          "ok usedoor player %d door %s id %x ent %x (%.1f units away, spot %d, door %d/%d)",
		          g_dooru_player, tag4(best->tag, c), (unsigned)best->id, e, bd, g_dooru_spot,
		          g_dooru_di + 1, g_dooru_ndoors);
		logf("usedoor: %s", g_dooru_msg);
		return 1;
	}
	{
		unsigned locked = !IsBadReadPtr((void *)(uintptr_t)(e + 0x120), 4) ? rd32(e + 0x120) : 0;
		unsigned en = !IsBadReadPtr((void *)(uintptr_t)(e + 0x24), 4) ? rd32(e + 0x24) : 0;
		unsigned busy = !IsBadReadPtr((void *)(uintptr_t)(e + 0xb8), 4) ? rd32(e + 0xb8) : 0;
		unsigned ur = !IsBadReadPtr((void *)(uintptr_t)(e + 0xc4), 4) ? rd32(e + 0xc4) : 0;
		_snprintf(g_dooru_msg, sizeof g_dooru_msg,
		          "error usedoor: the game ran the use but the door did not take the user (enabled %u busy %u "
		          "locked %u user %x, spot %d)", en, busy, locked, ur, g_dooru_spot);
		logf("usedoor: %s", g_dooru_msg);
	}
	return 2;
}

// The door's own check (FUN_0042a480) wants the character within 80 units of the door's interaction anchor
// (door+0x10c) and its forward vector pointing along the door's normal (dot >= 0.5). The test character
// usually spawns far from the nearest door, so the mod places it, lets a few frames of the game's own
// physics settle it and then runs the use - on the game thread only (test-only path).
// TASK 36: the attempts walk a list of candidate doors (nearest first, in the state the use can run in) and
// a list of spots per door (g_dooru_spots). Each attempt is verified after the settle (the character must
// still be within the check's reach and facing) and after the use (the door must have taken the character
// as its user), so a spot the game's physics rejects or a door whose +0x120 branch does nothing moves on to
// the next candidate instead of failing the whole request.
static void dooru_pick_doors(unsigned h)
{
	float pp[3] = { 0, 0, 0 };
	g_dooru_ndoors = 0;
	g_dooru_di = 0;
	g_dooru_spot = 0;
	if (!IsBadReadPtr((const void *)(uintptr_t)(h + H_POS), 12))
		memcpy(pp, (const void *)(uintptr_t)(h + H_POS), sizeof pp);
	for (int pass = 0; pass < 2 && g_dooru_ndoors < DOORU_MAX_DOORS; pass++) {
		// pass 0: only doors whose state FUN_0042c2b0's normal path accepts; pass 1: the rest, as a fallback
		for (;;) {
			int idx = -1;
			float bd = 4000.0f;
			for (int i = 0; i < g_door_n; i++) {
				if (pass == 0 && !dooru_usable(g_doors[i].ent))
					continue;
				int dup = 0;
				for (int k = 0; k < g_dooru_ndoors; k++)
					if (g_dooru_doors[k] == g_doors[i].ent) { dup = 1; break; }
				if (dup)
					continue;
				float d = adist(g_doors[i].pos, pp);
				if (d < bd) { bd = d; idx = i; }
			}
			if (idx < 0 || g_dooru_ndoors >= DOORU_MAX_DOORS)
				break;
			g_dooru_doors[g_dooru_ndoors++] = g_doors[idx].ent;
		}
	}
	logf("usedoor: %d candidate door(s) for player %d", g_dooru_ndoors, g_dooru_player);
}

static void door_use_frame(void)
{
	if (g_dooru_state != DOORU_QUEUED && g_dooru_state != DOORU_PLACED)
		return;
	unsigned w = world_obj();
	// TASK 39: the world is being rebuilt (a level change this copy is following: no world, or no level
	// tag yet) or a load/ChangeLevel is in flight (game+0x320 = 2/3/4). Every entity picked now would die
	// under the 400 ms settle, and the whole door table would be stale - so WAIT for the rebuild to finish
	// instead of answering "not in a level" (the soak's guest phase hit this every time right after the
	// host's own door changed the level). The pipe's 15 s answer still bounds the wait.
	if (!w || !rd32(w + 4) || rd32(game_obj() + 0x320) != 0 || !world_ready()) {
		if (g_dooru_req_at && GetTickCount() - g_dooru_req_at < DOORU_WAIT_MS - 3000)
			return;
		g_dooru_state = DOORU_DONE;
		_snprintf(g_dooru_msg, sizeof g_dooru_msg, "error usedoor: not in a level");
		return;
	}
	if (g_door_gen != g_world_gen || w != g_door_world || rd32(w + 4) != g_door_level) {
		door_scan(w, rd32(w + 4));
		g_dooru_ndoors = 0;   // the entities are new: pick again
		g_dooru_ent = 0;
	}
	unsigned h = player_human(g_dooru_player);
	if (!h) {
		g_dooru_state = DOORU_DONE;
		_snprintf(g_dooru_msg, sizeof g_dooru_msg, "error usedoor: player %d has no character", g_dooru_player);
		return;
	}
	if (g_dooru_state == DOORU_PLACED) {
		if (GetTickCount() - g_dooru_at < DOORU_SETTLE_MS)
			return;   // let the character land on the floor
		door_slot *best = dooru_slot();
		if (!best) {
			g_dooru_ndoors = 0;   // the door vanished with a level change: pick again
			g_dooru_ent = 0;
			g_dooru_state = DOORU_QUEUED;
			return;
		}
		float pp[3] = { 0, 0, 0 }, fw[3] = { 0, 0, 0 };
		if (!IsBadReadPtr((const void *)(uintptr_t)(h + H_POS), 12))
			memcpy(pp, (const void *)(uintptr_t)(h + H_POS), sizeof pp);
		if (!IsBadReadPtr((const void *)(uintptr_t)(h + H_DIR), 12))
			memcpy(fw, (const void *)(uintptr_t)(h + H_DIR), sizeof fw);
		float dx = pp[0] - g_dooru_anchor[0], dy = pp[1] - g_dooru_anchor[1], dz = pp[2] - g_dooru_anchor[2];
		float d3 = sqrtf(dx * dx + dy * dy + dz * dz);
		float dot = fw[0] * g_dooru_face[0] + fw[1] * g_dooru_face[1] + fw[2] * g_dooru_face[2];
		if (d3 > 78.0f || dot < 0.5f) {
			logf("usedoor: spot %d did not hold (%.1f units from the anchor, facing dot %.2f): next spot",
			     g_dooru_spot, d3, dot);
			g_dooru_spot++;
			g_dooru_state = DOORU_QUEUED;
			return;
		}
		int v = door_use_run(h, best, adist(g_dooru_door_pos, pp));
		if (v == 1) {
			g_dooru_state = DOORU_DONE;
			g_dooru_ent = 0;
			return;
		}
		if (v == 3) {   // TASK 39: the world was rebuilt under the settle: pick the doors again
			if (++g_dooru_stale > DOORU_MAX_STALE) {
				g_dooru_state = DOORU_DONE;
				return;
			}
			// The world object can come back at the SAME address (the heap reuses the block) under the SAME
			// level tag, so the table's key (world + level) cannot see that rebuild: scan again, or every
			// re-pick returns the same dead entity.
			door_scan(w, rd32(w + 4));
			g_dooru_ndoors = 0;
			g_dooru_ent = 0;
			g_dooru_di = 0;
			g_dooru_spot = 0;
			g_dooru_state = DOORU_QUEUED;
			return;
		}
		if (v == 2)
			g_dooru_spot = DOORU_NSPOTS;   // the use ran but the door stayed shut: another spot will not help
		else
			g_dooru_spot++;
		g_dooru_state = DOORU_QUEUED;
		return;
	}
	if (!g_dooru_ndoors) {
		dooru_pick_doors(h);
		if (!g_dooru_ndoors) {
			g_dooru_state = DOORU_DONE;
			_snprintf(g_dooru_msg, sizeof g_dooru_msg, "error usedoor: no door in level %x", (unsigned)rd32(w + 4));
			return;
		}
	}
	if (g_dooru_di >= g_dooru_ndoors || g_dooru_spot >= DOORU_NSPOTS) {
		// this door has no attempt left: the next candidate
		g_dooru_di++;
		g_dooru_spot = 0;
		g_dooru_ent = 0;
		if (g_dooru_di >= g_dooru_ndoors) {
			if (!g_dooru_msg[0])
				_snprintf(g_dooru_msg, sizeof g_dooru_msg, "error usedoor: no spot at the door(s) let the use run");
			g_dooru_state = DOORU_DONE;
			return;
		}
		return;
	}
	g_dooru_ent = g_dooru_doors[g_dooru_di];
	door_slot *best = dooru_slot();
	if (!best) {   // stale entry: re-pick next frame
		g_dooru_ndoors = 0;
		g_dooru_ent = 0;
		return;
	}
	if (g_dooru_spot == 0) {
		char c5[5];
		logf("usedoor: the game thread is running the request (player %d, door %s ent %x, door %d/%d)",
		     g_dooru_player, tag4(best->tag, c5), best->ent, g_dooru_di + 1, g_dooru_ndoors);
	}
	unsigned e = best->ent;
	float anchor[3] = { 0, 0, 0 }, dir[3] = { 0, 0, 1 };
	if (!IsBadReadPtr((const void *)(uintptr_t)(e + 0x10c), 24)) {
		memcpy(anchor, (const void *)(uintptr_t)(e + 0x10c), 12);   // the interaction anchor
		memcpy(dir, (const void *)(uintptr_t)(e + 0x13c), 12);      // the door's facing (its normal)
	}
	float n = sqrtf(dir[0] * dir[0] + dir[1] * dir[1] + dir[2] * dir[2]);
	if (n < 0.5f) { dir[0] = 0; dir[1] = 0; dir[2] = 1; n = 1.0f; }
	dir[0] /= n; dir[1] /= n; dir[2] /= n;
	float depth = g_dooru_spots[g_dooru_spot][0], side = g_dooru_spots[g_dooru_spot][1];
	float px = -dir[1], py = dir[0];   // the door's own sideways direction
	float tx = anchor[0] - dir[0] * depth + px * side;
	float ty = anchor[1] - dir[1] * depth + py * side;
	float tz = anchor[2] + 4.0f;       // TASK 36: the anchor's floor, not the character's own height
	if (IsBadWritePtr((void *)(uintptr_t)(h + H_POS), 24)) {
		g_dooru_state = DOORU_DONE;
		_snprintf(g_dooru_msg, sizeof g_dooru_msg, "error usedoor: the character's position is not writable");
		return;
	}
	float np[3] = { tx, ty, tz };
	memcpy((void *)(uintptr_t)(h + H_POS), np, 12);
	float nf[3] = { dir[0], dir[1], 0.0f };   // face along the door's normal (the check's dot >= 0.5)
	memcpy((void *)(uintptr_t)(h + H_DIR), nf, 12);
	memcpy(g_dooru_door_pos, anchor, sizeof g_dooru_door_pos);
	memcpy(g_dooru_anchor, anchor, sizeof g_dooru_anchor);
	memcpy(g_dooru_face, dir, sizeof g_dooru_face);
	g_dooru_tries++;
	{
		char c5[5];
		logf("usedoor: placed player %d at spot %d of door %s ent %x (depth %.0f, sideways %.0f)",
		     g_dooru_player, g_dooru_spot, tag4(best->tag, c5), e, depth, side);
	}
	g_dooru_at = GetTickCount();
	g_dooru_state = DOORU_PLACED;
}

static int door_use_request(int player, char *reply, size_t replysz)
{
	if (player < 0 || player > 1) {
		_snprintf(reply, replysz, "error usedoor <0|1>");
		return 0;
	}
	if (g_dooru_state == DOORU_QUEUED) {
		_snprintf(reply, replysz, "error usedoor: another request is in flight");
		return 0;
	}
	g_dooru_player = player;
	g_dooru_msg[0] = 0;
	g_dooru_verdict = 0;
	g_dooru_tries = 0;
	g_dooru_ent = 0;
	g_dooru_ndoors = 0;
	g_dooru_di = 0;
	g_dooru_spot = 0;
	g_dooru_face[0] = g_dooru_face[1] = g_dooru_face[2] = 0.0f;
	g_dooru_stale = 0;
	g_dooru_req_at = GetTickCount();
	g_dooru_state = DOORU_QUEUED;
	DWORD t0 = GetTickCount();
	while (g_dooru_state != DOORU_DONE) {
		if (GetTickCount() - t0 > DOORU_WAIT_MS) {
			g_dooru_state = DOORU_IDLE;
			_snprintf(reply, replysz, "error usedoor: the game thread did not run it in %d s", DOORU_WAIT_MS / 1000);
			return 0;
		}
		Sleep(10);
	}
	int ok = g_dooru_verdict;
	_snprintf(reply, replysz, "%s", g_dooru_msg);
	g_dooru_state = DOORU_IDLE;
	return ok;
}

// Both roles, game thread: the door table and the two transition helpers.
// TASK 43 diagnostic: what the game's own door transition does with a use. The transition lives inside the
// door object (FUN_0042c0c0 -> FUN_0042aa70, FINDINGS_43 section 1): it needs door+0xb8 ("in use") still
// set, door+0x24 ("enabled") still 1, the USER character's state 0x708 to end or the deadline door+0x4e to
// pass, and then door+0x118 (the destination) to differ from the level. A use that ends without a
// ChangeLevel is exactly the TASK 42 regression, so every CHANGE of one of those fields is one log line.
// The probe watches one entity for 8 s after a use (its own or a replayed one) and says when it is gone.
static unsigned g_dp_ent;
static DWORD g_dp_until, g_dp_at;
static DWORD g_dp_prev[8];

static void door_probe_arm(unsigned ent)
{
	g_dp_ent = ent;
	g_dp_at = 0;
	g_dp_until = GetTickCount() + 8000;
	memset(g_dp_prev, 0xff, sizeof g_dp_prev);
}

static void door_probe_tick(void)
{
	if (!g_dp_ent)
		return;
	DWORD now = GetTickCount();
	if ((LONG)(now - g_dp_until) > 0) {
		g_dp_ent = 0;
		return;
	}
	if (g_dp_at && now - g_dp_at < 120)
		return;
	g_dp_at = now;
	unsigned e = g_dp_ent, w = world_obj();
	char t[5];
	if (!w || IsBadReadPtr((void *)(uintptr_t)e, 0x150) || !world_has_entity(e)) {
		logf("doorprobe %s: the door ent %x is gone 8 s watch end (level %x)", g_role == 2 ? "guest" : "host", e,
		     w ? (unsigned)rd32(w + 4) : 0);
		g_dp_ent = 0;
		return;
	}
	unsigned u = rd32(e + 0xc4);
	DWORD v[8];
	v[0] = u;
	v[1] = u && !IsBadReadPtr((void *)(uintptr_t)(u + 0x2dc), 4) ? rd32(u + 0x2dc) : 0;
	v[2] = u && !IsBadReadPtr((void *)(uintptr_t)(u + 0x220), 4) ? rd32(u + 0x220) : 0;
	v[3] = rd32(e + 0xb8);
	v[4] = rd32(e + 0x24);
	v[5] = rd32(e + 0x120);
	v[6] = rd32(e + 0x118);
	v[7] = rd32(w + 4);
	if (!memcmp(v, g_dp_prev, sizeof v))
		return;
	memcpy(g_dp_prev, v, sizeof v);
	logf("doorprobe %s ent %x %s: user %x state %lu clip %lu | in use %lu enabled %lu d120 %lx dest %x | level %x",
	     g_role == 2 ? "guest" : "host", e, tag4(rd32(e + 0x10), t), v[0], (unsigned long)v[1], (unsigned long)v[2],
	     (unsigned long)v[3], (unsigned long)v[4], (unsigned long)v[5], (unsigned)v[6], (unsigned)v[7]);
}

static void door_tick(void)
{
	door_ensure();
	door_watch();
	door_apply_tick();
	door_use_frame();
	level_ask_tick();
	host_levelask_tick();
	door_probe_tick();
}

// This copy's own door use is still running: do not rebuild the world under it. The window is a safety
// net: the game clears character+0x2bc when it ends the use (FUN_0042a870) and that ends the guard at
// once, so the 6 s cap only matters for a use that never ends. The cap must be LONGER than a real door
// animation (measured 2.3-3.4 s on the shaped Steam link, run_s43_steam2: a 3 s cap let the guest's ask
// cut the host's own door off at exactly 3.0 s).
static int door_animation_running(void)
{
	if (!g_door_use_at || GetTickCount() - g_door_use_at >= 6000)
		return 0;
	unsigned h = player_human(g_role == 2 ? 1 : 0);
	if (h && !IsBadReadPtr((const void *)(uintptr_t)(h + 0x2bc), 4) && rd32(h + 0x2bc) == 0)
		return 0;   // the game's own use is over
	return 1;
}


// Pipe `scene` / `sync`: this copy's and the peer's scripted-event state (TASK 30).
static void scene_status(char *reply, size_t replysz)
{
	scene_info me, peer;
	int have;
	scene_read(&me);
	EnterCriticalSection(&g_scene_cs);
	peer = g_peer_scene;
	have = g_peer_scene_valid;
	LeaveCriticalSection(&g_scene_cs);
	char l1[8], l2[8], a1[8], a2[8];
	_snprintf(reply, replysz,
		"scene local state %u scene %u id %s level %s cine %u | peer %s state %u scene %u id %s level %s cine %u"
		" | sent %ld rcv %ld skips %ld left %ld stuck %ld missed %ld energy %ld"
		" | leave %lu pend %ld tries %d/%d",
		(unsigned)me.state, (unsigned)me.scene, tag4(me.a, a1), tag4(me.level, l1), (unsigned)me.cine,
		have ? "" : "(none)", (unsigned)peer.state, (unsigned)peer.scene, tag4(peer.a, a2), tag4(peer.level, l2),
		(unsigned)peer.cine, g_scene_sent, g_scene_rcv, g_scene_skips, g_scene_left, g_scene_stuck, g_scene_missed,
		g_energy_sets, (unsigned long)g_leave_seq, (long)g_pend_active, g_skip_tries, SCENE_SKIP_TRIES);
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

// ---- safe teleport (TASK 17 Part A) ----------------------------------------------------------------
//
// A plain write of the position triple at character+0x23c does stick (FINDINGS_16 section 4: the probe
// read the written value back 1.2 s later), but it says nothing about what is under the target. On H000 a
// teleport onto the CToeHeavyCase (z = 59.74) left the character in free fall for 468 units, and the old
// `tp` had no way back: the character stayed in the void, so the interaction scan (+0x73c) never selected
// the case.
//
// The engine's own answer to "is there floor here" is the character physics: the game's own placement
// paths do the same thing. CToeCharacterPos (tag PPOS 0x50504f53, constructor FUN_00414140, parser
// FUN_00414220 reading `position` into +0x104 and `player_controlled` into +0x11c) only names a position;
// the character's physics then settles the body onto the floor. There is no separate snap call to reuse,
// and the camera's floor pair (FUN_0057d9a0 / FUN_0057e9c0) belongs to the camera's collision object.
//
// So the safe tp runs on the game thread (frame_tick, one call per frame): it remembers the old position,
// writes the target once, then samples the character every frame. It accepts only when the character
// stays on the requested X/Y and its Z settles (10 stable frames) within TP_MAX_DROP units of the
// requested Z for at least TP_MIN_MS; otherwise it restores the old position and prints why. That is the
// "ground/collision query" the task asks for, with the physics as the query, plus the snap (the settled Z
// is the floor; the reply prints it so a caller can aim the next teleport exactly).
#define TP_IDLE 0
#define TP_START 1
#define TP_RUN 2
#define TP_DONE 3

#define TP_MAX_DROP 8.0f      // units: the settled floor must be within this of the requested Z
#define TP_MAX_XY 6.0f        // units: the physics must not push the body off the target
#define TP_MIN_MS 800         // observe at least this long before accepting a settle
#define TP_MAX_MS 3000        // give up (and restore) after this long

static CRITICAL_SECTION g_tp_cs;
static volatile LONG g_tp_state;
static int g_tp_pl, g_tp_have_dir;
static float g_tp_target[3], g_tp_dir[2], g_tp_old[3], g_tp_old_dir[3];
static DWORD g_tp_t0;
static float g_tp_prev_z;
static int g_tp_stable, g_tp_verdict;
static char g_tp_msg[160];

// Called on the game thread. Every exit goes through here so the pipe thread always sees a message.
static void tp_finish(int ok, int restore)
{
	if (restore) {
		unsigned h = player_human(g_tp_pl);
		if (h) {
			float *pos = (float *)(uintptr_t)(h + H_POS), *dir = (float *)(uintptr_t)(h + H_DIR);
			pos[0] = g_tp_old[0]; pos[1] = g_tp_old[1]; pos[2] = g_tp_old[2];
			if (g_tp_have_dir) { dir[0] = g_tp_old_dir[0]; dir[1] = g_tp_old_dir[1]; dir[2] = g_tp_old_dir[2]; }
		}
	}
	g_tp_verdict = ok;
	g_tp_state = TP_DONE;
}

// One frame of the teleport, on the game thread (prepended to frame_tick, so it also runs with no peer).
static void tp_frame(void)
{
	LONG st = g_tp_state;
	if (st != TP_START && st != TP_RUN)
		return;
	unsigned h = player_human(g_tp_pl);
	if (!h) {
		_snprintf(g_tp_msg, sizeof g_tp_msg, "error tp: no character for player %d", g_tp_pl + 1);
		tp_finish(0, 0);
		return;
	}
	float *pos = (float *)(uintptr_t)(h + H_POS);
	if (st == TP_START) {
		float *dir = (float *)(uintptr_t)(h + H_DIR);
		g_tp_old[0] = pos[0]; g_tp_old[1] = pos[1]; g_tp_old[2] = pos[2];
		g_tp_old_dir[0] = dir[0]; g_tp_old_dir[1] = dir[1]; g_tp_old_dir[2] = dir[2];
		pos[0] = g_tp_target[0]; pos[1] = g_tp_target[1]; pos[2] = g_tp_target[2];
		if (g_tp_have_dir) { dir[0] = g_tp_dir[0]; dir[1] = g_tp_dir[1]; dir[2] = 0.0f; }
		g_tp_prev_z = pos[2];
		g_tp_stable = 0;
		g_tp_t0 = GetTickCount();
		g_tp_state = TP_RUN;
		return;
	}
	{
		float x = pos[0], y = pos[1], z = pos[2];
		int ms = (int)(GetTickCount() - g_tp_t0);
		float dz = z - g_tp_target[2];
		int near_xy = fabsf_(x - g_tp_target[0]) <= TP_MAX_XY && fabsf_(y - g_tp_target[1]) <= TP_MAX_XY;
		if (fabsf_(z - g_tp_prev_z) < 0.02f)
			g_tp_stable++;
		else
			g_tp_stable = 0;
		g_tp_prev_z = z;
		if (dz < -TP_MAX_DROP) {
			_snprintf(g_tp_msg, sizeof g_tp_msg,
			          "refused: no floor at (%.1f, %.1f, %.1f) - the character fell %.1f units (z %.1f); "
			          "old position restored", g_tp_target[0], g_tp_target[1], g_tp_target[2], -dz, z);
			tp_finish(0, 1);
			return;
		}
		if (dz > TP_MAX_DROP) {
			_snprintf(g_tp_msg, sizeof g_tp_msg,
			          "refused: the floor at (%.1f, %.1f) is %.1f above the requested z (%.1f); old position restored",
			          g_tp_target[0], g_tp_target[1], dz, g_tp_target[2]);
			tp_finish(0, 1);
			return;
		}
		if (!near_xy && ms > 300) {
			_snprintf(g_tp_msg, sizeof g_tp_msg,
			          "refused: the game moved the character away from (%.1f, %.1f) to (%.1f, %.1f); old position restored",
			          g_tp_target[0], g_tp_target[1], x, y);
			tp_finish(0, 1);
			return;
		}
		if (ms >= TP_MIN_MS && g_tp_stable >= 10) {
			_snprintf(g_tp_msg, sizeof g_tp_msg, "ok settled at (%.2f, %.2f, %.2f) after %.1f s", x, y, z, ms / 1000.0f);
			tp_finish(1, 0);
			return;
		}
		if (ms >= TP_MAX_MS) {
			_snprintf(g_tp_msg, sizeof g_tp_msg,
			          "refused: no floor at (%.1f, %.1f, %.1f) - still moving after %.1f s (now z %.1f); old position restored",
			          g_tp_target[0], g_tp_target[1], g_tp_target[2], ms / 1000.0f, z);
			tp_finish(0, 1);
		}
	}
}

// Pipe-thread side: queue the request for the game thread, wait for its verdict, return it.
// safe = 0 keeps the old raw write (kept as `tpraw` for diagnostics).
static int tp_request(int pl, float x, float y, float z, int have_z, float dx, float dy, int have_dir, int safe,
                      char *reply, size_t replysz)
{
	unsigned h = player_human(pl);
	if (!h) {
		_snprintf(reply, replysz, "error tp: no character for player %d (in game?)", pl + 1);
		return 0;
	}
	if (!safe) {
		float *pos = (float *)(uintptr_t)(h + H_POS), *dir = (float *)(uintptr_t)(h + H_DIR);
		pos[0] = x; pos[1] = y; pos[2] = have_z ? z : pos[2];
		if (have_dir) { dir[0] = dx; dir[1] = dy; dir[2] = 0; }
		_snprintf(reply, replysz, "ok (raw write, not checked)");
		return 1;
	}
	EnterCriticalSection(&g_tp_cs);
	if (g_tp_state == TP_START || g_tp_state == TP_RUN) {
		LeaveCriticalSection(&g_tp_cs);
		_snprintf(reply, replysz, "error tp: another teleport is still in flight");
		return 0;
	}
	if (!have_z)
		z = *(float *)(uintptr_t)(h + H_POS + 8);
	g_tp_pl = pl;
	g_tp_target[0] = x; g_tp_target[1] = y; g_tp_target[2] = z;
	g_tp_dir[0] = dx; g_tp_dir[1] = dy;
	g_tp_have_dir = have_dir;
	g_tp_verdict = 0;
	g_tp_msg[0] = 0;
	g_tp_state = TP_START;
	LeaveCriticalSection(&g_tp_cs);
	{
		DWORD t0 = GetTickCount();
		for (;;) {
			if (g_tp_state == TP_DONE)
				break;
			if (GetTickCount() - t0 > TP_MAX_MS + 2000) {
				// The game thread never ran a frame (menu, minimised, loading): give the slot back so the
				// next teleport is not refused as "still in flight".
				g_tp_state = TP_IDLE;
				_snprintf(reply, replysz, "error tp: the game did not run a frame");
				return 0;
			}
			Sleep(10);
		}
	}
	{
		int ok = g_tp_verdict;
		_snprintf(reply, replysz, "%s", g_tp_msg);
		g_tp_state = TP_IDLE;
		return ok;
	}
}

// ---- TASK 28 TEST ONLY: finish a lock-picking mini-game the game's own way ---------------------------
//
// The CToeLockPick mini-game (FUN_004595f0, vtable+0x14) is a 3-D lock turned with the sticks; the bot
// cannot play it. This command runs the game's OWN completion on the acting copy: the lock object's use
// method (vtable+0x70 = FUN_0045ac10) with the character, in the state the game's own front-side check
// sets (+0x104 = 1), then the lock's own stop method (vtable+0x74). The shipped sync never runs another
// player's mini-game; this is a test tool like `netpause`/`netdroprx`.
#define APT_IDLE 0
#define APT_QUEUED 1
#define APT_DONE 2
#define APT_WAIT_MS 6000
#define APT_LCKP 0x4c434b50   // "LCKP", the CToeLockPick class tag

static CRITICAL_SECTION g_apt_cs;
static volatile LONG g_apt_state, g_apt_verdict;
static int g_apt_player;
static char g_apt_msg[192];

typedef void(__fastcall *apt_obj_t)(void *, void *, unsigned);

// Game thread: complete the lock pick the character player `pl` is linked to (character+0x2bc).
static void apt_frame(void)
{
	if (g_apt_state != APT_QUEUED)
		return;
	unsigned h = player_human(g_apt_player);
	unsigned e = h ? rd32(h + 0x2bc) : 0;
	unsigned cls = e ? rd32(e + 0x10) : 0;
	char ch[5], c4[5];
	if (!h || !e || cls != APT_LCKP || IsBadReadPtr((void *)(uintptr_t)e, 0x1c0)) {
		_snprintf(g_apt_msg, sizeof g_apt_msg,
		          "error aptdone: player %d is not using a lock pick (character %x action %x class %s)",
		          g_apt_player + 1, h, e, e ? tag4(cls, c4) : "----");
		g_apt_verdict = 0;
		g_apt_state = APT_DONE;
		return;
	}
	void **vt = *(void ***)(uintptr_t)e;
	if (!vt || !image_ptr((DWORD)(uintptr_t)vt) || IsBadReadPtr(vt, 0x78) ||
	    !code_in_exe((DWORD)(uintptr_t)vt[0x70 / 4]) || !code_in_exe((DWORD)(uintptr_t)vt[0x74 / 4])) {
		_snprintf(g_apt_msg, sizeof g_apt_msg, "error aptdone: lock %x has no usable vtable", e);
		g_apt_verdict = 0;
		g_apt_state = APT_DONE;
		return;
	}
	*(DWORD *)(uintptr_t)(e + 0x104) = 1;   // the front-side value FUN_0045a9e0 writes before its completion
	((apt_obj_t)(uintptr_t)vt[0x70 / 4])((void *)(uintptr_t)e, NULL, h);   // the game's own completion branch
	((apt_obj_t)(uintptr_t)vt[0x74 / 4])((void *)(uintptr_t)e, NULL, 3);   // the lock's own stop
	_snprintf(g_apt_msg, sizeof g_apt_msg, "ok aptdone: lock %x completed through its own use+stop for %s",
	          e, tag4(rd32(h + 0x14), ch));
	g_apt_verdict = 1;
	g_apt_state = APT_DONE;
}

// Pipe-thread side: queue the request for the game thread, wait for its verdict, return it.
static int aptitude_done_request(int player, char *reply, size_t replysz)
{
	EnterCriticalSection(&g_apt_cs);
	if (g_apt_state == APT_QUEUED) {
		LeaveCriticalSection(&g_apt_cs);
		_snprintf(reply, replysz, "error aptdone: another request is still in flight");
		return 0;
	}
	g_apt_player = player & 1;
	g_apt_msg[0] = 0;
	g_apt_verdict = 0;
	g_apt_state = APT_QUEUED;
	LeaveCriticalSection(&g_apt_cs);
	DWORD t0 = GetTickCount();
	while (g_apt_state != APT_DONE) {
		if (GetTickCount() - t0 > APT_WAIT_MS) {
			g_apt_state = APT_IDLE;
			_snprintf(reply, replysz, "error aptdone: the game thread did not run the request in %d s",
			          APT_WAIT_MS / 1000);
			return 0;
		}
		Sleep(10);
	}
	int ok = g_apt_verdict;
	_snprintf(reply, replysz, "%s", g_apt_msg);
	g_apt_state = APT_IDLE;
	return ok;
}

// ---- level change on the game thread (pipe `level`) --------------------------------------------------
//
// FINDINGS_22 4.3: the pipe "level" command called the game's ChangeLevel (FUN_004a1c00) straight on the
// pipe thread and two live runs hung there for minutes while both games kept running and syncing — the
// call takes state the game thread owns, so the pipe thread waited for it forever. It now runs the way
// the safe tp does: the pipe thread queues the request and waits, frame_tick makes the call on the game
// thread and publishes the verdict.
#define LVL_IDLE 0
#define LVL_QUEUED 1
#define LVL_DONE 2
#define LVL_WAIT_MS 30000

static CRITICAL_SECTION g_lvl_cs;
static volatile LONG g_lvl_state, g_lvl_verdict;
static unsigned g_lvl_tag, g_lvl_entry, g_lvl_flag;
static char g_lvl_msg[160];

// Game thread: perform a queued level change. Returns 1 when a request was handled (the caller leaves the
// frame: the game's request state machine (game+0x320 = 4) tears the world down right after this call).
static int level_frame(void)
{
	if (g_lvl_state != LVL_QUEUED)
		return 0;
	unsigned g = *(volatile unsigned *)0x6c3068;
	if (!g) {
		_snprintf(g_lvl_msg, sizeof g_lvl_msg, "error level: the game object is gone");
		g_lvl_verdict = 0;
		g_lvl_state = LVL_DONE;
		return 1;
	}
	// The same call the Cslh_ChangeLevel script command makes: FUN_004a1c00 is hooked, so the host still
	// forwards the change to the guest and the replay is not recorded as a transition the game made.
	InterlockedIncrement(&g_level_replay);
	((void(__fastcall *)(void *, void *, unsigned, unsigned, unsigned))0x4a1c00)((void *)(uintptr_t)g, NULL,
		g_lvl_tag, (unsigned)g_lvl_entry, (unsigned)g_lvl_flag);
	InterlockedDecrement(&g_level_replay);
	{
		char t[5];
		_snprintf(g_lvl_msg, sizeof g_lvl_msg, "ok level %s %u %u (game thread)", tag4(g_lvl_tag, t),
		          g_lvl_entry, g_lvl_flag);
	}
	g_lvl_verdict = 1;
	g_lvl_state = LVL_DONE;
	return 1;
}

// Pipe-thread side: queue the request for the game thread, wait for its verdict, return it.
static int level_request(unsigned tag, int entry, int flag, char *reply, size_t replysz)
{
	EnterCriticalSection(&g_lvl_cs);
	if (g_lvl_state == LVL_QUEUED) {
		LeaveCriticalSection(&g_lvl_cs);
		_snprintf(reply, replysz, "error level: another level change is still in flight");
		return 0;
	}
	g_lvl_tag = tag; g_lvl_entry = (unsigned)entry; g_lvl_flag = (unsigned)flag;
	g_lvl_msg[0] = 0;
	g_lvl_verdict = 0;
	g_lvl_state = LVL_QUEUED;
	LeaveCriticalSection(&g_lvl_cs);
	{
		DWORD t0 = GetTickCount();
		for (;;) {
			if (g_lvl_state == LVL_DONE)
				break;
			if (GetTickCount() - t0 > LVL_WAIT_MS) {
				// The game thread never ran a frame (loading, menu): give the slot back.
				g_lvl_state = LVL_IDLE;
				_snprintf(reply, replysz, "error level: the game thread did not run the request in %d s",
				          LVL_WAIT_MS / 1000);
				return 0;
			}
			Sleep(10);
		}
	}
	{
		int ok = g_lvl_verdict;
		_snprintf(reply, replysz, "%s", g_lvl_msg);
		g_lvl_state = LVL_IDLE;
		return ok;
	}
}

// ---- item use, host-authoritative (task 24 ---------------------------------------------------------
//
// FINDINGS_24 section 4: an item is used through the item object's vtable slot 28 (byte +0x70) with the
// character as the argument. That is the game's own path: the medikit (FUN_00450aa0) heals
// character life (+0x320) by maxlife*0.6 through the character's own life method and takes one from the
// item quantity (+0xc8); the energy drink (FUN_0044f6c0) heals maxlife*0.3. The whole body is guarded by
// life < maxlife, so a use at full life neither heals nor consumes. The game keeps item+0xc8 equal to
// the inventory entry's count (FUN_004b1000), so a consumed item is written back into entry+0xc.
//
// The host owns the inventory (PKT_ITEM) and the character life (ch_state): a use is applied on the HOST
// and mirrored. A guest that uses an item (its own player 2) forwards PKT_ITEMUSE instead of applying
// it locally — otherwise the host's next snapshot reverts the guest's heal and restores the quantity,
// and a use applied on both copies would be counted twice.
#define IUSE_IDLE 0
#define IUSE_QUEUED 1
#define IUSE_DONE 2
#define IUSE_WAIT_MS 10000
#define ITEM_USE_VT 0x70          // vtable slot 28 = "use on a character"

static CRITICAL_SECTION g_iuse_cs;
static volatile LONG g_iuse_state, g_iuse_verdict;
static int g_iuse_player;
static unsigned g_iuse_tag;
static char g_iuse_msg[160];
static volatile LONG g_itemuse_sent, g_itemuse_rcv, g_itemuse_applied;

typedef unsigned(__stdcall *item_find_t)(unsigned tag);

// The item object for an inventory entry: the game's own lookup first (FUN_004b0980 walks the created
// objects for a class tag); when the saved item has no live object (measured: MEDI has none), build one
// the way the game's inventory pass does - FUN_0045cdd0 creates the class instance and FUN_004b0300
// copies flags/tag/id/quantity out of the 32-byte entry. Unlike a weapon it is NOT registered in the
// world manager (it lives in the inventory), so it stays a hidden, collected item (+0xa8 = 1).
static unsigned item_object(unsigned tag, unsigned entry)
{
	static const BYTE p_new[6] = { 0x55, 0x8b, 0xec, 0x6a, 0xff, 0x68 };
	static const BYTE p_fill[6] = { 0x55, 0x8b, 0xec, 0x8b, 0x01, 0x8b };
	unsigned obj = ((item_find_t)0x4b0980)(tag), w, mgr;
	if (obj)
		return obj;
	if (!entry || !code_ok(0x45cdd0, p_new, 6) || !code_ok(0x4b0300, p_fill, 6))
		return 0;
	w = world_obj();
	mgr = w ? rd32(w + 0x1768) : 0;
	if (!mgr)
		return 0;
	obj = (unsigned)(uintptr_t)((new_weapon_t)0x45cdd0)((void *)(uintptr_t)mgr, NULL, tag);
	if (!obj || IsBadWritePtr((void *)(uintptr_t)obj, 0x120))
		return 0;
	((fill_weapon_t)0x4b0300)((void *)(uintptr_t)entry, NULL, (void *)(uintptr_t)obj);
	*(DWORD *)(uintptr_t)(obj + 0xa8) = 1;   // collected: in the inventory, not a placed world item
	return obj;
}

// Game thread: apply one item use through the game's own use method. Returns 1 when it happened.
static int item_use_apply(int player, unsigned tag, char *msg, size_t msg_sz)
{
	char t[5];
	unsigned w = world_obj(), inv = w ? rd32(w + 0x1790) : 0, ch = player_human(player);
	unsigned entry = 0, id = 0, n, item, vt, fn, i;
	int qty0, qty1;
	float before, maxlife;
	if (!inv) {
		_snprintf(msg, msg_sz, "error useitem: no inventory (no world yet)");
		return 0;
	}
	if (!ch) {
		_snprintf(msg, msg_sz, "error useitem: no character for player %d", player);
		return 0;
	}
	n = rd32(inv + 4);
	if (n > ITEM_MAX)
		n = ITEM_MAX;
	for (i = 0; i < n && !entry; i++) {
		unsigned e = inv + 8 + i * 0x20;
		if (rd32(e + 4) == tag) {   // entry: +0 flags, +4 tag, +8 id, +0xc count
			entry = e;
			id = rd32(e + 8);
		}
	}
	if (!entry) {
		_snprintf(msg, msg_sz, "error useitem: %s is not in the inventory", tag4(tag, t));
		return 0;
	}
	qty0 = (int)rd32(entry + 0xc);
	if (qty0 <= 0) {
		_snprintf(msg, msg_sz, "error useitem: %s count is 0", tag4(tag, t));
		return 0;
	}
	item = item_object(tag, entry);
	if (!item) {
		_snprintf(msg, msg_sz, "error useitem: no item object for %s (id %u)", tag4(tag, t), id);
		return 0;
	}
	if (IsBadWritePtr((void *)(uintptr_t)(item + 0xc8), 4)) {
		_snprintf(msg, msg_sz, "error useitem: bad item object %x for %s", item, tag4(tag, t));
		return 0;
	}
	*(int *)(uintptr_t)(item + 0xc8) = qty0;   // the game keeps the item count equal to the entry count
	vt = rd32(item);
	fn = vt ? rd32(vt + ITEM_USE_VT) : 0;
	if (!fn || IsBadCodePtr((FARPROC)fn)) {
		_snprintf(msg, msg_sz, "error useitem: %s has no use method (vtable %x)", tag4(tag, t), vt);
		return 0;
	}
	before = *(float *)(uintptr_t)(ch + 0x320);
	maxlife = *(float *)(uintptr_t)(ch + 0x31c);
	((void(__thiscall *)(void *, void *))fn)((void *)(uintptr_t)item, (void *)(uintptr_t)ch);
	qty1 = *(int *)(uintptr_t)(item + 0xc8);
	if (qty1 != qty0)
		*(int *)(uintptr_t)(entry + 0xc) = qty1;   // one was consumed: write it back like the inventory pass does
	_snprintf(msg, msg_sz, "ok useitem %s on player %d: life %.1f -> %.1f (max %.1f), count %d -> %d",
	          tag4(tag, t), player, before, *(float *)(uintptr_t)(ch + 0x320), maxlife, qty0, qty1);
	return 1;
}

// Any thread: hand a use to the game thread. One request at a time; a second one while one is queued is
// dropped (an item use is not something to queue up).
static void item_use_queue(int player, unsigned tag)
{
	EnterCriticalSection(&g_iuse_cs);
	if (g_iuse_state != IUSE_QUEUED) {
		g_iuse_player = player;
		g_iuse_tag = tag;
		g_iuse_msg[0] = 0;
		g_iuse_verdict = 0;
		g_iuse_state = IUSE_QUEUED;
	}
	LeaveCriticalSection(&g_iuse_cs);
}

// Game thread (frame_tick): apply a queued use.
static void item_use_frame(void)
{
	if (g_iuse_state != IUSE_QUEUED)
		return;
	g_iuse_verdict = item_use_apply(g_iuse_player, g_iuse_tag, g_iuse_msg, sizeof g_iuse_msg);
	if (g_iuse_verdict)
		InterlockedIncrement(&g_itemuse_applied);
	logf("%s: %s", g_role == 2 ? "guest" : "host", g_iuse_msg);
	g_iuse_state = IUSE_DONE;
}

// Pipe-thread side (host or solo): queue the use, wait for the game thread's verdict.
static int item_use_request(int player, unsigned tag, char *reply, size_t replysz)
{
	DWORD t0;
	if (!world_obj()) {
		_snprintf(reply, replysz, "error useitem: no world yet");
		return 0;
	}
	EnterCriticalSection(&g_iuse_cs);
	if (g_iuse_state == IUSE_QUEUED) {
		LeaveCriticalSection(&g_iuse_cs);
		_snprintf(reply, replysz, "error useitem: another use is still in flight");
		return 0;
	}
	LeaveCriticalSection(&g_iuse_cs);
	item_use_queue(player, tag);
	t0 = GetTickCount();
	while (g_iuse_state != IUSE_DONE) {
		if (GetTickCount() - t0 > IUSE_WAIT_MS) {
			g_iuse_state = IUSE_IDLE;
			_snprintf(reply, replysz, "error useitem: the game thread did not run the request in %d s",
			          IUSE_WAIT_MS / 1000);
			return 0;
		}
		Sleep(10);
	}
	{
		int ok = g_iuse_verdict;
		_snprintf(reply, replysz, "%s", g_iuse_msg);
		g_iuse_state = IUSE_IDLE;
		return ok;
	}
}

// Host network thread: the guest's own player used an item - apply it here, where the state is owned.
static void peer_on_itemuse(const char *buf, int n)
{
	const pkt_itemuse *p = (const pkt_itemuse *)buf;
	if (n != (int)sizeof *p || p->player > 3)
		return;
	InterlockedIncrement(&g_itemuse_rcv);
	logf("host: guest asked for an item use (player %u, tag %u)", p->player, p->tag);
	item_use_queue((int)p->player, p->tag);
}

// Guest: ask the host to apply a use instead of applying it here.
static int item_use_forward(int player, unsigned tag, char *reply, size_t replysz)
{
	char t[5];
	pkt_itemuse u;
	memset(&u, 0, sizeof u);
	u.player = (DWORD)player;
	u.tag = tag;
	if (!g_peer_ok) {
		_snprintf(reply, replysz, "error useitem: no link to the host");
		return 0;
	}
	net_send(PKT_ITEMUSE, &u, (WORD)(sizeof u - sizeof(pkt_hdr)));
	InterlockedIncrement(&g_itemuse_sent);
	_snprintf(reply, replysz, "ok useitem %s on player %d: forwarded to the host (it owns the inventory and the life)",
	          tag4(tag, t), player);
	return 1;
}

// ---- shared menus (TASK 36) -------------------------------------------------------------------------
// A menu is a shared session state, not a per-player screen. Each copy has ONE pause panel and ONE live
// inventory panel (world+0x1794 / world+0x179c), and the pause menu and the inventory read PLAYER 1's pad
// only (decompile 110548-110586: FUN_004b2b30(0x23, player 1's pad block)), so player 2 cannot drive them.
// The state read here was measured on both copies (FINDINGS_36 §7): world+0x11c == 5 (pause menu) / 2
// (inventory menu), controller +0xa4 == 3 (weapon wheel) / 4 (item menu).
//
// Rule 1 (input): while a menu is up, XInputGetState (obscoop2.c) hands the game the MERGED pad of both
// players on BOTH copies - same input, same game logic, so the cursor and the tab move identically. Sticks
// are merged only in the paused states (2/5); in the wheel/item menu the character can still walk, so only
// buttons and triggers are merged there.
// Rule 2 (convergence): both copies stream this state (PKT_MENU). If the peer is in a menu this copy is not
// in (or left one this copy is still in), this copy pulses the same button on the right pad - the same way
// the "guest START -> player-1 START pulse" has always worked. One pulse per correction, 400 ms apart.
#define MENU_PERIOD_MS 250
#define MENU_PEER_STALE_MS 1500
#define MENU_FRESH_MS 600       // TASK 37: a peer packet older than this is not acted on
#define MENU_SETTLE_MS 600      // TASK 37: no correction for this long after a LOCAL state change/pulse
#define MENU_STABLE_MS 500      // TASK 37: the divergence must persist this long in fresh packets
#define MENU_PULSE_MS 160
#define MENU_PULSE_GAP_MS 420

static volatile LONG g_menu_state = -1, g_menu_ui0, g_menu_ui1;        // this copy (game thread writes)
static volatile LONG g_peer_menu_state = -1, g_peer_menu_ui0, g_peer_menu_ui1, g_peer_menu_level, g_peer_menu_seq;
static volatile DWORD g_peer_menu_at;
static DWORD g_menu_sent_at, g_menu_sent_ui0 = (DWORD)-1, g_menu_sent_ui1 = (DWORD)-1;
static LONG g_menu_sent_state = -1;
static DWORD g_menu_pulse_at;
static volatile LONG g_menu_pulses, g_menu_sent, g_menu_rcv;
// TASK 37: a convergence pulse is only pressed on a STABLE, CONFIRMED divergence. The reviewer's run lost
// the inventory close to the opposite: both copies left the inventory within 9 ms, each then read the
// peer's previous packet (still "in the inventory") and pressed BACK (the open button) on its own pad,
// which re-opened it on both. So: never act within MENU_SETTLE_MS of this copy's own change, never act on a
// peer packet older than MENU_FRESH_MS, and only after the mismatch has survived MENU_STABLE_MS.
static DWORD g_menu_local_changed_at;   // this copy's own last menu change (or pulse)
static DWORD g_menu_div_since;          // when the current mismatch was first seen
static LONG g_menu_div_pst = -1;        // ... and the peer state it was seen with
static LONG g_menu_div_seq = -1;
static volatile LONG g_menu_corrections, g_menu_gated;   // pulses issued for a confirmed divergence / corrections skipped as not yet stable
// TASK 38: player 2's START edges (drop_remote_start in obscoop2.c). A START on player 2's pad cannot
// close a shared menu by itself - the game reads player 1's pad for the pause menu, and the network pulse
// only fires on the host - so menu_tick turns the edge into a START pulse on player 1's pad on THIS copy.
static DWORD g_menu_p2_edges;
// Menu changes are ordered by a sequence number, exactly like the scene sync's leave_seq (TASK 31): every
// LOCAL change bumps g_menu_my_seq, and a copy only corrects a divergence for a state NEWER than the one it
// has already applied. Without the order the two copies chase each other (measured: 2 -> 1 -> 2 ... every
// 400 ms, each copy pulsing the other). A tie goes to the host: only the guest corrects on a tie.
static DWORD g_menu_my_seq, g_menu_seen_seq;

// The world's menu state and the two controllers' UI state.
static void menu_read(int *state, int *ui0, int *ui1)
{
	int st = 0, u0 = 0, u1 = 0;
	unsigned w = world_obj();
	if (w) {
		unsigned s = rd32(w + 0x11c);
		if (s < 0x40)
			st = (int)s;
		unsigned ctl = rd32(w + 0x1748);
		if (ctl && !IsBadReadPtr((const void *)(uintptr_t)ctl, 0x764 + 0xa8)) {
			unsigned a = rd32(ctl + 0xa4), b = rd32(ctl + 0x764 + 0xa4);
			if (a < 8) u0 = (int)a;
			if (b < 8) u1 = (int)b;
		}
	}
	*state = st;
	*ui0 = u0;
	*ui1 = u1;
}

// The two world states measured as menus: 2 = the live inventory (CMenuInventoryLive: WEAPONS/ITEMS/TEAM and
// the documents/map panels it opens), 5 = the pause menu. Other states (6 cinematic, 0x11 game over, the
// load states) are NOT menus and must never be opened or closed by this code.
static int menu_world_menu(int st)
{
	return st == 2 || st == 5;
}

// Called from XInputGetState (obscoop2.c) on every poll: is a menu up, so the two pads must be merged?
// Only the two SHARED menus (inventory 2, pause 5) merge the pads: the wheel and the item menu are one
// player's own (and last a button hold), so merging there could hand one player's A to the other player's
// character during normal play.
int menu_input_active(void)
{
	if (g_role == 0 || !g_peer_ok)
		return 0;   // solo / no link: each pad stays its own
	return menu_world_menu((int)g_menu_state);
}

// Called from XInputGetState: may the merged pad also move the CHARACTER? Only in the paused menu states;
// in the wheel / item menu the characters still walk, so only buttons and triggers are merged there.
int menu_paused(void)
{
	return menu_world_menu((int)g_menu_state);
}

// Pipe/status text (game thread values; the pipe thread reads them at its own risk, like the other dumps).
static void menu_status(char *reply, size_t replysz)
{
	int st, ui0, ui1;
	menu_read(&st, &ui0, &ui1);
	_snprintf(reply, replysz,
	          "menu local st %d ui %d/%d seq %lu | peer st %ld ui %ld/%ld seq %ld age %lu ms | sent %ld rcv %ld pulses %ld "
	          "correct %ld gated %ld",
	          st, ui0, ui1, (unsigned long)g_menu_my_seq, g_peer_menu_state, g_peer_menu_ui0, g_peer_menu_ui1,
	          g_peer_menu_seq, (unsigned long)(g_peer_menu_at ? GetTickCount() - g_peer_menu_at : 0),
	          g_menu_sent, g_menu_rcv, g_menu_pulses, g_menu_corrections, g_menu_gated);
}

// Network thread: the peer's menu state (a convergence signal, not the data the menu is drawn from).
static void peer_on_menu(const char *buf, int n)
{
	const pkt_menu *p = (const pkt_menu *)buf;
	if (n != (int)sizeof *p)
		return;
	g_peer_menu_state = (LONG)p->state;
	g_peer_menu_ui0 = (LONG)p->ui0;
	g_peer_menu_ui1 = (LONG)p->ui1;
	g_peer_menu_level = (LONG)p->level;
	g_peer_menu_seq = (LONG)p->seq;
	g_peer_menu_at = GetTickCount();
	InterlockedIncrement(&g_menu_rcv);
}

// A short press of a button on one pad, through XInputGetState (obscoop2.c).
static void menu_pulse(int user, unsigned buttons, int rt, char what)
{
	menu_pulse_start(user, buttons, rt, MENU_PULSE_MS);
	g_menu_pulse_at = GetTickCount();
	g_menu_local_changed_at = g_menu_pulse_at;   // TASK 37: do not correct again before the settle window is over
	InterlockedIncrement(&g_menu_pulses);
	logf("%s: sharing the menu: pulsing %c on player %d's pad (peer menu %ld, this copy %ld)", 
	     g_role == 2 ? "guest" : "host", what, user + 1, g_peer_menu_state, g_menu_state);
}

// Game thread, once per frame: publish this copy's menu state and repair a divergence.
static void menu_tick(void)
{
	if (g_role == 0)
		return;
	int st, ui0, ui1;
	menu_read(&st, &ui0, &ui1);
	int prev = (int)g_menu_state;
	g_menu_state = st;
	g_menu_ui0 = ui0;
	g_menu_ui1 = ui1;
	if (!g_peer_ok)
		return;
	DWORD now = GetTickCount();
	// TASK 38: player 2's START while a shared menu is up: make it a START press on player 1's pad on this
	// copy, the same edge the host's network pulse makes there. It is an EDGE, and only while the menu
	// was ALREADY up at the previous tick (prev and st both a menu): the press that opened the menu can
	// never close it again, whichever copy opened it or however the open pulse reached this copy.
	DWORD edges = (DWORD)g_p2_start_edges;
	if (edges != g_menu_p2_edges) {
		g_menu_p2_edges = edges;
		if (menu_world_menu(prev) && menu_world_menu(st))
			menu_pulse(0, 0x0010, 0, 'S');
	}
	// TASK 37: while EITHER copy is in a menu, both keep publishing (a menu session). That is what makes
	// the freshness rule below possible: the copy that is back in normal play still says so every 250 ms.
	int active = menu_world_menu(st) || ui0 >= 3 || ui1 >= 3 || menu_world_menu((int)g_peer_menu_state);
	int changed = st != g_menu_sent_state || (DWORD)ui0 != g_menu_sent_ui0 || (DWORD)ui1 != g_menu_sent_ui1;
	if (st != prev) {   // a LOCAL change: it becomes the newest state of the pair (see g_menu_my_seq)
		g_menu_my_seq = (g_menu_my_seq > g_menu_seen_seq ? g_menu_my_seq : g_menu_seen_seq) + 1;
		g_menu_local_changed_at = now;
	}
	if (changed || (active && now - g_menu_sent_at >= MENU_PERIOD_MS)) {
		unsigned w = world_obj();
		pkt_menu p;
		memset(&p, 0, sizeof p);
		p.level = w ? rd32(w + 4) : 0;
		p.state = (DWORD)st;
		p.ui0 = (DWORD)ui0;
		p.ui1 = (DWORD)ui1;
		p.seq = g_menu_my_seq;
		p.owner = (DWORD)(ui0 != (int)g_menu_sent_ui0 ? 0 : (ui1 != (int)g_menu_sent_ui1 ? 1 : -1));
		net_send(PKT_MENU, &p, (WORD)(sizeof p - sizeof(pkt_hdr)));
		InterlockedIncrement(&g_menu_sent);
		g_menu_sent_at = now;
		g_menu_sent_state = st;
		g_menu_sent_ui0 = (DWORD)ui0;
		g_menu_sent_ui1 = (DWORD)ui1;
		if (st != prev && (menu_world_menu(st) || menu_world_menu(prev)))
			logf("%s: menu state %d -> %d (ui %d/%d, level %08lx, seq %lu)", g_role == 2 ? "guest" : "host", prev, st,
			     ui0, ui1, (unsigned long)(w ? rd32(w + 4) : 0), (unsigned long)g_menu_my_seq);
	}
	if (g_peer_menu_state < 0 || now - g_peer_menu_at > MENU_PEER_STALE_MS)
		return;
	int pst = (int)g_peer_menu_state;
	int pseq = (int)g_peer_menu_seq;
	// Is there a divergence at all, and which way? 1 = the peer is in a shared menu this copy is not in;
	// 2 = this copy is in one the peer has left.
	int diverge = menu_world_menu(pst) && st == 1 ? 1 : (pst == 1 && menu_world_menu(st) ? 2 : 0);
	if (!diverge) {
		g_menu_div_since = 0;
		g_menu_div_pst = -1;
		g_menu_div_seq = -1;
		return;
	}
	// TASK 37: a correction is only pressed on a confirmed divergence (see the constants above).
	if (now - g_menu_local_changed_at < MENU_SETTLE_MS)
		return;   // this copy's own menu state just changed: the peer's packet about it may still be on the way
	if (!g_peer_menu_at || now - g_peer_menu_at > MENU_FRESH_MS)
		return;   // the peer's word is not fresh: it may already have moved on (this is the reviewer's flake)
	if (g_menu_div_pst != pst || g_menu_div_seq != pseq) {
		g_menu_div_pst = pst;
		g_menu_div_seq = pseq;
		g_menu_div_since = now;
		InterlockedIncrement(&g_menu_gated);
		return;   // a new divergence (or a new reason): start its stability clock and wait
	}
	if (!g_menu_div_since)
		g_menu_div_since = now;
	if (now - g_menu_div_since < MENU_STABLE_MS)
		return;   // not confirmed yet
	if (pseq > (int)g_menu_seen_seq) {
		g_menu_seen_seq = (DWORD)pseq;   // the peer's newest change: this copy follows it
	} else {
		if (pseq < (int)g_menu_seen_seq)
			return;                     // an older state than the one already applied: never act on it
		if (g_role != 2)
			return;                     // a tie: the host does not correct, so the two cannot chase each other
	}
	if (now - g_menu_pulse_at < MENU_PULSE_GAP_MS)
		return;
	unsigned w = world_obj();
	DWORD lvl = w ? rd32(w + 4) : 0;
	if ((DWORD)g_peer_menu_level != lvl)
		return;   // the peer's menu state is from another level
	if (diverge == 1) {
		// the peer opened a menu this copy did not see: press the same button here
		InterlockedIncrement(&g_menu_corrections);
		if (pst == 5)
			menu_pulse(0, 0x0010, 0, 'S');    // START: the pause menu (probe: opens on both)
		else
			menu_pulse(0, 0x0020, 0, 'B');    // BACK: the inventory menu (probe: st 2 on both)
		return;
	}
	{   // the peer left the menu and this copy is still in it: press the same button to leave
		InterlockedIncrement(&g_menu_corrections);
		if (st == 5)
			menu_pulse(0, 0x0010, 0, 'S');    // START leaves the pause menu (FUN_004b2770)
		else
			menu_pulse(0, 0x2000, 0, 'A');    // A leaves the inventory (B is 0x2000 on the pad; measured: st 1 on both)
		return;
	}
	// The wheel (3) / item menu (4) are not repaired here: they are one player's own pad hold, already
	// carried by the pad stream on both copies, and a pulse there would disturb normal play.
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
	InitializeCriticalSection(&g_prop_cs);
	InitializeCriticalSection(&g_tp_cs);
	InitializeCriticalSection(&g_lvl_cs);
	InitializeCriticalSection(&g_iuse_cs);
	InitializeCriticalSection(&g_aptq_cs);   // TASK 28
	InitializeCriticalSection(&g_apt_cs);     // TASK 28 pipe `aptdone`
	InitializeCriticalSection(&g_scene_cs);   // TASK 30 (rx thread / game thread / pipe thread)
	InitializeCriticalSection(&g_door_cs);    // TASK 34 (rx thread / game thread)
	InitializeCriticalSection(&g_pb_cs);      // TASK 42 (rx thread / game thread): the puppet buffer
}

// Guest, game thread (TASK 37): the host is the only authority for the level. When this copy has been in
// a different level for LVL_HEAL_MS while both copies are idle, follow the host's level with the game's own
// ChangeLevel (the late-join path: the party table for that level is applied by hk_party_table when it is
// here, and the state stream corrects the characters). This is the guarantee that two transitions which
// raced can never leave the copies apart for good.
static void guest_level_heal(void)
{
	if (g_role != 2 || !g_peer_ok) {
		g_lvl_mismatch_since = 0;
		return;
	}
	DWORD now = GetTickCount();
	LONG hl = g_host_lvl;
	if (!hl || !g_host_lvl_at || now - g_host_lvl_at > LVL_HEAL_FRESH_MS || g_host_busy) {
		g_lvl_mismatch_since = 0;   // no fresh word from the host, or it is mid-transition itself
		return;
	}
	int queued;
	EnterCriticalSection(&g_req_cs);
	queued = g_req_head != g_req_tail;
	LeaveCriticalSection(&g_req_cs);
	unsigned g = game_obj(), w = world_obj();
	if (queued || !g || !w || rd32(g + 0x310) != 1 || rd32(g + 0x320) != 0) {
		g_lvl_mismatch_since = 0;   // a request is in flight or this copy is not in a live level
		return;
	}
	unsigned mine = rd32(w + 4);
	if (!mine || mine == (unsigned)hl) {
		if (g_lvl_mismatch_since) {
			char a[5], b[5];
			logf("guest: level %s matches the host again (%s): no self-heal needed", tag4(mine, a), tag4((unsigned)hl, b));
		}
		g_lvl_mismatch_since = 0;
		g_heal_tries = 0;
		return;
	}
	if (door_animation_running() || scene_local_cinematic())
		return;   // never rebuild the world under a door animation or a scripted event
	if (!g_lvl_mismatch_since) {
		char a[5], b[5];
		g_lvl_mismatch_since = now;
		logf("guest: level %s != host %s: waiting %d ms with both copies idle before following the host",
		     tag4(mine, a), tag4((unsigned)hl, b), LVL_HEAL_MS);
		return;
	}
	if (now - g_lvl_mismatch_since < LVL_HEAL_MS)
		return;
	if (g_heal_tries >= 3) {
		if (g_heal_tries == 3) {
			g_heal_tries = 4;
			logf("guest: the self-heal did not take the world to the host's level 3 times: not trying again until the copies agree");
		}
		return;
	}
	char a[5], b[5];
	logf("guest: SELF-HEAL: this copy is in %s, the host is in %s for %u ms with both copies idle: following the host",
	     tag4(mine, a), tag4((unsigned)hl, b), (unsigned)(now - g_lvl_mismatch_since));
	g_lvl_mismatch_since = 0;
	g_heal_tries++;
	// The host's newest transition is older than this heal by definition: never apply a repeat of it here.
	if (g_host_seq > 0 && (DWORD)g_host_seq > g_trans_applied)
		g_trans_applied = (DWORD)g_host_seq;
	g_accept_at = now + 4500;   // the rebuilt world may ask "player 2 is joining" again
	g_accept_until = g_accept_at + 150;
	g_apply_host_req = 1;
	if (g_change_level)
		g_change_level((void *)(uintptr_t)g, NULL, (unsigned)hl, (unsigned)g_host_entry, 1);
	g_apply_host_req = 0;
	InterlockedIncrement(&g_heals);
}

static void frame_tick(void)
{
	hang_note_frame();   // TASK 35: heartbeat for the stall watchdog (src/hang.c)
	InterlockedIncrement(&g_frames);   // a game thread that stops shows as a frozen count in `sync`
	// TASK 35: every mod step names itself before it runs, so a stall report from the watchdog says
	// whether the game thread never came back from a mod call or stopped in the game's own code.
	hang_phase("in level_frame (pipe level change)");
	if (level_frame())   // a pipe level change was queued: run it here and leave the frame to the game
		return;
	hang_phase("in tp_frame (safe teleport)");
	tp_frame();   // safe teleport: must run with no peer too (TASK 17 Part A)
	hang_phase("in apt_frame (test: lock-picking completion)");
	apt_frame();   // TASK 28 TEST ONLY: finish a queued lock-picking mini-game (pipe `aptdone`)
	hang_phase("in item_use_frame (item use / PKT_ITEMUSE)");
	item_use_frame();   // a queued item use (pipe `useitem`, or the guest's PKT_ITEMUSE on the host)
	if (!g_role) {
		hang_phase("game code after frame_tick (no role)");
		return;
	}
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
	hang_phase("in net_frame (status window title + packets)");
	net_frame();
	if (!g_peer_ok) {
		hang_phase("game code after frame_tick (no peer)");
		return;
	}
	hang_phase("in menu_tick (shared menus)");
	menu_tick();   // TASK 36: publish the menu state and make both copies show the same menu
	hang_phase("in world_gen_tick (world generation)");
	world_gen_tick();   // TASK 40: every entity table is keyed on this world generation
	{   // every 10 s: a line the testers can send along with the log
		static DWORD last_stat;
		DWORD now = GetTickCount();
		if (now - last_stat >= 10000) {
			last_stat = now;
			// TASK 42: the puppet numbers. "drift" is how far the game's own update moved the puppet away
			// from the owner's pose before this copy put it back (0 = the two simulations agree); "anim"
			// is how often the puppet showed exactly the state the owner streamed.
			{
				char ot[5], pt[5];
				unsigned own = player_human(g_role == 1 ? 0 : 1), pup = player_human(g_role == 1 ? 1 : 0);
				long an = (long)g_pb_anim_ok + (long)g_pb_anim_diff;
				logf("puppet stats: own %s at %.1f,%.1f,%.1f | peer %s %s at %.1f,%.1f,%.1f (stream %s, delay %.0f ms) | "
				     "drift mean %.2f max %.2f over %ld updates, anim %ld/%ld (%.0f%%), %ld state sets, %ld underruns, %ld extrapolated | rtt %ld ms",
				     tag4(own ? rd32(own + H_TAG) : 0, ot),
				     own ? *(const float *)(uintptr_t)(own + H_POS) : 0.0f,
				     own ? *(const float *)(uintptr_t)(own + H_POS + 4) : 0.0f,
				     own ? *(const float *)(uintptr_t)(own + H_POS + 8) : 0.0f,
				     tag4(pup ? rd32(pup + H_TAG) : 0, pt), pup ? "local" : "none",
				     pup ? *(const float *)(uintptr_t)(pup + H_POS) : 0.0f,
				     pup ? *(const float *)(uintptr_t)(pup + H_POS + 4) : 0.0f,
				     pup ? *(const float *)(uintptr_t)(pup + H_POS + 8) : 0.0f,
				     g_pb_tag ? "live" : "none", g_pb_delay,
				     g_pb_err_n ? g_pb_err_sum / g_pb_err_n : 0.0f, g_pb_err_max, g_pb_err_n,
				     (long)g_pb_anim_ok, an, an ? 100.0 * (double)g_pb_anim_ok / (double)an : 0.0,
				     g_pb_anim_sets, g_pb_under, g_pb_extrap, g_net_rtt_ms);
				// TASK 46: the intent path - state-change events recorded/replayed, frames where the
				// game's own movement machine ran for the puppet / was gated by the action states, and
				// the puppet's own move direction (what the machine consumes).
				logf("puppet intent: events recorded %ld replayed %ld | movement machine ran %ld gated %ld | peer intent %.2f,%.2f",
				     (long)g_ev_rec, (long)g_ev_rep, (long)g_puppet_move_run, (long)g_puppet_move_gated,
				     pup ? *(const float *)(uintptr_t)(pup + 0x288) : 0.0f,
				     pup ? *(const float *)(uintptr_t)(pup + 0x28c) : 0.0f);
				// TASK 43: which guard of puppet_target() refused this copy's puppet in the last 10 s.
				{
					char gs[220];
					int l = 0;
					gs[0] = 0;
					for (int i = 0; i < PUP_GUARDS; i++) {
						LONG n = InterlockedExchange(&g_pup_rej[i], 0);
						if (!n)
							continue;
						l += _snprintf(gs + l, sizeof gs - l, "%s%s %ld", l ? ", " : "", g_pup_guard_name[i], (long)n);
						if (l < 0 || l >= (int)sizeof gs)
							break;
					}
					if (gs[0])
						logf("puppet guards (last 10 s): %s", gs);
				}
			}
			g_pb_err_sum = 0; g_pb_err_max = 0; g_pb_err_n = 0;
			g_stat_sum = 0; g_stat_max = 0; g_stat_n = 0;
		}
	}
	if (g_role == 1) {
		if (g_join_pending) {
			g_join_pending = 0;
			host_welcome_guest();
		}
		hang_phase("in host_watch_level");
		host_watch_level();
		hang_phase("in host_repeat_tick");
		host_repeat_tick();
		hang_phase("in host_send_saves");
		host_send_saves();
		hang_phase("in host_send_state");
		host_send_state();
		hang_phase("in host_send_npcs");
		host_send_npcs();
		hang_phase("in host_send_progress");
		host_send_progress(0);
		hang_phase("in scene_tick (host)");
		scene_tick();                   // TASK 30: mirror the world's scripted-event state / apply a skip
		hang_phase("in door_tick (host)");
		door_tick();                    // TASK 34: door uses / transition objects on both copies
		hang_phase("in peer_apply_pickups (host)");
		peer_apply_pickups();
		hang_phase("in prop_tick (host)");
		prop_tick();                // TASK 26: chairs/boxes: carry and break state
		hang_phase("in apt_tick (host)");
		apt_tick();                 // TASK 28: character abilities on level objects
	} else {
		hang_phase("in attach_player2");
		attach_player2();
		hang_phase("in guest_apply_requests (the host's level/load request)");
		guest_apply_requests();
		hang_phase("in guest_apply_regions");
		guest_apply_regions();
		hang_phase("in guest_level_heal");
		guest_level_heal();         // TASK 37: follow the host's level if the copies ended apart
		hang_phase("in guest_apply_state (PKT_STATE)");
		guest_apply_state();
		hang_phase("in guest_apply_npcs");
		guest_apply_npcs();
		hang_phase("in peer_apply_pickups (guest)");
		peer_apply_pickups();
		hang_phase("in prop_tick (guest)");
		prop_tick();                // TASK 26: chairs/boxes: carry and break state
		hang_phase("in apt_tick (guest)");
		apt_tick();                 // TASK 28: character abilities on level objects
		hang_phase("in scene_tick (guest)");
		scene_tick();               // TASK 30: mirror the world's scripted-event state / apply a skip
		hang_phase("in door_tick (guest)");
		door_tick();                // TASK 34: door uses / transition objects on both copies
		hang_phase("in guest_follow_own_player");
		guest_follow_own_player();
		hang_phase("in guest_debug_p1");
		guest_debug_p1();
	}
	hang_phase("in the game's own code after frame_tick (update/render)");
}

static void sync_status(char *reply, size_t replysz)
{
	_snprintf(reply, replysz, "sync role %s sent %ld recv %ld applied %ld snaps %ld blends %ld skipped_level %ld timed %ld req_sent %ld req_applied %ld",
		g_role == 1 ? "host" : g_role == 2 ? "guest" : "off", g_snd_states, g_rcv_states, g_applied, g_snaps, g_blends,
		g_skipped_level, g_timed_corr, g_req_sent, g_req_applied);
	size_t l = strlen(reply);
	if (l < replysz)
		_snprintf(reply + l, replysz - l, " | prog sent %ld rcv %ld applied %ld | npc sent %ld rcv %ld applied %ld snaps %ld blends %ld unmatched %ld life %ld dead %ld state %ld | cam sets %ld", g_prog_chunks_sent, g_prog_chunks_rcv, g_prog_chunks_applied, g_npc_sent, g_npc_rcv,
			g_npc_applied, g_npc_snaps, g_npc_blends, g_npc_unmatched, g_npc_life, g_npc_dead, g_npc_state, g_cam_sets);
	l = strlen(reply);
	if (l < replysz)
		_snprintf(reply + l, replysz - l, " | saves_done %ld | real load stage %ld at %lu | pickup sent %ld rcv %ld applied %ld already %ld missing %ld",
			(long)g_saves_done, (long)g_real_load_stage, (unsigned long)g_real_load_at,
			g_pickup_sent, g_pickup_rcv, g_pickup_applied, g_pickup_skipped, g_pickup_missing);
	l = strlen(reply);
	if (l < replysz)
		_snprintf(reply + l, replysz - l, " | char sent %ld rcv %ld applied %ld blends %ld snaps %ld skipped %ld extrap %ld"
			" | puppet delay %.0f ms under %ld anim_sets %ld anim_diff %ld anim_ok %ld writes %ld",
			g_char_sent, g_char_rcv, g_char_applied, g_char_blends, g_char_snaps, g_char_skipped, g_pb_extrap,
			g_pb_delay, g_pb_under, g_pb_anim_sets, g_pb_anim_diff, g_pb_anim_ok, g_pb_writes);
	l = strlen(reply);
	if (l < replysz)
		_snprintf(reply + l, replysz - l, " | prop sent %ld rcv %ld applied %ld broke %ld drop %ld missing %ld",
			g_prop_sent, g_prop_rcv, g_prop_applied, g_prop_broken, g_prop_drop, g_prop_missing);
	l = strlen(reply);
	l = strlen(reply);
	if (l < replysz)
		_snprintf(reply + l, replysz - l, " | apt sent %ld rcv %ld applied %ld actions %ld",
			g_apt_sent, g_apt_rcv, g_apt_applied, g_apt_actions);
	l = strlen(reply);
	if (l < replysz)
		_snprintf(reply + l, replysz - l, " | puppet gated %ld frames %ld moves %ld", g_puppet_gated, g_puppet_frames,
		          g_pb_moves);   // TASK 45: moves = SetPosition calls (the collision body follows the pose)
	l = strlen(reply);
	if (l < replysz)
		_snprintf(reply + l, replysz - l, " | door sent %ld rcv %ld applied %ld missed %ld | ask sent %ld pend %ld",
			g_door_sent, g_door_rcv, g_door_applied, g_door_missed, g_ask_sent, (long)g_ask_pending);
	l = strlen(reply);
	if (l < replysz) {
		char hl[5];
		_snprintf(reply + l, replysz - l, " | trans applied %lu queued %lu stale %ld heal %ld host level %s busy %ld",
			(unsigned long)g_trans_applied, (unsigned long)g_trans_queued, g_trans_stale, g_heals,
			g_host_lvl ? tag4((unsigned)g_host_lvl, hl) : "-", g_host_busy);
	}
	l = strlen(reply);
	if (l < replysz)
		_snprintf(reply + l, replysz - l, " | teammate restores %ld", g_teammate_restores);
	l = strlen(reply);
	if (l < replysz)
		_snprintf(reply + l, replysz - l, " | frames %ld", g_frames);
}
