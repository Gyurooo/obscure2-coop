// Network link between a host and a guest copy of Obscure II (included by obscoop2.c).
//
// Design (hybrid): both copies run the game. The host's controller is the guest's player 1, the guest's
// controller is the host's player 2, so each copy simulates both players from the same inputs and the
// game's own logic produces the animations, door opening and "Press A" prompts. The host stays
// authoritative: it sends level / load / menu requests, which the guest executes in step (the guest drops
// its own level changes), and position snapshots that correct drift.
//
// Roles (OBSCOOP_ROLE): host | guest. Transport (OBSCOOP_NET): udp (one-PC tests, loopback only,
// OBSCOOP_UDP = host port) or steam (P2P through the game's steam_api.dll, friends only).
// Packet: u32 magic, u8 type, u8 version, u16 payload length, u32 seq, payload.

#include <winsock2.h>
#include <ws2tcpip.h>

#define NET_MAGIC 0x50324f42u   // "BO2P" little-endian
#define NET_VERSION 4   // 2: pad packets carry the sender's camera yaw; 3: timeline stamps, input delay, clock sync;
                        // 4: the state snapshot also carries the host's pad and yaw, so a lost HOSTPAD does not stop player 1 animating
enum { PKT_HELLO = 1, PKT_WELCOME = 2, PKT_INPUT = 3, PKT_PING = 4, PKT_PONG = 5, PKT_BYE = 6, PKT_HOSTPAD = 7,
	PKT_STATE = 8, PKT_REQ = 9, PKT_NPC = 10, PKT_REGION = 11, PKT_ITEM = 12, PKT_SAVE = 13, PKT_SAVE_ACK = 14 };
enum { REQ_LEVEL = 1, REQ_LOAD_PROGRESS = 2, REQ_LOAD_NAME = 3, REQ_TO_MENU = 9 };

#pragma pack(push, 1)
typedef struct { DWORD magic; BYTE type, version; WORD len; DWORD seq; } pkt_hdr;
typedef struct { pkt_hdr h; DWORD t_ms; xstate pad; float yaw; DWORD yaw_valid; DWORD delay_ms; float rtt_ms; DWORD in_level; } pkt_pad;   // t_ms: host timeline stamp      // INPUT (guest -> host) and HOSTPAD (host -> guest)
typedef struct { pkt_hdr h; DWORD t_ms; DWORD host_ms; } pkt_ping;   // pong: host_ms = the host's clock when it answered
typedef struct { DWORD tag; float pos[3]; float dir[3]; DWORD s220, s278; DWORD life; DWORD anim; } ch_state;   // anim = character+0x2dc (death/animation state)   // life = character+0x320
#define MAX_CH 8
typedef struct { pkt_hdr h; DWORD t_ms; DWORD level; DWORD n; xstate hpad; float yaw; DWORD yaw_valid; ch_state ch[MAX_CH]; } pkt_state;
typedef struct { pkt_hdr h; DWORD kind, a, b, c; char name[64]; } pkt_req;
typedef struct { DWORD cls, tag; float pos[3]; float dir[3]; } npc_state;   // cls = the object's vtable address (its class)
// A copy of part of the progress object (game+0x318): story / world state the guest must share.
#define REGION_MAX 960
typedef struct { pkt_hdr h; DWORD level; DWORD off; DWORD len; BYTE data[REGION_MAX]; } pkt_region;
#define ITEM_MAX 64
typedef struct { pkt_hdr h; DWORD level; DWORD count; DWORD data[ITEM_MAX * 4]; } pkt_item;   // inventory: count + 16-byte entries
#define SAVE_CHUNK 512
typedef struct { pkt_hdr h; char name[32]; DWORD off; DWORD len; BYTE data[SAVE_CHUNK]; } pkt_save;
typedef struct { pkt_hdr h; char name[32]; DWORD off; } pkt_save_ack;
#define MAX_NPC 24
typedef struct { pkt_hdr h; DWORD t_ms; DWORD level; DWORD n; npc_state npc[MAX_NPC]; } pkt_npc;
#pragma pack(pop)

static void guest_on_state(const char *buf, int n);
static void guest_on_item(const char *buf, int n);
static void guest_on_save(const char *buf, int n);
static void host_on_save_ack(const char *buf, int n);
static void host_save_begin(void);
static void guest_on_req(const char *buf, int n);
static void guest_on_npc(const char *buf, int n);
static void guest_on_region(const char *buf, int n);
static volatile LONG g_join_pending;   // host: a guest just connected, send it the current state from the main thread

