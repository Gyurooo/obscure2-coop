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
#define NET_VERSION 23   // 2: pad packets carry the sender's camera yaw; 3: timeline stamps, input delay, clock sync;
                        // 4: the state snapshot also carries the host's pad and yaw, so a lost HOSTPAD does not stop player 1 animating
                        // 5: ch_state carries the four live weapon tags and the selected slot (the hands)
                        // 6: PKT_ITEM carries whole 32-byte inventory entries (chunked), not 16-byte halves
                        // 7: PKT_SAVES_DONE tells the guest when the host's save transfer is complete (the guest may then
                        //    load a transferred save with the game's own menu path)
                        // 8: PKT_SAVES_DONE names the save file that just completed (and says when all of them have); the
                        //    transfer sends the file the host's load named (o2.sav too), not only game0..9.sav
                        // 9: PKT_PICKUP: a placed world item collected on one copy is collected on the other (both directions)
                        // 10: npc_state carries the enemy's life (+0x320) and AI/death state (+0x2dc); the host owns them
                        // 11: PKT_ITEMUSE: an item use on the guest's own player 2 is applied by the host (which owns the
                        //     inventory and the character life), so it lands once and is not reverted by the next snapshot
                        // 12: TASK 25: PKT_HELLO carries the guest's level / in-level / need-saves (a reconnect resumes
                        //     without a reload); PKT_CHAR: each side streams the character it owns (the guest player 2,
                        //     the host player 1) so the other copy follows the owner instead of re-simulating it
                        // 13: TASK 26, PKT_PROP: breakable/carryable props (chairs and cases) keep the same carried /
                        //     broken state and drop item on both copies
                        // 14: TASK 27: a PKT_PROP break also names the character that was holding the prop, so the
                        //     peer finds it by the hand it is in (a carried chair's position is no identity)
                        // 15: TASK 28, PKT_APT: an aptitude object's result (lock picked -> door unlocked, heavy
                        //     case moved) reaches the other copy as the fields/position it changed
                        // 16: TASK 30, PKT_SCENE: both copies stream the world's scripted-event state
                        //     (world+0x11c / world+0x12c) and a skip by either player skips on both; pkt_state
                        //     also carries the battery/energy (inventory+0xc88) a story event may set
                        // 17: TASK 31: pkt_scene carries leave_seq, so "I left the event" is an event that
                        //     cannot be lost (the receiver keeps a pending skip instead of comparing scene ids)
                        // 18: TASK 34, PKT_DOOR: a used door/transition object plays on the other copy too;
                        //     PKT_LEVELASK: the guest's own (dropped) ChangeLevel is asked of the host
                        // 19: TASK 36, PKT_MENU: both copies stream the menu state (world+0x11c: 5 = pause,
                        //     2 = inventory; each controller's UI state +0xa4: 3 = weapon wheel, 4 = item
                        //     menu). Both pads drive the open menu on both copies (merged input) and a
                        //     divergence is repaired by pulsing the same button on the right pad.
                        // 20: TASK 37, ordered transitions: pkt_req carries the host's transition sequence
                        //     (the guest applies only the newest, an older one is dropped/cancelled);
                        //     pkt_state carries the host's authoritative level/entry and whether it is in a
                        //     transition, so the guest can re-converge on the host's level (self-heal).
                        // 21: TASK 42, the puppet model: pkt_char now goes in BOTH directions (each copy
                        //     streams the character its own pad drives) and carries the velocity and the
                        //     owner's speed (character+0x278), so the receiver plays the peer's real
                        //     walk/run/action animation through the game's own state setter instead of
                        //     re-simulating it from a streamed pad. The character positions in pkt_state
                        //     no longer correct anyone.
                        // 22: TASK 43, the owner's per-player UI: pkt_char also carries the UI state of the
                        //     owner's own controller (+0xa4: 1 = aim stance, 3 = weapon wheel, 4 = item menu)
                        //     and the selected weapon slot (+0x714). The receiver writes them on the puppet's
                        //     controller record and calls the game's own HUD functions for that player, so
                        //     each player sees the other's wheel / item menu as before the puppet model.
                        // 23: TASK 46, the MOVE INTENT (Obscure 1 `host_record_wanted` + intent): pkt_char
                        //     also carries the owner's move direction (character+0x288, the value its input
                        //     controller writes through vtable slot 0x60) and the owner's last four state
                        //     changes with a sequence number. The receiver writes the intent into the puppet
                        //     and lets the game's own movement state machine run in the locomotion states,
                        //     so the game picks the gait and the lower-body animation layer (FINDINGS_46).
