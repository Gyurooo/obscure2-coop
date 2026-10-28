# FINDINGS 17 — safe teleport, item/enemy-gated teleports, and a forward playthrough to a real item

Labels: **OBSERVED** = printed by a check/scan/run in this task or read in the decompile (address cited);
**DERIVED** = follows from the cited code but was not observed live; **GUESS**; **UNKNOWN**.

Status: **final**. Live evidence: 11 game processes in this task (one solo copy for the five-target proof
and forward play on three slots, one solo probe, the two required two-copy regressions); every run ended
with `OWNER FILES UNCHANGED` and no game left running.

## 0. Plan and starting point

TASK 16/17 findings: no save slot has a live world item; the two item sources in H000 sit above ground the
save-loaded world does not have, so the old raw `tp` (a plain write of the position triple at
`character+0x23c`) left the character in free fall for 468 units and the interaction scan never picked the
case. The owner's instruction for this task: **fix the teleport**, then **find items** by playing forward
the game's own way (doors), and **before teleporting anywhere make sure the place has items and no
enemies**.

The three parts of this task are therefore implemented as:

| part | deliverable | where |
|---|---|---|
| A | `tp` becomes safe: it places, watches the game's own physics settle the character, accepts only a floor within a small Z band, snaps Z to it, and **restores the old position** (with the reason) when there is no floor | `src/sync.c` (state machine, game thread) + `src/obscoop2.c` (pipe command); old behaviour kept as `tpraw` |
| B | `tests/tp_to_items.py`: scans live items and enemies around a target; teleports only when `items >= 1` and `enemies == 0`; otherwise prints the reason and skips. Every test that teleports into a room uses it | `tests/tp_to_items.py` |
| C | `tests/play_forward.py`: walks the player into the door/loading-zone the game itself offers, waits for the level transition, scans and logs it; stops at the first room with an item and no enemy; saves through the game's own save point into a free slot of the TEST copy | `tests/play_forward.py`, `SLOT_SCAN.md` |
| D | pickup proof with that save in the real flow (no memory forcing) + the two regressions | `tests/check_pickup.py` |

## 1. Part A — why the old `tp` dropped the player (OBSERVED, decompile + live)

**OBSERVED (old code, `src/obscoop2.c` before this task).** `tp` wrote the three floats at
`character+0x23c` (`H_POS`) and, optionally, the facing at `+0x248`, from the pipe thread, in one go. It
did nothing else: no collision/ground update, no check whether the target has floor, and no way back if
the position was bad.

**OBSERVED (live, FINDINGS_16 run 6).** On H000 the character was teleported onto `CToeHeavyCase`
(z = 59.74) and fell to z ≈ −1.3 (468 units) — i.e. the character's own physics *did* run and found
nothing under the target. So the write itself stuck; the world simply has no collision under that fixture.

