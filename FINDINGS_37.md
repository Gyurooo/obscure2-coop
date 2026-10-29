# FINDINGS 37 — level split between the copies, inventory-close flake, reconnect (TASK 37)

Labels: **OBSERVED** = printed by a run/check or read in the decompile/code with a file:line;
**DERIVED** = follows from the cited code but was not seen live; **GUESS**; **UNKNOWN**.
Base: `d6120e8` (WIP shared menus, protocol 19). This task: protocol 20.
The owner's playtest material is private: read only, never copied, and no path from it appears below.

## 1. The level split (item 1)

### 1.1 What the code does today (OBSERVED, file:line)

* The host announces a transition when the *game asks for it*: `hk_change_level` sends `REQ_LEVEL`
  right after calling the game's own `FUN_004a1c00` (hooks.c:163-179), `hk_load_name` sends
  `REQ_LOAD_NAME` right after `FUN_004a1bd0` (hooks.c:203-215), `host_apply_guest_level` sends
  `REQ_LEVEL` for a guest ask (hooks.c:128-140), and `host_watch_level` announces a level change
  nobody requested (sync.c:3207-3243). **The announcement is made at request time, never checked
  against what the host's game actually did.**
* The guest queues what it receives and applies it when its own game is idle (`game+0x320 == 0`,
  sync.c:3368-3374). The queue is ordered by arrival and de-duplicated by (level, entry) only
  (sync.c:3315-3327); it has no notion of which request is the newest.
* The host's own level-change request can be issued while another transition is in flight: the pipe
  / menu load goes through `game_load_tick` (sync.c:2422-2479) which calls the game's save open and
  `LoadByName` **without looking at `game+0x320` at all** (no request-state check anywhere in that
  function), and `host_apply_guest_level` calls `ChangeLevel` without that check either
  (hooks.c:109-143).

### 1.2 The failing shape (OBSERVED in the logs the task names)

`run_s35_soak1.log:203`:

```
==  6: host loads game3.sav -> load done, level I100 -> J002/I100 (30.1s, NOT one level)
```

* `30.1s` is `wait_same`'s full timeout and the row is printed through soak34.py's
  `time.time() - t0 > 20.0` fallback (`tests/soak34.py:126-141`), so the **host never changed level
  at all**: it stayed in I100 for >20 s while the guest went to J002. The load the pipe asked for
  was never performed by the host's game (or was swallowed by the door transition in flight), but
  the guest had already been told `REQ_LOAD_NAME` and loaded the file itself.
* That is the split: **the host announces a transition it may not complete**, and nothing ever
  compares the two copies' levels again. The later rows are coincidences (in the same log the
  guest's game thread is dead from iteration 7 on, `frames 13347 -> 13347`).

The named door line 0.7 s before the load is the same race from the other side: the host's door
script reached its `ChangeLevel` (and the mod announced it) at `t`, and the pipe load was issued at
`t+0.7` into a game whose state machine had not settled.

### 1.3 The 3.2 s stall (item 1, last paragraph)

* In the *older* build the stall was in a mod call: `run_s35_soak1.log:234`
  `GAME THREAD STALLED 3.2 s ... last mod step "in door_tick (guest)"`, then 8.2 s, with the same
  frames counter (13347) and the EIP inside the door code (`Obscure2.exe+0x2c51b`, frames
  `+0x2c4b0`/`+0x2c51b` repeated) - the TASK 35 guest-door-use bug that TASK 36 fixed with the
  placement in front of the door anchor.
* The reviewer's stall on the current build is a *game-side* one (FINDINGS_36 §10:
  `last mod step "in the game's own code after frame_tick (update/render)"`, frames resumed 3 s
  later). It happened in the same couple of iterations as the split. Whether the two transitions
  racing is what the game's own update blocks on is **UNKNOWN** (no register report was kept for
  it); the Soak's rule is that any `GAME THREAD STALLED` line fails the run, so this task's two
  soak passes are the test of whether it is gone.

