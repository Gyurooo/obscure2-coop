// obscoop-relay: carries the co-op DLL's UDP packets over Steam, as app 480 ("Spacewar").
//
// Why: a game started from Steam is shown to friends as "playing <that game>", and only one game is shown per
// account. This relay runs next to the game under the free Steam sample app 480 and gives both players a
// friends-only lobby, rich presence ("Join Game") and Steam's relayed P2P messages, with no IP addresses. The game
// itself is not changed and does not need a different Steam identity (that makes its Steam copy protection restart
// it): the co-op DLL talks plain UDP on 127.0.0.1 and this program forwards it.
//
//   obscoop-relay host  [game_udp_port=27961]
//       Creates a friends-only lobby, sets rich presence "connect" so a friend can click Join Game, shows its
//       Steam ID, and forwards between one friend and the DLL (OBSCOOP_ROLE=host, OBSCOOP_NET=udp, same port).
//   obscoop-relay guest [host Steam ID | host Steam name | lobby:<id>] [listen_udp_port=27962]
//       Finds the host (given id or name, a Join Game click / invite, or a friend playing Spacewar with an obscoop
//       lobby), forwards between the DLL (OBSCOOP_ROLE=guest, OBSCOOP_NET=udp, OBSCOOP_UDP=<listen port>) and the host.
//   obscoop-relay selftest
//       Sends a message to this account's own id and reads it back (checks the message structure offsets).
//   Test transport without Steam: --udp-link <host:port> (guest) / --udp-link listen:<port> (host) joins two relays
//       over plain UDP so the whole chain can be tested with two game windows on one PC.
//
// steam_api.dll must be the 32-bit Steamworks.NET Standalone 2025.164.1 one (flat API), next to this exe.
// Flat API names and struct layouts are from playbook/networking-steam-spacewar.md.

#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdarg.h>

typedef uint64_t u64;
typedef unsigned char (*fn_b)(void);
#define STEAMCALL __cdecl

// ---- flat API, resolved at run time -----------------------------------------------------------------------
static HMODULE g_dll;
#define DECL(ret, name, args) static ret(STEAMCALL *name) args
DECL(int, SteamAPI_InitFlat, (char *err));
DECL(int, SteamAPI_GetHSteamPipe, (void));
DECL(void, SteamAPI_ManualDispatch_Init, (void));
DECL(void, SteamAPI_ManualDispatch_RunFrame, (int pipe));
DECL(unsigned char, SteamAPI_ManualDispatch_GetNextCallback, (int pipe, void *msg));
DECL(void, SteamAPI_ManualDispatch_FreeLastCallback, (int pipe));
DECL(unsigned char, SteamAPI_ManualDispatch_GetAPICallResult, (int pipe, u64 call, void *buf, int size, int expected, unsigned char *failed));
DECL(void *, SteamAPI_SteamUser_v023, (void));
DECL(void *, SteamAPI_SteamFriends_v018, (void));
DECL(void *, SteamAPI_SteamMatchmaking_v009, (void));
DECL(void *, SteamAPI_SteamNetworkingMessages_SteamAPI_v002, (void));
DECL(void *, SteamAPI_SteamNetworkingUtils_SteamAPI_v004, (void));
DECL(u64, SteamAPI_ISteamUser_GetSteamID, (void *self));
DECL(int, SteamAPI_ISteamFriends_GetFriendCount, (void *self, int flags));
DECL(u64, SteamAPI_ISteamFriends_GetFriendByIndex, (void *self, int i, int flags));
DECL(unsigned char, SteamAPI_ISteamFriends_GetFriendGamePlayed, (void *self, u64 id, void *info));
DECL(const char *, SteamAPI_ISteamFriends_GetFriendPersonaName, (void *self, u64 id));
DECL(const char *, SteamAPI_ISteamFriends_GetPersonaName, (void *self));
DECL(const char *, SteamAPI_ISteamFriends_GetFriendRichPresence, (void *self, u64 id, const char *key));
DECL(unsigned char, SteamAPI_ISteamFriends_SetRichPresence, (void *self, const char *key, const char *value));
DECL(int, SteamAPI_ISteamFriends_GetFriendRelationship, (void *self, u64 id));
DECL(u64, SteamAPI_ISteamMatchmaking_CreateLobby, (void *self, int type, int max));
DECL(u64, SteamAPI_ISteamMatchmaking_JoinLobby, (void *self, u64 lobby));
DECL(void, SteamAPI_ISteamMatchmaking_LeaveLobby, (void *self, u64 lobby));
DECL(unsigned char, SteamAPI_ISteamMatchmaking_SetLobbyData, (void *self, u64 lobby, const char *k, const char *v));
DECL(const char *, SteamAPI_ISteamMatchmaking_GetLobbyData, (void *self, u64 lobby, const char *k));
DECL(u64, SteamAPI_ISteamMatchmaking_GetLobbyOwner, (void *self, u64 lobby));
DECL(int, SteamAPI_ISteamMatchmaking_GetNumLobbyMembers, (void *self, u64 lobby));
DECL(u64, SteamAPI_ISteamMatchmaking_GetLobbyMemberByIndex, (void *self, u64 lobby, int i));
DECL(unsigned char, SteamAPI_ISteamMatchmaking_SetLobbyJoinable, (void *self, u64 lobby, unsigned char j));
DECL(unsigned char, SteamAPI_ISteamMatchmaking_InviteUserToLobby, (void *self, u64 lobby, u64 friend_id));
DECL(int, SteamAPI_ISteamNetworkingMessages_SendMessageToUser, (void *self, const void *identity, const void *data, uint32_t len, int flags, int channel));
DECL(int, SteamAPI_ISteamNetworkingMessages_ReceiveMessagesOnChannel, (void *self, int channel, void **out, int max));
DECL(unsigned char, SteamAPI_ISteamNetworkingMessages_AcceptSessionWithUser, (void *self, const void *identity));
DECL(void, SteamAPI_SteamNetworkingMessage_t_Release, (void *msg));
DECL(void, SteamAPI_SteamNetworkingIdentity_SetSteamID64, (void *identity, u64 id));
DECL(u64, SteamAPI_SteamNetworkingIdentity_GetSteamID64, (const void *identity));
DECL(unsigned char, SteamAPI_ISteamNetworkingUtils_SetGlobalConfigValueInt32, (void *self, int value, int v));