enum { PKT_HELLO = 1, PKT_WELCOME = 2, PKT_INPUT = 3, PKT_PING = 4, PKT_PONG = 5, PKT_BYE = 6, PKT_HOSTPAD = 7,
	PKT_STATE = 8, PKT_REQ = 9, PKT_NPC = 10, PKT_REGION = 11, PKT_ITEM = 12, PKT_SAVE = 13, PKT_SAVE_ACK = 14,
	PKT_SAVES_DONE = 15, PKT_PICKUP = 16, PKT_ITEMUSE = 17, PKT_CHAR = 18, PKT_PROP = 19, PKT_PROPS = 20,
	PKT_APT = 21, PKT_SCENE = 22, PKT_DOOR = 23, PKT_LEVELASK = 24, PKT_MENU = 25 };
enum { REQ_LEVEL = 1, REQ_LOAD_PROGRESS = 2, REQ_LOAD_NAME = 3, REQ_TO_MENU = 9 };

#pragma pack(push, 1)
typedef struct { DWORD magic; BYTE type, version; WORD len; DWORD seq; } pkt_hdr;
typedef struct { pkt_hdr h; DWORD t_ms; xstate pad; float yaw; DWORD yaw_valid; DWORD delay_ms; float rtt_ms; DWORD in_level; } pkt_pad;   // t_ms: host timeline stamp      // INPUT (guest -> host) and HOSTPAD (host -> guest)
typedef struct { pkt_hdr h; DWORD t_ms; DWORD host_ms; } pkt_ping;   // pong: host_ms = the host's clock when it answered
typedef struct { DWORD tag; float pos[3]; float dir[3]; DWORD s220, s278; DWORD life; DWORD anim; DWORD wep[4]; DWORD wcur; } ch_state;   // anim = character+0x2dc (death/animation state)   // life = character+0x320   // wep = the tags in the 4 live weapon slots (character+0x704 + i*4 -> weapon+0x10), wcur = character+0x714
#define MAX_CH 8
typedef struct { pkt_hdr h; DWORD t_ms; DWORD level; DWORD n; xstate hpad; float yaw; DWORD yaw_valid;
                 float energy; DWORD energy_valid; DWORD host_level, host_entry, host_busy, host_seq; ch_state ch[MAX_CH]; } pkt_state;
// TASK 25: the guest's hello repeats what it already has, so a reconnect is a resume and not a fresh join:
// level = the world tag it is in (0 = none), in_level = 1 when its game is in a level, need_saves = 1
// when this process has not received a save file from the host yet.
typedef struct { pkt_hdr h; DWORD level; DWORD in_level; DWORD need_saves; } pkt_hello;
// TASK 25/42: the character this copy owns (host: player 1, guest: player 2), streamed so the other
// copy plays it as a PUPPET (position, facing, the owner's speed +0x278, the game state +0x2dc) instead
// of re-simulating it from a delayed pad in another camera frame. vel = the character's velocity vector
// (character+0x294..0x29c); speed = character+0x278 (the value the game's own movement state machine
// uses to choose idle/walk/run); anim = character+0x2dc (the state id the whole game switches on, see
// FINDINGS_42 §1).
typedef struct { pkt_hdr h; DWORD t_ms; DWORD level; ch_state me; float vel[3]; DWORD speed;
                 DWORD ui; DWORD wsel;
                 // TASK 46: the MOVE INTENT. intent = character+0x288..0x290 (what the owner's input
                 // controller wrote through vtable slot 0x60; the move direction the game's own movement
                 // state machine turns into a step and into the lower-body animation layer at +0x224).
                 // wanted = the owner's current state (+0x2dc); ev_seq/ev_val = the last four value CHANGES
                 // of it, recorded on the owner before its update (Obscure 1 `host_record_wanted`), so a
                 // state that lasts less than one send interval (a swing, a use, a climb start) still
                 // reaches the receiver and is replayed in order.
                 float intent[3]; DWORD wanted; DWORD ev_seq; DWORD ev_val[4];
                 // gait: the owner's lower-body gait index (character+0x2e0: 0 pause, 1 forward, 2 back,
                 // 3 right, 4 left - what FUN_004da570 computes from the intent and the aim target and
                 // what FUN_004e7420 (vtable slot 0x4c) turns into the lower-body clip +0x224).
                 DWORD gait; } pkt_char;
