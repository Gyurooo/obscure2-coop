# FINDINGS 19 — doors and save points after a save load (TASK 19)

Labels: **OBSERVED** = printed by a run/check in this task, or read in the decompile / `.tsv` (address cited);
**DERIVED** = follows from the cited code/data but was not observed live; **GUESS**; **UNKNOWN**.
Decompile line numbers refer to `local\decomp2\Obscure2.exe.c`.

Status: in progress (starting point: the decompile part, written before the live runs finish).

## 0. The TASK 18 diagnostic was wrong

FINDINGS_18 §5 concluded "the interaction scan does not run after a save load" from
`character+0x73c` staying 0 at an eligible `CToeDoor` and at a `CToeSavePoint`. **That measurement cannot
show that.** The scan writes `character+0x73c` only for an entity whose `vtable+0x20` ("collectable") is
non-zero; doors and save points are *used* through a different call and never appear in `+0x73c`
(OBSERVED, see §1.3). `probe_door.py` was therefore blind to the door: at a door `+0x73c` is supposed to
stay 0.

## 1. The interaction scan (decompile)

### 1.1 The per-entity eligibility check — `FUN_0044d6a0` @ 0x44d6a0 (decompile 44129-44161)

```
if (((((param_1 == 1) || (param_1 == 3)) && entity[0xc0] == 0) &&          // interaction type, "hidden"
     ((param_2 != 0 && entity[0x20] != 0)))) &&                            // character, active
    ((entity[0xa8] == 0 && (entity[0xb0] == 0 && entity[0xac] == 0)))) {   // not collected, gates
  d = distance3(character[0x23c..] , entity[0x6c..]);
  if (d <= entity[0xa0])                                                   // radius
    if (ABS(entity[0x74] - (character[0x244] + (param_1 == 3 ? 150 : 0))) < 200)
      return 100;
}
return 0;
```

* `param_1` is the **interaction type**, not a player index: the scan calls it with 1, 2, 5, 9 and
  `FUN_0044d6a0` accepts only 1 and 3 (§1.3).
* There is **no facing / view-cone / line-of-sight test and no per-player test** in the entity check.
* `FUN_00450770` @ 0x450770 (decompile 46817-46850) is the `CToeItemMap` override: identical minus the
  `+0xb0` gate.

### 1.2 The scan itself lives in `FUN_004cf940` @ 0x4cf940 (decompile 126673-…, scan at 128115-128250)

`FUN_004cf940` is the character-controller input update — the function the mod already hooks
(`src/hooks.c` `hook_entry(0x4cf940, …)`). Its frame begins (126707):

```
local_10 = in_ECX[1];          // the character (controller+4)
if (local_10 == 0) return;
if (in_ECX[0x1d6] != 0) return;             // controller+0x758: whole update switched off
```

The scan block (128115-128250) runs when:

| # | condition | address |
|---|---|---|
| 1 | `character+0x2bc == 0` **or** `character+0x2bc->vtable+0xa8(character) != 0` | 128115-128122 |
| 2 | `controller+0xa4 == 0 || controller+0xa4 == 1` | 128124 |
| 3 | `character->vtable+0x90(2) != 0` | 128124-128125 |

then four passes over the global entity iterator (`FUN_0040f330` / `FUN_004d98c0`):

| pass | type | scan runs when | decompile |
|---|---|---|---|
| 0 | 1 | `controller+0xa4 == 0` | 128150-128175 |
| 1 | 2 | `controller+0xa4 == 0` | 128176-128186 |
| 2 | 5 | `character+0x2dc ∈ {1,2,4}` | 128188-128196 |
| 3 | 9 | always | 128197-128205 |

Per entity: `if (vtable+0x1c() != 0 || vtable+0x20() != 0) score = vtable+0x34(type, character)`; keep the
best score per pass and the best overall (`local_30`, 128200-128205).

### 1.3 What the winner is used for (decompile 128210-128245)

