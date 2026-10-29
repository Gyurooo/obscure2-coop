// obscoop Steam transport: P2P packets through the game's own steam_api.dll (2014, app 254480).
// Included by net.c. That DLL has no flat API, only C++ interfaces, so calls go through vtables:
//   SteamUser017        slot 2  GetSteamID() -> CSteamID           (returned through a hidden pointer)
//   SteamFriends013     slot 0  GetPersonaName(), slot 3 GetFriendCount(int flags),
//                       slot 4  GetFriendByIndex(int, int flags) -> CSteamID (hidden pointer),
//                       slot 5  GetFriendRelationship(CSteamID), slot 8 GetFriendGamePlayed(CSteamID, FriendGameInfo_t*)
//   SteamNetworking005  slot 0  SendP2PPacket(CSteamID, const void*, uint32, EP2PSend, int channel)
//                       slot 1  IsP2PPacketAvailable(uint32*, int), slot 2 ReadP2PPacket(void*, uint32, uint32*, CSteamID*, int)
//                       slot 3  AcceptP2PSessionWithUser(CSteamID), slot 7 AllowP2PPacketRelay(bool)
// MSVC thiscall: this in ECX, callee pops; a CSteamID argument is 8 bytes on the stack; a CSteamID
// result is written through a hidden pointer passed first; bool comes back in AL. A __fastcall
// function with an unused EDX argument has the same layout.
// Callbacks: SteamAPI_RegisterCallback(CCallbackBase*, id). CCallbackBase is { vtable, uint8 flags,
// int id }; MSVC puts the two Run overloads in reverse order, so the vtable is
// { Run(void*, bool, SteamAPICall_t), Run(void*), GetCallbackSizeBytes() } (as Steamworks.NET does on
// Windows). P2PSessionRequest_t = 1202 { CSteamID remote }.

typedef unsigned long long sid_t;
typedef void *(__cdecl *steam_getter_t)(void);
typedef void(__cdecl *register_cb_t)(void *cb, int id);
typedef sid_t *(__fastcall *get_sid_t)(void *self, void *edx, sid_t *ret);
typedef sid_t *(__fastcall *friend_by_index_t)(void *self, void *edx, sid_t *ret, int i, int flags);
typedef int(__fastcall *friend_count_t)(void *self, void *edx, int flags);
typedef int(__fastcall *friend_rel_t)(void *self, void *edx, sid_t id);
typedef unsigned char(__fastcall *friend_game_t)(void *self, void *edx, sid_t id, void *info);
typedef const char *(__fastcall *persona_name_t)(void *self, void *edx);
typedef const char *(__fastcall *friend_name_t)(void *self, void *edx, sid_t id);
typedef unsigned char(__fastcall *p2p_send_t)(void *self, void *edx, sid_t id, const void *data, DWORD len, int type, int ch);
typedef unsigned char(__fastcall *p2p_avail_t)(void *self, void *edx, DWORD *size, int ch);
typedef unsigned char(__fastcall *p2p_read_t)(void *self, void *edx, void *dst, DWORD cap, DWORD *size, sid_t *from, int ch);
typedef unsigned char(__fastcall *p2p_accept_t)(void *self, void *edx, sid_t id);
typedef unsigned char(__fastcall *p2p_relay_t)(void *self, void *edx, unsigned char allow);

#pragma pack(push, 4)
typedef struct { sid_t game_id; DWORD ip; WORD port, query_port; sid_t lobby; } friend_game_info;   // 24 bytes
#pragma pack(pop)

static void *g_suser, *g_sfriends, *g_snet;
static sid_t g_self_sid;
static char g_host_name[64];          // guest: the host's Steam name from OBSCOOP_HOST_NAME (optional)
static DWORD g_scan_appid = 254480;   // friends playing this app are host candidates (480 in Spacewar mode)
static sid_t g_host_sid_cfg;          // guest: host Steam id from OBSCOOP_HOST_STEAMID (optional)
static volatile LONG g_steam_ok, g_steam_session_requests, g_steam_accepted, g_steam_refused;
static volatile LONG g_steam_tx_fail;

static void **vt_of(void *iface) { return *(void ***)iface; }