static void *g_user, *g_friends, *g_mm, *g_msgs, *g_utils;
static int g_pipe;
static u64 g_self;

static void logf_(const char *fmt, ...)
{
	char b[512];
	SYSTEMTIME t;
	GetLocalTime(&t);
	int n = snprintf(b, sizeof b, "%02d:%02d:%02d ", t.wHour, t.wMinute, t.wSecond);
	va_list ap;
	va_start(ap, fmt);
	vsnprintf(b + n, sizeof b - n - 2, fmt, ap);
	va_end(ap);
	strcat(b, "\n");
	fputs(b, stdout);
	fflush(stdout);
	FILE *f = fopen("obscoop-relay.log", "ab");
	if (f) {
		fputs(b, f);
		fclose(f);
	}
}

static int load_steam(void)
{
	g_dll = LoadLibraryA("steam_api.dll");
	if (!g_dll) {
		logf_("steam_api.dll not found next to the relay");
		return 0;
	}
#define LOAD(n) do { *(void **)&n = (void *)GetProcAddress(g_dll, #n); if (!n) { logf_("steam_api.dll lacks %s (wrong version?)", #n); return 0; } } while (0)
	LOAD(SteamAPI_InitFlat); LOAD(SteamAPI_GetHSteamPipe); LOAD(SteamAPI_ManualDispatch_Init); LOAD(SteamAPI_ManualDispatch_RunFrame);
	LOAD(SteamAPI_ManualDispatch_GetNextCallback); LOAD(SteamAPI_ManualDispatch_FreeLastCallback); LOAD(SteamAPI_ManualDispatch_GetAPICallResult);
	LOAD(SteamAPI_SteamUser_v023); LOAD(SteamAPI_SteamFriends_v018); LOAD(SteamAPI_SteamMatchmaking_v009);
	LOAD(SteamAPI_SteamNetworkingMessages_SteamAPI_v002); LOAD(SteamAPI_SteamNetworkingUtils_SteamAPI_v004);
	LOAD(SteamAPI_ISteamUser_GetSteamID); LOAD(SteamAPI_ISteamFriends_GetFriendCount); LOAD(SteamAPI_ISteamFriends_GetFriendByIndex);
	LOAD(SteamAPI_ISteamFriends_GetFriendGamePlayed); LOAD(SteamAPI_ISteamFriends_GetFriendPersonaName); LOAD(SteamAPI_ISteamFriends_GetPersonaName);
	LOAD(SteamAPI_ISteamFriends_GetFriendRichPresence); LOAD(SteamAPI_ISteamFriends_SetRichPresence); LOAD(SteamAPI_ISteamFriends_GetFriendRelationship);
	LOAD(SteamAPI_ISteamMatchmaking_CreateLobby); LOAD(SteamAPI_ISteamMatchmaking_JoinLobby); LOAD(SteamAPI_ISteamMatchmaking_LeaveLobby);
	LOAD(SteamAPI_ISteamMatchmaking_SetLobbyData); LOAD(SteamAPI_ISteamMatchmaking_GetLobbyData); LOAD(SteamAPI_ISteamMatchmaking_GetLobbyOwner);
	LOAD(SteamAPI_ISteamMatchmaking_GetNumLobbyMembers); LOAD(SteamAPI_ISteamMatchmaking_GetLobbyMemberByIndex);
	LOAD(SteamAPI_ISteamMatchmaking_SetLobbyJoinable); LOAD(SteamAPI_ISteamMatchmaking_InviteUserToLobby);
	LOAD(SteamAPI_ISteamNetworkingMessages_SendMessageToUser); LOAD(SteamAPI_ISteamNetworkingMessages_ReceiveMessagesOnChannel);
	LOAD(SteamAPI_ISteamNetworkingMessages_AcceptSessionWithUser); LOAD(SteamAPI_SteamNetworkingMessage_t_Release);
	LOAD(SteamAPI_SteamNetworkingIdentity_SetSteamID64); LOAD(SteamAPI_SteamNetworkingIdentity_GetSteamID64);
	LOAD(SteamAPI_ISteamNetworkingUtils_SetGlobalConfigValueInt32);
	return 1;
}

