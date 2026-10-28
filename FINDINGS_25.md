# TASK 25 FINDINGS — two-player movement drift (A) and reconnect (B)

Labels: **OBSERVED** = printed by a check or visible in a run log / decompile this session;
**DERIVED** = follows from the cited code but not proven live; **GUESS** = plausible, unproven;
**UNKNOWN** = not established. Decompile lines: `local\decomp2\Obscure2.exe.c` (build 215294).

Branch w/combat @ 1a778d0, `NET_VERSION` 11 before this task and **12** after. Two test copies on
loopback and through the relays (`tests/run_chaos.sh`). Every runner stopped the games it started.

## 0. Summary

| part | what changed | result |
|---|---|---|
| **A movement** | each player's own character is the authority for its position/facing/animation (new `PKT_CHAR`, guest -> host), the host follows it with a blend plus a timestamp-based extrapolation, and the guest no longer pulls its own character towards the host's older snapshot | check_movement **A-E PASS** on loopback (3 runs of A-D, E in 2 of them plus the relay run). GIR1 copy difference phase C mean **8.16 -> 0.90/5.81**, phase D **20.39 -> 2.99/0.95** (loopback); on the 60 ms/20 ms/5 % relay C **10.99 -> 3.32**, D **14.50 -> 4.94**, and the relay run now **PASSES** instead of failing |
| **B reconnect** | `PKT_HELLO` now says what the guest already has (level, in-level, needs save files); the host resumes without a level reload and without a second save transfer; new test-only `netpause <ms>` pipe command; a lost link no longer lets the guest's own pad drive player 1 | 8 s link drop: the guest was back **0.5 s** after the link returned, **no level/load request** (count 1 -> 1), no save transfer; guest killed and restarted at the menu: the host transferred the saves and the new guest loaded `game0.sav` itself and was in the host's level |

`tests/run_reconnect.sh` is new (both cases above, verbatim in §3).

## 1. The model of the drift (before any change)

### 1.1 Who drives what, today

* Both copies simulate both characters. The host's own pad is fed to the game's input controller 0 on
  both copies (`PKT_HOSTPAD` + the `hpad` copy in `PKT_STATE`); the guest's pad is fed to the host's
  controller 1 (`PKT_INPUT` -> `vpad_set(g_remote_pad, ...)`) and to the guest's own controller 1
  (`XInputGetState`, `g_local_pad`). **OBSERVED** (src/net.c PKT_INPUT/net_tick, src/obscoop2.c XInputGetState).
* Authority for position was one-way: the host's `PKT_STATE` snapshot (both characters, every 16 ms) is
  applied on the guest (`guest_apply_state`). Nothing sent the guest's character position back to the
  host: the host re-simulated GIR1 from the pad that arrives over the link.
  **OBSERVED** (src/sync.c host_send_state / guest_apply_state).
* The guest's own copy was also pulled towards the host's: a timed error took half of it every snapshot,
  an untimed one 10 % above 15 units while the stick was held (the `local` path of `guest_apply_state`).
  **OBSERVED** (src/sync.c).
* The camera on each copy follows that copy's own player: the guest's camera follows GIR1
  (`guest_follow_own_player`, sync.c), the host's follows BOY1. The left stick is camera-relative
  (`remap_stick`, obscoop2.c), so the same stick means different world directions; the host rotates the
  guest's stick by `(peer_yaw - own_yaw)`. **OBSERVED** in code.

### 1.2 Baseline measurement (base25.dll = the tree at 1a778d0)

A throw-away probe (`$TMPDIR/move_probe.py`, read-only, not part of the worktree) sampled both copies at
25 Hz during three 4 s phases and printed, per phase, the GIR1 copy difference and the best time shift
(`host(t)` vs `guest(t-dt)`):

