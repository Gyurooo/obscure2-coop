# FINDINGS 41 — Steam transport on its own thread, one code path for UDP and Steam, a Steam-shaped test link

Branch `w/combat`, base deab8fb (v1.9). Only the transport (src/net.c, src/steam.c), the test link
(relay/relay.c) and the test runners changed. **No player-sync model change** (task part 3).

Labels: OBSERVED (read in the code / printed by a run), DERIVED (reasoned from those), GUESS, UNKNOWN.
Line numbers are from the base commit deab8fb unless the text says "now".

## 1. Why the old Steam path was unplayable while every test passed

OBSERVED (base code):

* `udp_thread` (src/net.c:629) looped on `select(…, 2 ms)`, received every datagram, called `net_handle`
  and then `net_tick()` — so the UDP transport ticked every <= 2 ms, independent of the render loop.
  `net_tick` sends the pad every 8 ms (src/net.c:554 host, :608 guest) and the guest pings every 500 ms.
* `net_frame` (src/net.c:652) was called from `hk_dev_Present` (src/window.c:131 → `frame_tick`,
  src/sync.c:6243), i.e. **once per rendered frame on the game thread**. The whole Steam transport —
  `steam_poll()` (receive) and `net_tick()` (send) — ran there. During a load, a long frame or a stall
  Present is not called, so nothing was received and nothing was sent: the pad stream arrives in bursts
  with gaps (the reviewer measured "off by mean 11.9 max 24.6 units … 270 snaps, 2192 blends" on the
  guest). All automated tests use `OBSCOOP_NET=udp`, so no test ever exercised that path.

### Is ISteamNetworking safe off the main thread? (the task's question 1)

* DERIVED (Steamworks docs): the Flat/vtable client API is documented as **not thread-safe** — the SDK's
  `isteamclient.h`/`isteamuser.h` entry points carry the `// NOT THREADSAFE - ensure that no other
  threads are accessing Steamworks API when calling!` note, and callbacks/call-results are only
  dispatched from `SteamAPI_RunCallbacks` on the thread that calls it. There is no documented guarantee
  that `SendP2PPacket` / `IsP2PPacketAvailable` / `ReadP2PPacket` may run on a second thread, so the
  safe design is a single lock around **every** Steamworks call.