```
if (local_30 != 0) {
  if (local_30->vtable+0x20() != 0) {          // collectable
    character+0x73c = local_30;                 // 128214  ← the ONLY write of +0x73c here
    character->vtable+0x44(0,0,0);              // stop the current animation
    character->vtable+0x48(0x640);              // play the pick-up animation
    return;
  }
  if (local_30->vtable+0x1c() != 0) {          // "usable" → doors, save points, levers, map
    local_30->vtable+0x34(type, character);     // re-check
    local_30->vtable+0x70(character);           // ← USE IT
    ...
```

So **a door is opened by the scan calling `vtable+0x70` on it — no button press of its own, and no
`+0x73c`**. Two consequences:

* `character+0x73c` is a *collect* target only. FINDINGS_18 §5 measured the wrong field at a door.
* Whatever stops the door must stop the scan itself (conditions 1-3) or the door's `vtable+0x34/0x70`.

### 1.4 The door's own check, in machine code (OBSERVED, objdump of the test copy)

`FUN_0042a480` disassembled at 0x42a480-0x42a595 is exactly the C above, and it measures the distance
from **`door+0x10c / +0x110 / +0x114`**, not from `door+0x6c / +0x70 / +0x74`
(`flds 0x10c(%esi); fsubs 0x23c(%edi)` …). Those three floats are copied from `+0x6c/+0x70/+0x74` when
the door entity is parsed (`FUN_0042b…` decompile 25167-25169), so they normally agree.
The 0.5 constant is at 0x68329c and the 80.0 at 0x656218.

The save point's `FUN_0046e6c0` (decompile 64851-64885) is the same shape with the plain position
`+0x6c/+0x70`, radius `+0xa0` and `dot(normalize(char -> entity), character+0x248..0x250) > 0.5`, plus
four extra gates: `entity+0x24 != 0`, `entity+0xb8 == 0`, `entity+0x150 != 0`, `entity+0x14 == 0`.

## 2. Live runs

### 2.1 `run_i1` — solo, slot 01 (I100), A pressed next to a door and next to the save point

`probe_interact.py` (new), one host copy, `loadsave game0.sav` (the same replay the pair flow uses).

```
-- at the start: level I100 mode 1 world 0x1918cf30 ctl 0x18ecf344
   player 0 char 0x1a3ee6c0 tag BOY1 vt 0x66683c
     char: anim+0x2dc 0 life+0x320 100.0 +0x278 0x0 +0x2bc 0x0 +0x73c 0x0 +0x880 0x0 +0x884 0x0
  char vtable 0x66683c: +0x1c->0x004c6c00 +0x20->0x004c6db0 +0x34->0x004c8210 +0x44->0x004c73b0 +0x48->0x004e3ed0 +0x70->0x004c76e0 +0x90->0x004dca40 +0xa8->0x004c9610 +0xb8->0x00476560
     ctl +0x04 0x1a3ee6c0 +0x14 0 +0x50 0xde6ee78 +0xa4 0 +0x758 0
  door CToeDoor         id ..<. at (-462.7, 488.8, 0.4) 561 away
  save CToeSavePoint    id ...` at (-223.8, -113.1, 97.6) 89 away
   CToeDoor           id ..<. at (-462.7, 488.8, 0.4): p20 1 coll 0 gates (0, 0, 0) radius 200.0
    its vtable 0x656254: +0x1c->0x00476560 +0x20->0x005e3b10 +0x34->0x0042a480 +0x38->0x0042a6f0 +0x70->0x0042c2b0
   tp -> ok settled at (-439.31, 422.84, 1.13) after 0.8 s
   press A (1/3)  nothing: level I100 mode 1 pos (-439.3, 422.8, 1.1) +0x73c 0x0
   ... (3 A presses, then the same at the save point: all "nothing")