typedef struct { pkt_hdr h; DWORD kind, a, b, c; char name[64]; DWORD seq; } pkt_req;
// life = character+0x320 (float bits), state = character+0x2dc (the NPC's AI/animation/death state; the
// same field the humans stream as `anim`). TASK 21: the host owns enemy life and death, the guest applies
// the difference through the game's own life method (see guest_apply_npcs).
typedef struct { DWORD cls, tag; float pos[3]; float dir[3]; DWORD life; DWORD state; } npc_state;   // cls = the object's vtable address (its class)
// A copy of part of the progress object (game+0x318): story / world state the guest must share.
#define REGION_MAX 960
typedef struct { pkt_hdr h; DWORD level; DWORD off; DWORD len; BYTE data[REGION_MAX]; } pkt_region;
#define ITEM_MAX 99     // the game's inventory holds up to 99 entries (FUN_004b0430 / FUN_004b07e0)
#define ITEM_CHUNK 32   // entries per packet: 32*32 + 32 bytes header = 1056, under the Steam transport's 1200-byte rule
// The inventory object (world+0x1790) is count at +4 and entries at +8, stride 0x20 (FUN_004b04a0: entry = obj+8+i*0x20).
// One entry is 32 bytes: +0 flags, +4 tag, +8 id, +0xc ammo, +0x10 (float, grenade count). Send whole entries, in
// chunks: off = first entry in this packet, count = entries here, total = the inventory's count.
typedef struct { pkt_hdr h; DWORD level; DWORD off; DWORD count; DWORD total; DWORD data[ITEM_CHUNK * 8]; } pkt_item;
#define SAVE_CHUNK 512
typedef struct { pkt_hdr h; char name[32]; DWORD off; DWORD len; BYTE data[SAVE_CHUNK]; } pkt_save;
typedef struct { pkt_hdr h; char name[32]; DWORD off; } pkt_save_ack;
// "this save file is complete on the guest" (name set), or all of them are (all = 1, name empty).
typedef struct { pkt_hdr h; DWORD all; char name[32]; } pkt_saves_done;
#define MAX_NPC 24
typedef struct { pkt_hdr h; DWORD t_ms; DWORD level; DWORD n; npc_state npc[MAX_NPC]; } pkt_npc;
// A placed world item collected on one copy: the other copy collects the same level entity through the
// game's own item collect method (class tag at item+0x10, id at item+4, position at item+0x6c).
typedef struct { pkt_hdr h; DWORD level; DWORD cls; DWORD id; float pos[3]; DWORD ch_tag; } pkt_pickup;
// A guest-side item use (TASK 24): the tag of the inventory item and the player who used it. The host
// applies it through the game's own use method, because the inventory (PKT_ITEM) and the character life
// (ch_state) are host-owned.
typedef struct { pkt_hdr h; DWORD player; DWORD tag; } pkt_itemuse;
// A breakable/carryable level prop (TASK 26). kind 1 = this character carries it, 2 = it carries nothing,
// 3 = it just broke. cls/id/pos name the prop (class tag at +0x10, id at +4, position at +0x6c); ch_tag
// names the character for a carry; drop_cls/drop_id/drop_pos name the item entity the break enabled
// (0 = the break produced none).
typedef struct { pkt_hdr h; DWORD kind; DWORD level; DWORD ch_tag; DWORD cls, id; float pos[3];
                 DWORD drop_cls, drop_id; float drop_pos[3]; } pkt_prop;
// The host's prop state once a second (TASK 26): every prop that is broken and the drop it enabled, so a
// break announcement lost with a packet, or made while the link was paused, still reaches the guest.
#define PROP_STATE_MAX 24
typedef struct { DWORD cls, id, drop_cls, drop_id; float pos[3], drop_pos[3]; } prop_state;
typedef struct { pkt_hdr h; DWORD level; DWORD n; prop_state e[PROP_STATE_MAX]; } pkt_props;
// TASK 28: an aptitude object's result. kind 1 = the character just started an ability on cls/id (action;
// the peer only logs it - the animation follows in ch_state); kind 2 = the object's result: the fields and
// the position that changed, so the peer writes exactly those (and only where its own value still equals
// the sender's "before"). cls/id/pos name the object (class tag +0x10, id +4, position +0x6c); ch_tag is
// the character that ran the ability.
#define APT_FIELDS 10
typedef struct { pkt_hdr h; DWORD kind; DWORD level; DWORD ch_tag; DWORD cls, id; float before[3];
                 DWORD old[APT_FIELDS], now[APT_FIELDS]; float pos[3]; } pkt_apt;