#include "steam.c"

static int g_use_steam;
static int g_last_candidates;
static int g_host_self_test;
static int g_remote_pad = 1, g_local_pad;   // host: the guest's pad is game user 1; guest: our controller index
static SOCKET g_sock = INVALID_SOCKET;
static struct sockaddr_in g_udp_peer;
static sid_t g_peer;
static volatile LONG g_peer_ok;
static volatile LONG g_net_rx, g_net_tx, g_net_bad, g_net_rtt_ms = -1;
static volatile LONG g_last_input_seq, g_last_hostpad_seq;
static DWORD g_last_guest_buttons;   // host: edge detection for the guest's START (pause request)
static volatile DWORD g_last_rx_tick;
static DWORD g_tx_seq;
static volatile float g_guest_rtt;      // host: the round trip the guest measured
static float g_rtt_max;                 // guest: the largest of the last 16 round trips (the delay has to cover it)

// Guest: estimate the host's clock. The sample with the smallest round trip among the last 8 is the best one.
static void clock_sample(const pkt_ping *pp)
{
	static int rtts[16], offs[8], nr, no;
	DWORD t1 = now_ms();
	int rtt = (int)(t1 - pp->t_ms);
	if (rtt < 0 || rtt > 5000)
		return;
	g_net_rtt_ms = rtt;
	rtts[nr++ & 15] = rtt;
	int mx = 0, cnt = nr < 16 ? nr : 16;
	for (int i = 0; i < cnt; i++)
		if (rtts[i] > mx)
			mx = rtts[i];
	g_rtt_max = (float)mx;
	int slot = no++ & 7;
	offs[slot] = (int)((LONG)(pp->host_ms - t1) + rtt / 2);
	static int offrtt[8];
	offrtt[slot] = rtt;
	int best = -1, ncount = no < 8 ? no : 8;
	for (int i = 0; i < ncount; i++)
		if (best < 0 || offrtt[i] < offrtt[best])
			best = i;
	g_clock_off = offs[best];
	if (no >= 3 && !g_clock_valid) {
		g_clock_valid = 1;
		logf("net: clock synced (host clock = ours %+ld ms, round trip %d ms)", g_clock_off, rtt);
	}
}

// The host's controller as the guest's game user 0 (player 1).
static xstate g_netpad;
static volatile DWORD g_netpad_tick;
static DWORD g_last_pad_t;   // host timeline stamp of the newest pad applied (HOSTPAD or STATE)

static sid_t udp_key(const struct sockaddr_in *a)
{
	return ((sid_t)ntohl(a->sin_addr.s_addr) << 16) | ntohs(a->sin_port);
}

static void net_send_to(sid_t to, BYTE type, void *pkt, WORD payload)
{
	pkt_hdr *h = (pkt_hdr *)pkt;
	h->magic = NET_MAGIC;
	h->type = type;
	h->version = NET_VERSION;
	h->len = payload;
	h->seq = ++g_tx_seq;
	int len = (int)(sizeof(pkt_hdr) + payload);
	int ok;
	if (g_use_steam) {
		ok = steam_send(to, pkt, len);
	} else {
		(void)to;
		ok = sendto(g_sock, (const char *)pkt, len, 0, (struct sockaddr *)&g_udp_peer, sizeof g_udp_peer) > 0;
	}
	if (ok)
		InterlockedIncrement(&g_net_tx);
}

static void net_send(BYTE type, void *pkt, WORD payload)
{
	net_send_to(g_peer, type, pkt, payload);
}

static int local_pad(int user, xstate *out)
{
	memset(out, 0, sizeof *out);
	if (user >= 0 && user < 4 && g_vpad_on[user]) {   // tests and bots: the virtual pad is this PC's own pad
		EnterCriticalSection(&g_vpad_cs);
		memcpy(out, &g_vpad[user], sizeof *out);
		LeaveCriticalSection(&g_vpad_cs);
		return 1;
	}
	load_xinput();
	return pad_read((DWORD)user, out) == ERROR_SUCCESS;
}

static void host_drop_guest(const char *why)
{
	if (!g_peer_ok)
		return;
	g_peer_ok = 0;
	vpad_set(g_remote_pad, 0, 0, 0, 0, 0, 0, 0, 0);
	logf("net: guest dropped (%s); virtual pad %d disconnected", why, g_remote_pad);
}

