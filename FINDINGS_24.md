# FINDINGS 24 — the controller map is the owner's own map; item use (healing) sync (TASK 24)

Labels: **OBSERVED** = printed by a run/check in this task (log quoted) or read in the decompile/exe
(address cited); **DERIVED** = follows from the cited code/data but was not observed live; **GUESS**;
**UNKNOWN**. Decompile line numbers refer to `local\decomp2\Obscure2.exe.c`.

Branch `w/combat` (HEAD 1b2089b) + this task's uncommitted changes. Sections are appended as the work
goes; the DONE / NOT DONE / UNKNOWN list is at the end.

## 1. The .ipt format (OBSERVED)

Decoded by parsing the two files that exist and checking that the parse consumes them exactly. The
decoder is `tests/ipt_table.py`; its output for both maps is `ipt_tables.log`.

```
u32 version        1
u32 action_count   200
per action slot (200 of them):
    u8  bound      0 = no binding, 1 = one binding follows
    u32 device     1 keyboard, 2 mouse, 3 gamepad 1, 4 gamepad 2
    u32 code       pad: 1003-1014 = the six analog axes +/- (FUN_0059b4f0 switches on exactly these
                   12 codes and returns "axis, pair"), 1015-1030 = buttons
                   keyboard: DirectInput scancodes, mouse: 1003+ button/axis codes
```

* **Action slots are grouped 0x28 (40) per player**: `FUN_004a2b50(param_1, ...)` clears
  `param_1 + 0 .. param_1 + 0x26` for `param_1` = 0 or **0x28** (decompile 97414-97431), and
  `FUN_004cf940` reads a character's actions as `FUN_0059b3e0(in_ECX[5] + N)` with player pairs
  9/0x31, 10/0x32, 1/0x29, 0x1b/0x43 — i.e. **+0x28**. So slots 0x00-0x27 are player 1,
  0x28-0x4f player 2, and 0x50+ are global/menu actions (0x51 INV_NEXT, 0x52 INV_PREV, 0x53, 0x54,
  0x59, 0x73 — the dialog at decompile 97452-97468 enumerates exactly those; the name strings sit in
  the pool at 0x662348 in that order).
* **The live map is little-endian, 724 bytes**: `<exe>\coop_profile\remote\o2.ipt`, read through the
  Steam RemoteStorage hook (`obscoop.log`: `remote FileRead o2.ipt (724) -> 724`). 8 + 200 + 62*8 = 704
  bytes, plus **20 trailing bytes** `03 00 00 00 04 00 00 00 00 00 00 00 00 00 00 00 03 00 00 00` (the
  two pad device numbers 3 and 4 as the first two words — DERIVED reading; the game ignores them here,
  it stops after the declared 200 slots).
* **The game's shipped default `data/o2_input.ipt` is BIG-endian, 728 bytes**, 65 bindings, and parses
  exactly to the last byte with zero trailing data. Its player 1 block is byte-for-byte the same
  bindings as the live map's player 1 block; its player 2 block is keyboard + mouse, not a pad.

Both tables are in `ipt_tables.log`. Summarised:

| | live o2.ipt (what the game loads) | data/o2_input.ipt (shipped default) |
|---|---|---|
| bindings | 62 | 65 |
| player 1 (0x00-0x27) | 28 pad1 bindings, codes 1003-1030 | **identical 28 pad1 bindings** |
| player 2 (0x28-0x4f) | 28 pad2 bindings (device 4), same codes as player 1 | 29 keyboard + 8 mouse |
| global (0x50+) | 6 keyboard (218-222, 228) | same 6 keyboard |

## 2. Does the mod's map bind ATTACK? (OBSERVED — and the map is not the problem)

**The file the mod seeds is byte-identical to the owner's real in-game map.**

