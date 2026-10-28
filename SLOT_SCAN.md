# SLOT_SCAN — every save slot of the host test copy, one game launch, read-only

Part A of TASK 15. Tool: `tests/scan_slots.py` (new, read-only), runner `tests/run_scan_slots.sh`
(one host copy on `local\obscure2-test`, started and stopped by the runner; **one** game launch loaded
all ten slots one after another with the game's own menu-load path `loadsave gameN.sav`, waiting for the
level tag to change and then 10 s of settle time before each scan).

## Data model used (OBSERVED live, this run)

* `world+0x1768` = `CToeManager`. The **level entity list** is `mgr+8` (node `{entity at +0, next at +4}`,
  count at `mgr+0x14`); the count matched the walked list in every slot (`+0x0` is a 1-node list,
  `mgr+0x18` is a different list that holds 14–45 entities — the inventory-derived objects, e.g.
  `CToeItemMap id ME0A` — and is NOT the level list). `FUN_00587780` (the accessor `FUN_0045f540` uses)
  walks exactly `mgr+8`/count `mgr+0x14`, which confirms this.
* Entity fields: class tag `+0x10`, id `+4`, collected `+0xa8`, active/world gate `+0x20` (base entity
  init `FUN_004020d0` sets it to 1), position `+0x6c/+0x70/+0x74`, interaction gates `+0xc0/+0xac/+0xb0`,
  radius `+0xa0`, mesh `+0x34`.
* Item-class entities are recognised by the 26 tags of the `CToeItem*` constructors (ITEMS_FINDINGS §1).
  The **class name** is read from the object's vtable RTTI (vtable−4 → COL → +0xc TypeDescriptor → name
  inline at +8), which is how doors / breakables / enemies are classified below.
* NPCs/enemies: `world+0x1760` (count +4, array +0xc), each object tagged by RTTI (`CCharacterNPC*`).
* "Live collectable" = item class, `+0xa8 == 0`, `+0x20 != 0`, gates `+0xc0/+0xac/+0xb0` all 0, and a
  sane position. The game's own interaction check `FUN_0044d6a0` / `FUN_00450770` requires exactly these
  (`+0x20 != 0`, `+0xa8 == 0`, `+0xc0/+0xac/+0xb0 == 0`, distance ≤ `+0xa0`).

## Table (one row per slot; all ten loaded, world up in every one)

| slot | file | level | entities | item-class entities | live collectable | enemies/NPCs (RTTI) | humans | player 1 position |
|---|---|---|---:|---:|---:|---|---|---|
| 01 | game0.sav | I100 | 30 | 1 (`ENDR` CToeItemEnergyDrink) | **0** | 2: CCharacterNPCAura, CCharacterNPCHomm | 2 (BOY1, GIR1) | (−275.5, −40.2, 0.1) |
| 02 | game1.sav | I015 | 37 | 2 (`MEDI` ×2 CToeItemMedikit) | **0** | 1: CCharacterNPCAura | 2 (BOY1, BOY2) | (−1448.0, −355.4, 29.0) |
| 03 | game2.sav | D003 | 27 | 0 (`MEDA` CToeItemMedallion, collected=1) | **0** | 3: CCharacterNPCAura, CCharacterNPCRam ×2 | 2 (BOY1, GIR1) | (8873.6, 13392.5, −246.7) |
| 04 | game3.sav | J002 | 40 | 0 | **0** | 1: CCharacterNPCAura | 2 (BOY1, GIR1) | (296.4, 757.3, −7.0) |
| 05 | game4.sav | J005 | 22 | 2 (`MEDI` ×2) | **0** | 1: CCharacterNPCAura | 2 (BOY1, GIR1) | (1768.2, −5586.4, 0.1) |
| 06 | game5.sav | G003 | 47 | 1 (`ENDR`) | **0** | 2: CCharacterNPCAura, CCharacterNPCTeacher (`PROF`) | 2 (BOY2, GIR1) | (2799.7, 1548.8, 321.9) |
| 07 | game6.sav | H000 | 44 | 0 | **0** | 4: CCharacterNPCAura, CCharacterNPC ×2, CCharacterNPCHomm | 2 (BOY3, GIR3) | (−2523.2, 386.4, 37.3) |
| 08 | game7.sav | H006 | 39 | 2 (`MEDI` ×2) | **0** | 1: CCharacterNPCAura | 2 (BOY1, GIR3) | (−448.4, 440.5, 2.6) |
| 09 | game8.sav | I004 | 14 | 1 (`ENDR`) | **0** | 1: CCharacterNPCAura | 2 (BOY1, GIR1) | (671.2, 182.7, 0.7) |
| 10 | game9.sav | I007 | 49 | 0 | **0** | 2: CCharacterNPCAura, CCharacterNPCMisc (`PROF`) | 4 (BOY1, BOY2, GIR1, GIR3) | (−1547.3, −874.7, −7.7) |