static void steam_session_request(sid_t from)
{
	InterlockedIncrement(&g_steam_session_requests);
	int ok = (g_host_self_test || getenv("OBSCOOP_ALLOW_SELF")) && from == g_self_sid ? 1 :
		g_role == 1 ? (g_peer_ok ? from == g_peer : steam_is_friend(from))
		: (g_host_sid_cfg ? from == g_host_sid_cfg : steam_is_friend(from));
	if (ok) {
		steam_accept(from);
		logf("steam: accepted a P2P session from a friend");
	} else {
		InterlockedIncrement(&g_steam_refused);
		logf("steam: refused a P2P session (not a friend, or not our peer)");
	}
}

// Sends a request to the guest (host only); the guest executes it in step with the host.
static void net_send_req(DWORD kind, unsigned a, unsigned b, unsigned c, const char *name)
{
	if (g_role != 1 || !g_peer_ok)
		return;
	pkt_req r;
	memset(&r, 0, sizeof r);
	r.kind = kind; r.a = a; r.b = b; r.c = c;
	if (name)
		_snprintf(r.name, sizeof r.name - 1, "%s", name);
	net_send(PKT_REQ, &r, sizeof r - sizeof(pkt_hdr));
}

static void net_handle(const char *buf, int n, sid_t from)
{
	const pkt_hdr *h = (const pkt_hdr *)buf;
	if (n < (int)sizeof *h || h->magic != NET_MAGIC || h->version != NET_VERSION ||
		(int)(sizeof *h + h->len) != n) {
		InterlockedIncrement(&g_net_bad);
		return;
	}
	if (g_role == 1) {
		if (!g_peer_ok) {
			if (h->type != PKT_HELLO)
				return;
			g_peer = from;
			g_peer_ok = 1;
			g_last_input_seq = 0;
			g_join_pending = 1;
			logf("net: guest joined (%s)", g_use_steam ? "steam" : "udp");
		} else if (from != g_peer) {
			return;
		}
		g_last_rx_tick = GetTickCount();
		InterlockedIncrement(&g_net_rx);
		switch (h->type) {
		case PKT_HELLO: {
			pkt_hdr w;
			host_save_begin();   // (re)send every save file to this guest
			net_send(PKT_WELCOME, &w, 0);
			break;
		}
		case PKT_INPUT: {
			const pkt_pad *in = (const pkt_pad *)buf;
			if (n != sizeof *in || (LONG)(h->seq - (DWORD)g_last_input_seq) <= 0)
				break;
			g_last_input_seq = (LONG)h->seq;
			// START from the guest pauses both copies: pulse player 1's START, which the game and the
			// HOSTPAD stream both see. Only while the guest is in a level.
			if (in->in_level && (in->pad.buttons & 0x0010) && !(g_last_guest_buttons & 0x0010) && game_in_level())
				g_pause_pulse_until = GetTickCount() + 120;
			g_last_guest_buttons = in->pad.buttons;
			if (in->yaw_valid) { g_peer_yaw = in->yaw; g_peer_yaw_valid = 1; }
			ring_push(&g_ring_p2, in->t_ms, &in->pad);
			g_guest_rtt = in->rtt_ms;
			vpad_set(g_remote_pad, 1, in->pad.buttons, in->pad.lx, in->pad.ly, in->pad.rx, in->pad.ry, in->pad.lt, in->pad.rt);
			break;
		}
		case PKT_PING: {
			pkt_ping pong = *(const pkt_ping *)buf;
			pong.host_ms = now_ms();
			if (n == sizeof pong)
				net_send(PKT_PONG, &pong, sizeof pong - sizeof(pkt_hdr));
			break;
		}
		case PKT_BYE:
			host_drop_guest("bye");
			break;
		case PKT_SAVE_ACK:
			host_on_save_ack(buf, n);
			break;
		}
	} else if (g_role == 2) {
		if (!g_peer_ok) {
			if (h->type != PKT_WELCOME)
				return;
			g_peer = from;
			g_peer_ok = 1;
			g_last_hostpad_seq = 0;
			logf("net: host welcomed us (%s)", g_use_steam ? "steam" : "udp");
		} else if (from != g_peer) {
			return;
		}
		g_last_rx_tick = GetTickCount();
		InterlockedIncrement(&g_net_rx);
		if (h->type == PKT_HOSTPAD) {
			const pkt_pad *in = (const pkt_pad *)buf;
			if (n == sizeof *in && (LONG)(h->seq - (DWORD)g_last_hostpad_seq) > 0) {
				g_last_hostpad_seq = (LONG)h->seq;
				g_netpad = in->pad;
				g_last_pad_t = in->t_ms;
				ring_push(&g_ring_p1, in->t_ms, &in->pad);
				if (in->delay_ms >= 20 && in->delay_ms <= 400)
					g_delay_ms = (LONG)in->delay_ms;
				if (in->yaw_valid) { g_peer_yaw = in->yaw; g_peer_yaw_valid = 1; }
				g_netpad_tick = GetTickCount();
			}
		} else if (h->type == PKT_SAVE) {
		guest_on_save(buf, n);
	} else if (h->type == PKT_ITEM) {
		guest_on_item(buf, n);
	} else if (h->type == PKT_STATE) {
			guest_on_state(buf, n);
		} else if (h->type == PKT_REGION) {
			guest_on_region(buf, n);
		} else if (h->type == PKT_NPC) {
			guest_on_npc(buf, n);
		} else if (h->type == PKT_REQ) {
			guest_on_req(buf, n);
		} else if (h->type == PKT_PONG && n == sizeof(pkt_ping)) {
			clock_sample((const pkt_ping *)buf);
		}
	}
}

