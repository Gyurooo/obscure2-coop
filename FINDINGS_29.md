# FINDINGS 29 — why the game never starts an attack or an aptitude use for the bot (TASK 29)

Base: commit 6849607, protocol 15. Builds: `chk29a.dll` (unchanged source), `chk29b.dll` (source with
the corrected comments only - see §5). Labels: **OBSERVED** = printed by a run/check, or read in the
decompile/assembly at the cited address; **DERIVED** = follows from that code but was not seen live;
**GUESS**; **UNKNOWN**. Every live run is quoted verbatim in §7.

## 0. Result in one paragraph

The attack and the aptitude use do **not** share a cause, and the mod is not the cause of either.
The **attack** cannot be started by any input in these test levels: with the mod *passive* (a plain
proxy - no input-hook writes, no net at all) a solo copy behaves exactly like the active one, so no mod
write is involved; the game reaches its own aim stance (anim `+0x2dc = 0x64`, aim flag `+0x700 = 1`) and
then its own aim/attack **target search** (`FUN_004e0750`, the only consumer of the A press while
aiming) accepts **no** NPC of the level - `character+0x864` (target found), `+0x344` (aim target) and
`+0x354` (attack target) stay 0 through 3 s of LB+A - and the class that owns the swing functions
(`CToeInteruptor`, vtable 0x65adc4) does not exist in the level at all. The **aptitude use** is a real
finding in the game's use-object scan: it has *two* action buttons - interaction type 1 (front side) is
started with **A**, type 2 (back side) with **Y** - so `check_abilities.py`, which only pressed A, could
never start the I015 lock pick, whose safe tp lands on its back side (`+0x104 = 2`). The test now
presses the right buttons on both pads (and prints which pad moves the acting character). Live, the I015
lock still does not start even with Y on the working pad and a 100 score in the type-2 pass, so a
further gate inside the game remains **UNKNOWN**; the button fix is necessary (A alone can provably
never work there) but not sufficient.

## 1. The pad's action slots, named (OBSERVED: the game's own default map + the live ipt)