// steam_appid.txt = 480 next to the relay: Steam then treats this process as Spacewar.
static void ensure_appid(void)
{
	FILE *f = fopen("steam_appid.txt", "rb");
	if (f) {
		fclose(f);
		return;
	}
	f = fopen("steam_appid.txt", "wb");
	if (f) {
		fputs("480", f);
		fclose(f);
	}
}

static int steam_up(void)
{
	SetEnvironmentVariableA("SteamAppId", "480");   // never inherit the game's id from a launcher script
	SetEnvironmentVariableA("SteamGameId", "480");
	ensure_appid();
	if (!load_steam())
		return 0;
	char err[1024] = "";
	int r = SteamAPI_InitFlat(err);
	if (r != 0) {
		logf_("SteamAPI_InitFlat failed (%d): %s%s", r, err, r == 2 ? " (is Steam running?)" : "");
		return 0;
	}
	SteamAPI_ManualDispatch_Init();
	g_pipe = SteamAPI_GetHSteamPipe();
	g_user = SteamAPI_SteamUser_v023();
	g_friends = SteamAPI_SteamFriends_v018();
	g_mm = SteamAPI_SteamMatchmaking_v009();
	g_msgs = SteamAPI_SteamNetworkingMessages_SteamAPI_v002();
	g_utils = SteamAPI_SteamNetworkingUtils_SteamAPI_v004();
	if (!g_user || !g_friends || !g_mm || !g_msgs) {
		logf_("a Steam interface is missing (user %p friends %p matchmaking %p messages %p)", g_user, g_friends, g_mm, g_msgs);
		return 0;
	}
	g_self = SteamAPI_ISteamUser_GetSteamID(g_user);
	if (g_utils) {   // 32 MB buffers (config ids: send buffer 9, recv buffer 47, recv max message size 22)
		SteamAPI_ISteamNetworkingUtils_SetGlobalConfigValueInt32(g_utils, 9, 32 << 20);
		SteamAPI_ISteamNetworkingUtils_SetGlobalConfigValueInt32(g_utils, 47, 32 << 20);
		SteamAPI_ISteamNetworkingUtils_SetGlobalConfigValueInt32(g_utils, 22, 32 << 20);
	}
	logf_("steam up as app 480; own Steam ID %llu, name \"%s\"", (unsigned long long)g_self, SteamAPI_ISteamFriends_GetPersonaName(g_friends));
	return 1;
}

// ---- callbacks ------------------------------------------------------------------------------------------------

#pragma pack(push, 8)
typedef struct { int user; int callback; unsigned char *param; int size; } cb_msg;
typedef struct { u64 call; int callback; uint32_t size; } call_done;
#pragma pack(pop)

enum { CB_LOBBY_JOIN_REQ = 333, CB_RP_JOIN_REQ = 337, CB_LOBBY_ENTER = 504, CB_LOBBY_CREATED = 513, CB_CALL_DONE = 703, CB_SESSION_REQ = 1251, CB_SESSION_FAILED = 1252 };

static int g_role;             // 1 host, 2 guest
static u64 g_lobby;            // the lobby we host or joined
static u64 g_host_id;          // guest: the host's Steam ID (once known)
static u64 g_peer_id;          // host: the guest's Steam ID (once it said hello)
static int g_lobby_ready;
static u64 g_join_lobby_req;   // guest: a lobby to join (Join Game click or invite)

static int is_friend(u64 id)
{
	return SteamAPI_ISteamFriends_GetFriendRelationship(g_friends, id) == 3;
}

