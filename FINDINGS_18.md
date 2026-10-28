# FINDINGS 18 — why does a loaded world "stop the player dead"? (TASK 18)

Labels as usual: **OBSERVED** = printed by a run/check in this task or read in the decompile (address
cited); **DERIVED** = follows from the cited code/data but was not observed live; **GUESS**; **UNKNOWN**.

Status: **final**. 14 game processes in this task (4 solo probe runs, 5 solo forward-play runs, 2 solo
single-entity probes, the two required two-copy regressions). Every run ended with
`OWNER FILES UNCHANGED (apart from Steam remotecache.vdf)` and no game left running.

## 0. What the earlier tasks claimed

TASK 16/17 left this picture: after a save load the pad either does not reach the player at all (H000:
"0.0 units in 20 s of held stick", `tests/probe_control.py`) or the character walks a couple of hundred
units and then "stops dead" (I007 ~250, G003 ~177), so no door was ever reached and TASK 17 Part C could
not save; FINDINGS_16 §7 read that as a missing-collision/level problem.

**Both symptoms are artefacts of the test harness.** The pad works in every save-loaded world measured
here, and the two "no movement" measurements are (a) a paused game and (b) a walker that does not know the
stick is camera-relative.

## 1. Movement measured in save-loaded worlds (OBSERVED)

`tests/probe_move.py` (new) drives ONE solo host copy after each save load: it prints the world state, the
input gate the character controller checks, every party character, then presses the virtual pad for 1 s in
each of the four directions, holds the best one for 15 s (sampled every second), and finally presses the
OPPOSITE stick, all four directions again, re-arms the pad, teleports back to the start and walks again.
That tail separates an **input loss** (nothing moves, ever) from a **spatial block** (the reverse press
moves the character at once).

Slot numbers are TASK 18's 1-based ones with the file they mean (SLOT_SCAN.md's table).

### 1.1 Run `run_p1` (host copy only, `chk18.dll`; the foreground window belonged to another process)

| slot (file) | level | world+0x11c (input gate) | 1 s per direction | 15 s held walk |
|---|---|---:|---|---|
| 10 (game9.sav) | I007 | 1 | up 80, down 281, left 305, right 279 | **moving for all 15 s**, ~300 u/s, circling |
| 05 (game4.sav) | J005 | 1 | up 60, down 275, left 307, right 275 | moved 602 units, then stood still |
| 01 (game0.sav) | I100 | 1 | up 317, down 187, left 140, right 292 | moved 274 units, then stood still |

### 1.2 Run `run_p2` (same, H000 first)

| slot (file) | level | gate | 1 s per direction | 15 s held walk | opposite stick 2 s | same stick 2 s | four directions again |
|---|---|---:|---|---|---|---|---|
| 07 (game6.sav) | H000 | 1 | up 301, down 307, left 322, right 260 | **moving for all 15 s**, ~300 u/s | 500 units | 492 units | 311 / 157 / 304 / 282 |
| 06 (game5.sav) | G003 | 1 | up 10, down 104, left 186, right 263 | moved 500 units, then still at x = 3069.12 for 12 s | **435 units** | **630 units** | 294 / 252 / 267 / 261 |
| 01 (game0.sav) | I100 | 1 | up 319, down 188, left 143, right 278 | moved 264 units, then still | **394 units** | **394 units** (back to the same spot) | 0 / 280 / 190 / 144 |

**What that says.**

1. **The pad reaches the player in every save-loaded world** (OBSERVED). Four 1-second presses move the
   character 10–322 units; the sustained walk runs at ~280–320 units/s — the game's own run speed.
2. **The "stops dead" is a wall, not an input loss** (OBSERVED). Where the character stopped (I100 at
   (-259.2, 431.8), G003 at (3069.1, 1037.9), J005 at (1248.7, -5205.4)) the OPPOSITE stick moves it 390–435
   units at once, and the same direction again walks it straight back to the same spot. That is geometry,
   not a dead pad.
