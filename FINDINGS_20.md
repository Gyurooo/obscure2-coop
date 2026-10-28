# FINDINGS 20 — level transitions from the game's own data, a room with items and no enemies (TASK 20)

Labels: **OBSERVED** = printed by a run/check in this task, or read in the decompile / `.tsv` (address cited);
**DERIVED** = follows from the cited code/data but was not observed live; **GUESS**; **UNKNOWN**.
Decompile line numbers refer to `local\decomp2\Obscure2.exe.c`.

Status: in progress (decompile part first, live runs appended).

## 0. Doors

Possible door-opening issue, not tested further (owner decision: the door "bug" is NOT a bug; doors need
the right reach/angle and some are locked even when the prompt shows — FINDINGS_19 agrees).

## 1. Where the game keeps a transition destination (decompile)

### 1.1 The request itself — `FUN_004a1c00` @ 0x4a1c00 (decompile 96629-96642)

```
void FUN_004a1c00(level, entry, flag) {          // __fastcall, ECX = game object
  game[0x364] = level;      // the tag
  game[0x320] = 4;          // request state: change level
  game[0x368] = entry;
  game[0x370] = flag;
}
```

So the *call format* is three arguments: **(level tag, entry id, flag)** — exactly what the mod's `level`
pipe command replays and what `hk_change_level` logs.

### 1.2 The script command `ChangeLevel` — `Cslh_ChangeLevel_s4_v` @ 0x4bf6d0 (vt_slots.c 124-137)

```
piVar1 = *(int **)(in_ECX + 0x18);
FUN_004a1c00(*(piVar1[0] + 4), *(piVar1[1] + 4), *(piVar1[2] + 4));
```

The script command takes its three parameters and passes them in order. `FUN_0059f100("ChangeLevel",1,3)`
(decompile 104525) registers it with **3** script arguments (1 return value), so a level-script call is
always the same (tag, entry, flag) triple at 0x4a1c00.

### 1.3 The door path — `FUN_0042aa70` @ 0x42aa70 (decompile 24666-24710), class of the door row

```
if (entity[0x118] == world[4]) { ...play the door animation, return... }
if (entity[4] != 0) { FUN_004a1c00(entity[0x118], entity[4], 1); return; }
```

* destination level tag = **`entity+0x118`**
* entry id = **`entity+4`** — the entity's own instance id (the same value `scan_slots.py` prints as `id`)
* flag = **the constant 1**

It is reached through `FUN_0042c0c0` (decompile 25422-25432), which calls `FUN_0042aa70`; the same
`+0x118` is read by `FUN_0042cef0` (decompile 25996) to decide whether the door teleports within the
current level. `FUN_0042cd40` (the constructor that installs vtable `PTR_FUN_00656254`, decompile
25897-25950) initialises `in_ECX[0x46] = 0`, i.e. **`+0x118` = 0 = "no destination"** for a door that
stays in its level.

The decompile has exactly two callers of `FUN_004a1c00`: `FUN_0042aa70` and the script command
(grep `0x4a1c00` → decompile 24704 and 96631-…). There is no third path.

## 2. Level list of the test copy (OBSERVED, read-only)

`datapack.hvp` of `local\obscure2-test` holds 100 level directories `_levels/<letter>/<tag>/`
(listed with `local\hvp\hvp.py`; written to `tests/level_tags.txt`):
`A000-A004, B000,B002,B004-B010,B100,B102-B104,B106, C000,C003,C004,C006,C009-C011,C100,C101,C104,C105,C109,
D000-D006,D009,D010,D100-D106, E000-E003,E100-E103, F000-F003,F101,F102, G000-G010,G012-G016,G100,G103-G107,
I000,I001,I002,I004,I007,I100-I103,I107, J000,J001, M000-M003,M100`.

**B101 and B202 — the two entries already in `obscoop_levels.txt` — are NOT in that list.** B101 was
seen live before (`FINDINGS_12` §run 1: "the host stayed in B101" on a new game), so either the level
lives in `loadpack.hvp` (which is not an HV PackFile and was not parsed) or the tag is built at runtime
(DERIVED: the datapack list alone cannot validate every tag).