```
== G-RIGHT host pad (0, 0) guest pad (32000, 0) | yaw host: own 71.1 peer 71.1 | yaw guest: own 71.1 peer 71.1
  -- GIR1 travel h=128.7 g=129.3
    t0.0-0.5 diff mean 0.8 max 2.4 dz 0.0 | move host (+31,-78) guest (+30,-78)
  -- GIR1 fit: host(t)=guest(t-0.00) mean 0.79 | guest(t)=host(t-0.00) mean 0.79
== G-FWD  (guest pad (0, 32000)): GIR1 travel h=177.7 g=177.9, diff mean 1.5 max 13.6, fit at dt=0.00
== BOTH host pad (0, 32000) guest pad (32000, 0) | yaw host: own 68.7 peer 68.7 | yaw guest: own 68.7 peer 68.7
  -- BOY1 travel h=466.0 g=465.0, diff mean 4.7 max 36.9
  -- GIR1 travel h=141.3 g=155.5
    t0.0-0.5 diff mean 9.0 max 53.9 dz 0.0 | move host (+0,-10) guest (+0,-10)
    t2.5-3.0 diff mean 9.0 max 53.9 dz 0.0 | move host (+8,+3) guest (+2,-14)
  -- GIR1 fit: host(t)=guest(t-0.00) mean 9.02 | guest(t)=host(t-0.00) mean 9.01
  end yaw host: own 89.7 peer 66.5 | guest: own 66.5 peer 89.7
```

**OBSERVED**, three things:

1. The failure is **not a lag**: the best fit is at dt = 0.00 in every phase, so the host's copy is not
   "behind" the guest's - it is at a *different point of a similar path* (the per-second moves match for
   a while and then part: t2.5-3.0 `host (+8,+3)` vs `guest (+2,-14)`). The copy difference grows with
   movement, not with delay.
2. With only the guest moving (G-RIGHT/G-FWD) the copies agree to 0.8-1.5 units: on loopback the pad
   reaches the host almost at once, and only one character moves, so the yaw remap is exercised in one
   direction only.
3. When **both** move, the two cameras see different worlds: at the end of BOTH the host's yaw is 89.7
   while the guest's is 66.5 (**23 deg apart**, because each camera follows its own player). The guest's
   stick is applied raw against the guest's camera; the host's copy only has the yaw-difference-corrected
   stick against the host's camera. Any error in that remap (sample age, the character's own turn,
   collisions taken on a slightly different heading) integrates over the 4 s hold - the paths part and
   the checks measure mean 8-20, max 46-90 units. Idle agreement was 0.02-0.6 units.

### 1.3 The conclusion that was fixed

GIR1's copies differ because the *host* re-simulates a character it does not own, in a camera frame that
is not the owner's, and the *guest* additionally drags its own character towards that copy. Fix: make
ownership explicit - the guest owns player 2 (position, facing, animation) and streams it; the host owns
player 1 (as before); each copy follows the other's streamed character with a blend.

## 2. Part A fix — the owner of each character streams it

### 2.1 The change (`NET_VERSION` 12)

* **`PKT_CHAR`** (new, type 18): guest -> host, every ~8 ms from `guest_send_char()` (frame hook):
  `{t_ms (host timeline), level, ch_state of player 2}`. Only what the owner owns is used: tag, pos,
  anim (dir on a whole move, life/weapons unused).
* **`host_apply_remote_char()`** (host frame hook): finds the human with the streamed tag and follows it.
  * **extrapolation**: the packet says where the character was at `t_ms`; the age is
    `timeline_now() - t_ms` (the guest stamps with the host clock it estimates from ping/pong). The
    target moves along the last two samples by that age (clamped to 0..120 ms, speed sanity
    < 30 000 units/s). This is the "delay alignment": without it the host's copy trails by speed x delay.
  * **blend**: `pos += (target - pos) * 0.7` per frame; a whole move only above 60 units (a door or a
    respawn the guest took alone). Nothing ever pulls the guest's copy.
  * animation (`+0x2dc`) is taken from the stream - the owner owns it. Life and weapons stay host-owned
    (`PKT_STATE`/`PKT_ITEM` unchanged), so damage and item use still apply on the host only.