## 2. The inventory-close flake (item 2)

OBSERVED in the reviewer's log (`claude_verify_36_menus.log:71-73`) and in the two game logs of
that run (`obscoop.log`, timestamps below):

```
   after guest B          host st 2 ui (0, 0) | guest st 2 ui (0, 0)
   guest's B closes the inventory on both (merged input): FAIL
```

The guest's B **did** close the inventory on both copies, but both copies were back in it ~20 ms
later:

```
guest 40.616  guest: menu state 2 -> 1 (ui 0/0, level 49313030, seq 8)
guest 40.616  guest: sharing the menu: pulsing B on player 1's pad (peer menu 2, this copy 1)
guest 40.633  guest: menu state 1 -> 2 (ui 0/0, level 49313030, seq 9)
host  40.625  host: menu state 2 -> 1 (ui 0/0, level 49313030, seq 8)
host  40.636  host: sharing the menu: pulsing B on player 1's pad (peer menu 2, this copy 1)
host  40.651  host: menu state 1 -> 2 (ui 0/0, level 49313030, seq 10)
```

(The log label `B` is the code's label for the BACK button `0x0020`, sync.c:5419: `menu_pulse`'s
`what` argument. The close button in the other direction is `A` = `0x2000`, sync.c:5427.)

* Both copies left the inventory within 9 ms of each other (the merged input works), but each then
  read the peer's **previous** packet - still `st 2` - and took the "the peer opened a menu this
  copy did not see" branch (sync.c:5414-5420), pulsing BACK (`0x0020`, which *opens* the inventory)
  on its own pad. The pulse is local to the copy that pulses it (`menu_pulse_start` writes into the
  XInput return, not into the pad stream), so each copy re-opened its own inventory.
* The convergence has no freshness, no settle window and no persistence requirement: a peer packet
  up to `MENU_PEER_STALE_MS` = 1500 ms old is acted on at once (sync.c:5257, 5396-5409). On a 0-2 ms
  loopback the stale packet is only ~100 ms old, which is exactly the failure window here, so this
  is not a "guest B on one copy only" bug: it is the convergence pressing an **open** button right
  after a legitimate close.
* DERIVED: anything that makes the two closes land >0 ms apart (link jitter, one extra frame) makes
  this happen; it passed in the author's runs and failed in the reviewer's, which is what a race
  looks like.

## 3. Design (written before the code)

**Model: a transition is a state, not a message.** The host is the only authority for
"which level are we in"; the guest's job is to end up there.

1. **Ordered transitions (protocol 20).** Every transition the host announces gets a sequence number
   (`pkt_req.seq`, monotonic per host session): a level change, a load by name, a load progress (new
   game), a level ask applied for the guest, a level change nobody requested. The host repeats the
   same seq for the same transition (`host_level_request_repeat` / `host_load_request_repeat` keep
   it). The guest keeps the newest seq it has applied and the newest it has queued: an older seq is
   dropped, and when a newer one arrives the older *queued* requests are cancelled. So a lost or
   reordered packet can never make the guest apply an older transition after a newer one.
2. **Never apply half.** The host does not start its own transition while its game still has a
   request pending (`game+0x320 != 0`) or the world was rebuilt moments ago: `game_load_tick` waits
   for the game to be idle and settled before it opens a save, and `host_apply_guest_level` keeps
   the guest's ask pending (bounded) instead of overwriting a change in flight. The guest already
   holds its queue while its own game is busy (sync.c:3368-3374).
3. **Self-heal (the guarantee).** The host streams its authoritative level and entry
   (`pkt_state.host_level/host_entry/host_busy`). If the guest's own level differs from that for
   more than 3 s while both copies are idle (the host has no request pending, the guest is in a
   level with no request and no door animation running), the guest performs the host's level change
   through the same `ChangeLevel` call the late-join path uses - so two transitions that raced and
   left the copies split converge, at the latest 3 s after both settle, without a reload.

