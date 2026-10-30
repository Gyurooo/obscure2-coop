# FINDINGS 48 — after the pickup checks the puppets stop following and both pictures freeze

Base: branch `w/combat`, HEAD = TASK 47 (all soaks PASS). Repro (task, 2/2 reviewer runs):
`OBSCOOP_PICKUP_CLASS=MEDI OBSCOOP_PICKUP_SPAWN=1 sh tests/run_pair.sh <dll> pair_j003.py check_pickup.py`
(the runner appends check_visible.py). Labels OBSERVED / DERIVED / GUESS / UNKNOWN.

## 0. What the reviewer's log says (OBSERVED, `_archive/claude_probe_pause.log`)

After `pickup OK ...` (both phases collected on both copies), check_visible finds on the host:

```
peer on this copy at (1290.4, -2789.0, 570.6) state 0, wired to its controller record: True
peer on its own copy at (6374.2, 273.8, 0.0) state 0 -> the two copies differ by 5962.43 units
peer collision body at (-27.6, 3185.9, -328.7) -> 7040.69 units from its owner (tolerance 8.0)
host_idle/host_stance/host_walked: PrintWindow keeps returning the same frame
```

and the same on the guest (peer BOY1 269.69 units away, stale body, frozen picture). Facts in those
numbers:

* the host's copy of GIR1 sits exactly at the position the HOST's own `tp peer player 2` wrote in
  check_pickup (`1290.44, -2789.00, 570.56`), NOT at the guest's final position (`... 554.29`): the
  streamed pose has not been applied since;
* its collision body is still at player 2's J003 entry point `(-27.6, 3185.9, -328.7)` - the body is
  moved only by `puppet_prepare` -> `puppet_write(move=1)` -> the game's SetPosition (FINDINGS_45), so
  the puppet was not driven in J003 on the host at all;
* both pictures are static while the local pad walks (`walk vs idle 0.02 %`).

## 1. Hypotheses (from the task) and the cheap way to tell them apart

| hypothesis | signature |
|---|---|
| the game is PAUSED (world+0x11c != 1: 2 inventory / 5 pause) | local pad does not move the local character; `menu` dump shows st 2/5; puppet guards count `world state` |
| the puppet stream/guards stopped after the teleports | local character still walks; guards count some other guard; stream counters keep rising |

A temporary probe (test-only, run from `$TMPDIR`, not committed; its output is in `run_s48_base.log`)
prints per copy: mode, world+0x11c sampled 12x, scene kind, controller UI, the `menu`/`scene`/`sync`
dumps, and drives that copy's own pad for 1.5 s to measure whether its own character still moves.

## 2. Measurements

### 2.1 The repro reproduces, and the state is world 8 (OBSERVED, `run_s48_base.log`, chk48base.dll = HEAD)

The probe run between check_pickup and check_visible:

```
== host: mode 1 world state 8 scene 0 | ctl ui 0/0 | own BOY1 (6292.2, 382.3, 0.0) | peer GIR1 (1290.4, -2789.0, 570.6)
   own body (6292.2, 382.3, 0.0) (0.00 from the pose) | peer body (-27.6, 3185.9, -328.7) (6184.33 from the pose)
   world state sampled 12x over 1.2 s: [8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8]
   own pad 0 stick up 1.5 s: own moved 0.00 units
== guest: mode 1 world state 8 scene 0 | ... own pad 0 stick up 1.5 s: own moved 0.00 units
```

So it is **not** the inventory (2) and **not** the pause menu (5): both copies sit in **world state 8**, and
the local pad no longer moves the local character (that is why check_visible's picture is static and why
the puppet guards fire: `puppet_target_g` rejects on `world+0x11c != 1`, `PG_WSTATE`, and `puppet_finish`
only runs when `puppet_prepare` returned 1 -> the pose stays where check_pickup's own `tp` left it and the
collision body stays at the J003 entry point).

### 2.2 What world state 8 is (OBSERVED, mod log + decompile)

Host log (`obscure2-test/obscoop.log` of the same run):

```
10:31:21.122 host: item pickup sent: class MEDI id ???? at (6292.2, 382.3, 0.0) by BOY1 [level J003]
10:31:21.127 scene: this copy entered a scripted event (world state 1, scene 8, id 0, level J003)
10:31:21.133 scene: this copy left the scripted event (world state 8, scene 0, level J003) after 0 ms
```

Guest log:

```
10:31:21.125 guest: item pickup applied: class MEDI id ???? at level J003 by BOY1 (collected=1)
10:31:21.125 scene: this copy entered a scripted event (world state 1, scene 8, id 0, level J003)
```