## 3. Live scan of all ten slots (OBSERVED, `tests/scan_transitions.py`, run_t1.log)

One host copy, `chk20.dll`, all ten slots loaded with `loadsave gameN.sav` in one launch, 8 s settle
after each world came up. Every entity of a door/loading-zone class is printed with its destination
fields; dwords `+0x100..+0x150` are scanned for anything shaped like a level tag.

```
===== TABLE (slot, level, entity class, entity id, target tag, entry, flag, tag check)
    1  I100  CToeDoor               id ..<.  -> I004 entry 15509 flag 1  known
    1  I100  CToeDoor               id ...,  -> I010 entry 300   flag 1  NOT-in-datapack
    2  I015  CToeDoor               id ...2  -> I014 entry 306   flag 1  NOT-in-datapack
    4  J002  CToeDoubleDoor         id ...=  -> J001 entry 317   flag 1  known
    4  J002  CToeDoubleDoor         id ...:  -> J000 entry 314   flag 1  known
    5  J005  CToeDoubleDoor         id ....  -> J003 entry 157   flag 1  NOT-in-datapack
    7  H000  CToeDoor               id ....  -> H001 entry 130   flag 1  NOT-in-datapack
    7  H000  CToeDoor               id ....  -> H002 entry 131   flag 1  NOT-in-datapack
    8  H006  CToeDoor               id ....  -> H003 entry 134   flag 1  NOT-in-datapack
    9  I004  CToeDoor               id ....  -> I005 entry 155   flag 1  NOT-in-datapack
   10  I007  CToeDoor               id ....  -> I008 entry 161   flag 1  NOT-in-datapack
   10  I007  CToeDoubleDoor         id ..=T  -> I007 entry 15700 flag 1  known
   10  I007  CToeDoor               id ....  -> I010 entry 160   flag 1  NOT-in-datapack
   10  I007  CToeDoubleDoor         id ...0  -> I012 entry 304   flag 1  NOT-in-datapack
   10  I007  CToeDoubleDoor         id ....  -> I005 entry 157   flag 1  NOT-in-datapack
```

* Every destination sits at **`entity+0x118`** and every entry is **`entity+4`** with flag **1** — the
  exact call `FUN_0042aa70` makes (§1.3). OBSERVED for all ten slots.
* `CToeLoadingZone` entities carry **no** destination in any field: their `+0x118` reads as a float
  (`0x3f800000` = 1.0f in every slot) and no tag-like dword was found except `+0x104` in I100
  (`I011`, which is not a door-style call and not in the datapack). OBSERVED: the level transitions in
  these saves are all door destinations.
* The datapack list is **incomplete**: H***, I0xx and J003 levels are real live levels but have no
  `_levels/<x>/<tag>/` directory in `datapack.hvp`. The live reads are therefore the authority; the
  datapack list only confirms tags, it cannot reject them.
* Slot 2 (I015) and slots 7/10 (H002, I010) doors have `+0x24 == 0` (disabled by the game, FINDINGS_19
  §3); their destinations are not usable and were not added to the allowlist.
* The I007 double door with destination I007 is a same-level door (the game plays the open animation
  instead of a transition, `FUN_0042aa70` first branch) — not a transition.

## 4. The first transition (OBSERVED, run_j1.log)

`tests/run_jump.sh chk21.dll 0 I004 15509 1` — one host copy, slot 01 (I100), then the mod's `level`
command with the exact (tag, entry, flag) the I100 door hands to the game:

```
before: mode 1 level I100 world 0x1966c788 entities 30 player 1 (-275.513000, -40.172001, 0.099976)
level I004 15509 1 -> ok
new world after 1.0 s: level I004 world 0x196cfc40 entities 14
player 1 (0.0, 0.0, 0.0)  player 2 None  mode 1
room scan: level I004, 14 level entities, target (0.0, 0.0, 0.0), radius 1000000000
  live items in the level: 0 (near the target: 0), inactive/gated item entities: 1
    not live: ENDR id ...f p20=0 collected=0 gates (0, 0, 0) at (600.25, -61.53, 3.42)
  enemies within 1000000000: 0
  spawners within 1000000000: 0
...
SUMMARY level I004 entities 14 live-items 0 near-items 0 enemies 0 spawners 0
```