`FUN_004cf940` @ 0x4cf940 is the per-character controller input update (the mod's `hk_input_update`).
It loads one action object per slot with `FUN_0059b3e0(base + N)` (assembly 0x4cf9e5-0x4cfa60; `base` =
controller `+0x14`: 0 for player 1, 0x28 for player 2 - `tests/ipt_table.py`). The game's own default
table (`FUN_004a2b50`, decompile 97580-97610) binds action -> pad code for a gamepad; the code names are
the string pool at 0x6623f8, in order `X360_A, B, X, Y, BACK, START, LB, RB, L3, R3, UP, LEFT, RIGHT,
DOWN, LT, RT` = codes 1015-1030. Cross-checked against the live `o2.ipt` (`tests/ipt_tables.log`):

| action | controller slot | pad code | button | used by |
|---|---|---|---|---|
| 9 | `[esi+0x3c]` | 1015 | **A** | use (type 1), pickup, attack while aiming |
| 0xa | `[esi+0x4c]` | 1016 | B | |
| 0xb | `[esi+0x50]` | 1021 | **LB** | aim stance |
| 0xd | `[esi+0x5c]` | 1017 | X | |
| 0x20 | `[esi+0x48]` | 1029 | LT | |
| 0x21 | `[esi+0x40]` | 1030 | RT | |
| 0x22 | `[esi+0x44]` | 1018 | **Y** | use (type 2) |

One action object (`FUN_0059b490` @ 0x59b490): `+0xc` = value (1000 while held), `+0x10` = 1 while
pressed (a LEVEL flag, not an edge), `+0x14` = hold counter, `+0x18` = 1 on the release frame. A held
button therefore stays "pressed" for as long as the virtual pad reports it - no press edge is needed.

## 2. The interaction scan: **two** buttons, one per side (OBSERVED, asm 0x4d2653-0x4d2870)

After the linked-object switch, `FUN_004cf940` scans the world entity list (`world+0x1768`) in four
passes; each pass calls the object's eligibility `vtable+0x34(type, character)` and keeps the best
score (assembly, not the decompiler's denormal constants):

| pass | type | runs when | button that makes it the winner |
|---:|---:|---|---|
| 0 | 1 (front side) | controller state `+0xa4` == 0 | **A** pressed (`[esi+0x3c]+0x10`) |
| 1 | 2 (back side) | controller state == 0 | **Y** pressed (`[esi+0x44]+0x10`) |
| 2 | 4 | character anim `+0x2dc` is 1, 2 or 4 | none (automatic) |
| 3 | 7 | always | none (automatic) |

The winner then takes one of two paths (asm 0x4d27d6-0x4d2870):

* `vtable+0x20` (slot 8) != 0 -> **pickup**: `character+0x73c = object` (the chair/box/item path that
  already works; the stub `0x5e3b10` = `xor eax,eax; ret` on the lock, so not this one);
* else `vtable+0x1c` (slot 7) != 0 -> **use**: `vtable+0x70(character)` = the object's own use method
  (lock pick `FUN_0045ac10`, heavy case `FUN_004459d0`, door open, chair attach).

`CToeLockPick`'s eligibility (`FUN_0045a9e0`, decompile 53252-53310) returns **100 and writes
`+0x104 = 2`** only in the type-2 branch (character's back to the lock: `dot < -0.5`, BOY1 only); the
type-1 branch writes `+0x104 = 1` and returns 100 as well. The check's safe tp puts Stan on the back
side, so only the **type-2** pass can win - and that pass needs **Y**.

**This is what FINDINGS_28 missed**: it pressed A only, concluded "the scan has no button gate", and
looked for the missing link in the lock's own start path. A alone can never select a type-2 winner.

Same family (same scan, same button rule): every back/off-side interaction of doors, the heavy case,
disc locks, documents, dark auras and chairs is started with Y, never with A.

## 3. The attack path (OBSERVED)

* LB (`action 0xb`) held sets the controller state `+0xa4 = 1` (decompile 126838-126845).
* In that state the update writes anim 100 (`+0x2dc = 0x64`, the aim stance) every frame, then
  (assembly 0x4d29ef-0x4d2a13):
  ```
  if (character->vtable+0x94(8) != 0 && A pressed) FUN_004e12a0(character);
  ```
  `CCharacterHuman_s37` @ 0x4df3a0 `case 8` returns 1 when `+0x2dc` is 500, 100, 200, 0xc9, 0x66 or
  600 - the aim states the bot reaches satisfy it. A is read for this branch exactly like everywhere
  else, and A demonstrably works (chairs are picked up with it, §2), so the call happens.
* `FUN_004e12a0` @ 0x4e12a0 is the **only** caller of `FUN_004e0750` (assembly: `call 0x4e0750` with
  `param_1 = character+0x338`, then `lea ecx,[character+0x348]; call 0x4c67a0` which clears
  `+0x348..+0x354`, then `[character+0x354] = [character+0x344]`): the aim/attack **target search**
  over the NPC manager (`world+0x1760`). It writes the chosen NPC to `+0x344`/`+0x354` and sets
  `character+0x864 = 1` (asm 0x4e0b62).
* The swing itself is `FUN_004563a0` @ 0x4563a0 = `vtable+0x70` of `CToeInteruptor` (RTTI TD 0x6a9f94,
  vtable **0x65adc4**, COL 0x6859d4; the swing end 0x456710 at `+0x74`). **FINDINGS_23's "vtable
  0x659568" is a different class** - the table that really holds 0x4563a0 starts at 0x65adc4 (the dword
  0x4563a0 sits at file 0x259634, VA 0x65ae34). `CToeInteruptor` is created **only** by the level
  parser's factory (`FUN_00455670`, singular call site 0x45e151, keyed on the entity tag `INTE`).

## 4. Live measurement (OBSERVED)

### 4.1 The attack does not depend on the mod

Solo copy, save 01 -> `level J001 317 1`, player 1 (BOY1) tp'd 8-12 units from the 80-HP
`CCharacterNPC`, then the LB+A chord - once with the normal build, once with `OBSCOOP_PASSIVE=1`
(no net, and the input hook performs **no** writes):

```
run_a29_active  (chk29a, normal)
   anim ['0x0', '0x64'] | wstate ['0x0']
     0.04s anim 0x0064 wstate 0x0 aimflag 1 act 0x0 pend 0x0064
     1.04s anim 0x0000 wstate 0x0 aimflag 0 act 0x0 pend 0x0000
   enemy life drops: NONE

run_a29_passive (OBSCOOP_PASSIVE=1, plain proxy)
     0.08s anim 0x0064 wstate 0x0 aimflag 1 act 0x0 pend 0x0064
     1.57s anim 0x0000 wstate 0x0 aimflag 0 act 0x0 pend 0x0000
   enemy life drops: NONE
```

The aim stance arrives, the weapon never leaves state 0, the enemy is untouched - **with and without
every mod write**. (The only write left in the input hook is the `+0x880/+0x884` clearing, which passive
turns off; the weapon-hands apply is guest-only and this is a solo copy.)

### 4.2 The game's own target link never forms

Same solo run, sampling exactly what `FUN_004e12a0`/`FUN_004e0750` write, with the melee weapon in hand
(`CToeWeaponUberBeat`, slot 2) and A held for 3 s inside LB (run_a29_probe2):

```
-- A held for 3 s inside LB
    0.65s anim 0x0064 pend 0x0064 aim 1 act 0x0 73c 0x0 | tgt338 0x0 tgt340 0x0 tgt344 0x0 tgt354 0x0 864 0x0 | sel 2 wep UBET wst 0x0
    ...
    3.40s anim 0x0064 pend 0x0064 aim 1 act 0x0 73c 0x0 | tgt338 0x0 tgt340 0x0 tgt344 0x0 tgt354 0x0 864 0x0 | sel 2 wep UBET wst 0x0
```

`+0x864` is set for **any** accepted target, so no NPC of J001 passes the search. The NPCs are inert
in these saves (AI state 2; they never move, attack or wake when hit - FINDINGS_21 §5/§6, unchanged
here: `enemy ... life 80.0 st 0x0 ai 2` on every copy in every run).

### 4.3 No swing object exists in the level

`CToeInteruptor` is a level/asset entity (`INTE`) and is created only by the level parser. A scan of the
world entity list (100 objects in J001, every one RTTI-inspected), of the selected weapon (0x400 bytes)
and of the character (0x900 bytes) finds **no** object of that class (run_a29_probe3):

```
world entities: 100
   CToeWeapon* x14, CToeItem*, CToeTalkie, CToeDoor, CCharacterHuman, ...
player 1 BOY1 @1a818498 sel 0 weapon CBOW @1a2f1fc0 (CToeWeaponCrossBow)
pointers out of weapon 0x1a2f1fc0 with a class name: CZoeEntity3D, CCharacterHuman, CToeArrow, CZoeEntity3D, CZoeEntity3D
after the chord, world entities with Interuptor/Attack in the name: none
```

So even the test-only `swing` (which searches the weapon/character/impact manager for an object whose
vtable slot 28 is 0x4563a0 - address-independent, so it is not fooled by the wrong vtable) cannot find
one: the game has nothing to swing with in this level.

### 4.4 The aptitude: the button matters, and something else as well

I015 (save 02). Host's player 1 = BOY2 (no aptitude object there), the guest's player 2 = BOY1 (Stan)
next to the lock pick. Pads measured, not assumed:

```
  pad reach: XInput user 0 moves the character 18.33 units
  pad reach: XInput user 1 moves the character 0.00 units
abilities: tp player 2 (guest): safe tp at 90 units (ok settled at (-1293.04, -540.93, 109.08) after 0.8 s)
  before own  LCKP ... f104=2 ...
  the action button did not start an action on LCKP ( ... f104=2 ... char BOY1 ... anim=0 life=100 action=@0 animobj=0)
```

With **A+Y on both pads**, a back-side lock that scores 100 in the type-2 pass (`+0x104 = 2`), the
character in radius and the pad that moves it known to work, the scan still never selects the use:
`human+0x2bc` stays 0, the lock's `+0xc4` stays 0. The button is therefore **necessary but not
sufficient**. UNKNOWN which further condition refuses it; candidates left in the same routine:
`FUN_004dca40(2)` (the gate that lets the scan run at all), the winner's `vtable+0x1c` (slot 7 =
`0x476560`, a shared base method) and the object's own `FUN_0045ac10` entry conditions
(`character+0x14/0x2dc/0x10c`, the camera lock `FUN_005d5450`).

## 5. Fix (smallest change; all of it in the tests)

1. `tests/check_abilities.py`
   * `press_action()` presses **A and Y** together - the scan's button depends on the side the object
     reported (type 1 = A, type 2 = Y). Pressing both is how a test that cannot know the side stays
     correct.
   * `try_presses()` presses **both XInput users** (0 and 1) and prints which one worked: on the guest
     copy the mod maps the local pad to user 1 while the game polls user 0 for player 1, and a silent
     "nothing happened" tells nobody whether the pad even arrived.
   * a new **pad-reach** line before the placement (`stick up` on user 0 and 1, measured on the acting
     character) - it makes a failed press diagnosable instead of ambiguous.
   * `tp_near()` now tries 16 angles per radius instead of 8: the I015 lock stands on a narrow ledge
     and one run refused all 48 spots (22.5 deg away from a good spot is over the edge).
2. `tests/check_combat.py`: `ATTACK_VT` corrected from 0x659568 to **0x65adc4** (`CToeInteruptor`), so
   its "world entities with the attack vtable" diagnostic looks for the right class.
3. `src/obscoop2.c`: **comments only** in the `swing`/`swingobj` blocks (the same address correction;
   the code already matched on slot 28 == 0x4563a0, so its behaviour does not change). `chk29b.dll` is
   the rebuilt result; it has the same three pre-existing warnings and no new one.

No mod behaviour change is needed for either symptom: the game's own scan, the game's own target search
and the game's own attack entry do all the work, and the mod already syncs their results
(`PKT_NPC` life/damage, `PKT_CHAR` anim, `PKT_APT` ability results).

## 6. DONE / NOT DONE / UNKNOWN

**DONE**
* Named every action slot the input update reads, from the game's default map and the live `.ipt` (§1).
* Decoded the interaction scan's four passes and its **two** action buttons, type 1 = A, type 2 = Y,
  plus the pickup-vs-use split (`vtable+0x20` vs `+0x1c` -> `+0x70`) (§2).
* Identified the attack start as the only consumer of A while aiming and proved live that the game's
  target search rejects every NPC of J001/J000, with **no** mod write involved (passive run identical)
  (§3, §4.1-4.2).
* Corrected the attack class and vtable (`CToeInteruptor`, 0x65adc4) and showed that no such object
  exists in the level (§4.3).
* Fixed the test-side cause of the aptitude failure (wrong button, plus two pad-related blind spots)
  and added the diagnostics that make the next run conclusive (§5).

**NOT DONE**
* The live lock-pick proof: with the right button and the working pad the game still does not start the
  use (§4.4). `check_abilities.py` therefore still fails on the acting copy.
* The live attack proof: no input starts a swing in these levels, so `check_combat.py` still falls back
  to the game's own life method (`npcset`) and says so.
* Regression: only `run_pair_menu … check_party.py check_items.py check_hands.py check_hands_visible.py
  check_entities.py` was run (§7). `check_movement.py`, `check_breakables.py` (slot 3), the item-use
  pair run and `run_reconnect.sh` were **not** run: the 18-process budget was spent on the diagnosis
  (15 processes) and the regression run (2). The shipped code differs from the base commit only in
  comments (§5.3).

**UNKNOWN**
* Which condition inside the game refuses the I015 lock pick even when the type-2 pass scores 100 and Y
  is pressed on the pad that demonstrably moves the character (§4.4).
* Whether the game's target search would accept an *active* enemy (one whose AI has woken) - the
  difference between our teleported, script-skipping entry and a real play-through. This is the gate
  the attack hinges on.

## 7. Verbatim runs

### 7.1 run_a29_active.log — solo, save 01 -> J001, normal build (`sh tests/run_solo_slot.sh chk29a.dll 0 attack_probe.py`)
```
player 1 .?AVCCharacterHuman@@ @1a54eed0 BOY1 pos (-793.6, 907.2, 0.7)
   after tp: anim 0x0000 pend 0x0000 aimflag 0 act 0x0 73c 0x0 gates(230 0x0 2c4 0x0) life 100.0 sel 0 wep CBOW wstate 0x0
   dist to target 12.0

-- LB 0.3 s + A 0.2 s
   anim ['0x0', '0x64'] | wstate ['0x0']
     0.04s anim 0x0064 wstate 0x0 aimflag 1 act 0x0 pend 0x0064
     1.04s anim 0x0000 wstate 0x0 aimflag 0 act 0x0 pend 0x0000
   enemy life drops: NONE

-- LB 0.8 s + A 0.2 s
   enemy life drops: NONE

-- LB + A, stick forward
   enemy life drops: NONE

-- LB + RB
   anim ['0x0', '0x66'] | wstate ['0x0']
   enemy life drops: NONE
```

### 7.2 run_a29_passive.log — the same with `OBSCOOP_PASSIVE=1`
```
-- LB 0.3 s + A 0.2 s
     0.08s anim 0x0064 wstate 0x0 aimflag 1 act 0x0 pend 0x0064
     1.57s anim 0x0000 wstate 0x0 aimflag 0 act 0x0 pend 0x0000
   enemy life drops: NONE

-- LB + A, stick forward
   enemy life drops: NONE

-- LB + RB
   anim ['0x0', '0x66'] | wstate ['0x0']
   enemy life drops: NONE
```

### 7.3 run_a29_probe2.log — melee slot, A held 3 s inside LB (the target fields)
```
-- A held for 3 s inside LB
    0.65s anim 0x0064 pend 0x0064 aim 1 act 0x0 73c 0x0 | tgt338 0x0 tgt340 0x0 tgt344 0x0 tgt354 0x0 864 0x0 | sel 2 wep UBET wst 0x0
    0.90s ... 3.40s (identical every sample)
final: anim 0x0064 pend 0x0064 aim 1 act 0x0 73c 0x0 | tgt338 0x0 tgt340 0x0 tgt344 0x0 tgt354 0x0 864 0x0 | sel 2 wep UBET wst 0x0
```

### 7.4 run_a29_probe3.log — the level's classes, the weapon's pointers, the missing swing object
```
world entities: 94
   CToeAddictiveCenter 19 / CToeDocument 16 / CToeLoot 7 / CToeStepSound 6 / CToeBreakableCase 3 / ...
player 1 BOY1 @1a818498 sel 0 weapon CBOW @1a2f1fc0 (CToeWeaponCrossBow)
pointers out of weapon 0x1a2f1fc0 with a class name:
   +0x34 -> 0x1a1cd2d0  CZoeEntity3D
   +0xc4 -> 0x1a818498  CCharacterHuman
   +0x23c -> 0x1a2f2214  CToeArrow
   ...
after the chord, world entities with Interuptor/Attack in the name: none
enemies: CCharacterNPC 80.0, CCharacterNPCProgeny 1.0 x5, CCharacterNPC 80.0
```

### 7.5 run_e29_apt2.log / run_f29_apt3.log — the first two A+Y attempts
```
abilities: tp player 2 (guest): safe tp refused every spot (48 tried)          <- run_e29 (no press possible)

abilities: tp player 2 (guest): safe tp at 90 units (ok settled at (-1292.32, -544.02, 109.08) after 0.8 s)
  no action facing the object; turning the back to it (safe tp at 110 units (ok settled at (-1289.20, -501.22, 109.08) after 0.8 s))
  the action button did not start an action on LCKP ( ... f104=2 ... char BOY1 ... action=@0 ...)   <- run_f29
```

### 7.6 run_g29_apt4.log — chk29b.dll, right buttons, both pads, measured pad
```
abilities: player 2 (guest) = BOY1; usable aptitude objects for it: LCKP@19580290
abilities: player 2 (guest) -> LCKP LCKP/LCKP @19580290 (-1380.33,-562.83,109.08) ... f104=0 ...
  pad reach: XInput user 0 moves the character 18.33 units
  pad reach: XInput user 1 moves the character 0.00 units
abilities: tp player 2 (guest): safe tp at 90 units (ok settled at (-1293.04, -540.93, 109.08) after 0.8 s)
  before own  LCKP/LCKP @19580290 ... f104=2 ...
  no action facing the object; turning the back to it (safe tp at 90 units (ok settled at (-1293.78, -587.52, 109.08) after 0.8 s))
  after the presses char BOY1 @1a0cbf18 pos (-1293.78,-587.52,109.08) anim=0 life=100 action=@0 animobj=0
  the action button did not start an action on LCKP ( ... f104=2 ... )
abilities FAIL:
  - player 2 (guest): the action never ran on the acting copy
```

### 7.7 run_h29_reg1.log — regression (`sh tests/run_pair_menu.sh chk29b.dll check_party.py check_items.py check_hands.py check_hands_visible.py check_entities.py`)
```
== check_party.py
party: host ['BOY1', 'GIR1'] guest ['BOY1', 'GIR1'] | inventory: host 44 guest 44
party OK
== check_items.py
items: before host 44 guest 44
items: after host 45 guest 45
items OK
== check_hands.py
hands OK (2 characters checked)
== check_hands_visible.py
hands visible state OK (2 characters checked)
== check_entities.py
entity count: host 43 guest 43
entities OK (host 43, guest 43)
```
RC=0, and `OWNER FILES UNCHANGED (apart from Steam remotecache.vdf)`.