i.e. the pickup itself starts a **noe scene** (`scene kind 8`) on BOTH copies, independently, a few ms
apart. Decompile `FUN_004b4cb0` @0x4b4cb0 (the world's per-frame state machine) handles request kind 8
with `(*(vtable+4))(world+0x140, ...)` - the noe scene's own start - and then stores the request kind into
`world+0x11c`, so **world state 8 = "a noe scene is being presented"** (same mechanism as the kine scene of
state 6, different file kind). `world+0x140` holds the scene name: the probe read **`fs_MEDI`** on both
copies - the game's own "found scene" for a medikit (OBSERVED, `run_s48_close.log`).

Why the mod did not care: `scene_cinematic()` only counted `state == 6` or `(state == 1 && scene != 0)`, so
state 8 was "not a scene" for the mod: it logged an immediate leave and never mirrored the presentation or
its dismissal.

### 2.3 How the presentation is left (OBSERVED, `run_s48_close.log`, chk48base.dll)

```
before: host state 1 guest state 1
collected on the host after 0.5 s
after the pickup: host mode 1 state 8 | guest mode 1 state 8 | scene name 'fs_MEDI'
host  scene: scene local state 8 ... cine 0 | peer state 8 ...
host pad A     -> host state 1 guest state 8
guest pad A    -> host state 1 guest state 1
...
host window: PASS -- ... peer collision body at (6374.2, 273.8, 0.0) -> 0.00 units ...
guest window: PASS -- ...
visible OK
```

So: **A on a pad ends the found scene** (both copies accepted their own pad's A), but **only on the copy
that pressed it** - the partner stays frozen in state 8 forever (the host was still 8 after the guest's
scene had been dismissed, and vice versa). With both copies out of state 8, check_visible PASSES unchanged
(peer 0.00 units, body 0.00, live picture): the whole failure is this stuck presentation.

This is the task's "must not freeze the partner forever" case: in the game's own 2-player mode both players
share one screen and one message, so either player's A ends it for both.

## 3. Fix

* `src/sync.c` `scene_cinematic()`: `state == 8` (the found-scene presentation, name in `world+0x140`) is a
  scripted event like the kine of state 6, so the existing scene machinery mirrors it, and when one copy
  leaves it the other copy carries the leave out with the game's own input.
* `src/sync.c` `scene_skip_begin()`: for state 8 the leave is pressed with **A on a pad**
  (`menu_pulse_start(0, 0x1000, 0, 160)`), not the cinematic's ESCAPE: A is what the game's own pickup
  message takes (OBSERVED 2.3), and a pad pulse can never open the pause menu the way a late ESCAPE can
  (TASK 34). Other scene kinds keep the ESCAPE ladder unchanged.
* `tests/check_pickup.py`: after each collect, `close_found_scene()` waits for the presentation, presses A
  on the collecting player's pad once (a player's own action), and requires BOTH copies back in world
  state 1 within 3 s (three tries); the phase fails otherwise. This is the live proof of the mirroring.

## 4. Live results (verbatim)

### 4.1 Repro run 1 - PASS (`run_s48_a1.log`, chk48a.dll)

```
   the game's found scene is up: host state 8, guest state 8 -> A on host player 1's pad (the way a player closes it)
   both copies back in normal play after 0.2 s
...
phase host->guest: OK
...
   the game's found scene is up: guest state 8, host state 8 -> A on guest player 2's pad (the way a player closes it)
   both copies back in normal play after 0.2 s
...
phase guest->host: OK
pickup OK: both directions collected on both copies, inventories match, no echo
== check_visible.py
host window: PASS -- the peer character is present in this copy's render world at its streamed position and state, and the window draws
guest window: PASS -- the peer character is present in this copy's render world at its streamed position and state, and the window draws
visible OK (the peer character is present in both copies' render worlds)
```

The mod's own log of the same run shows the mirroring (the leave is carried out on the OTHER copy, 13-15 ms
after the player's A):

```
host : 10:39:28.697 scene: this copy left the scripted event (world state 1, scene 0, level J003) after 1500 ms ... (leave 4)
guest: 10:39:28.699 scene: the peer left a scripted event (peer level J003, id 0, leave 4): pending skip armed
guest: 10:39:28.701 scene: the peer's copy has left the scripted event and this copy is still in it (world state 8, scene 0, id 0, level J003): pressing the game's own skip here (attempt 1 of 3)
guest: 10:39:28.714 scene: this copy left the scripted event (world state 1, scene 0, level J003) after 1531 ms ...
```

### 4.2 Repro run 2 - PASS (`run_s48_a2.log`, same DLL, same command)

```
   the game's found scene is up: host state 8, guest state 8 -> A on host player 1's pad (the way a player closes it)
   both copies back in normal play after 0.2 s
phase host->guest: OK
...
   the game's found scene is up: guest state 8, host state 8 -> A on guest player 2's pad (the way a player closes it)
   both copies back in normal play after 0.2 s
phase guest->host: OK
pickup OK: both directions collected on both copies, inventories match, no echo
host window: PASS -- the peer character is present in this copy's render world at its streamed position and state, and the window draws
guest window: PASS -- the peer character is present in this copy's render world at its streamed position and state, and the window draws
visible OK (the peer character is present in both copies' render worlds)
```

Note both item classes exercised the same path live: `fs_MEDI` (medikit, host->guest) and the backpack
(guest->host), i.e. the pickup presentation family, not one class.

### 4.3 One side effect seen in the logs (OBSERVED, not introduced by this task)

After a leave, the peer repeats it for 1.5 s (and while the leaving copy still sees the other in a scene),
and the receiver keeps its pending skip alive while those repeats arrive (`peer_on_scene`: "the peer is
still repeating that leave: keep the pending alive"). If a NEW found scene starts within ~500 ms of the
last repeat, the stale pending presses A on its first frame (guest log 10:39:30.277: "pressing the game's
own skip here (attempt 2 of 3)" at the frame the second scene appeared). In these runs the scene had not
presented yet (world state 1, scene kind 8), the press did nothing, and the player's own A closed it 1.5 s
later - the check's close step still succeeded. Left as it is: it is the pre-existing leave/pending policy
that keeps cutscene skips reliable (TASK 31/34), and tightening it is outside this task.

### 4.4 5-iteration steam soak - PASS (`run_s48_soak.log`, chk48a.dll)

`OBSCOOP_LINK=steam OBSCOOP_SOAK_ITERS=5 sh tests/run_soak.sh <...>/chk48a.dll`:

```
== check_attack_anim.py (timeout 180s)
   host pad: host PASS, guest PASS, cross-talk no
   guest pad: host PASS, guest PASS, cross-talk no
== check_anim_sync.py (what is played: both animation layers) (timeout 180s)
walk       upper clip 100%  lower clip 100%  upper plays 100%  lower plays 100%  clips seen yes  owner moved  272.3 units  PASS
run        upper clip  95%  lower clip 100%  upper plays 100%  lower plays 100%  clips seen yes  owner moved  339.2 units  PASS
aim-walk   upper clip 100%  lower clip 100%  upper plays 100%  lower plays 100%  clips seen yes  owner moved  293.6 units  PASS
swing      upper clip 100%  lower clip 100%  upper plays 100%  lower plays 100%  clips seen yes  owner moved    0.0 units  PASS
guest-walk upper clip 100%  lower clip 100%  upper plays 100%  lower plays 100%  clips seen yes  owner moved  344.6 units  PASS
== check_controls.py (timeout 180s)
   host: PASS (own character moved on both copies, the other did not)
   guest: PASS (own character moved on both copies, the other did not)
== check_visible.py (the peer character is drawn) (timeout 150s)
host window: PASS -- the peer character is present in this copy's render world at its streamed position and state, and the window draws
guest window: PASS -- the peer character is present in this copy's render world at its streamed position and state, and the window draws
== check_fight_pair.py (players attack each other) (timeout 240s)
attack-each-other OK (3 swings each way, both copies alive)
== soak34.py (5 location changes) (timeout 1500s)
soak OK (5 location changes, both copies alive)
== check_doors.py --reset game3.sav (timeout 300s)
doors OK (2 phase(s))
== liveness and crash reports
  host: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
  guest: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
=== soak run: PASS
```

(The 12-row anim-sync table is quoted in part; every row of it is `PASS` in the log.)

## 5. Same family (owner rule)

* The item-pickup presentation is one mechanism for every item class (`fs_MEDI` = medikit, the backpack in
  the guest->host phase): both classes were exercised live above, same code path.
* Other noe scenes (any other `world+0x12c == 8` start, e.g. a story scene started by a level script) go
  through the same `scene_cinematic()`/`scene_skip_begin()` code: **same code path, not tested live**.
* The kine/cinematic family (world state 6) keeps the ESCAPE skip and is untouched; the soak's level
  changes and the earlier cutscene check run through it without a change.
* Menus (states 2/5) are separate (`menu_tick`) and untouched.

## 6. DONE / NOT DONE / UNKNOWN

DONE
* Root cause found and measured: the pickup starts the game's own `fs_<class>` found scene (world state 8)
  on BOTH copies; state 8 stops the world, and the mod did not count it as a scene, so a dismissal on one
  copy left the partner frozen in state 8 forever (the task's "must not freeze the partner forever").
* Fix: state 8 is a shared scripted presentation (`scene_cinematic`), and the leave is carried out on the
  peer with a short **A pad pulse** (the input the game's own pickup message takes), not ESCAPE.
* `check_pickup.py` closes the message like a player (A on the collecting player's pad) and fails unless
  BOTH copies return to world state 1.
* Proof: the task command PASSES twice (pickup OK + visible OK both times), then the 5-iteration steam
  soak PASSES.

NOT DONE
* Nothing from the task is left open.

UNKNOWN
* Whether a player can also leave the found scene with a keyboard key (ESCAPE was not tried; A on a pad is
  proven on both copies).  GUESS: A is the only input the message waits for.
* Other noe scenes (state 8 from a story script) were not exercised live - the same code path now mirrors
  them, but a scene that ends by itself would be "left" by both copies anyway.