// ---- TASK 41: Steamworks is not thread-safe; serialise every call -----------------------------------
// The Steamworks client API is documented as not thread-safe (the SDK headers mark the interface entry
// points "NOT THREADSAFE - ensure that no other threads are accessing Steamworks API when calling"), and
// callbacks are only dispatched from SteamAPI_RunCallbacks on the game's own thread (Obscure2.exe.c:185958
// calls it in the game loop). The transport thread may call SendP2PPacket / IsP2PPacketAvailable /
// ReadP2PPacket while the game thread is inside SteamAPI_RunCallbacks, so every vtable call here takes one
// recursive lock (critical sections are recursive: steam_poll -> net_handle -> net_send nests, and the
// session-request callback -> steam_accept/steam_is_friend nests). Steam init stays on the game thread.
static CRITICAL_SECTION g_steam_cs;
static void steam_lock_init(void)
{
	InitializeCriticalSection(&g_steam_cs);
}
static void steam_lock(void) { EnterCriticalSection(&g_steam_cs); }
static void steam_unlock(void) { LeaveCriticalSection(&g_steam_cs); }

static int steam_is_friend(sid_t id)
{
	int r;
	steam_lock();
	r = g_sfriends && ((friend_rel_t)vt_of(g_sfriends)[5])(g_sfriends, NULL, id) == 3;   // k_EFriendRelationshipFriend
	steam_unlock();
	return r;
}

static void steam_accept(sid_t id)
{
	steam_lock();
	if (((p2p_accept_t)vt_of(g_snet)[3])(g_snet, NULL, id))
		InterlockedIncrement(&g_steam_accepted);
	steam_unlock();
}

// Fake CCallbackBase for P2PSessionRequest_t (1202). Runs on the main thread inside SteamAPI_RunCallbacks.
static void steam_session_request(sid_t from);
static void __fastcall cb_run_result(void *self, void *edx, void *param, DWORD io_fail, sid_t call)
{
	(void)self; (void)edx; (void)io_fail; (void)call;
	if (param)
		steam_session_request(*(sid_t *)param);
}
static void __fastcall cb_run(void *self, void *edx, void *param)
{
	(void)self; (void)edx;
	if (param)
		steam_session_request(*(sid_t *)param);
}
static int __fastcall cb_size(void *self, void *edx)
{
	(void)self; (void)edx;
	return 8;
}
static void *g_cb_vtable[3] = { (void *)cb_run_result, (void *)cb_run, (void *)cb_size };
static struct { void **vt; BYTE flags; BYTE pad[3]; int id; } g_cb_session = { g_cb_vtable, 0, { 0 }, 1202 };

static int steam_start(void)
{
	HMODULE m = GetModuleHandleA("steam_api.dll");
	if (!m) {
		logf("steam: steam_api.dll not loaded");
		return 0;
	}
	steam_getter_t user = (steam_getter_t)GetProcAddress(m, "SteamUser");
	steam_getter_t friends = (steam_getter_t)GetProcAddress(m, "SteamFriends");
	steam_getter_t net = (steam_getter_t)GetProcAddress(m, "SteamNetworking");
	register_cb_t reg = (register_cb_t)GetProcAddress(m, "SteamAPI_RegisterCallback");
	if (!user || !friends || !net || !reg) {
		logf("steam: missing exports");
		return 0;
	}
	steam_lock();   // interface getters, SteamID and the callback registration: one Steamworks call at a time
	g_suser = user();
	g_sfriends = friends();
	g_snet = net();
	if (!g_suser || !g_sfriends || !g_snet) {
		steam_unlock();
		logf("steam: interfaces not available yet (user %p friends %p net %p)", g_suser, g_sfriends, g_snet);
		return 0;
	}
	((get_sid_t)vt_of(g_suser)[2])(g_suser, NULL, &g_self_sid);
	const char *name = ((persona_name_t)vt_of(g_sfriends)[0])(g_sfriends, NULL);
	int nfriends = ((friend_count_t)vt_of(g_sfriends)[3])(g_sfriends, NULL, 4);
	((p2p_relay_t)vt_of(g_snet)[7])(g_snet, NULL, 1);
	reg(&g_cb_session, 1202);
	// Sanity: a real individual account id has universe 1, type 1 (0x011000010...) in the top bits.
	{
		friend_game_info me;
		memset(&me, 0, sizeof me);
		int playing = ((friend_game_t)vt_of(g_sfriends)[8])(g_sfriends, NULL, g_self_sid, &me);
		logf("steam: this account shows as %s (game id %llu); looking for friends in app %lu", playing ? "playing" : "not playing",
			(unsigned long long)(me.game_id & 0xffffff), (unsigned long)g_scan_appid);
	}
	int id_ok = (g_self_sid >> 52) == 0x011;
	logf("steam: ready; own id %s, persona name %s (%d chars), %d friends, session-request callback registered",
		id_ok ? "valid" : "INVALID", name ? "readable" : "missing", name ? (int)strlen(name) : 0, nfriends);
	steam_unlock();
	return id_ok;
}