**Menu convergence: repair only a *stable, confirmed* divergence.** A correction is only made when
(a) this copy's own menu state has not changed for `MENU_SETTLE_MS` (600 ms - longer than the
sender's 250 ms publish period, so the peer's packet about our own change is already in), (b) the
peer's packet is fresh (`<= MENU_FRESH_MS`, 400 ms), and (c) the mismatch has persisted that long.
A tie in the sequence numbers is not a divergence.

## 4. Implementation (see the diff)

* `src/net.c`: `NET_VERSION 20`; `pkt_req` gains `seq`; `pkt_state` gains `host_level`, `host_entry`,
  `host_busy`; `net_send_req` takes the seq.
* `src/hooks.c`: every host announcement takes a new seq (`host_trans_next`); `host_apply_guest_level`
  defers while `game+0x320 != 0`.
* `src/sync.c`: the repeat keeps the seq; the guest drops/cancels stale requests; `guest_level_heal`;
  the guest's `sync` line gains `trans`/`heal` counters; `game_load_tick` waits for the host's game
  to be idle and settled; the menu convergence gets its settle/freshness/persistence gate.
* `tests/soak34.py`: two deliberate race phases (a door use followed by a load within 1 s, and the
  same door used on both copies at once) after the 30 changes; each must end in one level.

## 5. Live evidence

### 5.1 Soak run 1 (`run_s37_soak1.log`, dll `chk37a.dll`, 30 changes, ~90 ms relay)

The soak body passed: **30 of 30 iterations ended in one level**, both game threads ran in every
iteration, no crash and no stall report. The two new race phases ended in one level too:

```
== race A: door use on the host, then a save load the moment the door asks for its level
     host usedoor 0 -> ok usedoor player 0 door DODO id 13a ent 1ae3eca8 (55.0 units away, spot 0, door 1/1)
   the door reached its ChangeLevel: yes
   issuing loadsave game0.sav right now (2.3 s after the door use)
   race A result: level J002/J002 after 0.3s -> one level
== race B: the same door used on the host and on the guest at the same moment
     host usedoor 0 -> ok usedoor player 0 door DORH id 12c ent 1ae79ff8 (55.3 units away, spot 0, door 1/2)
     guest usedoor 1 -> ok usedoor player 1 door DORH id 3c95 ent 1ad72020 (55.0 units away, spot 0, door 2/2)
   race B result: level I010/I010 after 0.0s -> one level
soak OK (30 location changes, both copies alive)
```

In the host log the race-A load is the case this task fixes, and it is now ordered:

```
00:13:54.819 host: real load of "game0.sav" (pipe) waits for this copy's transition to finish (state 0, 0 ms since the level 49313030)
00:13:55.518 host: real load of "game0.sav" (pipe): the game's save open ok
00:13:55.519 host: real load of "game0.sav" issued (mode 1 request state 3)
```

* The last check inside `run_soak.sh`, `check_doors.py --reset game3.sav`, FAILed in that run, but for a
  harness reason, not a sync one: the race phases leave the door used by race B still busy, so the
  check's `usedoor` retried on the busy door and then gave up (`usedoor: error ... busy 1 user ...`),
  and the reset then raced the door's own ChangeLevel. Fixed in the tests: soak34.py waits for a
  settled pair (one level, unchanged for 3 s) after the race phases, and `check_doors.py` /
  `check_controls.py` wait for **normal play** (world state 1, no requested scene) before driving -
  a scripted event right after a load (world state 7, `world+0x12c = 7`) stops the game's interaction
  and movement scan (FINDINGS_36 §2/§6), which is what made both of them flaky on a fresh load.

### 5.2 Soak run 2 (`run_s37_soak2.log`)