// Test only: OBSCOOP_DROP_HOSTPAD=1 suppresses HOSTPAD on the host, to check that the snapshot's
// copy of the pad keeps the guest's player 1 animating when the pad stream is lost.
static int drop_hostpad_test(void)
{
	static int v = -1;
	if (v < 0) {
		v = GetEnvironmentVariableA("OBSCOOP_DROP_HOSTPAD", NULL, 0) ? 1 : 0;
		if (v) logf("net: HOSTPAD suppressed (OBSCOOP_DROP_HOSTPAD=1)");
	}
	return v;
}

static void net_tick(void)
{
	static DWORD last_hello, last_ping, last_pad, tick;
	DWORD now = GetTickCount();
	if (g_role == 1) {
		if (g_peer_ok && now - g_last_rx_tick > (g_use_steam ? 10000u : 3000u))
			host_drop_guest(g_use_steam ? "timeout 10 s" : "timeout 3 s");
		static DWORD last_accept;
		if (g_use_steam && !g_peer_ok && now - last_accept >= 2000) {
			last_accept = now;
			// Steam may not show the friend as playing Obscure II, so accept from every friend (the guest's hello
			// is what starts the link; a session from a stranger is still refused in the callback).
			sid_t ids[256];
			int k = steam_all_friends(ids, 256);
			g_last_candidates = k;
			for (int i = 0; i < k; i++)
				steam_accept(ids[i]);
		}
		if (g_peer_ok && !drop_hostpad_test() && now - last_pad >= 8) {   // the host's own pad is the guest's player 1
			pkt_pad hp;
			local_pad(0, &hp.pad);
			hp.in_level = 1;
			hp.t_ms = now_ms();
			ring_push(&g_ring_p1, hp.t_ms, &hp.pad);
			{   // the delay follows the round trip the guest reports: half of it plus a margin; up quickly, down slowly
				static DWORD last_adapt;
				if (now - last_adapt >= 100) {
					last_adapt = now;
					int target = g_guest_rtt > 0 ? (int)(g_guest_rtt * 0.5f) + 30 : 60;
					target = target < 40 ? 40 : target > 250 ? 250 : target;
					int d = (int)g_delay_ms;
					d += target > d ? ((target - d) > 10 ? 10 : (target - d)) : -((d - target) > 2 ? 2 : (d - target));
					g_delay_ms = d;
				}
			}
			hp.delay_ms = (DWORD)g_delay_ms;
			hp.yaw = g_cam_yaw; hp.yaw_valid = (DWORD)g_cam_yaw_valid;
			net_send(PKT_HOSTPAD, &hp, sizeof hp - sizeof(pkt_hdr));
			last_pad = now;
		}
		return;
	}
	if (!g_peer_ok && now - last_hello >= 1000) {
		pkt_hdr hello;
		if (g_use_steam) {
			sid_t hosts[16];
			int n = steam_find_hosts(hosts, 16);
			g_last_candidates = n;
			static int scan_only = -1;
			if (scan_only < 0)
				scan_only = getenv("OBSCOOP_SCAN_ONLY") != NULL;   // test: count candidates, contact nobody
			for (int i = 0; i < n && !scan_only; i++)
				net_send_to(hosts[i], PKT_HELLO, &hello, 0);
			static int logged;
			if (!logged++)
				logf("net: looking for the host among %d candidate(s)", n);
		} else {
			net_send(PKT_HELLO, &hello, 0);
		}
		last_hello = now;
	}
	if (g_peer_ok && now - g_last_rx_tick > (g_use_steam ? 10000u : 3000u)) {
		g_peer_ok = 0;
		logf("net: host silent; saying hello again");
	}
	if (g_peer_ok && now - last_pad >= 8) {   // this PC's controller is the host's player 2
		pkt_pad in;
		local_pad(g_local_pad, &in.pad);
		in.in_level = (DWORD)game_in_level();
		in.t_ms = timeline_now();
		in.delay_ms = 0;
		in.rtt_ms = g_rtt_max;
		ring_push(&g_ring_p2, in.t_ms, &in.pad);
		in.yaw = g_cam_yaw; in.yaw_valid = (DWORD)g_cam_yaw_valid;
		net_send(PKT_INPUT, &in, sizeof in - sizeof(pkt_hdr));
		last_pad = now;
	}
	if (g_peer_ok && now - last_ping >= (g_clock_valid ? 500u : 150u)) {
		pkt_ping p;
		p.t_ms = now_ms();
		p.host_ms = 0;
		net_send(PKT_PING, &p, sizeof p - sizeof(pkt_hdr));
		last_ping = now;
	}
}

