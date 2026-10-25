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

static volatile LONG g_req_seq;   // number of requests seen, for tests

typedef void(__fastcall *req3_t)(void *, void *, unsigned, unsigned, unsigned);
typedef void(__fastcall *req1_t)(void *, void *, unsigned);
typedef void(__fastcall *req0_t)(void *, void *);
static req3_t g_change_level;
static req1_t g_load_progress, g_load_name;
static req0_t g_to_menu;

static void __fastcall hk_change_level(void *game, void *edx, unsigned level, unsigned entry, unsigned flag)
{
	char t[5];
	InterlockedIncrement(&g_req_seq);
	logf("request ChangeLevel level %s (0x%08x) entry %u flag %u [mode %u state %u]", tag4(level, t), level, entry, flag,
		*(unsigned *)((BYTE *)game + 0x310), *(unsigned *)((BYTE *)game + 0x320));
	g_change_level(game, edx, level, entry, flag);
}

static void __fastcall hk_load_progress(void *game, void *edx, unsigned arg)
{
	InterlockedIncrement(&g_req_seq);
	logf("request LoadProgress arg %u [mode %u]", arg, *(unsigned *)((BYTE *)game + 0x310));
	g_load_progress(game, edx, arg);
}

static void __fastcall hk_load_name(void *game, void *edx, unsigned name)
{
	InterlockedIncrement(&g_req_seq);
	logf("request LoadByName \"%.60s\" [mode %u]", name ? (const char *)name : "(null)", *(unsigned *)((BYTE *)game + 0x310));
	g_load_name(game, edx, name);
}

static void __fastcall hk_to_menu(void *game, void *edx)
{
	InterlockedIncrement(&g_req_seq);
	logf("request ToMenu [mode %u]", *(unsigned *)((BYTE *)game + 0x310));
	g_to_menu(game, edx);
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
}