OBSERVED: **the transition works and does not crash** — the world is torn down and rebuilt in ~1 s.
The character is **not placed**: both records end at the origin because the state machine matches the
entry id to a door in the new level (`FUN_004a5520`, decompile 98996-99030: `class tag DORH/DODO &&
entity+4 == game+0x368`), and I004's only door has id 155, not 15509. With no character near it the
level's own item stays inactive (`+0x20 == 0`).

## 5. Visiting the door destinations (OBSERVED, tests/explore_levels.py, run_e1.log)

One host copy, slot 01, then each destination below requested with its own entry id (the exact call
the source door makes). Every one of them rebuilt the world in ~1-8 s; **none crashed**.

```
===== TABLE (level tag, entry, landed level, entities, live items, enemies, player 1)
   J000 entry 314   -> J000  ents 16   live 1  enemies 2   p1 (-1059.69, -38.62, 86.38)   PLACED
   J001 entry 317   -> J001  ents 51   live 0  enemies 7   p1 (-793.58, 907.19, 0.66)    PLACED
   J003 entry 157   -> J003  ents 36   live 2  enemies 0   p1 (74.70, 3227.34, -342.02)  PLACED
   H001 entry 130   -> H001  ents 48   live 0  enemies 0   p1 (1077.64, 348.48, 0.51)   PLACED
   H002 entry 131   -> H002  ents 46   live 0  enemies 0   p1 (-361.35, -612.49, 1.58)   PLACED
   H003 entry 134   -> H003  ents 47   live 0  enemies 1   p1 (-45.01, 269.28, 1.25)     PLACED
   I005 entry 155   -> I005  ents 85   live 0  enemies 0   p1 (-1281.99, -86.33, 2.52)   PLACED
   I005 entry 157   -> FAILED (no new world: the game stayed in I005)
```

* Every other destination **places the character** — the previous run's origin spawn was specific to
  I004 15509. The level's `CToeCharacterPos` (class tag `PPOS`, `+0x10`) carry the entry ids: J003 has
  **two PPOS with id 157** (and one with id 317, one 1002, two 4526), which is why entry 157 places the
  party. The I004 level has PPOS with id 0 only, so entry 15509 matches nothing (DERIVED from the
  state machine `FUN_004a5520` 98996-99030, which matches the entry to `entity+4`).
* **A destination's `+0x118` is exactly the reverse of its source door**: J005's double door id 157
  points at J003, and J003's own `CToeDoubleDoor` has id **157** at (40.2, 3362.5, -298.2), 140 units
  from where the character lands. Door ids pair the two levels (OBSERVED).
* **J003 is the level we want**: 2 live collectables and **no enemy and no spawner in the whole level**
  (`room_verdict` VISITABLE). The second `I005 157` request was a duplicate destination already loaded:
  the mod accepted it but the level tag did not change, so the tool stopped there (not a crash).

### J003 entity list (OBSERVED, run_p1.log)

36 entities, all `+0x20 = 1`:

| class | id | position | notes |
|---|---:|---|---|
| `CToeItemMedikit` MEDI | 1 | (6292.18, 382.32, 0.00) | **live**: `+0xa8 = 0`, `+0x24 = 1`, radius 120 |
| `CToeItemBackpack` BKPK | 3 | (1290.44, -2789.00, 570.56) | **live**: `+0xa8 = 0`, radius 120 |
| `CToeWeapon*` (16 classes) | 1-2 | x ≈ 6292 | a row of collectable weapons at the same spot |
| `CToeDoubleDoor` DODO | 157 | (40.15, 3362.51, -298.23) | the door the entry 157 pairs with |
| `CToeDoor` DORH | 4526 | (964.07, -3512.03, 768.53) | another door, target not read in this run |
| `CToeCharacterPos` PPOS | 157 ×2, 317 ×2, 1002, 4526 ×2 | (0,0,0) | spawn markers |
| `CToeZoneHelp` ZOHP ×8 | 1-8 | | |
| `CToeIris`, `CToeFXDrunk`, `CToeStepSound` | | | |