* OBSERVED (decompile, Obscure2.exe.c:185958): the game calls `SteamAPI_RunCallbacks()` inside its own
  main game loop (same place as the game's other per-frame work). The mod never calls
  `SteamAPI_RunCallbacks` itself; it only `SteamAPI_RegisterCallback`s a `P2PSessionRequest_t` (1202)
  callback (src/steam.c:107), which therefore runs on the game's main thread.
* Decision (DERIVED): keep `steam_start()` (interface getters + `SteamAPI_RegisterCallback`) and the
  session-request callback where they are today (game/main thread); move only
  `SendP2PPacket`/`IsP2PPacketAvailable`/`ReadP2PPacket` (and the session accept, which the net thread
  also calls from `net_tick` on the host) to the transport thread, with one **recursive** critical
  section around all Steamworks calls, including the callback-driven ones. A critical section is
  recursive, so `steam_poll → net_handle → net_send → steam_send` and the callback →
  `steam_accept`/`steam_is_friend` paths nest safely.

## 2. The change (transport only)

* `src/net.c`: one thread, `net_thread`, for both transports. Each iteration drains everything that has
  arrived (`udp_drain()` via `select(0)` + `recvfrom`, or `steam_poll()`), runs `net_tick()` and waits
  1 ms on a waitable timer (timeBeginPeriod(1) resolved at run time from winmm.dll, so the documented
  build line does not change). UDP and Steam now share receive pacing, send pacing (pad every 8 ms,
  ping, snapshots/requests as the game thread queues them) — the same `net_tick` code.
* `src/net_frame` (game thread) now only does what must stay there: `steam_start()` (once) and the
  Steam-id file, and the *test* switch below. It no longer polls or ticks in the normal path.
* `src/steam.c`: `steam_lock()/steam_unlock()` around every vtable call; `steam_poll` is called from the
  transport thread.
* Shared state (`net_handle` → `vpad_set`, `ring_push`, the sync queues) was already touched from the
  UDP thread, so it is already locked/queued; the Steam path adds no new shared state (all Steam
  interface pointers are written once, on the main thread, before the transport thread starts).
* `OBSCOOP_TRANSPORT_FRAME=1` (test only) puts the **old** per-frame pump back on UDP as well: the
  transport thread is not started and `net_frame` (once per Present) does `udp_drain()` + `net_tick()`.
  It logs its own rate (`net: OLD per-frame pump: N ticks in … ms = … per second`) so the numbers in
  §4 are measurable.

NET_VERSION is unchanged: no packet layout changed (the version comment list is untouched).

## 3. The Steam-shaped test link (relay/relay.c)

New `--profile steam` on the relay's plain-UDP test link (`--udp-link`), per direction, each relay
shaping its own outgoing direction:

| part | value |
|---|---|
| base one-way delay | 37 ms (75 ms RTT) |
| jitter | -40..+40 ms per packet (clamped to >= 1 ms) |
| spikes | 1.5 % of packets get +75 ms one way (~150 ms RTT), counted |
| bursts | release times quantised to a 16-33 ms grid: packets due inside one window leave together |
| blackouts | every 4-8 s one 300-800 ms window in which every packet is dropped (counted), like a load/stall on the old per-frame path |
| loss | whatever `--loss` says (default 0) |

The relay logs the profile in its `udp link:` line and a 10 s summary (sent / lost / spikes /
blackouts / burst windows), so a run shows what the link did.

Test wiring:

* `OBSCOOP_LINK=steam` on `tests/run_pair_menu.sh` starts the two relays with `--profile steam` and
  runs the pair through them (guest DLL on 27962), i.e. the normal menu-load flow with a Steam-shaped
  link. Without it the script behaves exactly as before (no relay).
* `OBSCOOP_LINK=steam` on `tests/run_soak.sh` / `tests/run_chaos.sh` adds `--profile steam` to the two
  relays they already start. Default runs are unchanged.
* `OBSCOOP_TRANSPORT_FRAME=1` is inherited by the game copies through `duo.py`'s environment.
* The relay exe must be the one built from this source (worktree `relay/obscoop-relay.exe` here):
  `OBSCOOP_LLVM_MINGW=... i686-w64-mingw32-gcc -O2 -Wall -static -o relay/obscoop-relay.exe relay/relay.c -lws2_32`
  (the same two-line build `tools/build_release.sh` uses). A relay without `--profile` ignores the
  option silently, so the runner refuses an unknown `--` option (exit 2) instead.

Measured on the shaped link alone (two relays, a probe that mimics the DLL's 8 ms pad stream and a
one-shot ping, no game): one-shot round trip mean **86 ms** (one-way 43.0 ms each direction, min 16.6,
max 139.9, so spikes reach ~150-280 ms RTT); with the 8 ms pad cadence one-way mean **32.9 ms** (min 2.0,
p10 8.1, p90 58.1, max 98.3), **43 of 79** consecutive arrivals less than 2 ms apart (bursts) and
reordering visible (arrival gaps down to -56 ms). Blackouts fired every 4-8 s: one 50 s run logged
`9055 sent, 0 lost, 121 spikes, 7 blackouts (724 packets dropped), 1724 burst windows` (relay counters).
The 1 ms timer request the relay now makes is logged (`link: 1 ms timer resolution granted`); without it
the pump's 2 ms select really waits 15.6 ms and smears the profile.

## 4. Live measurements

All runs: same DLL (`chk41.dll`, built from this worktree), same link (`--profile steam`), same machine,
two game copies on loopback behind the relay pair. `check_movement.py` prints, per phase and character,
the copy difference in units (mean / max) and check_party the party + inventory.
Note the two fault-injection modes:

* `pump thread` = this task's design (transport thread, receive + `net_tick` ~900 times/s, pad every 8 ms).
* `pump frame` = `OBSCOOP_TRANSPORT_FRAME=1`, the old Steam pump on UDP (receive + `net_tick` once per
  Present). **Its rate is the frame rate**, and that is the whole point: the two test copies render the
  level at 120-152 fps (it is a 2007 game on a modern PC in a window), so uncapped the pump is 120-152
  ticks/s and the difference to the thread is small. The owner's copy does not render at 120 fps during
  play, and during a load it renders (and therefore pumps) not at all. `OBSCOOP_TRANSPORT_FPS=N` caps the
  pump to the frame rate of a real game, so the same DLL can show the old path at a realistic rate;
  `OBSCOOP_TRANSPORT_FPS=30` gave 21.3 ticks/s (the cap compares GetTickCount, whose 15.6 ms granularity
  turns a 33 ms period into ~47 ms), i.e. about the rate the game has at ~21 fps - the log line always
  states the rate actually reached.

### 4.1 The transport thread's pacing (OBSERVED, both copies' `obscoop.log`)

```
../obscure2-test/obscoop.log:  net: transport thread (udp): 8987 ticks over 10000 ms = 899 per second (state rx 4313 tx 6289)
../obscure2-test2/obscoop.log: net: transport thread (udp): 8642 ticks over 10000 ms = 864 per second (state rx 6120 tx 4889)
../obscure2-test/obscoop.log:  net: OLD per-frame pump: 1525 ticks over 10000 ms = 152.5 per second (one per Present)
../obscure2-test/obscoop.log:  net: OLD per-frame pump: 217 ticks over 10016 ms = 21.7 per second (one per Present)
../obscure2-test/obscoop.log:  net: OLD per-frame pump: 214 ticks over 10031 ms = 21.3 per second (one per Present, capped by OBSCOOP_TRANSPORT_FPS)
```
So the new thread ticks every 1.1-1.2 ms, i.e. **inside the required <= 2 ms**, independent of the frame
rate; the old pump's rate is the game's frame rate, measured 120-152/s in the level and 21.6/s when the
load/checks bring the frame rate down.

### 4.2 check_movement under the steam-like link (OBSERVED)

`diff_mean / diff_max` in units per phase (A idle, B host pad, C guest pad, D both, E right after load):

| run | E BOY1 | A BOY1 | B BOY1 | C GIR1 | D BOY1 | D GIR1 | verdict |
|---|---|---|---|---|---|---|---|
| **thread** #2 (final build) | 6.82 / 20.07 | 0.00 / 0.00 | 6.00 / 21.24 | 1.25 / 10.10 | 8.06 / 22.13 | 3.49 / 16.74 | **PASS all** |
| thread #1 (build before the cap switch) | 6.04 / 21.13 | 0.31 / 0.31 | 7.03 / 21.84 | 1.58 / 20.21 | 6.19 / 38.35 | 4.05 / **60.41** | D FAIL on one max sample |
| frame pump, uncapped (120-152/s) | 1.90 / 17.19 | 0.12 / 0.12 | 2.79 / 18.37 | 3.24 / 22.44 | 2.52 / 19.79 | 3.47 / 20.22 | PASS all |
| frame pump, capped (**21.3/s**) | 8.90 / 20.53 | 0.32 / 0.32 | 3.78 / 20.03 | 6.76 / **31.80** | 8.62 / **70.27** | 9.63 / **81.65** | D FAIL |

Reading (DERIVED, and the honest one):

* The thread passes; so does the old pump **while the game renders at 120-150 fps**. On this machine the
  per-frame pump is not measurably worse than the thread except in run-to-run noise (thread #1's single
  60.41 sample in D, a first-sample artefact at the start of a combined move).
* With the pump at the rate it really has in a normal game / under load (21.3/s, measured), phase D fails
  on **both** characters: means 8.62 / 9.63 (the check's limit is 10) against 8.06 / 3.49 for the thread,
  maxima 70.27 / 81.65 against 22.13 / 16.74, and a 19.5-unit **vertical** difference (dz) that the
  thread runs do not have (0.48 / 6.26). Phase C's GIR1 max also triples (31.80 vs 10.10).
* The guest's own 10 s statistics under the same link (OBSERVED, `obscoop.log`):
  * thread: `host characters off by mean 0.0-3.5 max 0.0-26.8 units over 242-270 snapshots (0 snaps, 101-188 blends); rtt 59-102 ms`
  * capped frame pump: `mean 0.3-4.4 max 0.3-26.4 over 151-179 snapshots (0 snaps, 65-135 blends); rtt 47-137 ms`
  These are close; the per-snapshot statistic is dominated by the link's jitter (mean error resets every
  10 s), while the phase D table above shows the effect of the pad cadence itself.

So: the transport thread is never worse and removes the frame-rate coupling; the old pump's failure is
visible as soon as its rate is the rate a game actually has (or collapses to during a load). What the
owner's "unplayable" experience needs beyond this test is a *load* on one side: the old path sends and
receives **nothing** for its whole duration (Present is not called while the level is built), which no
test can reproduce on loopback without loading inside a movement phase; the profile's 300-800 ms
blackouts model the same gap and both paths lose the same packets there.

## 4.3 The two soaks and the reconnect run

**Default link** - `sh tests/run_soak.sh chk41.dll` - **PASS** (verbatim in §6.1): attack animation and
controls OK, 30 location changes with every transition ending in one level on both copies, both race
phases, `check_doors.py` both directions, 0 crash lines, 0 stall reports, forced-crash report complete.

**Steam-like link** - `OBSCOOP_LINK=steam sh tests/run_soak.sh chk41.dll` - **FAIL**, and this is the one
result that needs a close reading (§6.2):

* Iterations 1-13 all ended in one level on both copies (`== 13: host loads game0.sav -> load done,
  level J002 -> I100/I100 (0.0s, one level) ...`), then soak34 itself stopped the loop:
  `game threads: host frames 23938 -> 24328, guest 23414 -> 23414 (STOPPED)` /
  `soak stops here: a game thread is not running any more (the watchdog report is in the log)`.
* `race A: level I100/I100 after 0.9s -> one level` - **PASS**.
* `race B: level I010/I100 after 35.2s -> NOT one level` - **FAIL**, and the guest's pipe said
  `guest usedoor 1 -> error usedoor: the game thread did not run it in 15 s`; `game threads: host 37392
  -> 37702, guest 23414 -> 23414 (STOPPED)`.
* The guest's **game thread had frozen** before that: 39 `GAME THREAD STALLED` reports, the first one
  `3.0 s - no frame for 3000 ms (frames 23414, last mod step "in the game's own code after frame_tick
  (update/render)")`, with the stack entirely in `Obscure2.exe`/`ntdll` (no mod frame). The guest's
  transport thread kept ticking (`net: transport thread (udp): 7554 ticks over 10000 ms = 755 per
  second`), so from the host's point of view the peer stayed connected while its game no longer ran.
  That is the same signature as the known game-side freeze in FINDINGS_39 (§"doorloop1.log": the stall
  stack inside the world update/camera loops) - the game hangs in its own code, not in the mod's.
* The level split and the failing `check_doors.py --reset game3.sav` (`NOT back in one level after 90 s
  (host J002 guest I100)`) are consequences of the frozen guest: it cannot follow any transition.
* The relay counters show the link did what it was built to do:
  `link profile steam (cumulative): 37083 sent, 351 lost, 522 spikes, 25 blackouts (3006 packets
  dropped), 6258 burst windows` (host) and `26564 sent, 253 lost, 424 spikes, 26 blackouts (2064 packets
  dropped), 6189 burst windows` (guest), while both copies' transport threads ran at 900/755 ticks per
  second and the guest's own statistics read
  `host characters off by mean 0.1 max 3.1 units over 265 snapshots (83 snaps, 330 blends); rtt 64 ms`.

So the transport did not show a defect of its own here (it ran, it delivered, the numbers it feeds are
fine), but a pre-existing game-side hang was triggered under this much harsher link (jitter +-40 ms,
16-33 ms bursts, 300-800 ms blackouts on top of 1 % loss). The same DLL and transport passed the default
soak (30 iterations + races + doors) and four steam-profile pair runs; whether the freeze is a function
of the link's variance rather than anything in this task cannot be decided from one run, and it is out
of this task's scope (the sync model is the next task).

**Reconnect** - `sh tests/run_reconnect.sh chk41.dll 1` - **PASS** (§6.3): `before: IN SYNC after 0.5 s
(level I100, 2 characters, worst copy difference 0.0 units)`, 8 s `netpause` on both copies,
`resume: IN SYNC after 0.5 s ...`, `CASE 1: no level or load request reached the guest (no reload)`,
and the log lines `net: guest dropped (timeout 3 s) ...`, `net: guest joined again and already has the
saves: no transfer`, `net: guest is already in level I100: resuming without a level or save request`.
Case 2 (kill + restart the guest) was **not** run: the 16-game-process hard limit was reached (see §5).

The steam-profile run also shows the relay's own counters while the pair plays, e.g.
`link profile steam (cumulative): 9055 sent, 0 lost, 121 spikes, 7 blackouts (724 packets dropped), 1724 burst windows`
on the host and similar on the guest in a 50 s window - i.e. the link really did drop traffic in
300-800 ms holes and deliver the rest in bursts, and the pair survived it.

### Note for the next task (DERIVED from the code, not changed here)

`net_tick` gates the pad on `GetTickCount() - last_pad >= 8`. Before this task nothing asked for a
1 ms system timer, so GetTickCount stepped in 15.6 ms units and the "8 ms" pad gate really fired every
~15.6 ms (64/s). The transport thread now requests a 1 ms timer (`timeBeginPeriod(1)`), so the gate
fires every ~8 ms; the relay's received-packet counter agrees: the host's stream was ~181 packets/s in
the steam-profile soak (≈125 pads/s + ≈62 snapshots/s), not ~126/s as a 64 Hz pad stream would give.
This is a side effect of the pacing, not a protocol change (packet layout unchanged, NET_VERSION stays
20).

## 5. DONE / NOT DONE / UNKNOWN

(filled in at the end)