```
md5 692ada3a309d6d9671b98b3e1b0fa11f  C:/Program Files (x86)/Steam/userdata/65661493/254480/remote/o2.ipt
md5 692ada3a309d6d9671b98b3e1b0fa11f  package/obscoop2-test-1.2/obscoop_o2.ipt
md5 692ada3a309d6d9671b98b3e1b0fa11f  obscure2-test/coop_profile/remote/o2.ipt
md5 692ada3a309d6d9671b98b3e1b0fa11f  obscure2-test2/coop_profile/remote/o2.ipt
```

(724 bytes each, zero differing bytes.) The userdata copy is the file the owner's *real* game reads and
writes for the profile they play with — the profile in which, per GAME_MECHANICS.md, **hold LB + press A
attacks**. So:

* **The seeded map binds attack exactly as the owner's working game does.** It cannot be "missing the
  attack binding": it is the same file, and it is the file in use during the tests (the profile copy is
  identical and the game logged reading it).
* **Player 1's block is identical to the game's own default** (`data/o2_input.ipt`), so the mod neither
  loses nor moves any player 1 binding; the only thing the mod's map changes against the shipped default
  is **player 2: keyboard/mouse → gamepad 2 (device 4)**, with the same button codes as player 1. That
  is deliberate and needed for co-op (the guest's player 2 must use a pad).
* The game does **not** build pad bindings at runtime: the pad bindings are in the file (device 3,
  codes 1003-1030) and are the same in both files. Nothing about XInput is inferred by the game.

FINDINGS_23 §4's "89 gamepad codes vs 15" is a **byte-pattern count, not a binding count** — parsed by
structure (above), the two files have 28 pad1 bindings each. That finding's conclusion ("the map is the
gamepad map, so the missing gamepad bindings are not the explanation") holds, but for a stronger reason:
the map is the owner's own working map.

### Where the seeded map came from (OBSERVED, git)

The seeding code is `src/obscoop2.c` (FINDINGS/git): the comment says *"the game starts with keyboard
controls, but co-op needs the gamepad map. A file obscoop_o2.ipt next to the exe is copied to the
(redirected) cloud save o2.ipt if there is none yet."*

```
git log --oneline -S "obscoop_o2.ipt" --all
1b2089b WIP Obscure II: level change on the game thread, ... attack input still not starting a swing
54f5932 WIP Obscure II: frozen world was the bot's D-pad, ... attack input still unknown
6704c30 WIP Obscure II: host-owned enemy life/death in the NPC stream (protocol 10), ... fight not proven
6fedf29 Window title status, Steam counters, shipped gamepad input map; Steam test build 0.2
```

The file itself arrived with **6fedf29** ("shipped gamepad input map", 2026-10-25 20:23) and is the
owner's userdata `o2.ipt` (dated 2026-10-25 18:29, i.e. older than the commit) copied into the package.
**So the map was not hand-written by the mod: it is the owner's real, working map.**

### Conclusion for part A

There is **nothing to fix in the map**: it is the owner's own map, player 1's block is the game's
default, and the only difference against the shipped default (player 2 on pad 2, device 4) is exactly
what co-op needs. The "LB gives the aim stance but no swing" result of FINDINGS_23 is therefore **not**
a binding problem, which is the task's stated fallback ("If the map is fine and still no swing: write
that down ... and go to Part B"). The live solo probe below re-checks the attack anyway.

## 3. The live solo probe in J001 (OBSERVED)

`sh tests/run_solo_slot.sh chk24.dll 1 <scratch probe>` (1 game process, `run_a24_probe2.log`). The
probe loads save 01 (game1.sav), runs the pipe `level J001 317 1`, teleports player 1 12 units from the
80-HP `CCharacterNPC`, proves the pad reaches the game, then tries the buttons.

Two things were wrong in the first attempt (`run_a24_probe.log`) and are worth recording:

* The probe sampled `humans[0]` of the world's human manager (`world+0x175c`) — in this save that is
  **BOY1**, while the character the pad and the pipe `tp` drive is **BOY2** (the mod resolves player 1
  as `world+0x1748` controller array `+4 + 0x764*0`). With the wrong character sampled, the run showed
  `anim max 0x01` for every button and looked like "the pad does nothing".
* With the right character (v2, quoted below) the pad demonstrably works.

```
== humans (manager list vs the controller the mod uses)
   mgr[0] BOY1   CCharacterHuman anim 0x0 at (-707.3, 907.2, 0.7)
   mgr[1] BOY2   CCharacterHuman anim 0x0 at (-793.6, 907.2, 0.7)
   controller[0] -> 0x1c6abc78 BOY2   CCharacterHuman anim 0x0 life 100.0 at (-793.6, 907.2, 0.7)
   controller[1] -> none

== tp player 1 next to it (1560.5 units away): ok settled at (354.04, -132.38, 27.66) after 0.8 s
   player 1 at (354.0, -132.4, 27.7) -> 12.0 units from the enemy | anim 0x0

== is the pad reaching the game at all? (solo run, virtual pad 0 only)
   stick up 0.7 s: player 1 moved 164.99 units
   LB held 0.8 s: anim max 0x0 (0x64 = the aim state) ws 0x0

== attack attempts (enemy life before 80.0)
   LB + A (owner chord)         life  80.0 ->  80.0 (drop  0.0) anim max 0x64
   LB + A held 1.4 s            life  80.0 ->  80.0 (drop  0.0) anim max 0x64
   A alone 0.8 s                life  80.0 ->  80.0 (drop  0.0) anim max 0x0
   LB + B                       life  80.0 ->  80.0 (drop  0.0) anim max 0x64
   LB + RB                      life  80.0 ->  80.0 (drop  0.0) anim max 0xc8
   LB + X                       life  80.0 ->  80.0 (drop  0.0) anim max 0x64
   LB + Y                       life  80.0 ->  80.0 (drop  0.0) anim max 0x64

== final
   enemy live on copy: 80.0 (started 80.0)
   player 1 anim 0x0
RESULT: no pad input damaged the enemy
```

* The pad works in a solo copy (165 units of stick movement), so the virtual pad is not the problem.
* **LB really does put the character into the aim state** (`+0x2dc = 0x64`) — confirmed again, now on a
  character whose pointer is the one the pad drives. `A` alone gives `0x00`; `LB+A` gives `0x64` and
  nothing more; `LB+RB` gives `0xc8` (FINDINGS_23 saw that too).
* **No button damages the enemy**: 7 combinations, life 80.0 throughout, weapon state 0.

This is the task's stated fallback: the map is fine (it is the owner's own map, section 2) and the swing
still does not happen, so the level-jump / inactive-enemy explanation stays open and Part B is next.