3. **H000 moves normally** (301/307/322/260 units in the four presses, then 15 s of continuous walking).
   The TASK 17 "0.0 units in 20 s" does not reproduce with this probe.
4. **Holding one stick walks in a circle** (OBSERVED): the sampled positions repeat with a period of about
   4–5 s in I007 and H000. A 2–3 second "did it move?" sample of such a walk can land back near the start,
   which is what SLOT_SCAN.md §5 recorded as "LEFT for 3 s, player 1 position unchanged".
5. The world's script state is normal: `world+0x11c` = 1 in every case. (`FUN_004cf940`, 0x4cf940, returns
   immediately when `world+0x11c == 0x11` — that value is the game-over state `FUN_004b2ab0`, 0x4b2ab0,
   entered when a party character's `+0x2dc` is 5 — and it is not set anywhere in these runs.)

**Why it circles (DERIVED).** The left stick is camera-relative — `src/obscoop2.c` (`remap_stick`, comment
"stick up = the camera's forward on the ground, stick right = its right"), matching `FUN_004cf940`
(0x4cf940), the character controller's input update — and this game's camera turns to follow the character.
A stick held in one place therefore describes a turn, not a straight line. A walker that calibrates one
stick→world basis and keeps using it (TASK 17 `play_forward.py`) circles once the camera has turned, stops
making progress on its target and gives up — exactly the "walked ~250 units and then stopped dead" lines of
the TASK 17 logs.

## 2. The two "0.0 units" measurements were the harness (OBSERVED)

### 2.1 START pauses the game, and a paused game ignores the pad

`tests/probe_control.py` (TASK 17) presses the game's own buttons — A, A, START, B, BACK, A — before it
measures the sticks. `probe_move.py --pause` (run `run_p3`, I007) repeats that in the same save-loaded
world:

```
   == pause test (what probe_control.py did before it measured 0.0 units)
      before any button: 1.5 s up moved 252.0 units
      after A    : mode 1 pos (-1516.3, -606.9, -9.6)
      after A    : mode 1 pos (-1516.3, -606.9, -9.6)
      after START: mode 1 pos (-1516.3, -606.9, -9.6)
      with START pressed (pause menu): 1.5 s up moved 0.0 units
      after START again: mode 1
      unpaused: 1.5 s up moved 264.5 units
```

Same world, same pad: 252 units before the buttons, **0.0 units with the pause menu open** (the position
does not change at all for the 12 s the menu stays up), 264.5 units again once it is closed.
`probe_control.py` measured a **paused game**, not a broken world.

### 2.2 The mod's own per-frame work changes nothing (OBSERVED)

`OBSCOOP_PASSIVE=1` (new switch: `src/obscoop2.c` `g_passive`, `src/hooks.c` `hk_input_update`,
`src/net.c` `net_start`) disables the network and the input hook's writes, keeping only the command pipe
and the virtual pad. Run `run_p3` (slot 10 / I007, the copy's log says
`passive mode on (no net, no input hook writes)`) versus the active run `run_p1` in the same slot:

| 1 s press | active (`run_p1`) | passive (`run_p3`) |
|---|---:|---:|
| up | 80.3 | 79.1 |
| down | 280.9 | 280.8 |
| left | 304.8 | 305.5 |
| right | 279.4 | 291.0 |
| 15 s held walk | circling at ~295-315 u/s | circling at ~296-314 u/s |

The mod's only per-frame action in a solo copy is clearing `human+0x880/+0x884` (the split-screen
"off-screen, walk to the camera target" flags, `src/hooks.c`); with it off the numbers are the same to
within a few units. A mod feature is therefore not what stops the character.

### 2.3 The load path is the menu's own (DERIVED, already established in TASK 12)

`src/sync.c` `game_load_tick` replays exactly the two calls the menu's Load makes (FINDINGS_12: save
manager open `FUN_0053d9b0` 0x53d9b0, then `LoadByName` `FUN_004a1bd0` 0x4a1bd0 = request state 3), on the
game's own thread from the game-update hook. The state machine that then builds the level
(`FUN_004a5520` 0x4a5520, block `== 3`) is the same block the menu reaches. There is no third menu-only
step to replay; the difference between "menu load" and `loadsave` is which thread issues the two calls,
and the mod issues them from the game thread.

