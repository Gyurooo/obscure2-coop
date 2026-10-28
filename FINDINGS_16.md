# FINDINGS 16 — a REAL world item from the game's own content, and pickup sync in the real flow

Labels: **OBSERVED** = printed by a check/scan/run in this task or read in the decompile (address cited);
**DERIVED** = follows from the cited code but was not observed live; **GUESS**; **UNKNOWN**.

Status: **final**. Live evidence: ten-slot host scan, three two-copy runs, one solo probe and the two
required regressions (see §5, §8).

## 0. Result in one paragraph

The item chain is now understood end to end from the game's own code: a `CToeBreakableCase` names a
`CToeContainer` in its `item_closed` field (`+0x134`, `FUN_0040d7b0` → `FUN_0040d3d0` resolves it to
`+0x13c`); breaking the case (`FUN_0040d510`, vtable slot 25) sets `+0xa4 = 1` and calls the container's
slot 28 (`0x41b220`), which clears the `+0xb0` interaction gate of up to ten item entities the container
holds (`obj1ID..obj10ID` / `obj1Type..obj10Type`, `FUN_0041b0d0`). **But none of the ten save slots has
that chain**: no `CToeContainer` exists in any level list, the breakable cases have `item_closed == 0`
(nothing inside), every `CToeItem*` entity has `+0x20 == 0` (inactive — the gate the game's own
`FUN_0044d6a0` requires), and the two cases that do exist sit above a floor the save-loaded world does
not have, so a teleported character falls 468 units away and the interaction scan never targets them
(`character+0x73c` stays 0). The task's core goal — a **real, unforced** item picked up on one copy and
gone on the other — is therefore **NOT achieved**; the proof still uses TASK 15's forced `+0x20`. What
this task did achieve: the full decompile of the chain, the answer to FINDINGS_15's open "why is the pad
ignored after a load" (the level intro has not placed the characters yet — once placed, `tp` sticks and
the pairs' movement works), a no-forcing `--spawn` mode of `tests/check_pickup.py` that is ready for a
save that does have an item, and both regressions green apart from the known movement-D flake.

## 1. The CToeLoot class exists live, but not in the static name lists

**OBSERVED** — `strings.tsv`/`rtti.txt` have no `.?AVCToeLoot@@`, but the live game does have the class:
the level scan reads the RTTI name **`CToeLoot`** from an entity's vtable in I100 (`CToeLoot x1`) and in
D003 (`CToeLoot x2`), tag `0x4c4f4f54` = `LOOT` (its constructor `FUN_0045bf10` (0x45bf10) writes
`in_ECX[4] = 0x4c4f4f54`; the vtable is `0x65b53c`, RTTI TD `0x6aa070`). So the static RTTI dump is
incomplete for this class and `SLOT_SCAN.md`'s `CToeLoot` rows were right; only the *name list* was
missing it. Its vtable slots: s5 `0x45c8c0`, s13 `0x45c0a0` (can-interact: needs the character to be
`GIR4` or a live `SYRI` entity, `FUN_004b0900`), s28 `0x45c3a0`, s29 `0x45bfc0`, s31 `0x45c060`
(attach: takes an entity whose class tag is `0x53595249` = `SYRI`).

The item-source classes that the static lists do contain: `CToeBreakableCase`, `CToeBreakableTwoStates`,
`CToeBreakableOnce`, `CToeBreakableDetailed`, `CToeBreakableByAnim`, `CToeBreakableManikin`,
`CToeHeavyCase`, `CToeChest`, `CToeChestKey`, `CToeContainer`, `CToeBeamCase`, `CToeLockPick`,
`CToeDiscLock` (strings.tsv 3184-3190, 3283, 3301 + the RTTI name list).

## 2. CToeBreakableCase — the object, its fields and how it breaks (OBSERVED, decompile)

Vtable and slots came from a read-only Ghidra query (`VtableSlots.java`, RTTI TypeDescriptor →
CompleteObjectLocator → vtable) on the existing project `local\ghidra-proj2\Obscure2`:

| item | value |
|---|---|
| RTTI TypeDescriptor / COL / vtable | `0x6a926c` / `0x683890` / **`0x6534b4`** |
| constructor (`*in_ECX = &PTR_FUN_006534b4`) | `FUN_0040d750` (0x40d750) |
| level-file parser (vtable s2) | `FUN_0040d7b0` (0x40d7b0) |
| **break** (vtable s25) | **`FUN_0040d510` (0x40d510)** |
| resolve links (vtable s4) | `FUN_0040d3d0` (0x40d3d0) |
| per-hitter effect select (s10) | `FUN_0040d270` (0x40d270) |