* **`guest_apply_state()`**: for `hs[k] == player_human(1)` (this copy's own character) the snapshot now
  only carries the *life*; position, facing and animation are left to the game, and the only position
  repair left is the catastrophic one (untimed error > 80 units). Everything else is unchanged;
  `host_send_state` still sends both characters (the life path needs it).
* `sync` reports `char sent/rcv/applied/blends/snaps/skipped/extrap` on both copies.

### 2.2 Why a blend and not a snap

The host's copy is still simulated from the guest's pad, so it moves on its own; the blend removes only
the part of the path that differs (the camera-frame error). A snap per packet would show as jitter when
packets arrive in a burst (the relay run); 0.7 per frame converges in ~2 frames.

### 2.3 Measured effect (loopback, same flow)

| phase / character | before (chk23/chk24 regression logs) | after `run_a25_r3.log` | after `run_reg25a.log` / `run_reg25b.log` |
|---|---|---|---|
| C GIR1 (guest pad only) | mean 3.17-12.70, max 22-76 (FAIL about one run in three) | mean **0.90**, max **12.27**, travel 419.7/419.7 | mean **0.57**, max **10.88** (`run_reg25a`); **5.81 / 41.85** (`run_reg25b`) |
| D GIR1 (both pads) | mean 14.50-20.39, max 46.20-64.79 (FAIL nearly every run) | mean **2.99**, max **19.89**, travel 472.0/455.5 | mean **3.28**, max **17.77** (`run_reg25a`); **0.95 / 2.87** (`run_reg25b`) |
| D BOY1 | mean 0.82-1.83, max 3.74-19.51 | mean **0.60**, max **9.27** | 1.22 / 11.93 (`run_reg25a`); 0.87 / 4.25 (`run_reg25b`) |
| idle copy difference | 0.32-0.55 | 0.02 (GIR1, the owner stream) / 0.58 (BOY1) | 0.00 / 0.43 (`run_reg25a`); 0.00 / 0.00 (`run_reg25b`) |

Intermediate step (kept in the logs): with the owner stream but a plain 0.5 blend and no extrapolation
(`run_a25_r1.log`) phase C was mean 8.16 / max 31.17 - the extrapolation took that to 0.90.

### 2.4 One failure and what it was

`run_a25_r2.log` has `D: FAIL -- BOY1 did not move: host 11.9 guest 15.3 units (min 20); GIR1 did not
move: host 1.8 guest 1.8 units (min 20)`. Both copies agreed to **0.03 units** while the failure was
reported: the characters were held against level geometry for the whole 4 s (GIR1 had already stopped
during the last second of phase C, `t4-5 h0 g0`), not out of sync. The check's phases chain the
characters' positions, so a phase that starts in a corner cannot travel. The same run's phase C was
mean 0.90 / max 12.27. **OBSERVED**, and a caveat for anyone reading a single run: the "did not move"
verdict means "the level blocked the character", the "copies differ" verdict means desync.

## 3. Part B — reconnect

### 3.1 What was wrong (code reading, then proven live)

* On **every** `PKT_HELLO` the host called `host_save_begin()` (a full 10-file transfer) and, on the main
  thread, `host_welcome_guest()` sent `REQ_LOAD_NAME` for the save it had loaded - so a guest that
  reconnected inside the same level was told to **reload the level**, losing both characters' positions.
  **OBSERVED** in code (net.c PKT_HELLO, sync.c host_welcome_guest).
* The guest's `guest_save_session()` (on `PKT_WELCOME`) forgot every file the previous session had
  received, so a load that waited for a transferred file could wait for a new transfer. **OBSERVED**.
* Sequence numbers were already fine: the host resets `g_last_input_seq` on hello, the guest resets
  `g_last_hostpad_seq` on welcome. **OBSERVED** (so a restarted guest's packets are not dropped).
* There was no way to drop the link for a test. **OBSERVED**.

### 3.2 The change

* `PKT_HELLO` carries `{level, in_level, need_saves}` (`NET_VERSION` 12). `need_saves` = this process has
  not received any save file from the host yet (`guest_need_saves`, sync.c).
* Host, on hello: transfer the saves **only** when the guest says it needs them; otherwise just log
  `guest joined again and already has the saves: no transfer`. `g_join_pending` is set in **both** cases
  (a guest that restarts inside the 3 s timeout sends its hello to the same address while the host still
  thinks it is connected, and it still needs the welcome path).
* `host_welcome_guest()`: if the hello said `in_level` and its level is the level the host is in, log
  `join: the guest is already in level X: resuming without a level or save request` and return - the
  progress block is still forced out at the top of the function, and the state/character streams resume.
* Guest: `guest_save_session()` keeps the received list when it already has files (a reconnect is not a
  new session).
* Guest input: while the link is gone **and** the copy was linked before (`g_ever_connected`) and is in a
  level, `XInputGetState(user 0)` returns an empty pad instead of the guest's own pad - otherwise a held
  stick would drive the host's character on the guest's copy only during the outage.
* New test-only pipe command **`netpause <ms>`** (0 clears): `net_send_to` and `net_handle` drop
  everything for that long and `net_tick` does not advance its timers, so the first tick after the pause
  runs the normal timeout -> hello -> welcome path. `net` reports `paused`.
* Built after the reconnect run above: a hello that arrives while the host still counts the guest as
  connected (a guest that restarts inside the 3 s timeout, same UDP address) now also sets
  `g_join_pending`, so that guest gets the welcome path too. **DERIVED** (the line is in the build used for
  the chaos run, which compiled and ran; the restart-inside-3-s case itself was not observed - the test's
  kill -> start sequence is longer than the 3 s timeout).

### 3.3 Observed (verbatim, `run_b25_r1.log`, `tests/run_reconnect.sh chk25.dll both`)

Case 1, link dropped 8 s in the middle of play, both copies:

```
  host : ok net paused for 8000 ms (0 = cleared)
  guest: ok net paused for 8000 ms (0 = cleared)
  host net after the drop: net role host via udp peer_ok 1 rx 2609 tx 3400 bad 0 last_input_seq 2780 rtt_ms -1 paused 0 guest_level 49313030
-- both copies, right after the link came back:
  resume t+ 0.0 s level host I100 guest I100 chars 2/2 copy diff 0.0
  resume t+ 0.5 s level host I100 guest I100 chars 2/2 copy diff 0.0
resume: IN SYNC after 0.5 s (level I100, 2 characters, worst copy difference 0.0 units)
guest level/load requests after: 1 (before 1)
CASE 1: no level or load request reached the guest (no reload)
```

and the host log at that moment (`0x49313030` in the `net` reply is the tag `I100`):

```
15:19:27.951 [26060] net: guest dropped (timeout 3 s); virtual pad 1 disconnected
15:19:27.966 [26060] net: guest joined (udp)
15:19:27.966 [26060] net: guest joined again and already has the saves: no transfer
15:19:27.989 [27060] join: the guest is already in level I100: resuming without a level or save request
```

Case 2, guest killed and started again at the main menu while the host keeps playing:

```
  killing guest pid 11176
  Obscure2.exe now: 1 (the host must still be there)
  starting a new guest copy (duo.py start-guest)
guest pid 18312
  late join t+ 0.0 s level host I100 guest I100 chars 2/2 copy diff 0.0
late join: IN SYNC after 0.5 s (level I100, 2 characters, worst copy difference 0.0 units)
-- the guest's own log about the join:
15:19:33.915 [12196] net: host welcomed us (udp)
15:19:34.418 [30724] guest: host LoadByName "game0.sav" (world none)
15:19:34.418 [30724] guest: real load of "game0.sav" requested (host)
15:19:34.840 [30724] guest: real load of "game0.sav" (host): the game's save open ok
15:19:34.840 [30724] guest: real load of "game0.sav" issued (mode 0 request state 3)
```

and the host:

```
15:19:33.680 [26060] net: guest dropped (timeout 3 s); virtual pad 1 disconnected
15:19:33.915 [26060] net: guest joined (udp)
15:19:33.915 [26060] host: save transfer starts (10 files, first "game0.sav")
```

So: 8 s drop -> dropped at 3 s, re-welcomed 15 ms after the guest said hello, **resume** (no load, no
transfer), in sync 0.5 s later. Restart -> the host treats it as a fresh join (saves + load request), the
guest loads the host's save and builds the level itself, exactly like a late join (FINDINGS_14).

**Limitation, stated plainly:** neither case held a pad, so the characters were where they had been and
"copy diff 0.0" at resume is the *control path* being intact, not a convergence measurement. The
convergence of a diverged character is covered by §2.3 and by the chaos run (same code paths); a future
run can press a stick during the drop (the script's `netpause` block is the place) to see GIR1's host
copy catch up after the resume (it is a > 60-unit case then, so it takes the whole-move path).

## 4. Verification

| run | what | result |
|---|---|---|
| `run_a25_base.log` | base25.dll (tree at 1a778d0) + the movement probe | the measurement in §1.2 |
| `run_a25_r1.log` | chk25.dll, owner stream, 0.5 blend, no extrapolation | A-E PASS, C mean 8.16 |
| `run_a25_r2.log` | chk25.dll, + extrapolation | A,B,C,E PASS; D "did not move" - geometry, both copies 0.03 apart (§2.4) |
| `run_a25_r3.log` | chk25.dll, the same | A-E **PASS** (C 0.90, D 2.99) |
| `run_reg25a.log` | `run_pair_menu.sh` + party/items/hands/hands_visible/entities/movement | all OK, A-E **PASS** (C 4.36, D 2.32) |
| `run_reg25b.log` | `run_pair.sh` + movement/pair_j003/pickup/itemuse/party/items/hands (pickup env on) | movement A-D **PASS**, pickup OK both directions, itemuse OK, party/items/hands OK |
| `run_b25_r1.log` | `tests/run_reconnect.sh chk25.dll both` | **PASS** (case 1 resume, case 2 re-join) |
| `run_chaos25.log` | `run_chaos.sh chk25b.dll 60 20 5` with movement | **PASS**: A 0.34, B 2.48/16.56, C 3.32/27.58, D GIR1 4.94/33.40, D BOY1 1.80/17.41, E 3.91/37.76, converged, save/party/hands/items OK |

Before/after on the same lossy link (old numbers from FINDINGS_13 §4, run 7):

| phase | before (relay) | after (`run_chaos25.log`) |
|---|---|---|
| E BOY1 | 9.87 / 26.73 | **3.91 / 37.76** |
| B BOY1 | 8.03 / 23.88 | **2.48 / 16.56** |
| C GIR1 | 10.99 / 34.62 | **3.32 / 27.58** |
| D GIR1 | 14.50 / 46.20 | **4.94 / 33.40** |
| D BOY1 | 3.79 / 29.18 | **1.80 / 17.41** |

Game processes started in this task: 17 (8 measurement/iteration + 2 regression + 3 reconnect + 2
regression + 2 chaos), under the 18 allowed. All stopped (`remaining Obscure2.exe: 0`).

### Notes for the next worker

* **The host's copy of GIR1 is a follower now.** Do not add a correction that pulls the *guest's* copy of
  player 2 towards the host's: that is exactly the drift this task removed (it now only repairs > 80
  units, untimed).
* `PKT_CHAR` is sent from the frame hook and applied in the frame hook; it is not queued like `PKT_STATE`
  (the newest sample wins, which is what a position stream wants).
* The extrapolation assumes the guest's `t_ms` is on the host timeline (`timeline_now()`); it is the same
  clock `hist_at`/`PKT_STATE` already use. Age > 120 ms (a stalled stream) disables it.
* `netpause` is test-only and pauses both directions on the copy it is sent to; a reconnect test should
  send it to both copies.