static DWORD WINAPI udp_thread(LPVOID arg)
{
	(void)arg;
	char buf[4096];
	for (;;) {
		fd_set rd;
		FD_ZERO(&rd);
		FD_SET(g_sock, &rd);
		struct timeval tv = { 0, 2000 };
		if (select(0, &rd, NULL, NULL, &tv) > 0) {
			struct sockaddr_in from;
			int fl = sizeof from;
			int n = recvfrom(g_sock, buf, sizeof buf, 0, (struct sockaddr *)&from, &fl);
			if (n > 0) {
				if (g_role == 1 && !g_peer_ok)
					g_udp_peer = from;
				net_handle(buf, n, udp_key(&from));
			}
		}
		net_tick();
	}
}

// Steam: once per frame on the main thread (Present hook).
static void net_frame(void)
{
	if (!g_use_steam || !g_role)
		return;
	if (!g_steam_ok) {
		static DWORD last_try;
		if (GetTickCount() - last_try < 1000)
			return;
		last_try = GetTickCount();
		if (!steam_start())
			return;
		g_steam_ok = 1;
		if (g_role == 1) {   // the host tells the friend this number (or the friend uses the host's Steam name)
			char path[MAX_PATH];
			_snprintf(path, MAX_PATH, "%s\\steam_id.txt", g_data);
			HANDLE f = CreateFileA(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS, 0, NULL);
			if (f != INVALID_HANDLE_VALUE) {
				char line[96];
				int l = _snprintf(line, sizeof line, "%llu\r\n", (unsigned long long)g_self_sid);
				DWORD w;
				WriteFile(f, line, (DWORD)l, &w, NULL);
				CloseHandle(f);
			}
			logf("steam: host Steam ID %llu (written to steam_id.txt; the guest puts it after HOST_STEAMID= in obscoop.ini)", (unsigned long long)g_self_sid);
		}
		if (g_host_self_test)
			g_host_sid_cfg = g_self_sid;
	}
	steam_poll();
	net_tick();
}

static int env_int(const char *name, int def)
{
	char v[32];
	return GetEnvironmentVariableA(name, v, sizeof v) ? atoi(v) : def;
}