// TASK 30: the world's scripted-event state (FINDINGS_30). state = world+0x11c (1 normal, 5 pause menu,
// 6 cinematic presentation, 0x11 game over), scene = world+0x12c (0 none, 6 kine, 7, 8 noe scene, 0xd),
// flags = world+0x130, a/b/d = world+0x138/0x13c/0x118 (the kine's parameters, a = the scene id).
// cine = 1 when the sender's copy is presenting a scripted event; a copy that is in one and hears that
// the peer is not in one applies the game's own skip, so both copies leave together.
// leave_seq (TASK 31) counts the sender's leaves of a scripted event: the receiver arms a pending skip on
// a change, so a leave cannot be lost by comparing scene ids (which differ between the copies) and it
// stays armed while the receiver's own scene is not there (yet). The sender repeats the leave until the
// peer has left too.
typedef struct { pkt_hdr h; DWORD t_ms; DWORD level; DWORD state; DWORD scene; DWORD flags; DWORD a, b, d;
                 DWORD name4; DWORD cine; DWORD leave_seq; } pkt_scene;
// TASK 34: a level-transition object (a door) was used on one copy. kind 1 = the use started. cls is the
// entity's class vtable address (the same on both copies: same exe build), id its +4, pos its +0x6c,
// ch_tag the character that used it. The receiver replays the game's own use path (vtable+0x34 then
// vtable+0x70) on its own copy of the same entity with the same character, so the door animation plays
// on both copies instead of only the level change.
typedef struct { pkt_hdr h; DWORD kind; DWORD level; DWORD ch_tag; DWORD cls, id; float pos[3]; } pkt_door;
// TASK 34: the guest's own ChangeLevel is not performed (the host decides). Once the host's own path has
// had its chance (the guest used the same door, so the host runs it too), the guest asks the host to do
// it; kind 1 = ask, kind 2 = cancel (the host already asked for that level and it was applied).
typedef struct { pkt_hdr h; DWORD kind; DWORD level, entry, flag; } pkt_levelask;
// TASK 36: a menu is a shared session state. state = world+0x11c (5 pause menu, 2 inventory menu, 1 normal),
// ui0/ui1 = the two input controllers' UI state (+0xa4: 0 none, 1 aim, 3 weapon wheel, 4 item menu), owner =
// the player whose UI state changed last (0/1, or -1 when only the world state did). The pads normally carry a
// menu open/close on both copies by themselves; this packet repairs the case where one copy did not see the
// input (a lost pad packet, a load in between), by pulsing the same button on the other copy.
typedef struct { pkt_hdr h; DWORD level; DWORD state, ui0, ui1; DWORD owner; DWORD seq; } pkt_menu;
#pragma pack(pop)

static void guest_on_state(const char *buf, int n);
static void guest_on_item(const char *buf, int n);
static void guest_on_save(const char *buf, int n);
static void guest_on_saves_done(const char *buf, int n);
static void guest_save_session(void);
static void host_on_save_ack(const char *buf, int n);
static void host_save_begin(void);
static void guest_on_req(const char *buf, int n);
static void guest_on_npc(const char *buf, int n);
static void guest_on_region(const char *buf, int n);
static void peer_on_pickup(const char *buf, int n);
static void peer_on_itemuse(const char *buf, int n);
static void peer_on_char(const char *buf, int n);   // TASK 42: the peer's character (a puppet here)
static void char_send_local(void);                 // TASK 42: this copy's own character, every 16 ms (sync.c)
static void peer_on_prop(const char *buf, int n);
static void guest_on_props(const char *buf, int n);
static void peer_on_apt(const char *buf, int n);
static void peer_on_scene(const char *buf, int n);   // TASK 30: the peer's scripted-event state (both roles)
static void peer_on_door(const char *buf, int n);    // TASK 34: a door used on the peer (both roles)
static void host_on_levelask(const char *buf, int n);   // TASK 34: the guest asks the host for a level change
static void peer_on_menu(const char *buf, int n);       // TASK 36: the peer's menu state (both roles)
static unsigned rd32(unsigned addr);      // sync.c
static unsigned world_obj(void);          // sync.c
static int guest_need_saves(void);        // sync.c: this process has no save file from the host yet
static volatile LONG g_join_pending;   // host: a guest just connected, send it the current state from the main thread
// Host: what the guest's last PKT_HELLO said about its own state. A reconnect inside the same level
// must not load anything (TASK 25 part B).
static DWORD g_hello_level, g_hello_in_level, g_hello_need_saves;

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

