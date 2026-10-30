# FINDINGS 47 — the owner's own character "barely moves" in run / aim-walk / aim-strafe: the LEVEL, not the mod

Base: HEAD = TASK 46 WIP commit. All live numbers below are from `chk47base.dll` = HEAD rebuilt (the 3
expected warnings only). Decompile: `decomp2/Obscure2.exe.c` (build 215294). Labels: OBSERVED / DERIVED.

## 0. Verdict (answer to the task's item 1)

**Geometry.** In the phases the check reported as FAIL the OWNER's own character consumed the stick and ran
its movement machine normally, but the spot it stood on had a wall / closed door in the walking direction:
the character does not move, and no field of the character says it is stuck. The same check drives nine
movement phases back to back from wherever the previous one ended; after walk / turn-left / walk-down the
character has travelled into the house at the north edge of I100 (`(-540.8, 433.5)`) and the next phase
(run, forward) walks into its wall. The `moved < 20 units` FAIL rows are the check's own "did this phase
prove anything" guard, not a sync defect: the clips agreed 100% in every FAIL row of the reviewer's log.

Not a mod bug, not a stuck state, and not a game rule of the aim stance:

| what the task asked to rule out | measurement (OBSERVED, run `run_diag1.log`) |
|---|---|
| the pad does not reach the game | `xread 0 -> 0 buttons 0000 lx 0 ly 24000` for the whole phase, `padshow ... vpad1 0,0,0,0 on 1` - the game gets `ly 24000` |
| the character is stuck (`state +0x2dc`, requested `+0x2e8`, speed `+0x278`) | at the start of every phase `state 0` (idle), `want 0`, `speed 0`; while the stick is held `state 1` (walk) / `2` (run) / `102` (aim), `speed 1143078912` = **648.0** (walk) and **1148829696** = 900.0 (run) - the game's own controller wrote the speed, so `+0x288` intent and `+0x278` speed are live |
| the game's aim-stance rule forbids walking | in the SAME aim stance at the same spot: aim-strafe moved **100.1** units and aim-run **100.1** units, aim-walk **0.0** |
| a wall (or nothing) | at `(-540.8, 433.5)`, no aim, plain walk: forward **0.0**, back **242.2**, left **76.0**, right **252.0** units - one direction blocked, three free |

The aim stance is not a no-walk rule in the decompile either: state 100 is handled by
`switchD_004e7f44_caseD_66` (decompile 142180..), which calls `FUN_004da7f0` (the displacement) and
`FUN_004da570` (the gait), i.e. the aim state has its own movement path; the gait the character gets
depends on the angle between the intent `+0x288` and the aim target `+0x750` (FUN_004da570, decompile
132929..132990).

## 1. The evidence in detail (OBSERVED)

### 1.1 The probe run (`$TMPDIR/diag47.py`, same phase sequence as check_anim_sync, `run_diag1.log`)

Owner = the host's own BOY1. `pos` = `+0x23c`, `int` = intent `+0x288`, `vel` = `+0x294`.

```
-- walk (host pad 0x0 lx 0 ly 24000)          start (-275.5, -40.2) st 0 want 0 sp 0
   t 0.1 st 1 want 0 sp 648 pos (-284.9, -34.3) int (+0.31, +0.95) | mode 1 req 0 w11c 1 w12c 0
   t 2.0 st 1 want 0 sp 648 pos (-215.3, 173.5) int (+0.39, +0.92)          moved 213.7
-- turn-left                                moved 243.2
-- walk-down                                moved 116.5
-- run (ly 32767)                             moved 339.8   (state 2 while running)
-- aim   (LB, no stick)  start (-540.8, 433.5)  moved   0.0  (not judged: no stick)
-- aim-walk (LB + ly 24000)  st 102 sp 648, pos (-540.8, 433.5) unchanged for 2 s   moved   0.0
-- aim-strafe (LB + lx -24000)                                      moved 100.1
-- aim-run  (LB + ly 32767)   pos (-580.7, 333.4) -> (-540.8, 433.5)  moved 100.1
-- still-walk (no aim, ly 24000)  at (-540.8, 433.5)                 moved   0.0
-- still-back                                                        moved 242.2
-- still-left                                                        moved  76.0
-- still-right                                                       moved 252.0
```

The world was in normal play the whole time (`mode 1 req 0 w11c 1 w12c 0` on every sample), so this is not
the scripted-event case check_controls' `normal()` waits for.

### 1.2 The pictures (OWNER's window, PrintWindow, start of each phase)

`shots47/aim-walk_before.png` (2560x1440, PrintWindow 1, 31 % lit) and `shots47/run_hold.png` (26 % lit):
the character stands INSIDE a dark room, in front of an interior wall/door frame, with the aim HUD (100/2)
visible in the aim phase. The rooms' brightness (26-33 %) is the inside of a house; the phases that moved
freely (still-back / still-right) are 67-72 % (outside). So the 0-unit phases are the character facing a
closed door / wall indoors.

### 1.3 Why the reviewer's FAIL rows are the same thing