**Which path every run in this task used (OBSERVED):** all of them used `loadsave gameN.sav` — the mod's
replay of the menu's two calls — because that is what the scan/forward-play tools have always used and it
is the path the pair flow uses too. Driving the game's own menu with keypresses (TASK 14's route) was not
repeated here: the replay is the same two calls on the game's own thread, and the movement measured in
§1 is not limited by anything the load leaves behind (the pad works, the physics runs, the camera runs).

### 2.4 The pad and its basis (OBSERVED)

Every run used the virtual pad of the pair tests: `pad 0 <buttons> <lx> <ly> [rx ry lt rt]` on the command
pipe, which replaces XInput user 0 for that copy (`src/obscoop2.c` `XInputGetState`). Measured stick basis
in I007 at the save position (camera yaw −180°), 0.6 s per press:

```
   stick up    0.6 s -> world (-51.0, -58.4) (planar 77.5, angle -131 deg, camera yaw -180 deg)
   stick down  0.6 s -> world (+134.2, +67.3) (planar 150.1, angle 27 deg, camera yaw -174 deg)
   stick left  0.6 s -> world (+48.4, -180.2) (planar 186.6, angle -75 deg, camera yaw -178 deg)
   stick right 0.6 s -> world (-143.2, +85.2) (planar 166.7, angle 149 deg, camera yaw -146 deg)
   camera-relative model: "up" is world -131 deg at camera yaw -180 deg, "right" is -80 deg from "up"
```

"up" is the camera's forward (the −131° vs −180° gap is the character's own turn during the press) and
"right" is −80° from it, i.e. the sign the walker derives from the data. A 1-second press covers ~280–320
units, so one press is already several hundred units of travel.


## 3. The entities are not inactive (OBSERVED)

`probe_move.py` `gate_dump` (run `run_p3`) prints the interaction gate fields of every level entity — the
same five fields the game's scan `FUN_0044d6a0` (0x44d6a0) tests (`+0x20 != 0`, `+0xa8 == 0`,
`+0xc0/+0xac/+0xb0 == 0`, distance <= `+0xa0`):

```
      CToeDoor                 id ....  p20 1 coll 0 gates (0, 0, 0) radius 200.0 at (  3285.0,  -2199.9,     0.0)
      CToeDoubleDoor           id ..=T  p20 1 coll 0 gates (0, 0, 0) radius 200.0 at (  3336.9,  -1729.6,    18.4)
      CToeDoor                 id ....  p20 1 coll 0 gates (0, 0, 0) radius 200.0 at ( -2216.6,  -1886.0,     0.0)
      CToeDoubleDoor           id ...0  p20 1 coll 0 gates (0, 0, 0) radius 200.0 at ( -2182.6,  -2261.4,    18.9)
      CToeDoubleDoor           id ....  p20 1 coll 0 gates (0, 0, 0) radius 200.0 at (   -27.1,  -2175.8,    16.7)
      CToeSavePoint            id ...V  p20 1 coll 0 gates (0, 0, 0) radius 200.0 at ( -1658.9,   -845.7,   118.6)
      CToeItemAmmo             id ...x  p20 0 coll 0 gates (0, 0, 0) radius 120.0 at (  -371.8,    -53.7,    93.9)
      CToeChestKey             id ....  p20 0 coll 1 gates (0, 0, 0) radius 120.0 at (  2002.9,  -2304.3,     0.4)
```

Doors and the save point are fully eligible (p20 = 1, no gates, radius 200); only the two item-class
entities are inactive, which is the TASK 15/16 item finding again.

## 4. Walking on foot — the harness fix and what it does (OBSERVED)