// Guest: candidate hosts = the configured id; else friends whose Steam name is OBSCOOP_HOST_NAME; else friends
// playing Obscure II (app 254480) right now. Steam does not always show a friend as playing (a game started from
// a copy, "appear offline", a hidden game), so the id or the name is the sure way.
static int steam_find_hosts(sid_t *out, int max)
{
	if (g_host_sid_cfg) {
		out[0] = g_host_sid_cfg;
		return 1;
	}
	steam_lock();
	if (!g_host_name[0] && getenv("OBSCOOP_TEST_NAME_FRIEND0")) {   // test only: use friend 0's name, never logged
		sid_t f0 = 0;
		((friend_by_index_t)vt_of(g_sfriends)[4])(g_sfriends, NULL, &f0, 0, 4);
		const char *nm = f0 ? ((friend_name_t)vt_of(g_sfriends)[7])(g_sfriends, NULL, f0) : NULL;
		if (nm)
			_snprintf(g_host_name, sizeof g_host_name, "%s", nm);
	}
	int n = 0, in_game = 0, by_name = 0, count = ((friend_count_t)vt_of(g_sfriends)[3])(g_sfriends, NULL, 4);
	for (int i = 0; i < count && n < max; i++) {
		sid_t id = 0;
		((friend_by_index_t)vt_of(g_sfriends)[4])(g_sfriends, NULL, &id, i, 4);
		if (!id)
			continue;
		if (g_host_name[0]) {
			const char *nm = ((friend_name_t)vt_of(g_sfriends)[7])(g_sfriends, NULL, id);
			if (nm && !_stricmp(nm, g_host_name)) {
				out[n++] = id;
				by_name++;
				continue;
			}
		}
		friend_game_info gi;
		memset(&gi, 0, sizeof gi);
		if (!((friend_game_t)vt_of(g_sfriends)[8])(g_sfriends, NULL, id, &gi))
			continue;
		in_game++;
		if (!g_host_name[0] && (gi.game_id & 0xffffff) == g_scan_appid)
			out[n++] = id;
	}
	steam_unlock();
	static int logged;
	if (!logged++)
		logf("steam: friends scan: %d of %d friends in a game, %d matched by name, %d candidates%s", in_game, count, by_name, n,
			g_host_name[0] ? " (looking for the host by Steam name)" : " (looking for friends playing Obscure II)");
	return n;
}

// Host: every Steam friend may start a session (the friend check in the session-request callback still applies).
static int steam_all_friends(sid_t *out, int max)
{
	int n = 0;
	steam_lock();
	int count = ((friend_count_t)vt_of(g_sfriends)[3])(g_sfriends, NULL, 4);
	for (int i = 0; i < count && n < max; i++) {
		sid_t id = 0;
		((friend_by_index_t)vt_of(g_sfriends)[4])(g_sfriends, NULL, &id, i, 4);
		if (id)
			out[n++] = id;
	}
	steam_unlock();
	return n;
}

static int steam_send(sid_t to, const void *data, int len)
{
	// k_EP2PSendUnreliable (0): the protocol handles loss itself; every packet stays under 1200 bytes.
	steam_lock();
	int ok = ((p2p_send_t)vt_of(g_snet)[0])(g_snet, NULL, to, data, (DWORD)len, 0, 0) != 0;
	steam_unlock();
	if (!ok) {
		InterlockedIncrement(&g_steam_tx_fail);
		return 0;
	}
	return 1;
}

static void net_handle(const char *buf, int n, sid_t from);

// Called on the transport thread (TASK 41) or, with OBSCOOP_TRANSPORT_FRAME=1, on the game thread. The Steam
// calls are under the lock; net_handle itself runs outside it (it may queue work and send replies, which take
// the lock again - a critical section is recursive, but keeping the section short is still better).
static void steam_poll(void)
{
	static char buf[4096];
	if (!g_snet)
		return;
	for (;;) {
		DWORD size = 0, got = 0;
		sid_t from = 0;
		int have;
		steam_lock();
		have = ((p2p_avail_t)vt_of(g_snet)[1])(g_snet, NULL, &size, 0) != 0;
		if (have)
			have = ((p2p_read_t)vt_of(g_snet)[2])(g_snet, NULL, buf, sizeof buf, &got, &from, 0) != 0;
		steam_unlock();
		if (!have)
			break;
		if (got <= sizeof buf)
			net_handle(buf, (int)got, from);
	}
}