```

OBSERVED: `controller+0xa4 = 0` (scan gate 2 passes), `character+0x2bc = 0` (gate 1 passes),
`anim = 0`, `life = 100`, `character+0x880/+0x884 = 0`; the door's own fields are eligible; and **A
does nothing at 70 units from both a door and a save point**. Note the character's forward at that
moment was `(-1.000, -0.018, 0.000)` while the door's direction is `(0, 1, 0)` - see §2.2.

### 2.2 `run_f1` — solo, slot 01, the same door: the facing numbers (OBSERVED)

`probe_face.py` (new) stands 60 units off the door and sweeps the eight stick directions, printing
everything both checks read (`entity+0x24`, `+0xb8`, the distance, and the two dot products; the
second one is `dot(character forward, door+0x13c..0x144)`):

```
door CToeDoor id ..<. at (-462.7, 488.8, 0.4)
   entity +0x24 0x1 +0xb8 0x0 ... ent dir (-0.000, 1.000, -0.000)
   after tp   dist2d 60.0 d3 60.0 | fwd (-1.000, -0.018, 0.000) | dot(char->target, fwd) +0.316  dot(fwd, ent+0x13c) -0.018
   up move 29 dist2d 57.3 | fwd (-0.070, 0.998, 0.000) | dot(char->target, fwd) +0.974  dot(fwd, ent+0x13c) +0.998
   right   dist2d 209.7 | fwd (0.992, -0.123, 0.000) | dot(char->target, fwd) -0.986  dot(fwd, ent+0x13c) -0.123
   ...
```

OBSERVED: the character's forward vector at `+0x248/+0x24c/+0x250` is a unit vector and tracks the
walk direction; at 57 units while facing the door **both dot products are ≈ +0.98**, i.e. every
condition of the door's `FUN_0042a480` holds at that instant.

### 2.3 `run_u1` — solo, slot 01: face the door, then press A (OBSERVED)

`probe_use.py` (new): for each of the eight stick directions it teleports back to 55 units, holds the
stick 0.35 s (turn), reads the dots, presses A for 0.45 s and watches mode / level / world / position.

```
== door: CToeDoor id ..<. at (-462.7, 488.8, 0.4), 561 away
   entity +0x24 0x1 +0xb8 0x0 +0x14 0 +0x150 0x21042104 +0x15c 0x21042104 +0xa0 200.0
   up        d2   37.6 d3   37.6 dot(char->t, fwd) +0.999 dot(fwd, entdir) +0.997 | char (-460.8, 451.3, 0.1)
   up-right  d2   41.5 ... dot +0.422 dot(fwd, entdir) +0.768
   ...
   result for the door: None
```

**Same result with A pressed while facing the door at 37.6 units.** So facing alone does not explain
it, and the scan's own gates are the remaining suspects (§1.2: `controller+0xa4` = 0, so the type-1
pass runs; the one gate not yet measured live is `character->vtable+0x90(2)` = `FUN_004dca40(2)`,
whose case-2 branch also tests `character+0x270`, `character+0x2c4` and a `FUN_004f1ee0` lookup).

The save point test in the same run could not complete: the mod's safe `tp` **refused** the target
(`refused: no floor at (-241.1, -60.9, 97.1) - the character fell 97.0 units (z 0.1)`), so the sweep
ran from wherever the character already was. The I100 save point sits 97 units above the floor - its
`+0x24` is 1 and `+0x150` is 1, but `entity+0x14 = 3`, which `FUN_0046e6c0` requires to be 0, so this
save point is refused by the game's own check in this world (DERIVED).

### 2.4 `run_dp1` — the PAIR flow, save 01 (I100), host's player 1 at the door

`tests/check_door_pair.py` (new), `run_pair.sh` (host loads save 01 through the game's own menu:
`start_save.py` presses A/DOWN/A ... Load a saved game ... slot 01), then the same sweep on the host:

```
   door CToeDoor id ..<. at (-462.7, 488.8, 0.4): +0x24 0x1 +0xb8 0x0 +0x10c..0x114 (-408.7, 488.8, 0.4) +0x13c..0x144 (-0.000, 1.000, -0.000)
   up         d2   37.8 d3   37.8 dot(char->door, fwd) +0.996 dot(fwd, doordir) +0.989 pos (-460.3, 451.1, 0.1)
   ...
   door result: None