static void make_identity(void *ident, u64 id)
{
	memset(ident, 0, 160);
	SteamAPI_SteamNetworkingIdentity_SetSteamID64(ident, id);
}

static void accept_from(u64 id)
{
	char ident[160];
	make_identity(ident, id);
	SteamAPI_ISteamNetworkingMessages_AcceptSessionWithUser(g_msgs, ident);
}

static int lobby_has_member(u64 id)
{
	if (!g_lobby)
		return 0;
	int n = SteamAPI_ISteamMatchmaking_GetNumLobbyMembers(g_mm, g_lobby);
	for (int i = 0; i < n; i++)
		if (SteamAPI_ISteamMatchmaking_GetLobbyMemberByIndex(g_mm, g_lobby, i) == id)
			return 1;
	return 0;
}

static void handle_callback(int id, const unsigned char *p, int size)
{
	switch (id) {
	case CB_LOBBY_CREATED:
		if (size >= 16) {
			int result = *(const int *)p;
			u64 lobby = *(const u64 *)(p + 8);
			if (result == 1 && !g_lobby_ready) {
				g_lobby = lobby;
				g_lobby_ready = 1;
				SteamAPI_ISteamMatchmaking_SetLobbyData(g_mm, lobby, "obscoop", "1");
				SteamAPI_ISteamMatchmaking_SetLobbyJoinable(g_mm, lobby, 1);
				char rp[64];
				snprintf(rp, sizeof rp, "+connect_lobby %llu", (unsigned long long)lobby);
				SteamAPI_ISteamFriends_SetRichPresence(g_friends, "connect", rp);
				SteamAPI_ISteamFriends_SetRichPresence(g_friends, "status", "Obscure II co-op (host)");
				logf_("lobby %llu created (friends only). Friends can use Join Game on your name, or the guest relay finds it.", (unsigned long long)lobby);
			} else if (result != 1) {
				logf_("creating the lobby failed (result %d)", result);
			}
		}
		break;
	case CB_LOBBY_ENTER:
		if (size >= 20) {
			u64 lobby = *(const u64 *)p;
			unsigned response = *(const unsigned *)(p + 16);
			if (response == 1 && g_role == 1) {
				g_lobby = lobby;   // our own lobby (the host also gets this callback)
			} else if (response == 1) {
				g_lobby = lobby;
				const char *tag = SteamAPI_ISteamMatchmaking_GetLobbyData(g_mm, lobby, "obscoop");
				if (tag && !strcmp(tag, "1")) {
					g_host_id = SteamAPI_ISteamMatchmaking_GetLobbyOwner(g_mm, lobby);
					logf_("joined lobby %llu; the host is %llu", (unsigned long long)lobby, (unsigned long long)g_host_id);
				} else if (lobby != g_lobby || tag) {
					logf_("lobby %llu is not an obscoop lobby (someone playing Spacewar); leaving", (unsigned long long)lobby);
					SteamAPI_ISteamMatchmaking_LeaveLobby(g_mm, lobby);
					g_lobby = 0;
				}
			} else {
				logf_("could not enter the lobby (response %u)", response);
			}
		}
		break;
	case CB_LOBBY_JOIN_REQ:
		if (size >= 8) {
			g_join_lobby_req = *(const u64 *)p;
			logf_("Join Game / invite accepted for lobby %llu", (unsigned long long)g_join_lobby_req);
		}
		break;
	case CB_RP_JOIN_REQ:
		if (size >= 8 + 8) {
			const char *conn = (const char *)(p + 8);
			unsigned long long lob = 0;
			if (sscanf(conn, "+connect_lobby %llu", &lob) == 1 && lob) {
				g_join_lobby_req = lob;
				logf_("Join Game clicked: lobby %llu", lob);
			}
		}
		break;
	case CB_SESSION_REQ:
		if (size >= 8) {
			u64 from = SteamAPI_SteamNetworkingIdentity_GetSteamID64(p);
			// Host: friends and lobby members only. Guest: only the host.
			int ok = from && (g_host_id ? from == g_host_id : (is_friend(from) || lobby_has_member(from)));
			if (ok)
				accept_from(from);
			logf_("session request from %llu: %s", (unsigned long long)from, ok ? "accepted" : "refused");
		}
		break;
	case CB_SESSION_FAILED:
		logf_("Steam session failed");
		break;
	}
}

static void pump_callbacks(void)
{
	SteamAPI_ManualDispatch_RunFrame(g_pipe);
	cb_msg m;
	while (SteamAPI_ManualDispatch_GetNextCallback(g_pipe, &m)) {
		if (m.callback == CB_CALL_DONE) {
			const call_done *d = (const call_done *)m.param;
			unsigned char *buf = malloc(d->size ? d->size : 1);
			unsigned char failed = 0;
			if (buf && SteamAPI_ManualDispatch_GetAPICallResult(g_pipe, d->call, buf, (int)d->size, d->callback, &failed) && !failed)
				handle_callback(d->callback, buf, (int)d->size);
			free(buf);
		} else {
			handle_callback(m.callback, m.param, m.size);
		}
		SteamAPI_ManualDispatch_FreeLastCallback(g_pipe);
	}
}