Two things left open by this section, and their status after the probe:

## 4. The item-use path (OBSERVED in the decompile)

**Use = the item object's vtable slot 28 (byte `+0x70`), called with the character.** Two wrappers do
nothing else: `FUN_0044f800` (energy drink) and `FUN_00450b90` (medikit) are
`if (param == 0) return 0; (*(*in_ECX + 0x70))(param); return 1;`. The slot is confirmed by address:
the energy drink's constructor `FUN_0044f550` sets vtable `0x65969c` (decompile 45807-45808) and its
use function `FUN_0044f6c0` is the dword at `0x65970c` = `0x65969c + 0x70` = slot 28; the medikit's use
`FUN_00450aa0` sits at `0x659ffc` = slot 28 of its vtable (`0x659f8c`).

**Medikit `FUN_00450aa0` @ 0x450aa0** (decompile 46972-47000), thiscall on the item, `param_1` = the
character:

```c
if (param_1 != 0 && (float)param_1[200] < (float)param_1[199]) {   // life +0x320 < max +0x31c
    ... low-life voice line when param_1[3] (+0xc) == 1 and the key is not held ...
    (**(code **)(*param_1 + 0x24))(fVar1 * 0.6);                   // character vtable slot 9: life += max*0.6
    *(int *)(in_ECX + 200) = *(int *)(in_ECX + 200) + -1;          // item +0xc8 (quantity) -= 1
    FUN_00591230(0x4d444b54, ...);                                 // game event / sound
}
```