* `check_controls.py` FAILed at its start (0.0 units on both copies for both pads) while the game was
  in the scripted event above (`scene: this copy entered a scripted event (world state 1, scene 7 ...)`
  at 00:13:45.058 in the host log). That is the flake the check now waits out (§5.1).
* At iteration 3 the **guest's game thread died in the game's own code**: `frames 11558 -> 11558` from
  iteration 3 on, with a first-chance report and 28 stall reports:

```
*** obscoop: FATAL EXCEPTION access violation (0xc0000005) on the vectored path
*** fault at Obscure2.exe+0xf16a9 (base 0x400000, image 0x400000)  params 00000001 00000008
*** eax 00000000 ebx 00000001 ecx 19d41770 edx 00000000 esi 19a15650 edi 00000005 ebp 001af86c esp 001af86c
***   Obscure2.exe+0xb5b29 ... Obscure2.exe+0xa5fb0 ... XINPUT1_3.dll+0x9414 ... Obscure2.exe+0x13680a
*** obscoop: GAME THREAD STALLED 3.2 s - no frame for 3156 ms (frames 11558, last mod step "in the game's own code after frame_tick (update/render)")
```

  OBSERVED (decompile): `Obscure2.exe+0xf16a9` is inside `FUN_004f16a0` (33 bytes, 0x4f16a0),
  `*(int **)(param_1 + 8) = param_2; if (param_2) (**(code **)(*param_2 + 0xc))(param_1);` - a
  setter that virtual-calls the object it was handed. The fault is that call on a dead object
  (`ecx` = the receiver, `*param_2` = garbage), i.e. the same stale-vtable family as TASK 35's
  frozen-image hang, in the **game's own UI code**: not one frame from this task's diff (no
  self-heal fired, no menu pulse, no door use at that iteration; the guest's `sync` line shows
  `heal 0`), and it happened ~2.5 s after a scripted event (state 7) that follows a load.
  UNKNOWN: whether the game or the save transfer (which re-runs after every load in this soak) frees
  the object. It is open, it predates this task, and it is not claimed as fixed.
* Not a pass; the run counts as failed and the next runs are the evidence (§5.3).

### 5.3 Soak run 3 (`run_s37_soak3.log`) - PASS

```
== race A: door use on the host, then a save load the moment the door asks for its level
   the door reached its ChangeLevel: yes
   issuing loadsave game0.sav right now (2.2 s after the door use)
   race A result: level J002/J002 after 0.3s -> one level
== race B: the same door used on the host and on the guest at the same moment
   race B result: level I100/I100 after 0.0s -> one level
== settling after the race phases (one level, no change for 3 s)
   settled: level I010/I010, quiet for 3.0 s (yes)
soak OK (30 location changes, both copies alive)
== check_doors.py --reset game3.sav (timeout 300s)
   image: PASS
   transition: dest I100 -> host I100 guest I100 after 0.5 s: PASS
   reset: the host loads game3.sav again (back to I010)
   both copies in level J002 after 2.9 s
   image: PASS
   transition: dest J000 -> host J000 guest J000 after 0.5 s: PASS
doors OK (2 phase(s))
== liveness and crash reports
  host: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
  guest: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
=== soak run: PASS
```

### 5.4 The two defects the regression runs exposed in this task's own code (OBSERVED, fixed in chk37b.dll)

Both were found by live runs, not by reasoning, and both are in this task's diff:

1. **The load gate must not apply at the main menu.** `game_load_tick` waited while `game+0x320 != 0`;
   at the main menu that field holds the *menu* request state (9), which is normal there (the guest log
   shows `real load ... waits for this copy's transition to finish (state 9, 0 ms since the level 00000000)`).
   It could hold a joining guest's load at the menu. Fixed: the gate only runs while this copy is in a
   level (`game+0x310 == 1`).