`FUN_0040d7b0` (the parser) reads these level-file attributes into the object:

| attribute | field | note |
|---|---|---|
| `sound` (`value`) | `+0x148` | break sound id (default `0x42524743` = "CGRB") |
| `position`, `rotation`, `fx_height` | `+0x6c`, matrix, `+0x144` | the case's transform / FX height |
| `mesh_name` | `+0x34` (mesh) | also sets `+0x138 = 1` |
| `item_closed` | **`+0x134`** | **the id of the `CONT` (CToeContainer) entity that holds the items** |
| `zone_id` | `+0x14c` | looked up as tag `0x5a4f4850` (`FUN_0045f540`, the same GetEntityByClassAndId the mod uses) |
| `breaker1..breaker12` | `+0x104 .. +0x130` | 12 break-strength/effect entries, selected per hitter tag in `FUN_0040d270` |
| `ps_on_break` | particle system | created on break |

`FUN_0040d3d0` resolves the two ids once the level is up:
`FUN_0045f540(0x434f4e54 /* "CONT" */, +0x134) → +0x13c` and
`FUN_0045f540(0x5a4f4850, zone_id) → +0x150`.

`FUN_0040d510` is the break itself (the only function in the class that uses the
"Splinter" mesh test and clears the collision):

```
if mesh name == "Splinter": particle FUN_00591230(...); FUN_005727c0(1000,700,1,arg)   // splinters
else:                       mesh+0x48 = 0                                              // hide the mesh
... FX at position ...
*(in_ECX + 0xa4) = 1;                                                     // +0xa4 = broken flag
if (*(in_ECX + 0x13c) != 0)  (*(*(in_ECX + 0x13c) + 0x70))(0);             // CONT->slot28(0)
```