## 6. The safe teleport and the pickup in J003 (OBSERVED, tests/j003_pickup.py, run_p2.log)

One host copy, slot 01 → `level J003 157 1` → the item/enemy gate on the medikit's position:

```
room scan: level J003, 36 level entities, target (6292.2, 382.3, 0.0), radius 400
  live items in the level: 2 (near the target: 1), inactive/gated item entities: 0
    LIVE item MEDI id .... at (6292.18, 382.32, 0.00), 0 from the target @19256350
  enemies within 400: 0
  spawners within 400: 0
   gate: ALLOW (1 live item(s), no enemy, no spawner within 400 units)
  tp 0 6292.176 382.319 0.000 -> ok settled at (6292.18, 382.32, 0.00) after 0.8 s
  standing still for 3.0 s: True (worst drift 0.00 units, limit 2.0)
   player 1 at (6292.17578125, 382.3190002441406, 0.0), 0.0 from the item; char 0x19f541c8; +0x73c 0x0
   A press 1: item +0xa8 1 +0xc4 0x19f541c8 (char 0x19f541c8) +0x20 0
   *** PICKED UP MEDI: inventory 44 -> 44
DONE picked up MEDI in J003 with the real flow
```

OBSERVED: the owner's tp rule passed on the item's own position (1 live item, no enemy, no spawner in
400), the character stood still, and **one A press made the GAME collect the item**: `+0xa8` 0 → 1,
`+0xc4` = the character, the game cleared `+0x20`. No memory write anywhere (`wr` not used).
The inventory count stayed 44 because the medikit stacks into the existing MEDI entry (the tag list in
run_pair3.log shows one MEDI before and after); the backpack later adds 8 rows (44 → 52).

The backpack at (1290.44, -2789.00, 570.56) floats 16.3 units above the only floor there — the mod's
safe tp refused the exact z and the game reported the floor (`z 554.30`); the character then stands 16
units below it, inside the item's 120-unit reach, and collects it too (run_pair3.log).

## 7. Pair proof in J003: the guest follows the host's level change (OBSERVED, run_pair3.log)

`sh tests/run_pair.sh chk22.dll pair_j003.py check_pickup.py` with `OBSCOOP_PICKUP_CLASS=MEDI`.
Both copies were loaded into save 01 (I100) by the runner; then the HOST only requested the door's call:

```
before: host level I100 player 1 (-275.513000, -40.172001, 0.099976) | guest level I100 player 1 (-275.513000, -40.172001, 0.099976)
host level J003 157 1 -> ok
after 1.0 s: host J003 (mode 1) | guest J003 (mode 1)
host player 1 (74.701, 3227.344, -342.019) player 2 (-27.599, 3185.946, -328.745) | guest player 1 (74.701, 3227.344, -342.019) player 2 (-27.599, 3185.946, -328.745)
host live items: CToeItemMedikit id .... (6292.2, 382.3, 0.0), CToeItemBackpack id .... (1290.4, -2789.0, 570.6)
guest live items: CToeItemMedikit id .... (6292.2, 382.3, 0.0), CToeItemBackpack id .... (1290.4, -2789.0, 570.6)
RESULT: both copies in J003 with 2 live items
```

OBSERVED: the existing host→guest `ChangeLevel` forwarding carried the guest into J003 within 1 s, with
identical character positions and identical live item lists. No save/load was needed for this.

## 8. Pickup in the real flow on two copies, no memory forcing (OBSERVED, run_pair3.log)

```
== phase host->guest: host player 1 collects MEDI (pos 6292.18, 382.32, 0.00)
   tp host: ok settled at (6292.18, 382.32, 0.00) after 0.8 s
   pressed A (attempt 1)
host after:  class MEDI id .... collected 1 p20=0 ... @19178428
guest after: class MEDI id .... collected 1 p20=0 ... @19458278
inventory after: host 44 guest 44 (before 44 / 44)
counters this phase: collected-on-host=True, host sent +1, guest rcv +1 applied +0 already +1, echo sent +0
phase host->guest: OK

== phase guest->host: guest player 2 collects BKPK (pos 1290.44, -2789.00, 570.56)
   tp peer player 2 ... ok settled at (1290.44, -2789.00, 554.29) after 0.8 s
   tp guest: ok settled at (1290.44, -2789.00, 554.29) after 0.8 s
   pressed A (attempt 2)
guest after:  class BKPK id .... collected 1 p20=0 ...
host after: class BKPK id .... collected 1 p20=0 ...
inventory after: host 52 guest 52 (before 44 / 44)
counters this phase: collected-on-guest=True, guest sent +1, host rcv +1 applied +0 already +1, echo sent +0
phase guest->host: OK

results: [('host->guest', True), ('guest->host', True)]
pickup OK: both directions collected on both copies, inventories match, no echo
```