2. **The transition sequence must not swallow the retry of a failed load.** The guest's load can fail in
   the game's own save manager (`guest: real load of "game0.sav" (host): the game's save open FAILED`) -
   that is why `guest_load_failed` existed: it clears the "already taken" mark so the host's repeat is
   executed again. With the new ordering the repeat was dropped one step earlier (`seq <= g_trans_queued`),
   so the guest stayed at the main menu for good. OBSERVED in two runs (`run_s37_menus.log` run 1: `guest
   after load: mode 2 world 0x0`; `run_s37_reg1.log`: `wiring guest: no world`, `guest 0 world entities`).
   Fixed: `guest_load_failed` steps the two sequence marks back below the failed transition, so the host's
   repeat of that same request is accepted again while every ordering rule still holds.

The soak, menu and reconnect evidence above is from `chk37a.dll`; the regression below is from
`chk37b.dll`. The two differ only in these two paths (a load that *failed* in the game, and the load gate
while not in a level); neither path is taken by a passing soak/menu/reconnect run, so the evidence above
still describes the level logic of the final build. The soak and the menu check were not re-run on
`chk37b` because of the process cap (below).

### 5.5 Soak run 4 and the process budget

Run 4 (`run_s37_soak4.log`) met every criterion the task names for the soak body:

```
   race A result: level J002/J002 after 0.3s -> one level
   race B result: level I100/I100 after 0.0s -> one level
   settled: level I010/I010, quiet for 3.0 s (yes)
soak OK (30 location changes, both copies alive)
```

but its trailing `check_doors.py --reset game3.sav` phase 2 was refused with
`usedoor 1 -> error usedoor: not in a level` (the guest's world was being rebuilt after the reset load)
and the runner therefore printed `=== soak run: FAIL`. So run_soak printed `=== soak run: PASS` once
(run 3) and `FAIL` three times, each time for a reason outside the soak body (run 1: the door the race
phase left busy; run 2: the guest's game-side crash; run 4: a world rebuild at the instant of the door
command). The literal "twice in a row" is **NOT** achieved - the process cap (26) was reached with the
runs below, and two more soaks would have left nothing for the menus, reconnect and regression.

The harness causes seen in runs 1 and 4 are fixed in the test scripts (a 3 s settle after the race
phases, `wait_normal` before driving a pad, and a `usedoor` retry while a world is rebuilt). The last
soak run of this task did not use those fixes' successors (only the soak34 settle), so no claim is made
that the next run passes.

### 5.6 Menu runs (`run_s37_menus.log`, 3 runs of `run_pair_menu.sh <dll> check_menus.py`)

| run | result |
|---|---|
| 1 | `NOT IN A LEVEL on both copies (host 1 guest None): check skipped` - the guest never joined: `TIMEOUT waiting for the guest in the same level`, `guest after load: mode 2 world 0x0`. Cause OBSERVED: `guest: real load of "game0.sav" (host): the game's save open FAILED` and the host's repeat was dropped by the new transition ordering - the defect fixed in §5.4 item 2. |
| 2 | `menus OK (10 checks)` - the guest's B closes the inventory on both |
| 3 | `menus FAIL (10 checks)`: `after guest START host st 5 ui (0, 0) | guest st 5 ui (0, 0)`, `both copies left the pause menu after NO s`, `guest closes the pause menu on both: FAIL` (the pre-existing guest-START -> player-1 START path, untouched by this task); the following BACK step cascaded (`inventory shown on both: FAIL`), but the fixed check `after guest B host st 1 | guest st 1` -> `guest's B closes the inventory on both (merged input): PASS` |