**Energy drink `FUN_0044f6c0` @ 0x44f6c0** (decompile 45882-45910) is the same with **0.3** and one extra
`FUN_00401340("energy_drink_stat")`. So:

* the heal goes through **character vtable slot 9 (+0x24)** — the same method `npcset` uses, with a
  *delta* argument (40 HP + 60 → clamped to 100 at `+0x31c`), and
* **the whole body is guarded by `life < max`**: a use at full life neither heals nor consumes. Two uses
  in a row therefore cannot consume two items unless the first heal left the character below max
  (e.g. 10 HP + 60 = 70 → a second medikit *would* be consumed).
* **quantity** is item `+0xc8` (ITEMS_FINDINGS §1), decremented once per use.

**The inventory** (`world+0x1790`, vtable 0x665844): count at `+4`, 32-byte entries at `+8`.
`FUN_004b04a0(tag, id, 0)` returns the entry of a tag; `FUN_004b1000` adds `item+0xc8` into
**entry `+0xc`**, so an inventory entry's stack count is its `+0xc` dword. The host already mirrors the
whole entry array to the guest (`PKT_ITEM`, sync.c `host_send_item`/`guest_apply_item`).

**How the pad opens the item menu** (DERIVED from `FUN_004cf940`, decompile 126669-127000): the human
controller stores the bound action objects in `in_ECX[0xf..0x28]`, with
`in_ECX[0x18] = FUN_0059b3e0(in_ECX[5] + 0xe)` — i.e. **action block+0x0e** (action 14 for player 1).
When that action is down (`*(obj+0xc) != 0`) the controller raises its UI state `in_ECX[0x29]` to **4**
(the item menu; 3 is the weapon wheel) and calls
`FUN_00551b70(character, inventory, state == 4)` → `FUN_00551040` → the inventory panel, which stays
open while `*(world+0x17a0)+0xa8 < 0x5dc` (1500 = the ~1.5 s the guide describes). The mouse wheel
actions `block+0x0f`/`block+0x10` (device 2) open it too. In the owner's map action 14 is bound to
`pad1` button code **1029**, and `INV_NEXT`/`INV_PREV` (slots 0x51/0x52) are bound to the keyboard only
(218/219) — on the pad the menu cycles by itself (GAME_MECHANICS: 0.2 s per item).

**Test-only pipe command added for the measurement**: `charset <0|1> <life>` applies a life value to a
player character through the same vtable slot 9 (`charset 0 40` makes player 1 injured so a 60-point
medikit heal is visible and so the `life < max` guard lets the use through).

* **UNKNOWN**: which action slot is "attack" (the exe has no per-action name table I could pair with
  the slot numbers; the names in the config dialog come from the pool at 0x662348, which is ordered by
  key, not by action).
* **UNKNOWN**: whether player 2's pad-2 bindings (device 4) reach the guest's pad at all — FINDINGS_23
  saw the guest's player 2 keep `+0x2dc = 0` (not even the aim stance) with LB held.

## 5. Which button is which action slot (OBSERVED)

The controller keeps the bound action objects at fixed int offsets of the human input controller
(`world+0x1748 + 0x764*player`), so they can be read live with the pointer table from `FUN_004cf940`
(§4). Probe `probe_item24b` pressed one button at a time and dumped the slots whose value went non-zero
(`run_b24_disc2.log`):

```
   A      slots [9]        ui state 0        LB     slots [11]       ui state 1
   B      slots [10]       ui state 0        RB     slots [12]       ui state 0
   X      slots [13]       ui state 0        RT     slots [14]       ui state 0
   Y      slots [34]       ui state 0        LT     slots -          ui state 0
   UP     slots [16, 27]   ui state 3        BACK   slots -          ui state 0
   DOWN   slots [15, 29]   ui state 3        START  slots -          ui state 0
   LEFT   slots [30]       ui state 3        L3     slots -          ui state 0
   RIGHT  slots [28, 38]   ui state 3        R3     slots [36]       ui state 0
```

