// Logging hooks on the game's request functions (Obscure II build 215294, addresses from the decompile).
// They are called with ECX = the game object (*(0x6c3068)); the game's own state machine at game+0x320
// then runs the request: 2 load progress, 3 load by name, 4 change level, 9 back to the menu.
// Included from obscoop2.c.

// Jumps from the function's entry to hook, after copying its first len bytes to a trampoline.
// The copied bytes must be whole position-independent instructions.
static BYTE *hook_entry(BYTE *f, const BYTE *prologue, int len, void *hook, const char *what)
{
	if (memcmp(f, prologue, len)) {
		logf("hook: %s prologue differs; not hooked", what);
		return NULL;
	}
	BYTE *t = VirtualAlloc(NULL, 32, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
	if (!t)
		return NULL;
	memcpy(t, f, len);
	t[len] = 0xe9;
	*(LONG *)(t + len + 1) = (LONG)((f + len) - (t + len + 5));
	DWORD old;
	VirtualProtect(f, len, PAGE_EXECUTE_READWRITE, &old);
	f[0] = 0xe9;
	*(LONG *)(f + 1) = (LONG)((BYTE *)hook - (f + 5));
	memset(f + 5, 0x90, len - 5);
	VirtualProtect(f, len, old, &old);
	FlushInstructionCache(GetCurrentProcess(), f, len);
	logf("hook: %s hooked", what);
	return t;
}

// A level tag is a dword of four ASCII characters, first character in the top byte ("B101" = 0x42313031).
static const char *tag4(unsigned v, char *out)
{
	out[0] = (char)(v >> 24); out[1] = (char)(v >> 16); out[2] = (char)(v >> 8); out[3] = (char)v; out[4] = 0;
	for (int i = 0; i < 4; i++)
		if (out[i] < 32 || out[i] > 126)
			out[i] = '?';
	return out;
}

// TASK 20: record a transition the game itself requested, so the pipe "level" allowlist grows from
// real observations only. Test-only: nothing is written unless OBSCOOP_LEVELS_LOG is set (the test
// runners set it). One line per distinct (tag, entry, flag); the file lives next to the DLL.
static void level_record_real(unsigned level, unsigned entry, unsigned flag)
{
	char t[5];
	tag4(level, t);
	if (t[0] == '?')
		return;
	char line[160];
	int existed = 1;
	FILE *f = fopen("obscoop_levels.txt", "r");
	if (f) {
		char et[8];
		unsigned e, fl;
		while (fgets(line, sizeof line, f)) {
			if (line[0] == '#' || sscanf(line, "%7s %u %u", et, &e, &fl) != 3)
				continue;
			if (!strcmp(et, t) && e == entry && fl == flag) {
				fclose(f);
				return;
			}
		}
		fclose(f);
	} else {
		existed = 0;
	}
	f = fopen("obscoop_levels.txt", existed ? "a" : "w");
	if (!f)
		return;
	if (!existed)
		fprintf(f, "# tag entry flag - only transitions seen from a real ChangeLevel may be requested\n");
	fprintf(f, "%s %u %u\n", t, entry, flag);
	fclose(f);
	logf("levels: recorded real transition %s %u %u", t, entry, flag);
}

static volatile LONG g_req_seq;   // number of requests seen, for tests
static volatile LONG g_req_sent;  // requests forwarded to the guest (host)
static unsigned g_last_level, g_last_entry, g_last_flag;   // host: the level the party is in, for a joining guest
static int g_apply_host_req;      // guest: the request being made comes from the host, let it through
static volatile DWORD g_guest_load_until; // guest: its own save load may change the level for this window

typedef void(__fastcall *req3_t)(void *, void *, unsigned, unsigned, unsigned);
typedef void(__fastcall *req1_t)(void *, void *, unsigned);
typedef void(__fastcall *req0_t)(void *, void *);
typedef int(__fastcall *party_t)(void *, void *, int, unsigned, unsigned, int *);
static req3_t g_change_level;
static req1_t g_load_progress, g_load_name;
static req0_t g_to_menu;
static party_t g_party_table;
static void host_level_request_repeat(unsigned level, unsigned entry, unsigned flag);   // sync.c
static void host_load_request_repeat(const char *name);   // sync.c
static void guest_note_own_level(unsigned level, unsigned entry, unsigned flag);   // sync.c (TASK 34)
static void test_hold_party(void);                    // sync.c
static void host_send_progress(int force);            // sync.c
static int guest_party_copy(unsigned level, BYTE *out);   // sync.c: the host's party table for this level
static void game_load_tick(unsigned game);                // sync.c: a real save load, on the game thread
static void host_save_include(const char *name);          // sync.c: remember the loaded file, send it to the guest
static void host_save_forget(void);                       // sync.c: the world no longer comes from a save file

// TASK 34: a level change this copy performed for the guest's ask (PKT_LEVELASK). The guest's own copy
// of the same door calls ChangeLevel a moment later; that call is the same transition and must not
// rebuild the world a second time (the owner's back-and-forth door glitch).
static DWORD g_ask_done_level, g_ask_done_at;

// Host, game thread: perform the level change the guest's own game asked for (its door script calls
// ChangeLevel every frame and the guest drops it), then tell the guest exactly like a local request does.
static void host_apply_guest_level(unsigned level, unsigned entry, unsigned flag)
{
	char t[5];
	if (g_role != 1 || !g_peer_ok)
		return;
	unsigned g = *(volatile unsigned *)0x6c3068;
	if (!g || *(unsigned *)((BYTE *)g + 0x310) != 1) {
		logf("host: the guest asked for ChangeLevel %s, but this copy is not in a level", tag4(level, t));
		return;
	}
	if (level == g_last_level) {
		logf("host: the guest asked for ChangeLevel %s: already here", tag4(level, t));
		return;
	}
	DWORD now = GetTickCount();
	if (g_ask_done_level == level && (LONG)(now - g_ask_done_at) < 2000) {
		logf("host: the guest's ask for %s is the change just made here: ignored", tag4(level, t));
		return;
	}
	logf("host: the guest asked for ChangeLevel %s (0x%08x) entry %u flag %u: doing it here", tag4(level, t), level,
		entry, flag);
	g_ask_done_level = level;
	g_ask_done_at = now;
	test_hold_party();
	host_send_progress(1);   // the party table must reach the guest before the level it belongs to
	((req3_t)g_change_level)((void *)(uintptr_t)g, NULL, level, entry, flag);
	g_last_level = level;
	g_last_entry = entry;
	g_last_flag = flag;
	net_send_req(REQ_LEVEL, level, entry, flag, NULL);
	InterlockedIncrement(&g_req_sent);
	host_level_request_repeat(level, entry, flag);
	g_accept_at = GetTickCount() + 4500;   // the rebuilt world asks "player 2 is joining" again
	g_accept_until = g_accept_at + 150;
}

static void __fastcall hk_change_level(void *game, void *edx, unsigned level, unsigned entry, unsigned flag)
{
	char t[5];
	InterlockedIncrement(&g_req_seq);
	if (g_role == 2 && g_peer_ok && !g_apply_host_req &&
	    (LONG)(GetTickCount() - g_guest_load_until) >= 0) {   // guest: only the host changes levels,
		guest_note_own_level(level, entry, flag);   // except its own save load; TASK 34 asks the host
		return;
	}
	// TASK 34: this copy's own door path asking for the level the guest just asked for: one change, not two.
	if (g_role == 1 && !g_apply_host_req && g_ask_done_level == level &&
	    (LONG)(GetTickCount() - g_ask_done_at) < 2000) {
		logf("request ChangeLevel %s is the change just made for the guest: not applied again", tag4(level, t));
		g_last_level = level;
		g_last_entry = entry;
		g_last_flag = flag;
		return;
	}
	logf("request ChangeLevel level %s (0x%08x) entry %u flag %u [mode %u state %u]", tag4(level, t), level, entry, flag,
		*(unsigned *)((BYTE *)game + 0x310), *(unsigned *)((BYTE *)game + 0x320));
	// TASK 20: in TEST runs every transition the game itself requests is added to the pipe "level"
	// allowlist (obscoop_levels.txt next to the DLL). A replayed transition is not a new observation.
	if (g_role != 2 && !g_level_replay && getenv("OBSCOOP_LEVELS_LOG"))
		level_record_real(level, entry, flag);
	g_change_level(game, edx, level, entry, flag);
	g_last_level = level; g_last_entry = entry; g_last_flag = flag;
	if (g_role == 1 && g_peer_ok) {   // after a load the game asks "player 2 is joining"; accept it once
		g_accept_at = GetTickCount() + 4500; g_accept_until = g_accept_at + 150;
		logf("join dialog: auto-accept pulse in 4.5 s");
	}
	if (g_role == 1 && !g_apply_host_req && g_peer_ok) {
		net_send_req(REQ_LEVEL, level, entry, flag, NULL);
		InterlockedIncrement(&g_req_sent);
		host_level_request_repeat(level, entry, flag);   // PKT_REQ is not reliable: repeat it for a moment
	}
}

static void __fastcall hk_load_progress(void *game, void *edx, unsigned arg)
{
	InterlockedIncrement(&g_req_seq);
	logf("request LoadProgress arg %u [mode %u]", arg, *(unsigned *)((BYTE *)game + 0x310));
	if (g_role == 1)   // a new game: the host's world no longer comes from a save file
		host_save_forget();
	if (g_role == 2 && !g_apply_host_req) {   // the guest's own save load: let its ChangeLevel through
		g_guest_load_until = GetTickCount() + 5000;
		logf("guest: own save load, allowing its ChangeLevel for 5 s");
	}
	g_load_progress(game, edx, arg);
	if (g_role == 1 && g_peer_ok) {
		g_accept_at = GetTickCount() + 4500; g_accept_until = g_accept_at + 150;
		logf("join dialog: auto-accept pulse in 4.5 s");
	}
	if (g_role == 1 && !g_apply_host_req && g_peer_ok) {
		net_send_req(REQ_LOAD_PROGRESS, arg, 0, 0, NULL);
		InterlockedIncrement(&g_req_sent);
	}
}

static void __fastcall hk_load_name(void *game, void *edx, unsigned name)
{
	InterlockedIncrement(&g_req_seq);
	logf("request LoadByName \"%.60s\" [mode %u]", name ? (const char *)name : "(null)", *(unsigned *)((BYTE *)game + 0x310));
	if (g_role == 1 && name)   // the file this load names: a guest that joins later must get exactly it
		host_save_include((const char *)name);
	g_load_name(game, edx, name);
	if (g_role == 1 && !g_apply_host_req && g_peer_ok && name) {
		net_send_req(REQ_LOAD_NAME, 0, 0, 0, (const char *)name);
		InterlockedIncrement(&g_req_sent);
		host_load_request_repeat((const char *)name);   // PKT_REQ has no ack: repeat it for a moment
	}
}

static void __fastcall hk_to_menu(void *game, void *edx)
{
	InterlockedIncrement(&g_req_seq);
	logf("request ToMenu [mode %u]", *(unsigned *)((BYTE *)game + 0x310));
	if (g_role == 1)   // back at the menu: the last load no longer describes what the host is in
		host_save_forget();
	g_to_menu(game, edx);
	if (g_role == 1 && !g_apply_host_req && g_peer_ok) {
		net_send_req(REQ_TO_MENU, 0, 0, 0, NULL);
		InterlockedIncrement(&g_req_sent);
	}
}

// The level change (state 4) starts by writing the guest's live party into the progress table and moving
// its records to the new level; the world is torn down and rebuilt right after that. Put the host's
// character table back between the two so the rebuilt world spawns the host's party (PARTY_FINDINGS 3.1).
// The table is copied through guest_party_copy, which checks and copies under the stash's lock: the UDP
// thread may be storing a newer one at the same time.
static int __fastcall hk_party_table(void *game, void *edx, int flag, unsigned level, unsigned entry, int *weapons)
{
	int r = g_party_table(game, edx, flag, level, entry, weapons);
	// g_apply_host_req is already cleared here: the game runs the level change on a later frame than the request.
	if (g_role == 2) {
		unsigned obj = *(unsigned *)((BYTE *)game + 0x318);
		BYTE party[0x140];
		if (obj && !IsBadWritePtr((void *)(uintptr_t)(obj + 0x1b0c), 0x140) && guest_party_copy(level, party)) {
			char lv[5], ch[5];
			unsigned first;
			memcpy((void *)(uintptr_t)(obj + 0x1b0c), party, 0x140);
			memcpy(&first, party, sizeof first);
			logf("guest: host party applied at level %s: first character %s", tag4(level, lv), tag4(first, ch));
		}
	}
	return r;
}

// Online each player has their own camera, so the second character is often off the other
// player's screen. Obscure II's local co-op reacts to that: the character update (FUN_004de4f0)
// sets human+0x884 ("off-screen in the other view") and human+0x880 ("off-screen in this view"),
// and the input update (FUN_004cf940) then walks the character to the camera target at 200 u/s,
// ignoring the player's pad while it runs. Clear both flags just before the input update so each
// player keeps control of their own character; the character update recomputes them every frame.
typedef void(__fastcall *input_update_t)(void *, void *, int);
static input_update_t g_input_update;
static void guest_weapons_frame(void);   // sync.c: the guest's held weapons, applied in the game's own update

static void __fastcall hk_input_update(void *self, void *edx, int dt)
{
	unsigned ch = *(unsigned *)((BYTE *)self + 4);
	if (g_passive) {   // OBSCOOP_PASSIVE: leave the game's own state alone
		if (g_input_update)
			g_input_update(self, edx, dt);
		return;
	}
	if (ch && !IsBadWritePtr((void *)(uintptr_t)(ch + 0x880), 8)) {
		*(unsigned *)(uintptr_t)(ch + 0x880) = 0;
		*(unsigned *)(uintptr_t)(ch + 0x884) = 0;
	}
	guest_weapons_frame();
	if (g_input_update)
		g_input_update(self, edx, dt);
}

// The game object's per-frame update (FUN_004a5f20, prologue 55 8b ec 56 8b f1) runs in every mode,
// the main menu included, and is where the request state machine (game+0x320) is executed. A real save
// load needs the game's own thread (the save manager allocates and reads inside the game's memory), so
// the pending load is issued from here, just before the state machine runs (sync.c: game_load_tick).
typedef void(__fastcall *game_update_t)(void *, void *, int);
static game_update_t g_game_update;

static void __fastcall hk_game_update(void *game, void *edx, int dt)
{
	game_load_tick((unsigned)(uintptr_t)game);
	if (g_game_update)
		g_game_update(game, edx, dt);
}

// ---- world item pickup (sync.c: pickup_local_collect / peer_apply_pickups) -----------------------
// An item entity is identified by its class tag at +0x10 (a 4-character tag; the map is "MAP\0")
// and its per-entity id at +4. The tags below are the ones the 28 CToeItem* constructors write
// (ITEMS_FINDINGS.md section 1).
static int item_class_tag(unsigned t)
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

static void pickup_local_collect(unsigned item, unsigned ch);   // defined in sync.c

// FUN_004ddad0(character): collects the entity in character+0x73c by calling its vtable slot 26.
// It is the single character-side entry point of every world item pickup (ITEMS_FINDINGS 3.3).
typedef void(__fastcall *char_collect_t)(void *, void *);
static char_collect_t g_char_collect;

static void __fastcall hk_char_collect(void *ch, void *edx)
{
	if (ch && (g_role == 1 || g_role == 2) && g_peer_ok) {
		unsigned item = *(unsigned *)((BYTE *)ch + 0x73c);
		if (item && !IsBadReadPtr((void *)(uintptr_t)item, 0xac) && item_class_tag(*(unsigned *)(uintptr_t)(item + 0x10)) &&
			*(int *)(uintptr_t)(item + 0xa8) == 0)
			pickup_local_collect(item, (unsigned)(uintptr_t)ch);
	}
	if (g_char_collect)
		g_char_collect(ch, edx);
}

static void install_request_hooks(void)
{
	static const BYTE p_change[6] = { 0x55, 0x8b, 0xec, 0x8b, 0x45, 0x08 };
	static const BYTE p_prog[9] = { 0x55, 0x8b, 0xec, 0x8b, 0x81, 0x1c, 0x03, 0x00, 0x00 };
	static const BYTE p_name[6] = { 0x55, 0x8b, 0xec, 0x8b, 0x45, 0x08 };
	static const BYTE p_menu[10] = { 0xc7, 0x81, 0x20, 0x03, 0x00, 0x00, 0x09, 0x00, 0x00, 0x00 };
	g_change_level = (req3_t)hook_entry((BYTE *)0x4a1c00, p_change, 6, (void *)hk_change_level, "ChangeLevel (0x4a1c00)");
	g_load_progress = (req1_t)hook_entry((BYTE *)0x4a1ba0, p_prog, 9, (void *)hk_load_progress, "LoadProgress (0x4a1ba0)");
	g_load_name = (req1_t)hook_entry((BYTE *)0x4a1bd0, p_name, 6, (void *)hk_load_name, "LoadByName (0x4a1bd0)");
	g_to_menu = (req0_t)hook_entry((BYTE *)0x4a1c30, p_menu, 10, (void *)hk_to_menu, "ToMenu (0x4a1c30)");
	static const BYTE p_input[6] = { 0x55, 0x8b, 0xec, 0x83, 0xec, 0x3c };
	g_input_update = (input_update_t)hook_entry((BYTE *)0x4cf940, p_input, 6, (void *)hk_input_update,
		"CharacterControllerInput update (0x4cf940)");
	static const BYTE p_party[6] = { 0x55, 0x8b, 0xec, 0x83, 0xec, 0x08 };
	g_party_table = (party_t)hook_entry((BYTE *)0x4a20c0, p_party, 6, (void *)hk_party_table, "party table (0x4a20c0)");
	static const BYTE p_update[6] = { 0x55, 0x8b, 0xec, 0x56, 0x8b, 0xf1 };
	g_game_update = (game_update_t)hook_entry((BYTE *)0x4a5f20, p_update, 6, (void *)hk_game_update,
		"game update (0x4a5f20)");
	static const BYTE p_collect[9] = { 0x56, 0x8b, 0xf1, 0x8b, 0x8e, 0x3c, 0x07, 0x00, 0x00 };
	g_char_collect = (char_collect_t)hook_entry((BYTE *)0x4ddad0, p_collect, 9, (void *)hk_char_collect,
		"character collect (0x4ddad0)");
}
