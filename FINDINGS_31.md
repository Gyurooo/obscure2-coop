# FINDINGS 31 — cutscene skip forwarding made reliable in both directions (TASK 31)

Labels: **OBSERVED** = printed by a run in this task / read in the decompile or a log with an address;
**DERIVED** = follows from the cited code but was not observed live; **GUESS**; **UNKNOWN**.
Decompile = `local\decomp2\Obscure2.exe.c`; mod logs = `<test dir>\obscoop.log` (UTF-16LE), written by `logf`.

Branch: `w/combat` HEAD (TASK 30, protocol 16) -> protocol **17** after this task.

## 0. Summary

| item | finding |
|---|---|
| symptom | a skip on either copy left the OTHER copy in the B101 new-game intro (`world+0x11c = 6`) for the whole 8 s window; `skips 0` on that copy, i.e. the mod never even pressed its skip |
| where the skip was lost | in the **decision**, not in the input: the stayed copy's `scene` reply shows `skips 0 left 0 stuck 0` in both reviewer logs, so `scene_skip_begin()` was never reached |
| why | TASK 30 only forwarded a skip when the two copies' scene **identities** matched: `last_a == me.a && (!last_n \|\| last_n == me.name4)`, with `last_n`/`name4` = the 4 bytes at `world+0x140` (the noe-scene name buffer). During a **kine** (state 6) nothing writes `+0x140`, so the two copies carry unrelated leftovers there and the comparison drops the skip - sometimes (the one passing run had matching values) |
| fix | the leave is now an **event**: the leaving copy increments `pkt_scene.leave_seq` and repeats the leave (1.5 s unconditionally, up to 8 s while the peer still reports a scene at that level); the receiver **arms a pending skip** on that packet the moment it arrives (RX thread), independent of the local scene state, and presses the game's own skip as soon as it is in a scripted event of that level; the skip ladder is retried 3x, 1.2 s apart |
| also fixed | `g_scene_enter_tick` was overwritten on every heartbeat, so the "left ... after N ms" log always said `0 ms` (visible in the reviewer's host log); the enter/leave log lines are now true edges and also fire for a copy whose first report is already inside a scene |

## 1. The two reviewer logs (OBSERVED)

`claude_verify_30_hostskip.log` (host skips):

```
  host  left the event after 0.0 s (skips 0)
  guest left the event after -1.0 s (skips 0, its own input: none)
FAIL: the guest is STILL in the scripted event 8 s after the host skipped (no forwarding)
host scene : scene local state 1 ... | peer  state 6 ... | sent 96  rcv 124 skips 0 left 0 stuck 0 missed 1
guest scene: scene local state 6 ... | peer  state 1 ... | sent 124 rcv 96  skips 0 left 0 stuck 0 missed 0
```

`claude_verify_30_guestskip.log` (guest skips) — the mirror image:

```
  guest left the event after 0.0 s (skips 0)
  host  left the event after -1.0 s (skips 0, its own input: none)
host scene : scene local state 6 ... | peer  state 1 ... | sent 123 rcv 96  skips 0 left 0 stuck 0 missed 0
guest scene: scene local state 1 ... | peer  state 6 ... | sent 96  rcv 123 skips 0 left 0 stuck 0 missed 1
```

What the counters say (**OBSERVED**, these are the mod's own numbers):

* The stayed copy **received** the other copy's "I left" state (`peer state 1 ... cine 0`) and its own scene
  was still `state 6 ... cine 1`, same level `B101`, same id `01_1`. All the data a skip decision needs was
  there, and the packets kept coming (`rcv 96` vs the sender's `sent 96`).
* `skips 0` on the stayed copy = `scene_skip_begin()` never ran -> the decision in `scene_tick()` returned
  early. `stuck 0` proves the skip ladder itself was never started (and in the TASK 30 passing run the same
  ladder left the guest in 0 ms, so the input path works).
* `missed 1` is on the copy that LEFT (it sees the peer still in the scene) - so the two copies did talk
  about their states in both directions.

## 2. Which check dropped it (DERIVED from the TASK 30 source in this worktree)

`scene_tick()` (protocol 16) needed `me.cine && !peer.cine && me.level == peer.level && last_a == me.a &&
(!last_n || last_n == me.name4)` with `last_a/last_n` = the identity fields of the peer's last **cine**
packet and `me.a/me.name4` = this copy's `world+0x138` / `world+0x140`.

* state, scene id (`world+0x138` = `0x30315f31`, "01_1"), level (`B101`) and `cine` all matched in the
  reviewer logs (they are printed by the `scene` command), so of the compared fields only **`name4`**
  (`world+0x140`) is not visible in the logs - and it is the only one that is not a scene id at all:
  FINDINGS_30 §2 calls `+0x140` the noe-scene **name string**, written only by `FUN_004b2890` (NoeScene).
  In a kine (state 6, the B101 intro) nothing writes it, so the two copies keep whatever their own level
  load left there.
* That matches the flakiness exactly: the one passing run compared equal values, the two reviewer runs did
  not. A single byte of leftover in one copy's buffer is enough to drop the skip, and nothing retries it.
* The `!` on `last_a` also made the forwarding depend on the receiver having seen a **cine** packet before
  the leave; any lost packet there dropped the skip for good (the leave was re-sent for only 3 s).

## 3. The fix (protocol 17)

`pkt_scene` gains `leave_seq` (this copy's count of "I left a scripted event").

1. **Leave is an event, not a state compare** (`peer_on_scene`, RX thread): a leave is armed when the
   peer's `leave_seq` changes, or when its `cine` flag falls. No scene-id / name-buffer comparison is
   involved any more (`world+0x140` is still sent and logged, but it no longer gates anything).
2. **Pending skip** (`g_pend_*`): armed on the RX thread -> a game-thread check a frame later cannot miss
   it, and it does not depend on seeing the peer's "in a scene" packets first. It is applied when this copy
   is in a scripted event at the same level (or starts one within 10 s), so a skip that arrives while this
   copy is still **loading into** the scene is applied when its scene becomes active.
3. **Repeat until acknowledged** (`scene_send`): the leaving copy repeats the leave 4x/s for 1.5 s
   unconditionally and up to 8 s while the peer still reports a scripted event at that level (then it
   stops by itself - the peer is out). Each repeat refreshes the receiver's pending, so a slow or busy
   receiver cannot lose it.
4. **Retry the ladder** (`scene_skip_frame`): 3 ladders, 1.2 s apart, per received leave (the game can
   ignore a press in the first frames of a scene), instead of one ladder and a permanent `g_skip_failed`.
5. **No self-skip after leaving together**: a pending is dropped as soon as this copy is out of the event
   (with a 0.5 s grace), so a chained scene that follows a skip is not skipped by a stale pending.

## 4. Live result (OBSERVED)

`tests/run_cutscene_pair.sh chk31a.dll --skip-by host|guest`, 3 runs each in a row, one build (`chk31a.dll`,
built from this worktree's source), logs `run_a31_host1..3.log` / `run_a31_guest1..3.log`:

```
run_a31_host1.log  host  left the event after 0.0 s (skips 0)
                   guest left the event after 0.0 s (skips 1, its own input: none)
                   PASS: the skip on the host ended the event on the guest (forwarded skip applied, skips 1)
                   cutscene sync: PASS
run_a31_host2.log  ... guest left the event after 0.0 s (skips 1, its own input: none) ... cutscene sync: PASS
run_a31_host3.log  ... guest left the event after 0.0 s (skips 1, its own input: none) ... cutscene sync: PASS
run_a31_guest1.log guest left the event after 0.0 s (skips 0)
                   host  left the event after 0.0 s (skips 1, its own input: none)
                   PASS: the skip on the guest ended the event on the host (forwarded skip applied, skips 1)
                   cutscene sync: PASS
run_a31_guest2.log ... host left the event after 0.0 s (skips 1, its own input: none) ... cutscene sync: PASS
run_a31_guest3.log ... host left the event after 0.0 s (skips 1, its own input: none) ... cutscene sync: PASS
```

6 of 6 runs: the forwarded copy left on its **first** skip ladder (`tries 1/3`, `stuck 0` in every run's
final `scene` reply) and the check's own measurement is `0.0 s` against a 1 s requirement. Both copies end
`state 1 scene 0` at `B101` with the same party and positions, e.g. (`run_a31_host1.log`):

```
host scene : scene local state 1 scene 0 id 01_1 level B101 cine 0 | peer  state 1 scene 0 id 01_1 level B101 cine 0 | sent 90 rcv 90 skips 0 left 0 stuck 0 missed 1 energy 0 | leave 1 pend 0 tries 0/3
guest scene: scene local state 1 scene 0 id 01_1 level B101 cine 0 | peer  state 1 scene 0 id 01_1 level B101 cine 0 | sent 90 rcv 90 skips 1 left 1 stuck 0 missed 0 energy 0 | leave 1 pend 0 tries 1/3
```

`sent 90 rcv 90` = every packet the two copies sent arrived (loopback); `leave 1` on both = each copy's
leave was reported once and the peer's leave was consumed; `pend 0` at the end = no stale pending skip is
left armed (that is what keeps a chained scene from being skipped by accident).

The mod log of the same run (`obscure2-test2\obscoop.log`, guest = the copy that stayed):

```
18:45:25.092 [40564] scene: the peer left a scripted event (peer level B101, id 0x30315f31, leave 1): pending skip armed
18:45:25.096 [40668] scene: the peer's copy has left the scripted event and this copy is still in it (world state 6, scene 0, id 0x30315f31, level B101): pressing the game's own skip here (attempt 1 of 3)
18:45:25.103 [40668] scene: this copy left the scripted event (world state 1, scene 0, level B101) after 20125 ms; repeating it until the peer leaves too (leave 1)
18:45:25.103 [40668] scene: the local copy left the scripted event 0 ms after the skip was pressed
```

**OBSERVED: leave packet -> pending armed -> skip pressed -> out, in 11 ms** (the 4 ms between the two
thread ids is the RX thread vs the game thread). The log also shows why the identity compare was unsound:
the copies enter the event with `world state 0, scene 1, id 0` and only later show `state 6, scene 0,
id 0x30315f31` - `world+0x12c`/`world+0x138` change *during* the event, so any comparison of them between
two copies is a race.

### 4.1 Regression (OBSERVED)

```
OBSCOOP_SLOT=3 sh tests/run_pair_menu.sh <dll> check_breakables.py                                  -> breakables OK (2 chairs), exit 0   [run_a31_reg_break.log]
sh tests/run_pair_menu.sh <dll> check_party.py check_items.py check_hands.py check_entities.py       -> party OK, items OK, hands OK, entities OK (43/43), exit 0   [run_a31_reg_main.log]
sh tests/run_reconnect.sh <dll> 1                                                                   -> "resume: IN SYNC after 0.5 s", no level/load request, CASE 1 PASS, exit 0   [run_a31_reg_reconn1.log]
```

`run_reconnect.sh <dll> both` was **not** run: case 2 kills the guest and starts a *new* guest process, so
`both` needs 3 game processes. After the six cutscene runs and the two pair-menu runs the count was 16
(6 x 2 + 2 + 2); case 1 took the remaining 2 (total 18), so `both` would have needed a 19th. Case 1 (a dead
link for 8 s in mid-play, exactly the packet path this task changed) passed with no reload. Case 2 (guest
restart) is UNKNOWN for this build.

## 5. Same-family coverage

The forwarded skip is one code path for the whole scripted-event family of FINDINGS_30 §1/§2: everything
that sets `world+0x11c != 1` or `world+0x12c != 0` (kine/FMV = 6, the other scene kinds 7, 8/NoeScene,
0xd, a scripted camera, dialogs and the character freeze) ends with the same local skip input, and the new
code never looks at *which* kind it is - it only compares "in a scripted event" and the level. So a noe
scene, a story dialog or an FMV is forwarded by exactly the code proven here. No live event of those kinds
was reachable from save 01 (I100 has no cutscene, FINDINGS_30 §4) - **same code path, not tested live**.

## 6. UNKNOWN / not covered

* Which field actually differed in the reviewer runs: `world+0x140` (the noe-scene name buffer, the only
  compared field that is not a scene id) is the prime suspect (**DERIVED** from the old source plus the
  reviewer logs, which print every other compared value as equal), but a transient `world+0x138` difference
  is not excluded. The new code does not depend on either field, so the fix holds whichever it was.
* `run_reconnect.sh both` case 2 (guest restart) was not run (process cap, §4.1). A restarted guest starts
  at `leave_seq 0`, which the host sees as a changed counter and turns into a pending skip; that pending is
  dropped within 0.5 s whenever the host is not in a scripted event (`scene_tick`), so the risk is limited
  to a host that is *in* a cutscene when a guest restarts. **DERIVED, not tested.**
* The skip ladder's pad fallback (START, A) was again never needed: ESCAPE alone left the event in every
  run, both copies (`left ... 0 ms after the skip was pressed`).
* Repeats of the leave beyond the first one were never exercised by a *lost* packet (loopback dropped
  none: `sent == rcv` in all six runs); the repeat path is **DERIVED** from the code, and only its
  "peer still in the scene" branch is observable in the logs (the leaving copy logs once, then keeps
  sending silently).

## 7. Game processes used in this task (18 max)

| # | run | processes |
|---|---|---:|
| 1 | `run_cutscene_pair.sh --skip-by host` (`run_a31_host1.log`) | 2 |
| 2 | `run_cutscene_pair.sh --skip-by guest` (`run_a31_guest1.log`) | 2 |
| 3 | `run_cutscene_pair.sh --skip-by host` (`run_a31_host2.log`) | 2 |
| 4 | `run_cutscene_pair.sh --skip-by guest` (`run_a31_guest2.log`) | 2 |
| 5 | `run_cutscene_pair.sh --skip-by host` (`run_a31_host3.log`) | 2 |
| 6 | `run_cutscene_pair.sh --skip-by guest` (`run_a31_guest3.log`) | 2 |
| 7 | `run_pair_menu.sh` slot 3 + `check_breakables.py` | 2 |
| 8 | `run_pair_menu.sh` + `check_party/items/hands/entities` | 2 |
| 9 | `run_reconnect.sh 1` | 2 |
| | **total** | **18** |

No process was killed that this task did not start; every run ended with `still running: []`.