// ---- messages ---------------------------------------------------------------------------------------------------

enum { CH_GAME = 0, CH_CONTROL = 1 };
enum { SEND_UNRELIABLE = 0, SEND_NONAGLE = 1, SEND_RELIABLE = 8 };

static void send_to(u64 to, const void *data, int len, int channel, int reliable)
{
	char ident[160];
	make_identity(ident, to);
	SteamAPI_ISteamNetworkingMessages_SendMessageToUser(g_msgs, ident, data, (uint32_t)len, (reliable ? SEND_RELIABLE : SEND_UNRELIABLE) | SEND_NONAGLE, channel);
}

// Reads the sender of a message. The identity sits at offset 12 in the 32-bit DLL (offset 16 by the headers'
// packing): keep whichever decodes to an id.
static u64 msg_sender(const unsigned char *m)
{
	u64 a = SteamAPI_SteamNetworkingIdentity_GetSteamID64(m + 12);
	u64 b = SteamAPI_SteamNetworkingIdentity_GetSteamID64(m + 16);
	static int logged;
	if (!logged++)
		logf_("message layout: sender read at +12 = %llu, at +16 = %llu", (unsigned long long)a, (unsigned long long)b);
	return a ? a : b;
}

typedef void (*on_msg_t)(u64 from, int channel, const unsigned char *data, int len);

static void drain_channel(int channel, on_msg_t cb)
{
	void *msgs[16];
	int n = SteamAPI_ISteamNetworkingMessages_ReceiveMessagesOnChannel(g_msgs, channel, msgs, 16);
	for (int i = 0; i < n; i++) {
		const unsigned char *m = msgs[i];
		const unsigned char *data = *(const unsigned char *const *)m;
		int size = *(const int *)(m + 4);
		u64 from = msg_sender(m);
		if (data && size > 0 && size <= 65536)
			cb(from, channel, data, size);
		SteamAPI_SteamNetworkingMessage_t_Release(msgs[i]);
	}
}

// ---- the UDP side (the game DLL) --------------------------------------------------------------------------------

static SOCKET g_udp = INVALID_SOCKET;
static struct sockaddr_in g_game_addr;   // host: the DLL's port. guest: the DLL's source address (learned)
static int g_game_addr_known;
static u64 g_rx_game, g_tx_game;

// Optional plain-UDP link instead of Steam (tests with two game windows on one PC).
static SOCKET g_link = INVALID_SOCKET;
static struct sockaddr_in g_link_peer;
static int g_link_peer_known, g_use_link;


// ---- test only: delay, jitter and loss on the plain-UDP link, to behave like the internet ------------------------
static int g_lag_ms, g_jit_ms, g_loss_pct;
static double ms_now(void)
{
	static LARGE_INTEGER f;
	LARGE_INTEGER c;
	if (!f.QuadPart)
		QueryPerformanceFrequency(&f);
	QueryPerformanceCounter(&c);
	return (double)c.QuadPart * 1000.0 / (double)f.QuadPart;
}
typedef struct { double due; int len; unsigned char data[1500]; } lag_pkt;
static lag_pkt g_lagq[2048];
static int g_lag_head, g_lag_tail;

static void link_send_now(const unsigned char *data, int len)
{
	if (g_link_peer_known)
		sendto(g_link, (const char *)data, len, 0, (struct sockaddr *)&g_link_peer, sizeof g_link_peer);
}

static void link_send(const unsigned char *data, int len)
{
	if (!g_lag_ms && !g_jit_ms && !g_loss_pct) {
		link_send_now(data, len);
		return;
	}
	if (g_loss_pct && (rand() % 100) < g_loss_pct)
		return;
	if (len > 1500 || ((g_lag_tail + 1) & 2047) == g_lag_head)
		return;
	lag_pkt *p = &g_lagq[g_lag_tail];
	p->due = ms_now() + g_lag_ms + (g_jit_ms ? (double)(rand() % (g_jit_ms + 1)) : 0.0);
	p->len = len;
	memcpy(p->data, data, len);
	g_lag_tail = (g_lag_tail + 1) & 2047;
}