Doors / destructibles seen in the level list (RTTI-classified, count per slot):

| slot | doors | breakables / containers | other emphases |
|---|---|---|---|
| 01 | CToeDoor ×2 | — (CToeLoot ×1) | chairs ×7 |
| 02 | CToeDoor ×1 | **CToeBreakableCase ×1**, CToeLockPick ×1, CToeLoot 0 | path helpers ×10 |
| 03 | — | CToeBoxNPC ×1, CToeLoot ×2 | camera move-around, light cone |
| 04 | CToeDoubleDoor ×2, CToeDiscLock ×1 | CToeChestKey ×2, CToeDisc ×3 | story room (chairs ×11) |
| 05 | CToeDoubleDoor ×1 | CToeRecharge ×1 | park |
| 06 | — | **CToeBreakableTwoStates ×1**, CToeWater ×1 | teacher NPC |
| 07 | CToeDoor ×2 | **CToeBreakableCase ×1**, **CToeHeavyCase ×1**, CToeLoot ×3, CToeLockPick ×1 | respawners ×2 |
| 08 | CToeDoor ×1 | — | pedestals ×3 |
| 09 | CToeDoor ×1 | — | mirror, interactive help |
| 10 | CToeDoor ×2, CToeDoubleDoor ×3 | **CToeBreakableCase ×1**, CToeChain ×1, CToeChestKey ×1, CToeRecharge ×1 | physics ×6 |

## What the scan shows (OBSERVED)

1. **No slot contains a live collectable world item.** Every item-class entity found is either a
   carried/inventory object (also present in the 44-entry inventory of slot 01 and in the
   inventory-derived `mgr+0x18` list) with `+0x20 == 0`, or (D003) a medallion already `+0xa8 == 1`.
2. The item entities that do exist keep `+0xa8 == 0` but `+0x20 == 0`, so the game's own interaction
   check `FUN_0044d6a0` refuses them: they cannot be picked up even if the player stands on them.
3. Their positions are often still 0 or garbage during the first seconds after a load; the energy drink
   in I100 got a real position (−570.8, −248.7, 0.6) only after ~8 s in a separate probe. That is a
   *timing* effect of the level build, not a different item.
4. The level entity lists are small (14–49) and consist of markers and fixtures (`CToeCharacterPos`,
   `CToeZoneHelp`, `CToeAddictiveCenter`, `CToeIris`, `CToeStepSound`, chairs, doors, save points,
   loading zones, a few `CToeLoot`/`CToeBreakable*`/`CToeItem*`). The level's full prop and loot set is
   not present right after a save load.
5. **The character does not move when the pad is pressed in this solo host run** (LEFT for 3 s, player 1
   position unchanged, probe 1 and probe 2). The same pad press moves the character in the pair runs
   (check_movement). The likely reason is that a save-loaded world runs its level intro/script before
   the player regains control; UNKNOWN which exact state blocks it.

## What would activate items (DERIVED, next task)

* Items are not part of the level's static object list in these saves: they appear as `CToeItem*`
  entities only when something creates them. The level objects that can create items are present:
  `CToeLoot` (slot 01, 03, 07), `CToeBreakableCase/TwoStates` (02, 07, 10), `CToeHeavyCase` (07),
  `CToeChestKey`/`CToeDiscLock` (04, 10), `CToeContainer`-like cases. Searching/breaking one of those
  would spawn a real item; that needs the level to be *running* and the player to reach and use it.
* The most promising slots for that are 02 (I015: breakable case + lockpick + 2 medikits), 07 (H000:
  breakable case + heavy case + 3 loot + 2 medikits + 2 respawners) and 10 (I007: breakable case +
  chest key + 3 double doors).