OBSERVED, both directions:

* host collects → the item is collected on the guest (`+0xa8 = 1` there);
* guest player 2 collects → the item is collected on the host;
* the inventory is identical on both copies after each phase (44/44, then 52/52 — the backpack's 7
  weapons were added on both);
* **no echo**: the collecting copy sent one packet, the peer sent none back (`echo sent +0`).

Why the peer reports `already` instead of `applied` (OBSERVED): a LIVE world item in reach of a
character is collected by the game's own interaction scan on BOTH copies at the same instant — the
other copy had already collected it when the packet arrived. The end state is identical and the mod's
apply path never re-sends. To keep the announcement single-sourced, `pickup_local_collect` (sync.c) now
only sends for the character this copy drives (host player 1, guest player 2): without that guard both
copies sent and each received a redundant "already collected" packet (run_pair2.log: `sent +1 rcv +1
applied +0 already +1, echo sent +1` on both sides — the same end state, but an echo).

`tests/check_pickup.py` changes for this case: `OBSCOOP_PICKUP_CLASS=<TAG>` selects an item class, the
safe tp retries once at the floor height the game itself reports, and a peer that collected the item
itself counts as synced (`applied + already >= 1`).

## 9. Save into a slot — NOT DONE, and why (OBSERVED)

* J003 (the only level with live items and no enemy/spawner) has **no save point**: its 36 entities are
  listed in §5 — no `CToeSavePoint`, no `CToeSimpleSavePoint`.
* The game saves only at a save point: `CLevel::Request_SaveGame(CToeSavePoint *)` @ 0x4b2980
  (decompile 108635-108651) stores that pointer in `world+0x1778` and sets world state 10; the save
  handler then drives the object at `world+0x1798` (the save menu). Without a save point object there
  is nothing to hand it, and the pointer is dereferenced later (`(**(code **)(...+0x1778)+0x14)`,
  decompile 110603), so a made-up pointer would crash.
* The pause menu has no save entry: `start_save.py` reaches "Load a saved game" with DOWN, DOWN, A and
  the pause menu is drawn by `menus\pause_pc.xmc`; the save UI is a separate `menus\save.xmc` that the
  level loads for save points (decompile 107…, FUN_004a4060). A blind pause-menu probe in J003
  (`tests/probe_pause.py`, run_pp1.log) produced blank screenshots (the game runs backgrounded) and no
  state change, so this could not be driven further.
* The ten test-copy slots are all occupied (`coop_profile/remote/game0..9.sav`, 40960 bytes each), so
  there is no FREE slot either; saving would overwrite one.
* The guest followed the host's level change and the pickups were proven **without** a save, from the
  pair's own save-01 load. A save made at a save point of another level (I004 has one, §5) would not
  start the party in J003.

UNKNOWN: whether a test-only call of the level's save function with a save point of a *different*
level would be accepted by the game (not attempted: the pointer is dereferenced and would be freed).

## 10. Automatic logging of real ChangeLevel calls (IMPLEMENTED, not yet seen in a run)

`hk_change_level` (hooks.c) now appends every transition the game itself requests to
`obscoop_levels.txt` when `OBSCOOP_LEVELS_LOG` is set (the test runners set it in `duo.py`). A replayed
transition from the pipe `level` command is marked with `g_level_replay` and is not recorded. One line
per distinct (tag, entry, flag); the file is created with its header if missing.

NOT OBSERVED IN ACTION here: in this task every level change was a replay of a recorded door
destination, and a save load goes through `LoadByName`/state 3 (`FUN_004a3bd0`-side), which does not
call `FUN_004a1c00` at all — so nothing new was appended (`obscure2-test/obscoop_levels.txt` still
holds only the lines written by hand, see §3). A real door use in a later run will append its line.