// ---- TASK 41: one transport thread for both transports ---------------------------------------------
// udp_thread used to own receive + net_tick for UDP (every <= 2 ms) while the Steam path ran the same work
// once per rendered frame inside net_frame, i.e. not at all during loads, long frames and stalls: the owner's
// Steam playtest was unplayable while every (UDP) test passed. Now one thread does receive + net_tick for UDP
// AND Steam at the same pacing; net_frame keeps only what belongs to the game thread (Steam init).
// OBSCOOP_TRANSPORT_FRAME=1 (test only) puts the old per-frame pump back on UDP, so the difference can be
// measured with the same DLL, the same link and the same checks.
static int g_transport_frame;            // OBSCOOP_TRANSPORT_FRAME=1: no transport thread, net_frame pumps
static int g_transport_fps;             // OBSCOOP_TRANSPORT_FPS=N: the modelled frame rate of the pump (0 = every Present)
static HANDLE g_net_thread, g_net_timer;
static volatile LONG g_net_ticks;         // transport loop iterations (pacing evidence)
static DWORD g_net_last_note;
static void net_tick(void);               // below

// ---- test-only link pause (TASK 25 part B) -----------------------------------------------------
// `netpause <ms>` on the pipe stops this copy from sending and receiving for that long, which is how the
// reconnect test drops the link in the middle of play without touching the transport. 0 clears it.
static volatile LONG g_net_pause_until;
static int net_paused(void)
{
	DWORD until = (DWORD)g_net_pause_until;
	return until && (LONG)(GetTickCount() - until) < 0;
}
// TASK 27: `netdroprx <ms>` drops only what arrives (the send path keeps running) - the shape of "packets
// lost while the link is up". Measured in TASK 27: the copy that drops its own incoming packets also loses
// the partner's controller from the game's point of view, and it stops applying prop packets for the rest of
// the session, so check_breakables.py no longer drives a phase with it (see FINDINGS_27 §5). Kept as a test
// switch next to `netpause` for "lost datagram" experiments.
static volatile LONG g_net_rx_drop_until;
static int net_rx_dropped(void)
{
	DWORD until = (DWORD)g_net_rx_drop_until;
	return until && (LONG)(GetTickCount() - until) < 0;
}
static void net_rx_drop_set(DWORD ms)
{
	LONG until = ms ? (LONG)(GetTickCount() + ms) : 0;
	InterlockedExchange(&g_net_rx_drop_until, until);
	if (ms)
		logf("net: incoming packets dropped for %lu ms (test)", (unsigned long)ms);
	else
		logf("net: incoming packets accepted again (test)");
}
static void net_pause_set(DWORD ms)
{
	LONG until = ms ? (LONG)(GetTickCount() + ms) : 0;
	InterlockedExchange(&g_net_pause_until, until);
	if (ms)
		logf("net: link paused for %lu ms (test): no packet is sent or received", (unsigned long)ms);
	else
		logf("net: link pause cleared (test)");
}

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
	if (net_paused()) {   // test-only: the link is down, the packet is dropped like a lost datagram
		return;
	}
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
	g_hello_level = 0;   // the next hello has to say again what the guest has
	g_hello_in_level = 0;
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
static void net_send_req(DWORD kind, unsigned a, unsigned b, unsigned c, const char *name, DWORD seq)
{
	if (g_role != 1 || !g_peer_ok)
		return;
	pkt_req r;
	memset(&r, 0, sizeof r);
	r.kind = kind; r.a = a; r.b = b; r.c = c; r.seq = seq;
	if (name)
		_snprintf(r.name, sizeof r.name - 1, "%s", name);
	net_send(PKT_REQ, &r, sizeof r - sizeof(pkt_hdr));
}