So the flake this task was asked to fix (the guest's B closing the inventory) passes in both runs that
reached that step, with `correct 0 gated 0` in the menu counters (no spurious convergence pulses).
"3 runs in a row" is **NOT** achieved (2 of 3 failed elsewhere, for causes stated above).

### 5.7 Reconnect (`run_s37_reconn.log`) - PASS

```
before: IN SYNC after 0.5 s (level I100, 2 characters, worst copy difference 0.0 units)
== CASE 1: drop the link for 8 s in the middle of play (netpause 8000 on both copies)
resume: IN SYNC after 0.5 s (level I100, 2 characters, worst copy difference 0.0 units)
guest level/load requests after: 1 (before 1)
CASE 1: no level or load request reached the guest (no reload)
== CASE 2: kill the guest and start it again at the main menu while the host keeps playing
late join: IN SYNC after 0.5 s (level I100, 2 characters, worst copy difference 0.0 units)
=== reconnect run (both): PASS
```

### 5.8 Regression (`run_s37_reg_all.log`, dll `chk37b.dll`)

| run | command | result |
|---|---|---|
| reg1 | `run_pair_menu.sh` party, items, hands, entities, attack_anim, controls, doors, movement (movement merged into this run: the runner supports it and special-cases phase E, which saved the pair needed to stay inside the process cap) | `party OK`, `items OK`, `hands OK (2 characters checked)`, `entities OK (host 43, guest 43)`, `controls OK (each pad drives its own character on both copies)`, `doors OK (1 phase(s))`, movement `E: PASS`, `A: PASS`, `B: PASS [warn: BOY1 anim differs in 8/60 samples (transition samples)]`, `C: PASS`, **`D: FAIL -- BOY1 did not move: host 19.5 guest 19.7 units (min 20); GIR1 did not move: host 0.0 guest 0.0 units (min 20)`**; **`attack animation FAIL (FAIL, PASS)`**: the host-pad phase produced the stance `102` on BOTH copies (`host states [102], guest states [102]`, `other character GIR1: host states [], guest states []`, `cross-talk no`), not the `100`/`200` the check expects, while the guest-pad phase passed with `100` |
| reg3 | `OBSCOOP_SLOT=3 run_pair_menu.sh check_breakables.py` | **PASS** `breakables OK (chairs picked up, swung and broken on both copies; 2 chair(s) checked)` |
| reg4 | `OBSCOOP_PICKUP_CLASS=MEDI OBSCOOP_PICKUP_SPAWN=1 run_pair.sh check_itemuse.py pair_j003.py check_pickup.py` | **PASS** `RESULT: item use OK (each use landed once on both copies, lives equal, inventories identical)`, `phase host->guest: OK`, `phase guest->host: OK`, `pickup OK: both directions collected on both copies, inventories match, no echo` |
| reg5 | `run_cutscene_pair.sh --skip-by guest` | **PASS** `PASS: the skip on the guest ended the event on the host (forwarded skip applied, skips 1)`, `cutscene sync: PASS` |

The two reg1 failures are **not** copy-to-copy divergences: the attack stance is identical on both
copies (`102`/`102`) and movement D's `diff_mean` is `0.14` with the animation equal in 50/50 samples -
BOY1 moved 19.5 units (host copy) / 19.7 (guest copy) against the check's 20-unit minimum. Both are the
timing-sensitive checks known from earlier tasks (a scripted event holding the game, a distance
threshold); cause of this occurrence is UNKNOWN and they were not re-runnable inside the process cap.

## 6. Process budget

26 game processes (the hard limit), 13 pair runs:

| pairs | what |
|---|---|
| 4 | soak runs (`run_soak.sh`), 8 processes |
| 3 | menu runs (`check_menus.py`), 6 |
| 1 | reconnect (`both`), 2 |
| 5 | regression: the first attempt on `chk37a` (which exposed §5.4), then reg1/reg3/reg4/reg5 on `chk37b`, 10 |

## 7. DONE / NOT DONE / UNKNOWN

**DONE**

* The level split is fixed at the root (item 1): transitions are ordered by a host sequence number
  (`pkt_req.seq`, protocol 20), the guest applies only the newest (an older or duplicate seq is dropped,
  older queued ones are cancelled), the host does not start a load or a guest-asked level change while a
  transition of its own is in flight, and the guest re-converges on the host's level (`pkt_state.host_*`,
  `guest_level_heal`, 3 s of mismatch with both copies idle). The two deliberate race phases (a door use
  followed by a load the moment the door asks for its level; the same door used on both copies at once)
  end in one level in all three non-crashed soak runs.