static void net_start(void)
{
	char role[16] = "", net[16] = "udp", peer[64] = "127.0.0.1", hostid[32] = "";
	GetEnvironmentVariableA("OBSCOOP_ROLE", role, sizeof role);
	GetEnvironmentVariableA("OBSCOOP_NET", net, sizeof net);
	GetEnvironmentVariableA("OBSCOOP_PEER", peer, sizeof peer);
	GetEnvironmentVariableA("OBSCOOP_HOST_STEAMID", hostid, sizeof hostid);
	GetEnvironmentVariableA("OBSCOOP_HOST_NAME", g_host_name, sizeof g_host_name);
	g_role = !_stricmp(role, "host") ? 1 : !_stricmp(role, "guest") ? 2 : 0;
	if (!g_role)
		return;
	g_remote_pad = env_int("OBSCOOP_REMOTE_PAD", 1) & 3;
	g_remote_pad_idx = g_remote_pad;
	g_local_pad = env_int("OBSCOOP_LOCAL_PAD", 0) & 3;
	if (!_stricmp(net, "steam")) {
		g_use_steam = 1;
		g_host_sid_cfg = _strtoui64(hostid, NULL, 10);
		g_host_self_test = !_stricmp(hostid, "self");
		logf("net: %s over steam (starts after SteamAPI_Init), remote pad %d, local pad %d, host id %s",
			g_role == 1 ? "host" : "guest", g_remote_pad, g_local_pad, g_host_sid_cfg ? "configured" : "from friends list");
		return;
	}
	if (_stricmp(net, "udp")) {
		logf("net: transport '%s' unknown", net);
		g_role = 0;
		return;
	}
	int port = env_int("OBSCOOP_UDP", 27961);
	WSADATA w;
	WSAStartup(MAKEWORD(2, 2), &w);
	g_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
	struct sockaddr_in me = { 0 };
	me.sin_family = AF_INET;
	me.sin_addr.s_addr = htonl(INADDR_LOOPBACK);   // loopback only: udp is the one-PC test transport
	if (g_role == 1) {
		me.sin_port = htons((u_short)port);
	} else {
		me.sin_port = 0;
		g_udp_peer.sin_family = AF_INET;
		g_udp_peer.sin_port = htons((u_short)port);
		inet_pton(AF_INET, peer, &g_udp_peer.sin_addr);
		g_peer = udp_key(&g_udp_peer);
	}
	if (bind(g_sock, (struct sockaddr *)&me, sizeof me)) {
		logf("net: bind failed (%d)", WSAGetLastError());
		return;
	}
	logf("net: %s over udp, %s port %d, remote pad %d, local pad %d", g_role == 1 ? "host" : "guest",
		g_role == 1 ? "listening on 127.0.0.1" : peer, port, g_remote_pad, g_local_pad);
	CloseHandle(CreateThread(NULL, 0, udp_thread, NULL, 0, NULL));
}

// One line for the window title: who we are and whether we are linked.
static void net_status_line(char *out, size_t sz)
{
	if (!g_role) {
		_snprintf(out, sz, "co-op off (no role set)");
	} else if (g_use_steam && !g_steam_ok) {
		_snprintf(out, sz, "co-op %s: waiting for Steam", g_role == 1 ? "host" : "guest");
	} else if (!g_peer_ok) {
		if (g_role == 1)
			{
			if (g_use_steam && g_self_sid)
				_snprintf(out, sz, "co-op host: waiting for a guest. Your Steam ID: %llu", (unsigned long long)g_self_sid);
			else
				_snprintf(out, sz, "co-op host: waiting for a guest (%s)", g_use_steam ? "Steam" : "UDP");
		}
		else
			_snprintf(out, sz, "co-op guest: looking for the host (%d candidate%s%s)", g_last_candidates, g_last_candidates == 1 ? "" : "s",
				g_host_sid_cfg ? ", by Steam ID" : g_host_name[0] ? ", by Steam name" : "");
	} else if (g_net_rtt_ms >= 0) {
		_snprintf(out, sz, "co-op %s: connected, %ld ms", g_role == 1 ? "host" : "guest", g_net_rtt_ms);
	} else {
		_snprintf(out, sz, "co-op %s: connected", g_role == 1 ? "host" : "guest");
	}
	out[sz - 1] = 0;
}

static void net_status(char *reply, size_t replysz)
{
	_snprintf(reply, replysz, "net role %s via %s peer_ok %ld rx %ld tx %ld bad %ld last_input_seq %ld rtt_ms %ld",
		g_role == 1 ? "host" : g_role == 2 ? "guest" : "off", g_use_steam ? "steam" : "udp", g_peer_ok, g_net_rx,
		g_net_tx, g_net_bad, g_last_input_seq, g_net_rtt_ms);
	size_t l = strlen(reply);
	if (g_use_steam && l < replysz)
		_snprintf(reply + l, replysz - l, " steam_ok %ld session_requests %ld accepted %ld refused %ld tx_fail %ld candidates %d", g_steam_ok,
			g_steam_session_requests, g_steam_accepted, g_steam_refused, g_steam_tx_fail, g_last_candidates);
}