So **breaking a CToeBreakableCase calls CToeContainer's vtable slot 28 (0x70/4)**, i.e. the container is
the thing that releases whatever the case holds. Callers of `FUN_0040d510` (Ghidra xrefs):
`FUN_0040e140` (0x40e140, a one-shot guarded by global `DAT_006c2bf8`), `FUN_004653d0` (0x4653d0, the
"hit" handler: it reads both players' health and picks one of the 12 `breakerN` entries by tag) and the
vtable slot itself (0x653518), plus a direct call at 0x40df6f in the class's own `FUN_0040df...` family.

## 3. CToeContainer — the real item source (OBSERVED, decompile)

| item | value |
|---|---|
| class tag `+0x10` | `0x434f4e54` = `CONT` |
| RTTI TD / COL / vtable | `0x6a9500` / `0x683ec8` / **`0x654c6c`** |
| constructor | `FUN_0041af70` (0x41af70) |
| level-file parser (s2) | `FUN_0041b0d0` (0x41b0d0) |
| **slot 28 = the "open" the breakable calls** | **`0x41b220`** (decompile in §3.1) |

`FUN_0041b0d0` parses **`obj1ID..obj10ID`** (`value`) into `+0xc + 4*i` and **`obj1Type..obj10Type`**
(`value`, a 4-char class tag parsed by `FUN_004a8e00`, the tag-from-string helper) into `+0x12c + 4*i`.
A container therefore carries **up to ten (id, class-tag) item definitions** — those are the entities it
creates when it is opened. That is the game's own "spawn a world item" data, and it is why the pickup
test never needed to invent an item: the level file already says which one to spawn.

### 3.1 What slot 28 does (OBSERVED, decompile of 0x41b220)

`0x41b220` is not a function in the Ghidra database (it is reached only through the vtable), so it was
decompiled on demand (`DecompileAt.java`, read-only, project not saved). It is ten identical blocks:

```
if (*(int *)(in_ECX + 0x154 + 4*i) != 0)  *(int *)(*(int *)(in_ECX + 0x154 + 4*i) + 0xb0) = 0;
```
for `i = 0..9`, i.e. **it clears the `+0xb0` interaction gate of up to ten item entities the container
holds** (`+0x154 .. +0x178`). `+0xb0` is one of the three gates the game's own interaction check
`FUN_0044d6a0` tests (`+0xc0/+0xac/+0xb0 == 0`, ITEMS_FINDINGS §1). So the chain is:

```
player breaks CToeBreakableCase  ->  FUN_0040d510 (+0xa4 = 1, mesh hidden, splinter particles)
                                 ->  CToeContainer (item_closed id) slot 28
                                 ->  +0xb0 = 0 on the container's item entities   => they become pickable
```

That is the game's own "spawn/release a world item" path; no memory write is needed to make an item
real, only the player action that breaks the case.

**UNKNOWN** (to be checked live): whether the released entities also need `+0x20` to be non-zero
(SLOT_SCAN saw `+0x20 == 0` on every item it scanned — those were probably the carried/inventory ones),
and whether a container in these saves has its `+0x154..` pointers resolved at all (they are not set by
the parser `FUN_0041b0d0`; some other resolve step fills them).

## 4. Why the pad does nothing after a load (OBSERVED live, this task)

FINDINGS_15 §2 left "why does the save-loaded world ignore the pad" open. The answer is **time, not
state**: the world pointer and the level tag exist ~0.2-1 s after `loadsave`, but the characters are
**not placed yet** — they sit at (0,0,0)/(2.0,0.1,0) and every probe made in that window sees
"the pad does nothing" and a teleport that does not stick. Once the level has run its intro, the
characters appear at their real start positions.

Measured in a two-copy run (slot 06, `run_pair_menu.sh` + a micro-probe):

```
level I100 mode 1 req 0 | humans 2 | ctl0 human 1bf14ba0 tag BOY1
start                  human pos (  -275.513,    -40.172,      0.100) anim 0    dir ( -1.00, -0.02)
pad LEFT 2s: ('ok', 'ok')
after LEFT 2s          human pos (  -275.513,    -40.172,      0.100) anim 0    dir ( -1.00, -0.02)
tp 0 500 600 700 -> ok
after tp 0.02s         human pos (   500.000,    600.000,    700.000) anim 0    dir ( -1.00, -0.02)
after tp 1.2s          human pos (   500.000,    600.000,    700.000) anim 0    dir ( -1.00, -0.02)
```

So the character is placed at I100's start (-275.5, -40.2, 0.1) — the same value SLOT_SCAN reported —
and `tp` **does** stick. The same check made right after the load (before the intro ran) reads
(0,0,0)/(nan,nan,nan) and a `tp` that is immediately overwritten. That is the whole "the pad is
ignored" effect: no input reaches a character that the level has not placed yet, and the intro is what
places it. The new `--spawn` mode therefore waits for the placement (`wait_placed()` in
`tests/check_pickup.py`) instead of probing blind, which is the "wait it out the game's own way" the
task asked for.

LEFT not moving BOY1 *after* placement is a separate matter: I100's start faces a wall/door in that
direction (the movement checks drive forward+sideways and travel 115-473 units), so this probe does not
show a pad fault.

## 5. Live runs (verbatim excerpts)

| # | launcher | slot / level | what it showed |
|---|---|---|---|
| 1 | one copy, `loadsave game1.sav` | 02 / I015 | world up in 1.0 s, 37 entities, one `CToeBreakableCase` at (-1398.6, -1171.1, 493.4) with **`item_closed(+0x134) = 0`** (the case holds nothing), two `CToeItemMedikit` (`+0x20=0`, one with `+0xb0=1`); player read as (256.1, 0.0, 3.4e7) — the probe ran before the intro placed the character |
| 2 | one copy, all ten slots in one launch (`/tmp` scanner) | 01..10 | class histogram + every item source per slot (table in §6). **No `CToeContainer` in any slot**; only slot 05 has a breakable with `item_closed != 0` |
| 3 | two copies, `loadsave game5.sav` | 06 / G003 | `CToeBreakableTwoStates` at (2430.2, 942.1, 331.9) `+a4=1` (already broken), `item_closed(+0x134)=0x19d04e40` = the `CToeItemEnergyDrink` entity, `cont(+0x13c)` resolved; A and X on it changed nothing because both characters were still at the origin (run started too early) |
| 4 | two copies, `loadsave game0.sav` | 01 / I100 | `CToeLoot` at (0.0, 0.0, 0.0), `+20=0`; characters at the origin; `tp` did not stick (same early window) |
| 5 | micro-probe, same pair | 01 / I100 | characters **placed** at (-275.513, -40.172, 0.100); `tp 0 500 600 700` sticks; LEFT 2 s moves nothing (§4) |
| 6 | `check_pickup.py --spawn`, two copies | 06 / H000 | placed at (-2523.15, 386.38, 37.30); 2 sources (`CToeHeavyCase` at z=59.7, `CToeBreakableCase` at z=466.9); tp ok, but the character **falls 468 units** to z=-1.3 (no floor in the loaded world) → `+0x73c` stays 0, A/X/B do nothing, 0 live items |
| 7 | full menu regression + `--spawn` | 01 / I100 | all old checks pass (movement D flake only); 1 source (`CToeLoot` at the origin, `+20=0`), tp onto it, A/X/B → `+0x73c=0`, no entity created, no live item |
| 8 | old flow `run_pair.sh` + `check_pickup.py` | save 01 / I100 | `check_party`/`items`/`hands` OK; **pickup host→guest OK** (host `sent 1`, guest `rcv 1 applied 1`, `collected 1` on both, inventories 44/44, echo 0) — this is the pre-existing path with `+0x20` forced |

Verbatim, run 6 (the best unforced attempt):

```
host: player 1 placed after 0.0 s at (-2523.15, 386.38, 37.30)
guest: player 2 placed after 0.0 s at (-2523.15, 471.28, 37.30)
host: 2 item source(s) in the level (level H000, 44 entities)
   CToeBreakableCase          class BKCS id .... collected 0 p20=1 p34=0 pos (721.35, 1075.67, 466.93) gates c0=0 ac=0 b0=0 r=200.0 @19641620
   CToeHeavyCase              class HCAS id .... collected 0 p20=1 p34=18d08bf0 pos (-6.63, -578.99, 59.74) gates c0=0 ac=0 b0=0 r=200.0 @19d15198
 -- CToeHeavyCase @19d15198 at (-6.63, -578.99, 59.74), 2695 away: tp player 1 onto it
    tp -> ok
    A: source broken(+a4)=0 active(+20)=1 collected(+a8)=0 gate(+b0)=0 | +0x73c=0x0 | entities 44 (was 44) | live items 0
    ... (5 more presses: X, X, X, B — identical) ...
 -- CToeBreakableCase @19641620 at (721.35, 1075.67, 466.93), 3345 away: tp player 1 onto it
    ... (6 presses: A, A, X, X, X, B — identical) ...
live items after the spawn attempt: host 0 guest 0
```

Verbatim, run 7 (the I100 loot):

```
host: player 1 placed after 0.0 s at (-259.44, 431.10, 0.10)
guest: player 2 placed after 0.0 s at (330.19, 79.55, 0.90)
host: 1 item source(s) in the level (level I100, 30 entities)
    A: source broken(+a4)=0 active(+20)=0 collected(+a8)=0 gate(+b0)=0 | +0x73c=0x0 | entities 30 (was 30) | live items 0
    ... (5 more presses — identical) ...
live items after the spawn attempt: host 0 guest 0
```

## 6. What the ten slots actually contain (OBSERVED, run 2)

| slot | level | entities | item sources present | live item |
|---|---|---:|---|---|
| 01 | I100 | 30 | `CToeLoot` ×1 (at the origin, `+20=0`), `CToeItemEnergyDrink` (`+20=0`) | 0 |
| 02 | I015 | 37 | `CToeBreakableCase` (`item_closed=0`), `CToeLockPick`, `CToeItemMedikit` ×2 (`+20=0`, one `+b0=1`) | 0 |
| 03 | D003 | 27 | `CToeLoot` ×2, `CToeItemMedallion` (collected) | 0 |
| 04 | J002 | 40 | `CToeChestKey` ×2 (both `+a8=1`), `CToeDiscLock` | 0 |
| 05 | J005 | 22 | `CToeItemMedikit` ×2 (`+20=0`) | 0 |
| 06 | G003 | 47 | `CToeBreakableTwoStates` (broken, `item_closed` → `CToeItemEnergyDrink` `+20=0`), `CToeItemEnergyDrink` | 0 |
| 07 | H000 | 44 | `CToeBreakableCase` (`item_closed=0`), `CToeHeavyCase`, `CToeLoot` ×3, `CToeLockPick`, `CToeRespawner` ×2 | 0 |
| 08 | H006 | 39 | `CToeItemMedikit` ×2 (`+20=0`) | 0 |
| 09 | I004 | 14 | `CToeItemEnergyDrink` (`+20=0`) | 0 |
| 10 | I007 | 49 | (per SLOT_SCAN: breakable + chest key + chain) | 0 |

**No slot has a `CToeContainer` entity at all** — the only class with the `obj1ID..obj10ID` /
`obj1Type..obj10Type` item definitions (§3) that a breakable would release. And every `CToeItem*` in
every slot has `+0x20 == 0`, the gate the game's own interaction check `FUN_0044d6a0` requires
(44141-44144).

## 7. Why no unforced item could be produced (OBSERVED / DERIVED)

1. **The saves have no live item**: all `CToeItem*` entities are `+0x20 == 0` (table above). That gate is
   set to 1 by the base entity constructor `FUN_004020d0` (1031); something in the save-restore/level
   build sets it to 0 for these items, and nothing the player can do in these worlds sets it back.
2. **The breakables hold nothing**: the cross-reference that would release an item is
   `CToeBreakableCase+0x134` (`item_closed`) → a `CONT` container. In I015 and H000 it is **0**; in G003
   it points at an already-collected item of an already-broken case.
3. **The one class that can create items (`CToeContainer`) does not exist in any of the ten saves**, so
   `FUN_0040d510`'s `CONT->slot28` call has no target.
4. **The sources that do exist are out of reach in the loaded world**: the H000 breakable sits at
   z = 466.9 and the heavy case at z = 59.7, but the save-loaded world has no collision floor under
   them — the teleported character falls to z ≈ -1.3 — and the interaction scan never selects them
   (`character+0x73c` stays 0), so A/X/B do nothing. I100's only source (`CToeLoot`) is at the world
   origin and its own can-interact (`FUN_0045c0a0`, 54053) refuses unless the collecting character is
   `GIR4` or a live `SYRI` entity exists.

**DERIVED fix**: the trigger exists and is small — breaking a `CToeBreakableCase` calls
`CToeContainer::slot28` which clears `+0xb0` on the ten item entities the container holds. A level that
actually has a `CToeContainer` with `objNID/objNType` entries (or a playthrough save from a real
game where the container was populated) would give a real item. The alternative that needs no new
content is to make the *loaded* world reachable: the missing floors are a level-resource problem, not a
mod problem, so a live co-op session must be started from a real 2-player game rather than a solo
`loadsave` (which is why the movement checks travel 470 units in the pair flow and nothing here).

## 8. Regressions (verbatim results)

`sh tests/run_pair_menu.sh chk.dll check_party.py check_items.py check_hands.py check_hands_visible.py
check_entities.py check_movement.py check_pickup.py` (with `OBSCOOP_PICKUP_SPAWN=1`):

```
party: host ['BOY1', 'GIR1'] guest ['BOY1', 'GIR1'] | inventory: host 44 guest 44
party OK
items: before host 44 guest 44
items: after host 45 guest 45
items OK
hands OK (2 characters checked)
hands visible state OK (2 characters checked)
entities OK (host 43, guest 43)
E: PASS
A: PASS
B: PASS
C: PASS
D: FAIL -- GIR1 copies differ: mean 15.55 max 46.73 (max 10.0/55.0) [warn: GIR1 anim differs in 4/50 samples]
results: [('host->guest', None), ('guest->host', None)]
```

`sh tests/run_pair.sh chk.dll check_party.py check_items.py check_hands.py check_pickup.py` (old flow):

```
hands OK (2 characters checked)
inventory: host 44 guest 45
phase host->guest: OK
pickup OK: both directions collected on both copies, inventories match, no echo
```

The movement phase D failure is the known flaky phase on main (FINDINGS_13/14/15: mean 6.96-15.55); the
task says to report it, not chase it. Everything else passes.

## 9. DONE / NOT DONE / UNKNOWN

**DONE**
* `CToeBreakableCase` / `CToeContainer` / `CToeLoot` decompiled: vtable slots, level-file fields
  (`item_closed`, `breaker1..12`, `obj1ID..obj10ID`, `obj1Type..obj10Type`), the break call chain
  (`FUN_0040d510` → `CONT->slot28` → `+0xb0 = 0`), and the checks (`FUN_0044d6a0`, `FUN_0045c0a0`).
* The FINDINGS_15 open question "why does the save-loaded world ignore the pad" is answered: the level
  intro has not placed the characters yet; after placement `tp` sticks and the pairs' movement works.
* `tests/check_pickup.py --spawn` (no memory writes) implemented and run on three slots; it waits for
  placement, tries every source with the game's own A/X/B, and only then runs the pickup phases.
* Both required regressions pass apart from the known movement-D flake; the pickup sync itself still
  works in both directions on the old flow.

**NOT DONE**
* No real (unforced) world item was produced in any of the ten saves: no `CToeContainer` exists, the
  breakables hold nothing, and the existing sources are unreachable (no floor) or refuse interaction.
  The "pick it up on one copy and see it vanish on the other" proof therefore still uses the forced
  `+0x20` from TASK 15.
* Consequence: the breakable/loot sync could not be exercised either (nothing could be broken), so no
  screenshots of "broken on one copy, whole on the other" exist.

**UNKNOWN**
* Whether a real playthrough save (or a level whose `CToeContainer` is populated) would make the chain
  work end-to-end; the decompile says yes, no live run has shown it.
* Why the save-loaded worlds have no collision floor under their fixtures — a level-resource issue.