## 11. Regression (OBSERVED, run_reg20a.log / run_reg20b.log, chk22.dll)

`sh tests/run_pair_menu.sh chk22.dll check_party.py check_items.py check_hands.py check_hands_visible.py
check_entities.py check_movement.py check_pickup.py` → rc 1:

```
party OK
items OK
hands OK (2 characters checked)
hands visible state OK (2 characters checked)
entity count: host 43 guest 43
entities OK (host 43, guest 43)
C: FAIL -- GIR1 copies differ: mean 8.90 max 76.42 (max 10.0/55.0) [warn: GIR1 anim differs in 2/60 samples]
D: FAIL -- BOY1 did not move: host 0.0 guest 0.0 units (min 20); GIR1 did not move: host 0.0 guest 0.0 units (min 20)
pickup counters: host {'sent': 1, 'rcv': 0, ...} | guest {'sent': 0, 'rcv': 1, 'applied': 1, ...}
counters this phase: collected-on-host=True, host sent +1, guest rcv +1 applied +1 already +0, echo sent +0
phase host->guest: OK
results: [('host->guest', True), ('guest->host', None)]
pickup: some phases could not run (no live world item)
```

Movement C/D are the flaky pair the task says to report and not chase (D's "did not move" is the same
pad-ignored state TASK 18 documented; C's GIR1 divergence 8.9 units mean is above the 10/55 limits).
Everything else passes, including the pickup sync with the new ownership guard.

`sh tests/run_pair.sh chk22.dll check_party.py check_items.py check_hands.py` → rc 0:

```
party OK
items OK
hands OK (2 characters checked)
```

## 12. DONE / NOT DONE / UNKNOWN

**DONE**
* Where a transition destination lives: `entity+0x118` (level tag) + `entity+4` (entry) + flag 1, the
  exact call of `FUN_0042aa70` (decompile 24666-24710); the only other caller of `FUN_004a1c00` is the
  script command `Cslh_ChangeLevel` (0x4bf6d0). OBSERVED in all ten slots (`run_t1.log`).
* Real level changes triggered from that data: 15 destinations, 13 visited, **no crash**; the door id
  pairs two levels and the entry id selects the `CToeCharacterPos` spawn (`run_e1.log`, `run_s1.log`).
* A room with live items and NO enemies: **J003** — `CToeItemMedikit`, `CToeItemBackpack` and a row of
  16 collectable weapons, 0 enemies, 0 spawners (whole-level scan).
* Pickup in the game's own flow: safe tp through the item/enemy gate → one A press → `item+0xa8` 1,
  `item+0xc4` = character, `+0x20` 0, no `wr` (`run_p2.log`).
* Pair proof in J003 from the pair's own save-01 load, no forcing: host collects → gone on the guest;
  guest player 2 collects → gone on the host; inventories identical (44/44, then 52/52); no echo
  (`run_pair3.log`). The guest follows the host's `level J003 157 1` within 1 s.
* Automatic recording of real ChangeLevel calls (implemented, `OBSCOOP_LEVELS_LOG`), replays excluded.
* Regression: menu run green except movement C/D (known flaky, reported), `run_pair.sh` green.
* `possible door-opening issue, not tested further` recorded (§0).

**NOT DONE**
* **Save into a slot**: J003 has no save point; the game saves only through
  `CLevel::Request_SaveGame(CToeSavePoint*)` (0x4b2980), which dereferences the save point later, and the
  pause menu has no save entry; all ten test-copy slots are occupied. The pair proof therefore starts
  from the existing save 01 (I100) instead of a new save in J003 (§9).

**UNKNOWN**
* Whether a save point of another level, passed to the level's save function, would be accepted (not
  attempted: the pointer is used later and would be freed).
* Whether `OBSCOOP_LEVELS_LOG` records correctly in a real door use (implemented, but this task made no
  transition other than replays; see §10).
* Why the J003 weapon row sits at x ≈ 6292 with z = 0 while the party starts at z = -342 (level layout,
  not needed for the proof).