static void lag_pump(void)
{
	// jitter can reorder: send everything that is due, scanning the whole queue
	for (int i = g_lag_head; i != g_lag_tail; i = (i + 1) & 2047) {
		lag_pkt *p = &g_lagq[i];
		if (p->len > 0 && p->due <= ms_now()) {
			link_send_now(p->data, p->len);
			p->len = 0;
		}
	}
	while (g_lag_head != g_lag_tail && g_lagq[g_lag_head].len == 0)
		g_lag_head = (g_lag_head + 1) & 2047;
}

static void to_game(const unsigned char *data, int len)
{
	if (g_udp == INVALID_SOCKET || !g_game_addr_known)
		return;
	sendto(g_udp, (const char *)data, len, 0, (struct sockaddr *)&g_game_addr, sizeof g_game_addr);
	g_rx_game++;
}

static void to_peer(const unsigned char *data, int len)
{
	if (g_use_link) {
		link_send(data, len);
		return;
	}
	u64 to = g_role == 1 ? g_peer_id : g_host_id;
	if (to)
		send_to(to, data, len, CH_GAME, 0);
}

// ---- control channel: hello / welcome / keep-alive ----------------------------------------------------------------

static DWORD g_last_peer_rx;
static int g_linked;

static void on_message(u64 from, int channel, const unsigned char *data, int len)
{
	if (channel == CH_CONTROL) {
		if (len >= 5 && !memcmp(data, "HELLO", 5) && g_role == 1) {
			// Host: only a friend or lobby member becomes the guest.
			if (!g_peer_id || g_peer_id == from) {
				if (!g_peer_id && !(is_friend(from) || lobby_has_member(from)))
					return;
				accept_from(from);
				if (!g_peer_id)
					logf_("guest %llu linked", (unsigned long long)from);
				g_peer_id = from;
				g_linked = 1;
				g_last_peer_rx = GetTickCount();
				send_to(from, "WELCOME", 7, CH_CONTROL, 1);
			}
		} else if (len >= 7 && !memcmp(data, "WELCOME", 7) && g_role == 2 && from == g_host_id) {
			if (!g_linked)
				logf_("host welcomed us; the relay link is up");
			g_linked = 1;
			g_last_peer_rx = GetTickCount();
		} else if (len >= 4 && !memcmp(data, "PING", 4) && (from == g_peer_id || from == g_host_id)) {
			g_last_peer_rx = GetTickCount();
		}
		return;
	}
	if ((g_role == 1 && from == g_peer_id) || (g_role == 2 && from == g_host_id)) {
		g_last_peer_rx = GetTickCount();
		to_game(data, len);
	}
}

// ---- finding the host (guest) -------------------------------------------------------------------------------------

static char g_want_name[64];

static u64 find_host_by_name_or_presence(void)
{
	int count = SteamAPI_ISteamFriends_GetFriendCount(g_friends, 4);
	for (int i = 0; i < count; i++) {
		u64 id = SteamAPI_ISteamFriends_GetFriendByIndex(g_friends, i, 4);
		if (!id)
			continue;
		if (g_want_name[0]) {
			const char *nm = SteamAPI_ISteamFriends_GetFriendPersonaName(g_friends, id);
			if (nm && !_stricmp(nm, g_want_name))
				return id;
			continue;
		}
		unsigned char info[32];
		memset(info, 0, sizeof info);
		if (!SteamAPI_ISteamFriends_GetFriendGamePlayed(g_friends, id, info))
			continue;
		u64 game = *(u64 *)info;
		u64 lobby = *(u64 *)(info + 16);
		if ((game & 0xffffff) == 480) {
			const char *rp = SteamAPI_ISteamFriends_GetFriendRichPresence(g_friends, id, "connect");
			if (rp && !strncmp(rp, "+connect_lobby", 14))
				return id;
			if (lobby)
				return id;
		}
	}
	return 0;
}

// ---- main loop --------------------------------------------------------------------------------------------------------

static void setup_udp(int port, int bind_port)
{
	WSADATA w;
	WSAStartup(MAKEWORD(2, 2), &w);
	g_udp = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
	struct sockaddr_in me;
	memset(&me, 0, sizeof me);
	me.sin_family = AF_INET;
	me.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
	me.sin_port = htons((u_short)bind_port);
	if (bind(g_udp, (struct sockaddr *)&me, sizeof me)) {
		logf_("cannot bind 127.0.0.1:%d (%d)", bind_port, WSAGetLastError());
		exit(2);
	}
	if (g_role == 1) {   // host: send to the DLL's port
		memset(&g_game_addr, 0, sizeof g_game_addr);
		g_game_addr.sin_family = AF_INET;
		g_game_addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
		g_game_addr.sin_port = htons((u_short)port);
		g_game_addr_known = 1;
	}
}

static void set_title(const char *s)
{
	char t[160];
	snprintf(t, sizeof t, "obscoop-relay - %s", s);
	SetConsoleTitleA(t);
}