static void net_handle(const char *buf, int n, sid_t from)
{
	const pkt_hdr *h = (const pkt_hdr *)buf;
	if (net_paused() || net_rx_dropped())   // test-only link pause: nothing arrives either
		return;
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
			// TASK 25: the hello says what the guest already has. A guest that was in a level before the
			// link dropped does not need a second save transfer; a fresh guest (nothing received yet) does.
			const pkt_hello *hi = (const pkt_hello *)buf;
			if (n == sizeof *hi) {
				g_hello_level = hi->level;
				g_hello_in_level = hi->in_level;
				g_hello_need_saves = hi->need_saves;
			} else {
				g_hello_level = 0;   // an older/empty hello: behave like a fresh guest
				g_hello_in_level = 0;
				g_hello_need_saves = 1;
			}
			if (g_hello_need_saves)
				host_save_begin();   // (re)send every save file to this guest
			else
				logf("net: guest joined again and already has the saves: no transfer");
			g_join_pending = 1;   // also while still "connected": a guest that restarted inside the 3 s
			                      // timeout sends its hello to the same address, and it still needs the
			                      // welcome path (resume, or the load that brings it back into the game)
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
		case PKT_PICKUP:
			peer_on_pickup(buf, n);
			break;
		case PKT_ITEMUSE:
			peer_on_itemuse(buf, n);
			break;
		case PKT_CHAR:
			peer_on_char(buf, n);   // TASK 42: the character the guest's pad drives (player 2) - a puppet here
			break;
		case PKT_PROP:
			peer_on_prop(buf, n);   // a prop carry/break from the guest (applied on the game thread)
			break;
		case PKT_APT:
			peer_on_apt(buf, n);    // an aptitude result from the guest (applied on the game thread)
			break;
		case PKT_SCENE:
			peer_on_scene(buf, n);  // TASK 30: the guest's scripted-event state / its skip
			break;
		case PKT_DOOR:
			peer_on_door(buf, n);   // TASK 34: the guest used a door: play the same door use here
			break;
		case PKT_LEVELASK:
			host_on_levelask(buf, n);   // TASK 34: the guest's own level change, applied here
			break;
		case PKT_MENU:
			peer_on_menu(buf, n);       // TASK 36: the guest's menu state (convergence signal)
			break;
		}
	} else if (g_role == 2) {
		if (!g_peer_ok) {
			if (h->type != PKT_WELCOME)
				return;
			g_peer = from;
			g_peer_ok = 1;
			g_ever_connected = 1;
			g_last_hostpad_seq = 0;
			guest_save_session();   // a new session: the host starts its save transfer again
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
		} else if (h->type == PKT_CHAR) {
			peer_on_char(buf, n);    // TASK 42: the character the host's pad drives (player 1) - a puppet here
		} else if (h->type == PKT_SAVE) {
		guest_on_save(buf, n);
	} else if (h->type == PKT_SAVES_DONE) {
		guest_on_saves_done(buf, n);
	} else if (h->type == PKT_ITEM) {
		guest_on_item(buf, n);
	} else if (h->type == PKT_PICKUP) {
		peer_on_pickup(buf, n);
	} else if (h->type == PKT_PROP) {
		peer_on_prop(buf, n);
	} else if (h->type == PKT_PROPS) {
		guest_on_props(buf, n);
	} else if (h->type == PKT_APT) {
		peer_on_apt(buf, n);
	} else if (h->type == PKT_SCENE) {
		peer_on_scene(buf, n);   // TASK 30: the host's scripted-event state / its skip
	} else if (h->type == PKT_DOOR) {
		peer_on_door(buf, n);    // TASK 34: the host used a door: play the same door use here
	} else if (h->type == PKT_MENU) {
		peer_on_menu(buf, n);    // TASK 36: the host's menu state (convergence signal)
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
	if (net_paused())   // test-only link pause: no timers advance, so the first tick after it acts at once
		return;
	// TASK 42: the character stream is sent from HERE, not from the frame tick: the game renders ~17 fps
	// on a loaded PC, and a 58 ms stream cannot feed a 100 ms interpolation buffer (the receiver was
	// extrapolating on most frames). The transport thread ticks every <= 2 ms, so the character goes out
	// every 16 ms = 60 Hz whatever the frame rate does.
	char_send_local();
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
		pkt_hello hello;
		memset(&hello, 0, sizeof hello);
		{   // TASK 25: what this copy already has, so a reconnect after a dropped link is a resume
			unsigned w = world_obj();
			hello.in_level = (DWORD)game_in_level();
			hello.level = (hello.in_level && w) ? rd32(w + 4) : 0;
			hello.need_saves = (DWORD)guest_need_saves();
		}
		if (g_use_steam) {
			sid_t hosts[16];
			int n = steam_find_hosts(hosts, 16);
			g_last_candidates = n;
			static int scan_only = -1;
			if (scan_only < 0)
				scan_only = getenv("OBSCOOP_SCAN_ONLY") != NULL;   // test: count candidates, contact nobody
			for (int i = 0; i < n && !scan_only; i++)
				net_send_to(hosts[i], PKT_HELLO, &hello, (WORD)(sizeof hello - sizeof(pkt_hdr)));
			static int logged;
			if (!logged++)
				logf("net: looking for the host among %d candidate(s)", n);
		} else {
			net_send(PKT_HELLO, &hello, (WORD)(sizeof hello - sizeof(pkt_hdr)));
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

// Everything that has arrived on the UDP socket, applied through net_handle. Runs on the transport thread
// (and, with OBSCOOP_TRANSPORT_FRAME=1, in net_frame on the game thread - the old pump).
static void udp_drain(void)
{
	char buf[4096];
	if (g_sock == INVALID_SOCKET)
		return;
	for (;;) {
		fd_set rd;
		FD_ZERO(&rd);
		FD_SET(g_sock, &rd);
		struct timeval tv = { 0, 0 };
		if (select(0, &rd, NULL, NULL, &tv) <= 0)
			return;
		struct sockaddr_in from;
		int fl = sizeof from;
		int n = recvfrom(g_sock, buf, sizeof buf, 0, (struct sockaddr *)&from, &fl);
		if (n <= 0)
			return;
		if (g_role == 1 && !g_peer_ok)
			g_udp_peer = from;
		net_handle(buf, n, udp_key(&from));
	}
}

// 1 ms pacing for the transport loop. Windows' default timer is 15.6 ms, so a 1 ms wait would really be
// 15.6 ms without a resolution request; timeBeginPeriod is resolved at run time from winmm.dll so the
// documented build line (no -lwinmm) still links. A periodic auto-reset waitable timer is re-armed once and
// simply waited on: a loop body that took longer than 1 ms finds it already signalled.
static void net_pace_init(void)
{
	HMODULE mm = LoadLibraryA("winmm.dll");
	if (mm) {
		typedef UINT(WINAPI *time_begin_t)(UINT);
		time_begin_t tb = (time_begin_t)GetProcAddress(mm, "timeBeginPeriod");
		if (tb && tb(1) == 0)
			logf("net: 1 ms timer resolution requested (transport pacing)");
	}
	g_net_timer = CreateWaitableTimerA(NULL, FALSE, NULL);
	if (g_net_timer) {
		LARGE_INTEGER due;
		due.QuadPart = -10000;   // 1 ms (100 ns units, relative)
		SetWaitableTimer(g_net_timer, &due, 1, NULL, NULL, FALSE);
	}
}

static void net_pace_wait(void)
{
	if (g_net_timer)
		WaitForSingleObject(g_net_timer, 10);
	else
		Sleep(1);
}

// The one transport thread (UDP and Steam): receive everything, then run net_tick, every <= 2 ms. It runs the
// same net_tick the old UDP thread ran, so it touches exactly the state that was already touched off the game
// thread (virtual pads, pad rings, the queued sync work - all locked/queued); the Steam calls inside net_tick
// and net_handle are serialised with the game thread's Steamworks callback thread by steam_lock().
static DWORD WINAPI net_thread(LPVOID arg)
{
	(void)arg;
	net_pace_init();
	for (;;) {
		if (g_use_steam) {
			if (g_steam_ok)   // SteamAPI_Init is the game thread's; nothing to poll before it ran
				steam_poll();
			else
				Sleep(2);
		} else {
			udp_drain();
		}
		if (!g_use_steam || g_steam_ok) {
			net_tick();
			InterlockedIncrement(&g_net_ticks);
			DWORD now = GetTickCount(), dt = now - g_net_last_note, span = g_net_last_note ? 10000u : 1000u;
			if (dt >= span) {   // pacing evidence: after 1 s, then every 10 s
				LONG n = g_net_ticks;
				logf("net: transport thread (%s): %ld ticks over %lu ms = %.0f per second (state rx %ld tx %ld)",
					g_use_steam ? "steam" : "udp", n, (unsigned long)dt, dt ? (double)n * 1000.0 / dt : 0.0,
					g_net_rx, g_net_tx);
				g_net_ticks = 0;
				g_net_last_note = now;
			}
		}
		net_pace_wait();
	}
}

static void net_thread_start(void)
{
	if (g_net_thread)
		return;
	g_net_thread = CreateThread(NULL, 0, net_thread, NULL, 0, NULL);
	if (g_net_thread)
		CloseHandle(g_net_thread);
	logf("net: transport thread started (receive + net_tick every <= 2 ms, %s)", g_use_steam ? "steam" : "udp");
}

// The game thread, once per Present. TASK 41: it keeps only what belongs to this thread - SteamAPI_Init is
// done by the game on this thread and the game calls SteamAPI_RunCallbacks here too (Obscure2.exe.c:185958),
// so the P2PSessionRequest callback keeps running here. Receive and net_tick belong to the transport thread.
// OBSCOOP_TRANSPORT_FRAME=1 (test only) puts the OLD per-frame pump back on UDP: no transport thread, and this
// function receives and runs net_tick once per Present - exactly what the Steam path did before TASK 41.
static void net_frame(void)
{
	if (!g_role)
		return;
	if (!g_use_steam && !g_transport_frame)
		return;   // udp: the transport thread owns receive and net_tick
	if (g_use_steam && !g_steam_ok) {
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
		if (!g_transport_frame)
			net_thread_start();   // TASK 41: from now on the transport thread receives and ticks
	}
	if (!g_transport_frame)
		return;
	{   // OBSCOOP_TRANSPORT_FRAME=1: the old per-frame pump, and its rate
		static DWORD last_note, last_pump;
		static LONG n;
		DWORD now = GetTickCount();
		if (g_transport_fps) {   // model a game that renders at this rate (the test copies render at 120-150 fps)
			DWORD period = 1000u / (DWORD)g_transport_fps;
			if (last_pump && now - last_pump < period)
				return;   // this Present was faster than the modelled frame
			last_pump = now;
		}
		if (g_use_steam)
			steam_poll();
		else
			udp_drain();
		net_tick();
		n++;
		if (!last_note)
			last_note = now;
		else if (now - last_note >= 10000) {
			logf("net: OLD per-frame pump: %ld ticks over %lu ms = %.1f per second (one per Present%s)", n,
				(unsigned long)(now - last_note), (double)n * 1000.0 / (double)(now - last_note),
				g_transport_fps ? ", capped by OBSCOOP_TRANSPORT_FPS" : "");
			last_note = now;
			n = 0;
		}
	}
}

static int env_int(const char *name, int def)
{
	char v[32];
	return GetEnvironmentVariableA(name, v, sizeof v) ? atoi(v) : def;
}

static void net_start(void)
{
	char role[16] = "", net[16] = "udp", peer[64] = "127.0.0.1", hostid[32] = "";
	if (getenv("OBSCOOP_PASSIVE")) {   // TASK 18 test switch: no net at all
		g_role = 0;
		logf("passive: net not started");
		return;
	}
	GetEnvironmentVariableA("OBSCOOP_ROLE", role, sizeof role);
	GetEnvironmentVariableA("OBSCOOP_NET", net, sizeof net);
	GetEnvironmentVariableA("OBSCOOP_PEER", peer, sizeof peer);
	GetEnvironmentVariableA("OBSCOOP_HOST_STEAMID", hostid, sizeof hostid);
	GetEnvironmentVariableA("OBSCOOP_HOST_NAME", g_host_name, sizeof g_host_name);
	g_transport_frame = env_int("OBSCOOP_TRANSPORT_FRAME", 0) != 0;
	g_transport_fps = g_transport_frame ? env_int("OBSCOOP_TRANSPORT_FPS", 0) : 0;
	g_role = !_stricmp(role, "host") ? 1 : !_stricmp(role, "guest") ? 2 : 0;
	if (!g_role)
		return;
	if (g_transport_frame)
		logf("net: OBSCOOP_TRANSPORT_FRAME=1 (TEST): the OLD per-frame pump - receive and net_tick once per Present%s, no transport thread",
			g_transport_fps ? " (capped to the modelled frame rate)" : "");
	if (g_transport_fps)
		logf("net: OBSCOOP_TRANSPORT_FPS=%d: the per-frame pump models a game that renders at %d fps (the test copies render at 120-150 fps)",
			g_transport_fps, g_transport_fps);
	g_remote_pad = env_int("OBSCOOP_REMOTE_PAD", 1) & 3;
	g_remote_pad_idx = g_remote_pad;
	g_local_pad = env_int("OBSCOOP_LOCAL_PAD", 0) & 3;
	if (!_stricmp(net, "steam")) {
		g_use_steam = 1;
		steam_lock_init();   // one (recursive) lock for every Steamworks call, game thread and transport thread
		g_host_sid_cfg = _strtoui64(hostid, NULL, 10);
		g_host_self_test = !_stricmp(hostid, "self");
		logf("net: %s over steam (starts after SteamAPI_Init), remote pad %d, local pad %d, host id %s",
			g_role == 1 ? "host" : "guest", g_remote_pad, g_local_pad, g_host_sid_cfg ? "configured" : "from friends list");
		return;   // the transport thread starts in net_frame once steam_start() succeeded
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
	if (!g_transport_frame)
		net_thread_start();
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
	l = strlen(reply);
	if (l < replysz)
		_snprintf(reply + l, replysz - l, " paused %d rxdrop %d guest_level %08lx pump %s transport_ticks %ld", net_paused(), net_rx_dropped(),
			(unsigned long)(g_role == 1 ? g_hello_level : 0), g_transport_frame ? "frame" : "thread", g_net_ticks);
}