`tests/play_forward.py`'s `Walker` now aims with the **live camera yaw** the mod publishes (`cam` →
`g_cam_yaw`, taken from the D3D view matrix) instead of a basis measured once:

    world angle = up_world + (yaw_now - yaw_at_calibration) + sign * atan2(lx, ly)

`up_world` and `sign` come from two short measured presses (up and right; the opposite press is the
fallback when a wall blocks one), the old measured basis stays as the fallback when the mod has no valid
camera yaw, `walk_to()` holds the stick without releasing it and re-aims ~6 times a second while counting
the units it walked, and a blocked path is handled like a player would (follow the wall on one side, back
out of a corner, re-aim). `try_door()` also measures a transition from the position *at the press* (it
used to compare against the walk's start, which made any 500-unit walk look like a transition).

Runs (all solo, all on foot — no teleport, no level tag requested):

| run | slot / level | units walked | outcome |
|---|---|---:|---|
| `run_pf1` | 10 / I007 | 8335 | reached the nearest door (1213 away) to 86 units |
| `run_pf2` | 10 / I007 | 11078 | reached the door to 82 units, pressed A (4x) — no transition |
| `run_pf3` | 10 / I007 | 11332 | stood **61 units** from the door (its radius 200), pressed A (4x) — no transition |
| `run_pf5` | 05 / G003 (game5.sav) | 2286 | the level's only exit is a `CToeLoadingZone` 2257 away and 167 units above the walkable roof; the walker got stuck on the roof edge, 1647 short |

So the walking half of the success criterion is met on I007 (8335–11332 units on foot, well over 1000),
but **no door transition happened**.

## 5. The door/save-point interaction does not fire in these loaded worlds (OBSERVED, cause UNKNOWN)

`tests/probe_door.py` (new) puts the character next to an eligible entity with the mod's safe `tp` and
samples `character+0x73c` — the entity the game's interaction scan selects — every 40 ms while pressing a
button:

Run `run_pd1` (slot 10 / I007, nearest `CToeDoor`, radius 200):

```
  door CToeDoor         id .... at (-2216.6, -1886.0, 0.0), 1213 away: p20 1 coll 0 gates (0, 0, 0) radius 200.0
  tp -> ok settled at (-2177.92, -1827.60, 0.08) after 0.8 s
  distance to the door: 70.0
  pressed A: +0x73c before 0x0, seen during the press [] ([]), after 0x0, pos (-2177.9, -1827.6, 0.1)
  pressed A: ...  pressed X: ...  pressed B: ...  pressed Y: ...      (all: +0x73c stays 0x0)
```

Run `run_pd2` (same slot, `CToeSavePoint`, radius 200, 70 units away in 2-D and 140 in 3-D):

```
  tp -> ok settled at (-1591.19, -863.29, -2.83) after 0.8 s
  pressed A: +0x73c before 0x0, seen during the press [] ([]), after 0x0, pos (-1591.2, -863.3, -2.8)
  mode before closing with B: 1 (1 = in game)
  mode after B: 1
```

Two different class families, both eligible by every field the scan checks and both well inside their
radius, are never selected and do nothing on any of the four action buttons. **In the pair flow on I100 an
A press does collect an item** (regression `run_reg1`, `pickup host->guest ... phase host->guest: OK`), so
the scan path itself works there. **UNKNOWN** which variable matters: the save-loaded world (this task's
subject), the level (I007/H000), or a solo copy with no peer. It is the same symptom TASK 16 recorded for
items ("character+0x73c stays 0") and it is worth its own task; it is not a pad or physics problem (the
pause test in §2.1 shows the buttons reach the game, and START still opens the pause menu).

Consequence for TASK 18's success criterion: the character **walks freely** (≥ 1000 units, measured) in
I007 and G003, but **cannot pass a door or loading zone** in these save-loaded worlds because the door
never becomes usable — so the "through a door" half is NOT met.

## 6. Regressions (verbatim results)

`sh tests/run_pair_menu.sh <abs>/chk18.dll check_party.py check_items.py check_hands.py check_hands_visible.py
check_entities.py check_movement.py check_pickup.py` (run `run_reg1`, menu flow, save 01 / I100):

```
party: host ['BOY1', 'GIR1'] guest ['BOY1', 'GIR1'] | inventory: host 44 guest 44
party OK
items: before host 44 guest 44
items: after host 45 guest 45
items OK
hands OK (2 characters checked)
hands visible state OK (2 characters checked)
entities OK (host 43, guest 43)
E: PASS [warn: BOY1 anim differs in 5/60 samples (transition samples)]
A: PASS
B: PASS
C: FAIL -- GIR1 copies differ: mean 12.70 max 64.76 (max 10.0/55.0) [warn: GIR1 anim differs in 5/60 samples (transition samples)]
D: FAIL -- GIR1 copies differ: mean 17.54 max 53.50 (max 10.0/55.0) [warn: BOY1 anim differs in 2/50 samples (transition samples); GIR1 anim differs in 4/50 samples (transition samples)]
...
phase host->guest: OK
guest live items: 0 (player 2 at (365.86, 61.18, 0.10))
NO live world item reachable on the guest: phase guest->host cannot run
results: [('host->guest', True), ('guest->host', None)]
pickup: some phases could not run (no live world item)
```

`sh tests/run_pair.sh <abs>/chk18.dll check_party.py check_items.py check_hands.py` (run `run_reg2`, old
flow, save 01):

```
party: host ['BOY1', 'GIR1'] guest ['BOY1', 'GIR1'] | inventory: host 44 guest 44
party OK
items: before host 44 guest 44
items: after host 45 guest 45
items OK
hands OK (2 characters checked)
```

Movement C and D fail with the known copy-difference flake (FINDINGS_13/14/15/16/17: `D: FAIL` in most
runs, mean 6.96–20.56; C has also failed before). The task says to report it, not chase it. Everything else
passes; the guest→host pickup phase still cannot run because only one live item exists in the slot
(unchanged from TASK 17).

## 7. DONE / NOT DONE / UNKNOWN

**DONE**

* **The "stops dead" is a test-harness artefact, with evidence.** The pad moves the character in all five
  save-loaded worlds tried (I007, J005, I100, H000, G003) at ~280–320 units/s; a "stop" reverses at once
  with the opposite stick (390–435 units) and is a wall; a held stick walks a circle because the stick is
  camera-relative and the camera follows.
* **The TASK 17 "0.0 units in 20 s" is the pause menu**, proved live (252 units → 0.0 with START →
  264.5 after closing), because `probe_control.py` pressed START before measuring.
* **The mod is not involved**: `OBSCOOP_PASSIVE=1` (new switch) gives the same movement to within a few
  units per second.
* **The loaded level is not missing entities**: doors and the save point are `p20 = 1`, gates 0, radius
  200.
* **The walker is fixed** (camera-yaw aiming, ~6 re-aims/s, wall following, distance counted) and walks
  8335–11332 units on I007 and 2286 on G003 on foot; it reaches the level's nearest door.
* Both required regressions run and pass apart from the known movement C/D flake.

**NOT DONE**

* **No door / loading-zone transition on foot in slot 10 (I007) or slot 05/06 (G003).** In I007 the walker
  reaches the door but the door never becomes usable (§5); in G003 the only exit is a loading zone 2257
  units away at a different height and the walker got stuck on the roof edge. So the second half of the
  success criterion ("through at least one door/loading zone") is not met.
* The cause of the dead interaction (§5) is not identified: it affects doors and save points, is not the
  pad (START works) and not the entity fields; it needs its own task.

**UNKNOWN**

* Whether the interaction works in a *fresh game* (no save load) — that is the control this task did not
  have the process budget for (a new game was never started).
* Whether it works in a pair flow on the same save-loaded level (only I100 was ever exercised with a peer,
  and there the item pickup works).
* Why the party's second/third characters (`BOY2`, `GIR3` in I007) sit at `+0x2dc = 1900` far from the
  party — the same "record that is not in this level" pattern PARTY_FINDINGS described, not investigated
  here.