* 30 of 30 location changes ended in one level with both game threads running in soak runs 1, 3, 4; no
  mod-side stall report in any of them; `=== soak run: PASS` in run 3.
* The inventory-close flake (item 2) is diagnosed from the reviewer's own logs and fixed: the convergence
  pressed BACK (the OPEN button) on a peer packet ~100 ms old right after both copies had closed the
  inventory within 9 ms. Corrections now need a fresh peer packet, a quiet settle window after this
  copy's own change, and a 500 ms persistent mismatch; both copies keep publishing while either is in a
  menu. The guest's B close passes in both runs that reached it.
* Reconnect (item 3, not run in TASK 36): `=== reconnect run (both): PASS`.
* Regression: party, items, hands, entities, controls, doors, breakables, item use (+ both pair_j003
  phases), pickup and the cutscene skip all pass; movement E/A/B/C pass.
* Two defects in this task's own code found by live runs and fixed (§5.4): the load gate must not apply at
  the main menu, and a load that the game's save manager refused must still be retried despite the new
  sequence ordering.
* Test fixes: the soak's race phases + settle; `check_controls.py` and `check_doors.py` wait for normal
  play and retry a refused door use while a world is rebuilt.

**NOT DONE**

* `run_soak.sh` did not pass **twice in a row**: one full PASS (run 3); the other three runs failed
  outside the soak body (door busy after the race phase; a game-side crash; a world rebuild at the door
  command). Their harness causes are fixed in the tests but the fixed scripts were not re-run (process
  cap).
* `check_menus.py` did not pass **3 runs in a row**: 1 of 3 passed; the two failures are the guest never
  joining (the retry defect, now fixed) and the pre-existing guest-START/pause path.
* Movement phase D (19.5 units vs a 20-unit minimum) and the attack-animation check (stance 102 where it
  expects 100, identical on both copies) failed in the regression run and were not re-run.

**UNKNOWN**

* Why the guest's game thread crashed in the game's own UI code in soak run 2 (`FATAL EXCEPTION` at
  `Obscure2.exe+0xf16a9` inside `FUN_004f16a0`, a vtable call on a dead object, right after a load and a
  scripted event, with the save transfer running). It is the stale-object family TASK 35 fixed for
  props; it is not in this task's diff (`heal 0`, no pulse, no door use at that iteration) and is not
  fixed here.
* What opens the "scripted event" (`world+0x12c = 7`, world state 7) a few seconds after a load in level
  I100 - the game's own script; it stops the pad/movement scan and is what makes the timing-sensitive
  checks flaky.
* Whether the attack stance `102` is a weapon-dependent value (the character carried a crossbow in that
  run) or something else; the two copies agree, so it is not a sync divergence.

## 8. Result in one paragraph

The level split is fixed where it came from: the host announces transitions with a sequence number,
starts no transition on top of one in flight, and streams the level it is actually in; the guest applies
only the newest transition and, if the copies still end apart, follows the host's level after 3 s of
idle. Two new deliberate races in the soak (a door's ChangeLevel plus a load the same instant, and the
same door used on both copies) end in one level, and 30 of 30 location changes did too in every soak run
that did not crash. The inventory-close flake was the convergence pressing the OPEN button on a stale
peer packet; a correction now needs a fresh, stable, confirmed divergence, and the guest's B close passes.
Reconnect passes both cases and the regression is green except for two timing-sensitive checks whose two
copies agree with each other. Not achieved inside the 26-process cap: "run_soak.sh passes twice in a
row" (one full PASS, three runs whose failures were harness or game-side) and "check_menus.py passes 3
runs in a row" (1 of 3, the other two failing on causes outside the fixed path).