with the slots' bindings read from the action objects (`slot 9 code 1015 dev 3`, `10:1016`, `11:1021`,
`12:1022`, `13:1017`, `14:1029`, `15:1028`, `16:1025`, `27:1025`, `28:1027`, `29:1028`, `30:1026`,
`34:1018`, `36:1024`, `38:1027`). So **code 1015 = A, 1016 = B, 1017 = X, 1018 = Y, 1021 = LB,
1022 = RB, 1024 = R3, 1025 = UP, 1026 = LEFT, 1027 = RIGHT, 1028 = DOWN, 1029 = RT**. LT, BACK, START
and L3 drive no per-player gameplay slot (BACK/START are the menu/pause buttons; LT does nothing here).
`LB` raises UI state 1, the D-pad raises state 3 (the weapon wheel), RT and the rest leave it at 0.

## 6. Item use on two copies: measurement and the fix (OBSERVED)

### 6.1 What already worked

`charset <0|1> <life>` (new, test-only, §4) applied through the character's own life method reaches the
other copy through `ch_state`: `life host 30.0 / guest 30.0` one second after the host's call
(`run_b24_measure.log`, `run_b24_fix3.log`). So character life is already synced host -> guest.

### 6.2 The item menu could not be driven from a test copy (OBSERVED, open)

The item menu is UI state 4, raised by player action slot 0x0e (code 1029 = **RT**, §5) and holding the
inventory (`FUN_00551b70(character, world+0x1790, state == 4)`). On a test copy, holding RT and pressing
A did **not** consume an item; instead the controller's UI state ended at **3** (the weapon wheel) on
both copies and stayed there:

```
   after the use   life host 30.0 / guest 30.0 | MEDI 6/6 ENDR 5/5 | ui 3/3
  !!! the medikit heal is 0.0, expected 60
  !!! the item menu is still open after the medikit (host 3 guest 3)      (run_b24_measure.log)
```

**UNKNOWN**: how a player's visit through the item wheel completes a use (which confirm button the panel
reads, and whether the wheel needs the character to be idle for longer). The test drives the **game's own
use method** instead (§4: item vtable slot 28), so what is measured below is the use path and its sync,
not the menu navigation.

### 6.3 The differences the measurement found (OBSERVED)

Two real gaps, both fixed in this task:

1. **A host use is not enough on its own — it already propagates, but a guest use is not applied at
   all.** With `useitem` called on the guest's copy before the fix, the use would be local only: the
   guest's inventory is a mirror of the host's (`PKT_ITEM`) and its character life comes from `ch_state`,
   so the next host snapshot restores both. The task's fix: the guest forwards `PKT_ITEMUSE`
   (new packet, NET_VERSION 11) and the **host** applies the use on its game thread — one owner, one
   consumption.