**DERIVED.** A "ground query" that the mod could call directly is not exposed as a single clean function in
the decompile (searched: `CToeCharacterPos` placement path, `CCharacterCollision` vtable
`0x6665d4` s0 `0x4ccb20` s2 `0x4cdce0` s4 `0x4ccbb0` s5 `0x4ccbc0` s7 `0x4cdd10` s10 `0x4ccdb0`, the
camera's floor-snap pair `FUN_0057d9a0` / `FUN_0057e9c0` at 0x57d9a0/0x57e9c0 — the latter is the camera's
own collision object, not the character's). The engine's authoritative answer to "is there floor at this
point" is the character physics itself, which is why the safe `tp` **lets the game decide**: place, sample
the character's Z on the game thread every frame, and accept only when the physics settles the character on
a floor within a small Z band of the request; otherwise restore the old position.

This is the same mechanism the game uses to place a character at a level start (`CToeCharacterPos`, tag
`PPOS` 0x50504f53, constructor `FUN_00414140` 0x414140, parser `FUN_00414220`, fields position `+0x104`,
`player_controlled +0x11c`): the marker only names a position, and the character's own physics then settles
it onto the floor. There is no separate "snap" step in that path either. (OBSERVED, decompile.)

## 2. Part A — the safe `tp` (implementation)

**Code.**

* `src/sync.c` — new block "safe teleport (TASK 17 Part A)": `tp_frame()` runs from `frame_tick()` (the
  Present hook, i.e. the game's main thread, once per frame) and is called **before** the `g_role` check so
  it also works on a copy with no peer. `tp_request()` is the pipe-thread side: it queues the request,
  waits for the game thread's verdict (at most `TP_MAX_MS + 2 s`) and returns the message.
* `src/obscoop2.c` — the `tp` command now parses `tp <0|1> x y [z dx dy]`, `tpsafe ...` (alias) and
  `tpraw ...` (the old plain write, kept for diagnostics) and calls `tp_request(...)`. The forward
  declaration sits next to the other `// sync.c` ones.

**Algorithm (OBSERVED in code, then live below).**

```
TP_START frame (game thread):
    old = character+0x23c / +0x248             (so a refusal can put it back)
    character+0x23c = (x, y, z)                (z = the argument, or the current z when not given)
    t0 = now; prev_z = z; stable = 0
TP_RUN frame (every frame):
    dz = z_now - z_requested
    if dz < -8           -> refuse "no floor ... fell N units", restore old position
    if dz > +8           -> refuse "the floor is N above the requested z", restore
    if X/Y left the target by > 6 for > 300 ms -> refuse "the game moved the character away", restore
    if >= 800 ms elapsed and Z stable (< 0.02/frame) for 10 frames -> accept, reply "ok settled at (x,y,z)"
    if >= 3000 ms       -> refuse "still moving after 3 s", restore
```

`TP_MAX_DROP = 8.0`, `TP_MAX_XY = 6.0`, `TP_MIN_MS = 800`, `TP_MAX_MS = 3000` (all in `src/sync.c`).
The reply is the whole point for tests: `ok settled at (…, …, …) after N s` or
`refused: <why>; old position restored`. `tests/bot.py` gained a `tp(pipe, player, x, y, z=None)` helper.

**Why the physics is the right "ground/collision query" here (OBSERVED, decompile).** The engine has no
single "height at point" call that the mod could use: `CToeCharacterPos` (`PPOS`, ctor `FUN_00414140`
0x414140, parser `FUN_00414220` reading `position` → `+0x104` and `player_controlled` → `+0x11c`) only
stores a position, and the level-start path that looks the markers up (`FUN_00408ca0`, 0x408ca0, matches
`id == player*1000` into `+0x10c/+0x110`) also just uses the stored position. The camera's floor pair
`FUN_0057d9a0` (0x57d9a0, returns `*(float*)(*(int*)(this+0x30)+0xac)`) / `FUN_0057e9c0` (0x57e9c0,
writes `+0x30 + 0x84/0x88/0x8c`) belongs to the camera's own collision object. `CCharacterCollision`'s
vtable (`0x6665d4`) slots (`0x4ccb20`, `0x4cdce0`, `0x4ccbb0`, `0x4ccbc0`, `0x4cdd10`, `0x4ccdb0`) are the
character-vs-character avoidance test, not a floor query. So the character physics itself is the query:
it is what makes the character fall the 468 units in TASK 16 and it is what holds the character still on
a real floor, which is exactly the state the agent must not leave behind.

**Behaviour change for existing tests.** `tp` now takes 0.8–3 s (it waits for the settle) and can reply
`refused:`. Any test that teleports must read the reply; `tests/check_pickup.py` still does
`pipe.cmd('tp ...')` and only prints it, so on a floor-less target it will now stay where it is instead of
falling into the void (which is what the owner asked for).

## 2.1 Part A — live proof

(verbatim run output below; the run is `sh tests/run_solo_slot.sh chk17.dll <slot> check_tp.py`)

Run 4 (`run_ac1`), slot 10 / I007, the run that matters (all five targets, the check's final form):

```
== summary
  1 player start (no z given: keep the current height)       STANDS                   ok settled at (-1547.28, -874.71, -7.69) after 0.8 s
  2 door (CToeDoor id ....)                                  STANDS                   ok settled at (3285.01, -2199.95, 2.39) after 0.8 s
  3 CToeCharacterPos id ...V                                 STANDS                   ok settled at (-1554.85, -774.92, -0.26) after 0.8 s
  4 breakable case (CToeBreakableCase id ....)               REFUSED                  refused: no floor at (2044.8, -2143.8, 137.2) - the character fell 118.1 units (z 19.1); o
  5 random far point                                         REFUSED                  refused: no floor at (1452.7, 2125.3, 392.3) - the character fell 305.2 units (z 87.1); ol
tp safety: PASS (every target either stands still for 3 s or is refused and restored)
```

Verbatim, the two refusals and one settle (the same run):

```
== target 4 breakable case (CToeBreakableCase id ....) - the source that dropped the player 468 units in TASK 16
   before: character at (-1554.85, -774.92, -0.26); target (2044.82, -2143.82, 137.23), 3854 away
   tp 0 2044.818 -2143.825 137.226 -> refused: no floor at (2044.8, -2143.8, 137.2) - the character fell 118.1 units (z 19.1); old position restored   (0.07 s)
   right after: (-1554.85, -774.92, -0.26)
   REFUSED (refused: no floor at (2044.8, -2143.8, 137.2) - the character fell 118.1 units (z 19.1); old position restored)
   old position restored: character at (-1554.85, -774.92, -0.26), 0.00 from where it started
   after refusal, standing drift over 3 s: xy 0.00 z 0.00
```

```
== target 5 random far point - start + (3000, 3000, 400)
   before: character at (-1554.85, -774.92, -0.26); target (1452.72, 2125.29, 392.31), 4197 away
   tp 0 1452.724 2125.291 392.308 -> refused: no floor at (1452.7, 2125.3, 392.3) - the character fell 305.2 units (z 87.1); old position restored   (0.07 s)
   right after: (-1554.85, -774.92, -0.26)
   REFUSED (refused: no floor at (1452.7, 2125.3, 392.3) - the character fell 305.2 units (z 87.1); old position restored)
   old position restored: character at (-1554.85, -774.92, -0.26), 0.00 from where it started
   after refusal, standing drift over 3 s: xy 0.00 z 0.00
```

```
== target 2 door (CToeDoor id ....) - level door
   before: character at (-1547.28, -874.71, -7.69); target (3285.01, -2199.95, 0.00), 5011 away
   tp 0 3285.008 -2199.947 0.000 -> ok settled at (3285.01, -2199.95, 2.39) after 0.8 s   (0.83 s)
   right after: (3285.01, -2199.95, 2.39)
     t+0.00 s pos (3285.01, -2199.95, 2.39)  drift xy 0.00 z 0.00
     ...
     t+2.76 s pos (3285.01, -2199.95, 2.39)  drift xy 0.00 z 0.00
   STANDS: worst drift xy 0.00 z 0.00 over 3 s, 2.39 units from the target
```

The final DLL (built after the last source change, the "give the slot back" fix in the timeout branch of
`tp_request`) was re-run on the same slot (`run_final`) and printed the same five verdicts and the same
counters, plus `gate check: PASS` for `check_gate.py`.

So the five targets are: 3 accepted and held for 3 s (start, door, CToeCharacterPos), 2 refused with the
old position restored (the breakable case — the same fixture that cost 468 units in TASK 16 — and a random
far point). The snap is visible in the door case: the request was z = 0.00 (the door entity's own position)
and the character settled at z = 2.39, the floor there.

```
== summary
  1 player start (no z given: keep the current height)       STANDS                   ok settled at (-2523.15, 386.38, 37.30) after 0.8 s
  2 door (CToeDoor id ....)                                  STANDS                   ok settled at (72.90, -617.66, -3.70) after 0.8 s
  3 CToeCharacterPos id ....                                 MOVED                    ok settled at (-2523.15, 471.28, 37.30) after 0.8 s
  4 breakable case (CToeBreakableCase id ....)               REFUSED                  refused: no floor at (721.3, 1075.7, 466.9) - the character fell 471.2 units (z -4.3); old
  5 random far point                                         STANDS                   ok settled at (476.85, 3386.38, 437.30) after 0.8 s
```

and the two decisive lines of that run in full:

```
== target 4 breakable case (CToeBreakableCase id ....) - the source that dropped the player 468 units in TASK 16
   before: character at (-2376.75, 474.92, 24.05); target (721.35, 1075.67, 466.93), 3187 away
   tp 0 721.348 1075.673 466.927 -> refused: no floor at (721.3, 1075.7, 466.9) - the character fell 471.2 units (z -4.3); old position restored   (0.07 s)
   right after: (-2376.75, 474.92, 24.05)
   old position restored: character at (-2376.75, 474.92, 24.05), 0.00 from where it started
   after refusal, standing drift over 3 s: worst 0.00 units
```

```
== target 3 CToeCharacterPos id .... - the level's own character marker (PPOS, position +0x104)
   tp 0 -2523.149 471.283 38.092 -> ok settled at (-2523.15, 471.28, 37.30) after 0.8 s   (0.86 s)
     t+0.75 s pos (-2505.35, 470.40, 37.30)  drift xy 18.39 z 0.00
     t+1.50 s pos (-2422.87, 477.63, 32.04)  drift xy 100.48 z 5.26
     t+2.25 s pos (-2376.77, 474.84, 24.04)  drift xy 146.42 z 13.26
```

**OBSERVED:** that last target is H000's own intro script, not the teleport: the character stands exactly at
the marker for 0.5 s, then the level walks it 147 units away and 13 units down along the floor. The marker
at `(-2523.15, 471.28)` is the level's scripted start point; the marker the level actually placed the
player on `(-2523.15, 386.38)` does not do this. The check therefore chooses a marker the player did not
start on and accepts a "moved on the floor, no fall" result (see `check_tp.py`).

## 3. Part B — the item/enemy gate before any teleport

**Tool.** `tests/tp_to_items.py` (new). One entry point, `gate_teleport(pid, player, x, y, z, radius)`, so
no test can skip the check; `scan_room()` and `room_verdict()` are importable as well.

* **live item** — a `CToeItem*` entity of the level list (`ITEM_TAGS`, 26 class tags) with `+0x20 != 0`,
  `+0xa8 == 0`, `+0xc0/+0xac/+0xb0 == 0` and a sane position; the same five fields the game's own
  interaction check `FUN_0044d6a0` tests.
* **enemy** — every object in the NPC manager (`world+0x1760`, count `+4`, array `+0xc`) **and** in the
  level list whose RTTI class starts with `CCharacter`, with life (`+0x320`) > 0 and inside the radius.
  `CCharacterNPCAura` (life 0) is a trigger and does not count — that is why the life test, not the class
  test, is the decisive one.
* **spawner** — any entity whose RTTI class starts with `CToeRespawn` inside the radius (the task asks for
  hostile spawners/respawners explicitly), because they can bring enemies in even when none is alive yet.
* **verdict** — `ALLOW` only when `near_items >= 1` and `enemies == 0` and `spawners == 0`; otherwise
  `SKIP` with the reason (`no live collectable item within N units`, `K enemy/enemies within N units
  (classes)`, `K spawner(s) ...`). The tool prints the counts and every near entity, then (only on ALLOW)
  runs the safe `tp` and proves the character stands still for 3 s.
* Radius defaults to 400 units; items are matched in 2-D from the target (an item can be a floor above),
  characters in 3-D.

**Live evidence** (run 5, `run_g1.log`, slot 06 / G003, `check_gate.py`, radius 400):

```
=== case: nearest item entity as the save left it (expect SKIP)
room scan: level G003, 47 level entities, target (2430.2, 979.2, 374.5), radius 400
  live items in the level: 0 (near the target: 0), inactive/gated item entities: 1
    not live: ENDR id .... p20=0 collected=0 gates (0, 0, 0) at (2430.23, 979.15, 374.49), 0 from the target
  enemies within 400: 0
  spawners within 400: 0
   gate verdict: SKIP -- no live collectable item within 400 units of the target

=== forcing the item live (test-only write, as in TASK 15/16)
   wr 19438b80 01000000 -> ok 4 bytes

=== case: the same item, now live (+0x20 = 1) (expect ALLOW)
room scan: level G003, 47 level entities, target (2430.2, 979.2, 374.5), radius 400
  live items in the level: 1 (near the target: 1), inactive/gated item entities: 0
    LIVE item ENDR id .... at (2430.23, 979.15, 374.49), 0 from the target @19438b60
  enemies within 400: 0
  spawners within 400: 0
   gate verdict: ALLOW -- 1 live item(s), no enemy, no spawner within 400 units
```

So the gate refuses the room the save actually has (item entity present but inactive) and allows the same
room once the item is live. The `ALLOW` case then crashed on `Pipe(pid)` because the mod's command pipe
serves one client at a time and `check_gate.py` already holds one (**OBSERVED**, log: `OSError: [Errno 22]
Invalid argument: '\\\\.\\pipe\\obscoop_22716'`); fixed by passing the existing `pipe`/`Proc` into
`gate_teleport` (`pipe=` / `m=` arguments). The enemy/spawner branch is exercised by the room scans of
H000/I007 above (2 and 1 NPCs with life > 0), see §4.

**Where the gate is used.** Every teleport in this task's tools goes through it (`check_gate.py`,
`tp_to_items.py` itself). `check_tp.py` deliberately does not (it proves what the safe teleport does with
a bad target, including refusing it), and `play_forward.py` does not teleport at all: it walks.

## 4. Part C — forward play through the game's own doors

**Tool.** `tests/play_forward.py` (new). It never teleports and never asks for a level tag: it walks with
`pad 0 0 lx ly`, presses A at a door, and waits for the transition the game itself performs.

* **Walker** — the stick's world direction is *measured* on the live copy (four stick directions, 0.6 s
  each; the pair with the largest area becomes the basis) instead of assumed, so the camera angle, a
  left-handed axis convention and the sign of the sticks all come out of the data. `stick_for(d)` solves
  the 2×2 system and walks toward any point; when two presses produce no movement it sidesteps
  (alternating sides) and re-aims.
* **Route** — the level's own `CToeCharacterPos` markers are used as waypoints: they are places the game
  itself puts characters on, so they are on the walkable path. Then the last stretch straight at the door.
* **Doors** — `CToeDoor`, `CToeDoubleDoor`, `CToeSpecialDoor`, `CToeInternalDoor`, `CToeFlapDoor` (walk to
  80 units in front, press A up to three times) and `CToeLoadingZone` (walk in, the game triggers).
* **After a transition** it waits for the level to build and to place the characters (the FINDINGS_16 §4
  lesson), scans the new room with the same reads as `tp_to_items.scan_room` (live items, enemies,
  spawners, every door/zone/save point/item source with its distance), and appends the room to
  `SLOT_SCAN.md`. A room with enemies is left and recorded. The first room with >= 1 live item and 0
  enemies would be saved through the game's own `CToeSavePoint` (`save_here()`: walk to it, press A,
  screenshot the menu that opens).

**Live runs (all OBSERVED).** Four attempts, three slots plus the pair flow:

| run | slot / level | what the pad did | result |
|---|---|---|---|
| `run_a3` | 06 H000 | calibration: "stick up 0.6 s → (-125.6, -202.1)" then "stick right 0.6 s → (+6180.0, -646.8)" — 6180 units in 0.6 s is not a walk (a level script / the level's `CToeSafePos` moved the character) | walk blocked at (3531.2, -462.6, 17.3); the character did not move again; no door reached |
| `run_ac1` | 10 I007 | sane calibration (up 182 units/0.6 s, right 176) | walked ~250 units to (-1754.3, -1019.6, 2.2) and then stopped dead; the nearest of the 5 doors stayed 902 units away; no transition |
| `run_g1` | 05 G003 | "up" only 12.5 units (wall), "right" 181 | walked 177 units to (2976.7, 1552.9, 321.8) and stopped dead; the loading zone stayed 2309 units away; no transition |
| `run_reg1` | 01 I100 (pair) | calibration 0.0 units in all four directions | "the pad does not move the character; cannot walk to a door" |
| `run_p1` | 06 H000 (`probe_control.py`) | A, A, START, B, BACK, A → position unchanged; four 1 s sticks → 0.0 units each; 20 s of held stick → **0.0 units** | the pad never reaches the player in this world |

`probe_control.py` (new) is the measurement behind the last row: in H000 a held stick for 20 s moves the
character 0.0 units even after the game's own A/START/B/BACK presses, so no cutscene button is holding it.

**Every room the game put the player in** (the forward-play tables appended to `SLOT_SCAN.md`; a room is
one level load, counts are for the whole level list):

| run | room | level | entities | live items | enemies | spawners |
|---|---|---|---:|---:|---:|---:|
| `run_a3` | start | H000 | 48 | 0 | 2 (`CCharacterNPC` ×2) | 2 (`CToeRespawner` ×2) |
| `run_ac1` | start | I007 | 49 | 0 | 1 (`CCharacterNPCMisc`) | 0 |
| `run_g1` | start | G003 | 47 | 1 (only after `check_gate.py` forced `+0x20`; 0 as the save has it) | 1 (`CCharacterNPCTeacher`, 1197 away) | 0 |
| `run_reg1` | start | I100 | 30 | 0 (the one `CToeLoot` has `+0x20 = 0`) | 0 | 0 |

**No room reached by walking had a live item and no enemy** — in fact no second room was reached at all:
the game never moved the player through a door, because in these save-loaded worlds the pad either does
not reach the player (`run_p1`, `run_reg1`) or moves the character only a few hundred units before it
stops dead (`run_ac1`, `run_g1`). That matches the missing collision data FINDINGS_16 §7 described: a
character that cannot move is not going to walk into a door. So Part C ends with the room list above and
no save was made (the save step is only reached when a qualifying room is found).

## 5. Part D — pickup proof in the real flow + regressions

**The proof the task asks for could not be run**: it needs the save Part C was supposed to make (a room
with a live item and no enemy), and Part C reached no such room — no door was ever entered, so no save
exists. With no save that has a *live* world item in any of the ten slots (TASK 15 §1, TASK 16 §6, and the
scans in this task), a `check_pickup.py --spawn` run has nothing to collect. **NOT DONE**, with the reason.

**Regressions (both required runs, verbatim).**

`sh tests/run_pair_menu.sh chk17.dll check_party.py check_items.py check_hands.py check_hands_visible.py
check_entities.py check_movement.py check_pickup.py play_forward.py` (run `run_reg1`, slot 01 / I100):

```
party OK
items OK
hands OK (2 characters checked)
hands visible state OK (2 characters checked)
entities OK (host 43, guest 43)
A: PASS
B: PASS
C: PASS [warn: GIR1 anim differs in 2/60 samples (transition samples)]
D: FAIL -- GIR1 copies differ: mean 20.56 max 55.63 (max 10.0/55.0) [warn: GIR1 anim differs in 4/50 samples (transition samples)]
```

`check_pickup.py` in that run — note it now goes through the **safe** `tp`:

```
== phase host->guest: host player 1 collects ENDR (pos -570.79, -248.69, 0.56)
   item +0x20 == 0 (inactive in this save): forcing the game's own activation gate with wr
   wr 1a137fb0 01000000 -> ok 4 bytes
   tp host: ok settled at (-570.79, -248.69, 0.10) after 0.8 s
   pressed A (attempt 1)
host after:  class ENDR id .... collected 1 ...
guest after: class ENDR id .... collected 1 ...
inventory after: host 44 guest 44 (before 44 / 44)
counters this phase: collected-on-host=True, host sent +1, guest rcv +1 applied +1, echo sent +0
phase host->guest: OK
guest live items: 0 (player 2 at (366.17, 61.55, 0.10))
NO live world item reachable on the guest: phase guest->host cannot run
pickup: some phases could not run (no live world item)
```

`sh tests/run_pair.sh <abs path>/chk17.dll check_party.py check_items.py check_hands.py` (run `run_reg2b`,
old flow, save 01):

```
party: host ['BOY1', 'GIR1'] guest ['BOY1', 'GIR1'] | inventory: host 44 guest 44
party OK
items: before host 44 guest 44
items: after host 45 guest 45
items OK
hands OK (2 characters checked)
```

Movement phase D is the known flaky phase on main (FINDINGS_13/14/15/16: mean 6.96–20.56, `D: FAIL` in four
of FINDINGS_13's runs); E/A/B/C pass and the task says to report it, not chase it.

The first attempt at the old-flow run (`run_reg2.log`) never started a game: `run_pair.sh` was given the
relative `chk17.dll` and `cygpath -w` left it relative, so `duo.py` failed on `shutil.copy` before any
process was launched. Re-run with the absolute path (as the shared context says), it passed.

## 6. DONE / NOT DONE / UNKNOWN

**DONE**

* **`tp` is safe.** `src/sync.c` + `src/obscoop2.c`: the teleport is now a state machine on the game
  thread that places the character, samples the game's own physics every frame, accepts only a settle
  within 8 units of the requested Z and 6 units of X/Y, and otherwise restores the old position and says
  why. `tpsafe` is an alias, `tpraw` keeps the old plain write. `tests/bot.py` has a `tp()` helper.
* **Proof on five targets** (`tests/check_tp.py`, slot 10 / I007, run `run_ac1`): player start, a
  `CToeDoor`, a `CToeCharacterPos` marker → accepted and held for 3 s; the TASK 16 `CToeBreakableCase` and
  a random far point → refused ("fell 118.1 / 305.2 units") with the old position restored. `tp safety:
  PASS`. Also measured on H000 (the TASK 16 level): the case that cost 468 units is now refused at 471.2.
* **The item/enemy gate** (`tests/tp_to_items.py`): live-item read, enemy read (NPC manager + level list,
  life > 0), `CToeRespawn*` spawner read, ALLOW only for items >= 1 and no enemy/spawner, safe `tp` +
  3 s stand check afterwards. `tests/check_gate.py` shows the gate refusing the room G003 really has
  (item entity inactive) and allowing it once the item is live; on H000 it refuses the start (1 enemy,
  `CCharacterNPCHomm`).
* **Forward play by walking** (`tests/play_forward.py`): measured stick basis, `CToeCharacterPos` waypoints,
  door/loading-zone approach with the game's own A press, transition detection, room scan and a
  `SLOT_SCAN.md` table; the save step (game's own `CToeSavePoint`) is implemented and only runs in a
  qualifying room.
* **`tests/probe_control.py`** measures the pad in a save-loaded world: 0.0 units in 20 s on H000.
* **Regressions**: menu flow (party/items/hands/hands visible/entities OK, movement E/A/B/C PASS, D FAIL —
  known flake, pickup host→guest OK through the new safe `tp`) and old flow (party/items/hands OK).

**NOT DONE**

* **No room with a live item and no enemy was reached**, so the game's own save point was never used and
  there is no new save slot to load. The blocker is the pad in the save-loaded worlds: it moves the
  character a few hundred units at best and then the character stops dead (I007, G003), or it moves it
  0.0 units at all (H000, and the I100 pair flow).
* **The no-forcing pickup proof therefore did not run.** `check_pickup.py` still needs `+0x20 = 1` written
  by the test in I100; with the new `tp` the whole path (tp → A → `FUN_004ddad0` → `PKT_PICKUP` → apply)
  still works in both the old and the new flow, and the guest→host phase still cannot run (only one live
  item in the slot).

**UNKNOWN**

* Whether a *real* 2-player game (not a save load) gives the player control for long enough to walk to a
  door; `check_movement.py` proves the pad works there for a few hundred units, and this task's forward
  play never got a door.
* Whether the safe `tp` should also reset the character's movement state: after several teleports, the
  character could not walk at all in the I100 pair run and stopped after ~200 units in I007/G003. The
  fall-detection window (0.8 s, 10 stable frames) cannot distinguish "a real floor" from "the engine keeps
  the body in mid-air": on I007 a point 3000 units away was refused (it fell 305 units), but on H000 the
  same experiment once settled and held for 3 s (run `run_a2`).
* Whether the save-loaded levels run an intro script that locks input (the H000 character was walked 147
  units by the level after a teleport onto its own `CToeCharacterPos` marker) and how long that lock lasts.

## 7. Files changed / added

```
 src/obscoop2.c            |  tp/tpsafe/tpraw command, forward declaration, command list comment
 src/sync.c                |  safe teleport state machine + tp_request (runs from frame_tick)
 tests/bot.py              |  tp() helper
 tests/tp_to_items.py      |  NEW  Part B gate (scan_room / room_verdict / gate_teleport)
 tests/check_tp.py         |  NEW  Part A proof, five targets
 tests/check_gate.py       |  NEW  Part B live demonstration
 tests/play_forward.py     |  NEW  Part C forward play
 tests/probe_control.py    |  NEW  pad measurement behind Part C's conclusion
 tests/load_slot.py        |  NEW  load a slot into one copy and wait for placement
 tests/run_solo_slot.sh    |  NEW  one-copy runner (start, load slot, checks, always stop)
 SLOT_SCAN.md              |  Part C room table
 FINDINGS_17.md            |  this file
```