The reviewer's log rows and this run's rows disagree on the SAME phases with the SAME pads:

```
reviewer (s46 soak):  run 6.3 | aim-walk 0.0 | aim-strafe 19.6 | aim-run 283.7
this probe:           run 339.8 | aim-walk 0.0 | aim-strafe 100.1 | aim-run 100.1
```

Only the starting position differs. On HEAD the same check can also pass all of them (the run right after
this probe: `aim-walk 22.8, aim-strafe 293.1 PASS`, `run ... 739.3` - same code, different spot).

## 2. The fix (task item 2, geometry branch)

`tests/check_anim_sync.py`: every movement phase now starts on the character's OWN known open spot, placed
with the mod's safe `tp` under the owner's teleport rule (`tests/tp_to_items.py` `scan_room` +
`room_verdict`: at least one live item, no enemy, no spawner within 400 units - the soak's rule), and if the
owner still does not move in the phase's direction the phase is replayed ONCE from the spot with the stick
reversed (walking away from the wall), printing which direction was free. The verdict is unchanged
(UP_OK / LO_OK / ADV_OK / `moved >= 20`); no threshold was relaxed.

`tests/check_controls.py`: same family - it drives a pad for 1.3 s and requires 20 units, and the reviewer's
run passed the host phase with **23.9** units at the same blocked spot `(-540.9, 433.3)` (check_visible's
line in that log). It gets the same open-spot placement, and its second attempt (which already re-drove the
pad after 25 s of waiting) now drives the OTHER way.

## 3. The runs (verbatim, `chk47base.dll` = HEAD sources rebuilt)

### 3.1 run_pair_menu (steam profile), first fixed build - PASS

```
open spot of BOY1 (host copy, its player 1): (-275.5, -40.2, 0.1) - ... | safe tp: ok settled at (-275.51, -40.17, 0.10) after 0.8 s
run        upper clip 100%  lower clip 100%  ...  clips seen yes  owner moved  338.4 units  PASS
aim-walk   upper clip 100%  lower clip 100%  ...  clips seen yes  owner moved  292.2 units  PASS
aim-strafe upper clip 100%  lower clip 100%  ...  clips seen yes  owner moved  232.9 units  PASS
aim-run    upper clip 100%  lower clip 100%  ...  clips seen yes  owner moved  295.9 units  PASS
anim-sync OK (what is played, not the state id)
   host copy moved: player 1 213.3, player 2 0.0 units | guest copy: player 1 213.3, player 2 0.0 units
   host: PASS (own character moved on both copies, the other did not)
   host copy moved: player 1 0.0, player 2 331.6 units | guest copy: player 1 0.0, player 2 331.6 units
   guest: PASS (own character moved on both copies, the other did not)
controls OK (each pad drives its own character on both copies)
```
(the reviewer's run of this check gave `run ... 6.3 units FAIL`, `aim-walk ... 0.0 units FAIL`)

### 3.2 run_pair_menu (steam profile), second run - anim-sync PASS, check_controls exposed the same geometry

```
aim-walk   ...  owner moved  291.1 units  PASS
aim-strafe ...  owner moved  226.2 units  PASS
anim-sync OK (what is played, not the state id)
open spot of guest player 2: (-520.8, -79.0, 0.1) - ... | safe tp: ok settled at (-520.82, -79.00, 0.10) after 0.8 s
   host copy moved: player 1 0.0, player 2 0.8 units | guest copy: player 1 0.0, player 2 0.8 units
   guest: FAIL (own character moved on both copies, the other did not)          [twice, both attempts]
controls FAIL (PASS, FAIL)
```
The guest's character stood at a spot where "forward" is walled (0.8 units both times, pad `ly 30000`), the
same thing as the task's FAIL rows. A "known open spot" cannot promise room in the *camera-relative* forward
direction, so check_controls' second attempt now drives with the stick reversed (as check_anim_sync's
phases already did). Both soaks below run the fixed check_controls and pass.

### 3.3 The soaks (final checks) - PASS

```
walk       ...  owner moved  268.9 units  PASS          (steam)
aim-walk   ...  owner moved  290.1 units  PASS
aim-strafe ...  owner moved  225.9 units  PASS
aim-run    ...  owner moved  293.4 units  PASS
anim-sync OK (what is played, not the state id)
controls OK (each pad drives its own character on both copies)
soak OK (30 location changes, both copies alive)
  host: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
  guest: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
=== soak run: PASS
```
The same lines appear in the plain-loopback soak (`soak_plain.log`): `anim-sync OK`, `controls OK`,
`soak OK (30 location changes, both copies alive)`, `=== soak run: PASS`.

Not tested live / not reachable: the open-spot *item fallback* (nearest live item) never triggered - save 01
in I100 has no live collectable item near either spawn, so `open_spot` accepted the character's own spot
(the item part of the owner's rule is for loot rooms, see the comment in tests/tp_to_items.py). Levels with
live items would take the fallback path; every phase would then start on an item spot instead. Same code
path, not tested live.