static int selftest(void)
{
	if (!steam_up())
		return 1;
	const char *hello = "obscoop selftest";
	for (int i = 0; i < 100; i++) {
		pump_callbacks();
		if (i == 5)
			send_to(g_self, hello, (int)strlen(hello), 0, 1);
		void *msgs[4];
		int n = SteamAPI_ISteamNetworkingMessages_ReceiveMessagesOnChannel(g_msgs, 0, msgs, 4);
		for (int k = 0; k < n; k++) {
			const unsigned char *m = msgs[k];
			const unsigned char *d = *(const unsigned char *const *)m;
			int sz = *(const int *)(m + 4);
			logf_("selftest: received %d bytes \"%.*s\" from %llu (own id %llu)", sz, sz, d, (unsigned long long)msg_sender(m), (unsigned long long)g_self);
			SteamAPI_SteamNetworkingMessage_t_Release(msgs[k]);
			return 0;
		}
		Sleep(50);
	}
	logf_("selftest: nothing came back (Steam does not loop a message to the same account)");
	return 3;
}

int main(int argc, char **argv)
{
	if (argc < 2) {
		puts("usage: obscoop-relay host [udp_port] | guest [host id|name|lobby:id] [udp_port] | selftest   [--udp-link ...]");
		return 1;
	}
	const char *mode = argv[1];
	if (!strcmp(mode, "selftest"))
		return selftest();
	g_role = !strcmp(mode, "host") ? 1 : !strcmp(mode, "guest") ? 2 : 0;
	if (!g_role) {
		puts("mode must be host, guest or selftest");
		return 1;
	}
	int port = g_role == 1 ? 27961 : 27962;
	const char *target = "";
	const char *link = NULL;
	for (int i = 2; i < argc; i++) {
		if (!strcmp(argv[i], "--udp-link") && i + 1 < argc)
			link = argv[++i];
		else if (!strcmp(argv[i], "--lag") && i + 1 < argc)
			g_lag_ms = atoi(argv[++i]);
		else if (!strcmp(argv[i], "--jitter") && i + 1 < argc)
			g_jit_ms = atoi(argv[++i]);
		else if (!strcmp(argv[i], "--loss") && i + 1 < argc)
			g_loss_pct = atoi(argv[++i]);
		else if (g_role == 2 && !target[0] && !(argv[i][0] >= '0' && argv[i][0] <= '9' && strlen(argv[i]) < 6))
			target = argv[i];
		else if (atoi(argv[i]) > 0 && strlen(argv[i]) < 6)
			port = atoi(argv[i]);
		else
			target = argv[i];
	}
	setup_udp(port, g_role == 1 ? 0 : port);   // host: ephemeral socket, forwards to the DLL on `port`; guest: listens on `port`
	u64 want_id = 0, want_lobby = 0;
	if (g_role == 2) {
		if (!strncmp(target, "lobby:", 6))
			want_lobby = _strtoui64(target + 6, NULL, 10);
		else if (target[0] >= '0' && target[0] <= '9' && strlen(target) >= 15)
			want_id = _strtoui64(target, NULL, 10);
		else if (target[0])
			snprintf(g_want_name, sizeof g_want_name, "%s", target);
	}
	if (link) {   // plain UDP link between two relays
		g_use_link = 1;
		g_link = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
		struct sockaddr_in me;
		memset(&me, 0, sizeof me);
		me.sin_family = AF_INET;
		me.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
		if (!strncmp(link, "listen:", 7)) {
			me.sin_port = htons((u_short)atoi(link + 7));
			bind(g_link, (struct sockaddr *)&me, sizeof me);
			logf_("udp link: listening on 127.0.0.1:%d (lag %d ms, jitter %d ms, loss %d%%)", atoi(link + 7), g_lag_ms, g_jit_ms, g_loss_pct);
		} else {
			bind(g_link, (struct sockaddr *)&me, sizeof me);
			memset(&g_link_peer, 0, sizeof g_link_peer);
			g_link_peer.sin_family = AF_INET;
			g_link_peer.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
			g_link_peer.sin_port = htons((u_short)atoi(strchr(link, ':') ? strchr(link, ':') + 1 : link));
			g_link_peer_known = 1;
			logf_("udp link: sending to 127.0.0.1:%d", ntohs(g_link_peer.sin_port));
		}
	} else if (!steam_up()) {
		return 1;
	}
	logf_("relay %s: game UDP 127.0.0.1:%d%s", g_role == 1 ? "host" : "guest", port, g_use_link ? " (udp link, no Steam)" : "");
	if (!g_use_link && g_role == 1) {
		g_lobby_ready = 0;
		SteamAPI_ISteamMatchmaking_CreateLobby(g_mm, 1, 2);   // result arrives as callback 513
		char t[120];
		snprintf(t, sizeof t, "host, Steam ID %llu", (unsigned long long)g_self);
		set_title(t);
		FILE *f = fopen("steam_id.txt", "wb");
		if (f) {
			fprintf(f, "%llu\r\n", (unsigned long long)g_self);
			fclose(f);
		}
	}
	if (g_role == 2 && want_id)
		g_host_id = want_id;
	DWORD last_hello = 0, last_ping = 0, last_scan = 0, last_stat = 0;
	unsigned char buf[65536];
	for (;;) {
		DWORD now = GetTickCount();
		fd_set rd;
		FD_ZERO(&rd);
		FD_SET(g_udp, &rd);
		if (g_use_link)
			FD_SET(g_link, &rd);
		struct timeval tv = { 0, 2000 };
		int sel = select(0, &rd, NULL, NULL, &tv);
		if (g_use_link)
			lag_pump();
		if (!g_use_link)
			pump_callbacks();
		if (sel > 0 && FD_ISSET(g_udp, &rd)) {   // the game DLL -> peer
			struct sockaddr_in from;
			int fl = sizeof from;
			int n = recvfrom(g_udp, (char *)buf, sizeof buf, 0, (struct sockaddr *)&from, &fl);
			if (n > 0) {
				if (g_role == 2) {
					g_game_addr = from;
					g_game_addr_known = 1;
				}
				if (!g_use_link || g_linked || g_role == 2)
					to_peer(buf, n);
				g_tx_game++;
			}
		}
		if (g_use_link && sel > 0 && FD_ISSET(g_link, &rd)) {   // the peer relay (plain UDP) -> the game DLL
			struct sockaddr_in from;
			int fl = sizeof from;
			int n = recvfrom(g_link, (char *)buf, sizeof buf, 0, (struct sockaddr *)&from, &fl);
			if (n > 0) {
				g_link_peer = from;
				g_link_peer_known = 1;
				g_linked = 1;
				to_game(buf, n);
			}
		}
		if (!g_use_link) {
			drain_channel(CH_CONTROL, on_message);
			drain_channel(CH_GAME, on_message);
			if (g_role == 2) {
				if (!g_host_id && g_join_lobby_req) {
					SteamAPI_ISteamMatchmaking_JoinLobby(g_mm, g_join_lobby_req);   // result: LobbyEnter -> host id
					g_join_lobby_req = 0;
				}
				if (!g_host_id && want_lobby) {
					SteamAPI_ISteamMatchmaking_JoinLobby(g_mm, want_lobby);
					want_lobby = 0;
				}
				if (!g_host_id && now - last_scan >= 2000) {
					last_scan = now;
					u64 h = find_host_by_name_or_presence();
					if (h) {
						g_host_id = h;
						logf_("found the host %llu among your friends", (unsigned long long)h);
					}
				}
				if (g_host_id && !g_linked && now - last_hello >= 1000) {
					last_hello = now;
					send_to(g_host_id, "HELLO", 5, CH_CONTROL, 1);
				}
				if (!g_host_id && now - last_stat >= 5000) {
					last_stat = now;
					set_title("guest: looking for the host (Join Game, Steam ID or name)");
				}
			}
			if (g_linked && now - last_ping >= 1000) {
				last_ping = now;
				u64 to = g_role == 1 ? g_peer_id : g_host_id;
				if (to)
					send_to(to, "PING", 4, CH_CONTROL, 0);
			}
			if (g_linked && (int)(now - g_last_peer_rx) > 10000) {   // signed: g_last_peer_rx may be newer than `now` (taken at the top of the loop)
				logf_("peer silent for 10 s; link dropped");
				g_linked = 0;
				if (g_role == 1)
					g_peer_id = 0;
			}
		}
		{   // what Steam shows for this account: one game at a time, so the relay and the game can hide each other
			static DWORD last_presence;
			if (!g_use_link && now - last_presence >= 10000) {
				last_presence = now;
				unsigned char info[32];
				memset(info, 0, sizeof info);
				int playing = SteamAPI_ISteamFriends_GetFriendGamePlayed(g_friends, g_self, info);
				logf_("Steam shows this account as %s (game id %llu)", playing ? "playing" : "not playing", (unsigned long long)(*(u64 *)info & 0xffffff));
			}
		}
		if (now - last_stat >= 5000 && g_linked) {
			last_stat = now;
			char t[120];
			snprintf(t, sizeof t, "%s: linked, to game %llu / from game %llu packets", g_role == 1 ? "host" : "guest",
				(unsigned long long)g_rx_game, (unsigned long long)g_tx_game);
			set_title(t);
		}
	}
}