2. **A saved inventory item has no live item object.** `FUN_004b0980(tag)` (the game's lookup in the
   created-object list) returns 0 for MEDI, so the first version of the command answered
   `error useitem: no item object for MEDI (id 1)` (`run_b24_fix2.log`). The command now builds the
   object from the 32-byte inventory entry the way the inventory pass does (`FUN_0045cdd0` creates the
   class instance, `FUN_004b0300` copies flags/tag/id/**quantity** into it) and marks it collected
   (`+0xa8 = 1`) without registering it as a placed world item.

(The third bug found on the way was mine: the pipe command built the tag byte-reversed
(`MEDI` -> `IDEM`); tags are stored the way `tag4()` prints them, `MEDI` = 0x4d454449.)

### 6.4 The result (OBSERVED, run_b24_fix3.log)

```
== 1. host player 1 uses a MEDIKIT (life 30 -> 90 expected, one item)
   host charset 0 30 -> ok charset 0 character 1bee86d8 life 100.0 -> 30.0 (asked 30.0) max 100.0
   after charset (both copies)        life host 30.0 / guest 30.0 | MEDI 6/6 ENDR 5/5 | ui 0/0
   host useitem MEDI 0 -> ok useitem MEDI on player 0: life 30.0 -> 90.0 (max 100.0), count 6 -> 5
   after the use                      life host 90.0 / guest 90.0 | MEDI 5/5 ENDR 5/5 | ui 0/0

== 2. guest player 2 uses an ENERGY DRINK (life 40 -> 70 expected, one item)
   host charset 1 40 -> ok charset 1 character 1c0000e8 life 100.0 -> 40.0 (asked 40.0) max 100.0
   life p2 host 40.0 guest 40.0
   guest useitem ENDR 1 -> ok useitem ENDR on player 1: forwarded to the host (it owns the inventory and the life)
   life p2 host 70.0 guest 70.0 | ENDR 4/4 | MEDI 5/5 | ui p2 0/0
   heal 30.0 on the host for player 2 (40.0 -> 70.0)

== final
   player 1 life host 90.0 guest 90.0 | player 2 life host 70.0 guest 70.0
   inventory host 44 entries guest 44 entries | MEDI 5/5 ENDR 4/4
RESULT: item use OK (each use landed once on both copies, lives equal, inventories identical)
```

* medikit: **+60.0 life (30 -> 90)**, quantity **6 -> 5 on both copies**, inventories byte-identical.
* energy drink on the guest's player: **+30.0 life (40 -> 70)**, quantity **5 -> 4 on both copies**.
* **no double use**: one item per use on both copies.
* the item menu is not left open (UI state 0 on both copies).
* the check prints `life difference on 25 samples max 60.00` for phase 1: that is the convergence window
  (the guest learns the new life with the next `PKT_STATE`), not a settled difference — the settled
  comparison right before it and every assertion use settled values, like `check_combat.py`.

## 7. Regression (OBSERVED)

Game processes used: **15 of the task's 16** — 5 solo (Part A probe v1, probe v2 twice, two item-menu
discovery probes) and 5 pairs (measurement, three fix iterations, one regression pair). The task's
reserve was 6 for the regression list; the discovery of the item-menu path and three fix iterations used
more than planned, so the six-check menu suite (`run_pair_menu.sh ... check_party check_items
check_hands check_hands_visible check_entities check_movement`, 2 processes) was **not run** — the last
process would not have covered it. Reported as NOT DONE below.

1. `sh tests/run_pair.sh <chk24.dll> check_itemuse.py check_party.py check_items.py check_hands.py`
   (run_b24_fix3.log) — item use OK, and the trio after it:

```
party: host ['BOY1', 'GIR1'] guest ['BOY1', 'GIR1'] | inventory: host 44 guest 44
party OK
items: before host 44 guest 44
items: after host 45 guest 45
items OK
in hand: host [('BOY1', 'CBOW'), ('GIR1', 'CSAW')] guest [('BOY1', 'CBOW'), ('GIR1', 'CSAW')]
hands OK (2 characters checked)
```

   (check_hands prints `inventory: host 44 guest 45` there because check_items had just picked an item up
   on one copy a moment earlier; the hands it compares are equal — the same informational line as in
   FINDINGS_23 §7.)

2. `OBSCOOP_PICKUP_CLASS=MEDI OBSCOOP_PICKUP_SPAWN=1 sh tests/run_pair.sh <chk24.dll> pair_j003.py
   check_pickup.py` (run_reg24b.log):

```
phase host->guest: OK
phase guest->host: OK
pickup counters: guest {'sent': 1, 'rcv': 1, 'applied': 0, 'already': 1, 'missing': 0} | host {'sent': 1, 'rcv': 1, 'applied': 0, 'already': 1, 'missing': 0}
results: [('host->guest', True), ('guest->host', True)]
pickup OK: both directions collected on both copies, inventories match, no echo
```

   Both runs ended with no game left (`still running: []`) and
   `OWNER FILES UNCHANGED (apart from Steam remotecache.vdf)`.

## 8. DONE / NOT DONE / UNKNOWN

**DONE**

* **The .ipt format is decoded** (8-byte header + 200 slots of "1 byte + optional u32 device + u32
  code"), with the 40-slot-per-player grouping (`FUN_004a2b50` / `FUN_004cf940`) and the axis/button
  split of the pad codes (`FUN_0059b4f0`, 1003-1014 axes, 1015-1030 buttons). `tests/ipt_table.py`
  prints both maps; its output is `ipt_tables.log` (§1).
* **Part A's answer: the mod's map is the owner's own working map.** The seeded `obscoop_o2.ipt` is
  byte-identical (md5 692ada3a309d6d9671b98b3e1b0fa11f) to the `o2.ipt` in the owner's real Steam
  profile; player 1's 40 action slots are identical to the game's shipped `data/o2_input.ipt`, and the
  only difference against that default is player 2 on pad 2 (device 4) — deliberate and needed for
  co-op. **Nothing in the map needed fixing** (§2). The map arrived with commit 6fedf29 as the owner's
  userdata file, not hand-written.
* **The pad reaches the game in a test copy**: 165 units of stick movement, and LB+A really does give the
  aim state `+0x2dc = 0x64` (measured on the character the pad drives — the first probe sampled the wrong
  human, `humans[0]` = BOY1 instead of the controller's BOY2). **No pad button damages the enemy**:
  7 combinations on the 80-HP `CCharacterNPC` at 12 units, life 80.0 throughout (§3).
* **The item-use path in the decompile**: use = the item's vtable slot 28 (+0x70) with the character;
  medikit `FUN_00450aa0` heals maxlife*0.6, energy drink `FUN_0044f6c0` heals maxlife*0.3, both guarded by
  `life < maxlife`, both taking one from quantity `+0xc8`; the inventory entry's stack count is `+0xc`
  (§4).
* **The button -> action-slot map of the shipped pad map, measured live**: A=9, B=10, X=13, Y=34,
  LB=11, RB=12, UP=16/27, DOWN=15/29, LEFT=30, RIGHT=28/38, R3=36, RT=14; LT/BACK/START/L3 drive no
  gameplay slot; the item-menu slot 0x0e is **RT** (code 1029) (§5).
* **Item use is synced host-authoritatively** (new `PKT_ITEMUSE`, NET_VERSION 11): the host applies a use
  through the game's own method on the game thread; a guest's use is forwarded to the host instead of
  being applied locally and then reverted. `tests/check_itemuse.py` measures both phases on both copies:
  medikit +60 (30 -> 90), quantity 6 -> 5; guest's energy drink +30 (40 -> 70), quantity 5 -> 4; lives
  equal, inventories byte-identical, no double use, no menu left open (§6).
* Regression: party / items / hands and the MEDI pickup pair in both directions pass (§7).

**NOT DONE**

* **The six-check menu suite** (`run_pair_menu.sh` with check_party/check_items/check_hands/
  check_hands_visible/check_entities/check_movement) was not run: the task's 16-game-process cap was
  spent on the Part A probe and the item-menu discovery (15 used, 1 left, the suite needs 2).
* **The item use was not driven through the item menu with the pad.** RT+A left the controller in the
  weapon-wheel UI state (3) on both copies and consumed nothing, so the checks drive the game's own use
  method through the test-only `useitem` command. The pad flow through the wheel is therefore untested.
* **The attack still does not start a swing** (Part A's open question): with the owner's own map in
  place, LB+A gives the aim stance and nothing else. The level-jump / inactive-enemy explanation stays
  open, as the task anticipated.

**UNKNOWN**

* Which action slot is "attack" (the exe has no per-action name table that could be paired with the slot
  numbers) and therefore which bound button the game considers the attack; and why the game refuses the
  swing in J001 even with the aim state reached.
* How the item wheel completes a use with the pad: which action confirms it and why holding RT+A raises
  the weapon wheel instead of the item menu on a test copy (`in_ECX[0x1d4]` / character `+0xb3` gates the
  menu state and were not investigated further).
* Whether the wheel's *selected* item can differ between the two copies while a guest uses it (the wheel
  cycles every 0.2 s locally). With the pad replay the host applies its own selection, and `PKT_ITEM` +
  `ch_state` make both copies agree afterwards; not measured.