```

OBSERVED: pair or solo makes no difference at this door, and the character state of both copies is
identical in every field the scan's gates read (`controller+0xa4 = 0`, `character+0x230 = 0`,
`+0x2bc = 0`, `+0x2c4 = 0`, `anim = 0`). So the gate that fails is not in the character's own state.

## 3. All ten slots: the interaction DOES work, and the game disables some doors (OBSERVED)

`tests/probe_slots19.py` (new): one host copy, all ten save slots in one launch. For each slot it stands
the character 40 units from the door's **anchor +0x10c** *facing it exactly* (`tp` takes `dx dy` and
writes `character+0x248/+0x24c`), presses A, and reads the entity's own **use field `+0xc4`** (the use
function `FUN_0042c2b0` stores the character there). A door use need not change the level, so this is
the only reliable sign - and what TASK 18 watched (level / world / position) cannot see it.

```
    1  I100  door no         save no         0/0/0
    2  I015  door no         save no         0/0/0
    3  D003  door -          save no         0/0/0
    4  J002  door USED       save no         0/0/0
    5  J005  door no         save no         0/0/0
    6  G003  door -          save no         0/0/0
    7  H000  door -          save -          0/1/0
    8  H006  door USED       save no         0/0/0
    9  I004  door USED       save no         0/0/0
   10  I007  door no         save no         0/0/0
```

**A door after a save load works** (J002 `CToeDoubleDoor`, H006 `CToeDoor`, I004 `CToeDoor`: the
entity's `+0xc4` became the character pointer). What the three working doors had in common: the
character stood inside the **80-unit reach of `+0x10c`** and its forward vector pointed at the door
(`dot(forward, door+0x13c..) >= 0.5` - the check's own condition).

**Two of the failing doors are disabled by the game, not by us** (OBSERVED): the I007 door (slot 10,
the level TASK 18 could never open) has **`+0x24 = 0`**, and `FUN_0042a480` returns 0 on its first line
when `entity+0x24` is 0; I015's door is the same (`+0x24 = 0`). So that door is not usable for anyone in
that save, however the character stands.

**The other two failures are unexplained** (UNKNOWN): I100's and J005's doors have `+0x24 = 1`,
`+0xb8 = 0`, the character 37-40 units from the anchor with the dot at +0.97..+1.00, and the door is
still not taken. The remaining difference must be inside the scan's own gate
`character->vtable+0x90(2)` = `FUN_004dca40`, whose case 2 looks up level objects
(`FUN_0045f540(0x424f4952)`, `FUN_0045f540(0x54555242)`) and returns 0 when one is present - i.e. a
per-level "character may not act" switch (DERIVED, not proven).

**Save points never fired in any of the ten slots.** Every `CToeSavePoint` reads `+0x24 = 1`,
`+0xb8 = 0`, `+0x150 = 1`, `+0x14 = 3`, direction `(0,0,0)`; the character was put 40 units away facing
it. `FUN_0046e6c0` wants `dot(unit(character -> entity), forward) > 0.5` in 2-D, which the door-side
placement satisfied for the doors. Whether `+0x14` (3 in every save point, 0 in every door) is also a
gate was not settled: the decompile tests `entity+0x14 == 0`, but the disassembly of 0x46e6c0
(0x46e6c0-0x46e760) shows no `0x14(%esi)` compare (UNKNOWN).

## 4. The fix (harness, not the game)

`tests/play_forward.py` (TASK 17/18's walker) now:

* treats a door's goal as its **interaction anchor `+0x10c`** (printed: 54-90 units off the rendered
  position in the levels measured) instead of `+0x6c`, and stops 45 units from it - inside the 80-unit
  reach;
* calls the new `Walker.face(target)` before every A press: it nudges the stick toward the target and
  reads `character+0x248/+0x24c` (the forward vector) until `dot(unit(target - pos), forward) >= 0.6`.
  The TASK 17/18 walker pressed A without ever guaranteeing the facing, and a character that stops
  walking sideways never qualifies (both checks want 0.5);
* reads `used_by(rec)` = `entity+0xc4` after each press and reports
  `used (door opened, level unchanged)` - the TASK 18 criterion could not see a door that opens
  without a level change.

`tests/probe_door.py`'s diagnostic (`character+0x73c`) is wrong for doors (§0/§1.3) and its successor
`tests/probe_door2.py` / `probe_slots19.py` use `entity+0xc4` instead.