* The blocker to test next: find why the save-loaded world does not accept player input
  (character+0x73c is never set even standing on a door or at an item's position, and LEFT does not
  move the character), i.e. which game state (intro/cutscene/pause) has to be cleared after `loadsave`.

## Raw scan output

`scan_all2.log` (this worktree's session scratch): one full block per slot with every entity, the
class-tag histogram and both players; the table above is derived from it. The first, shorter scan
(`scan_all.log`) shows the same picture with positions read too early.

## TASK 17 Part C - forward play through the game's own doors (host copy)

Tool: `tests/play_forward.py`. It walks the character with the pad (no teleport and no requested level tag)
to the level's own doors / loading zones, presses A, waits for the transition the game performs, then
scans the new room with the same reads as `scan_slots.py` and appends it here. "A room" is one level load;
the counts are over the level's whole entity list (live items = `CToeItem*` with `+0x20 != 0`, `+0xa8 == 0`,
gates 0; enemies = `CCharacter*` with life > 0; spawners = `CToeRespawn*`).

| run | save slot | room | level | entities | live items | enemies | spawners | player 1 | outcome |
|---|---|---:|---|---:|---:|---:|---:|---|---|
| `run_a3` | 06 (game6.sav) | start | H000 | 48 | 0 | 2 (`CCharacterNPC` x2) | 2 (`CToeRespawner` x2) | (-2523.1, 386.4, 37.3) | walk blocked at (3531.2, -462.6, 17.3); no transition |
| `run_ac1` | 10 (game9.sav) | start | I007 | 49 | 0 | 1 (`CCharacterNPCMisc`) | 0 | (-1547.3, -874.7, -7.7) | walked ~250 units, then stopped; nearest of 5 doors still 902 away; no transition |
| `run_g1` | 05 (game5.sav) | start | G003 | 47 | 1 (only after `check_gate.py` set `+0x20 = 1`; 0 as the save has it) | 1 (`CCharacterNPCTeacher`, 1197 away) | 0 | (2799.7, 1548.8, 321.8) | walked 177 units, then stopped; loading zone still 2309 away; no transition |
| `run_reg1` | 01 (game0.sav), pair flow | start | I100 | 30 | 0 (`CToeLoot` has `+0x20 = 0`) | 0 | 0 | (-570.8, -248.7, 0.1) | pad moved the character 0.0 units in every direction |

No second room was reached in any run, so no door/loading zone transition happened and no save was made
(the save step only runs in a room with a live item and no enemy).

Why (OBSERVED, `tests/probe_control.py` on H000): the game's own menu buttons (A, A, START, B, BACK, A)
do not change anything, the four 1-second stick presses move the character 0.0 units each, and 20 s of a
held stick moves it 0.0 units. In I007 and G003 the character walks a few hundred units after the load and
then stops dead. That is the same missing-collision picture FINDINGS_16 section 7 describes.

## TASK 18 correction to section "What the scan shows" 5 and to the Part C conclusions

Section 5 above ("the character does not move when the pad is pressed in this solo host run ... LEFT for
3 s, player 1 position unchanged") and the Part C paragraph ("walks a few hundred units and then stops
dead ... the same missing-collision picture") are **superseded**. `tests/probe_move.py` measured the same
worlds and the pad works in every one of them (TASK 18, FINDINGS_18.md §1-§2):

* 1 s presses move the character 10-322 units in every save slot tried (I007, J005, I100, H000, G003), and
  a held stick walks at ~280-320 units/s.
* where the character "stopped dead" the reverse stick moves it 390-435 units at once: it had walked into a
  wall, not lost its input.
* holding one stick walks a **circle** (the stick is camera-relative and the camera follows the character),
  so a short fixed-duration sample can end near the start position - which is what "LEFT for 3 s,
  position unchanged" recorded.
* the "0.0 units in 20 s" of `probe_control.py` is the **pause menu**: that probe presses START before it
  measures, and a paused game ignores the pad (0.0 units with the menu open, 264.5 units again once it is
  closed, same world, same pad).

The walker used for Part C was fixed accordingly (`tests/play_forward.py`: aim with the live camera yaw and
re-aim ~6 times a second); it then walked 8335-11332 units on I007 and reached the level's nearest door.
What remains open is the door interaction itself: a `CToeDoor` that is eligible for the game's interaction
scan (p20 = 1, gates 0, radius 200) is never selected at 61-70 units and does not open on A (FINDINGS_18
§5).
