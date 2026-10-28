# FINDINGS 21 — combat sync: enemy life/death/animation and player attacks (TASK 21)

Labels: **OBSERVED** = printed by a run/check in this task, or read in the decompile / `.tsv` (address cited);
**DERIVED** = follows from the cited code/data but was not observed live; **GUESS**; **UNKNOWN**.
Decompile line numbers refer to `local\decomp2\Obscure2.exe.c`, addresses to the test copy's
`Obscure2.exe` (image base 0x400000). Script-command handlers were resolved by reading the vtable the
script registration installs (`PTR_FUN_xxx` at the `FUN_0059f100("Name",…)` site) straight out of the
exe, slot 4 (slots 0-3 are the shared argument-fetching trampolines 0x4af860/0x59f090/0x59f2d0/0x59f370).

Status: decompile part done; live measurement and implementation below as they happen.

## 1. Life and max life: character +0x320 / +0x31c (OBSERVED in the decompile)

* **`CharacterGetLife` handler = `FUN_004c04d0` @ 0x4c04d0** (registration decompile 104453, vtable
  `PTR_FUN_006652d4`). Body (decompile 116334-116347):

  ```
  local_8 = *(undefined4 *)(*(int *)**(undefined4 **)(in_ECX + 0x18) + 800);   // 800 = 0x320
  ```

  So the script `CharacterGetLife` returns the float at **character+0x320** — the same field the mod
  already reads for humans (`sync.c:829`), and now confirmed for any character, NPC included.
* **`CharacterSetLife` handler = `FUN_004c0470` @ 0x4c0470** (registration decompile 104440). It computes
  `delta = wanted - (float)piVar1[200]` (`[200]` = +0x320) and then either the character's own
  `vtable+0x24` method (`if (piVar1[3] == 1)`) or **`FUN_004c6e10(delta)`**.
* **`FUN_004c6e10` @ 0x4c6e10** (decompile 121155-121166) is the plain life-add helper:

  ```
  life = param_1 + *(float *)(in_ECX + 800);        // +0x320
  *(float *)(in_ECX + 800) = life;
  if (*(float *)(in_ECX + 0x31c) < life)            // max life
      *(undefined4 *)(in_ECX + 800) = *(undefined4 *)(in_ECX + 0x31c);
  ```

  **life = float +0x320, max life = float +0x31c**. The clamps are to the max, so a negative delta
  (damage) goes through the same function and can reach <= 0.

## 2. Damage path: NPC hit handler → state machine → life delta → death (OBSERVED)

* **`CCharacterNPC::Hit` = vtable slot 21 @ 0x4fa170** (`vt_slots.c:15729` `CCharacterNPC_s21_v @ 004fa170`).
  Decompile 150900-151000. It is the *entry point* a weapon hit takes:
  * tracks **the character that hit me** in `in_ECX[0x1d4]` = **NPC+0x750** and a consecutive-hit
    counter in `in_ECX[0x1d5]` = **NPC+0x754** (decompile 150918-150934). `+0x750` is what the script
    command `NPCGetLastCharacterHitMe` (`FUN_004bd230`, registration decompile 103186, vtable
    `PTR_FUN_006633ac`) returns.
  * `param_2` = hit type, `param_3` = damage; the NPC reacts (`in_ECX[3]` = anim state, `in_ECX[0x1dc]`),
    then calls the base hit method `(**(code **)(*in_ECX + 0x50))(…)` = **slot 20 @ 0x4fa490**
    (`CCharacterNPC_s20_v`), which is the large hit/knockdown state machine (decompile 151007-…).
    Inside it, a life change is done by `(**(code **)(*in_ECX + 0x24))(-param_3)` = **vtable slot 9**.
  * Also present: `FUN_004a9250(0x34c0001x,1,0x5dc,param_1[4],0)` — a feedback event keyed on the
    attacker's entity id and a fixed id (`0x5dc`), not needed for sync.
* **`CCharacterNPC` life-change method = vtable slot 9 @ 0x4f5bf0** (`CCharacterNPC_s9_v`), decompile
  148235-…:

  ```
  FUN_004c6e10(param_1);                              // life += delta, clamp to max
  if ((float)in_ECX[200] <= 0.0) {                    // life at +0x320 <= 0
      ... (**(code **)(*in_ECX + 0x184))(3);          // change state -> death (state 3)
      ...
  }
  ```

  So **the death decision is "life +0x320 <= 0"** inside the character's own life method, and it is
  entered from every source of damage because they all funnel through vtable slot 9.
* **Human counterpart = `CCharacterHuman_s9_v` @ 0x4da180**, decompile 132721-132737:

  ```
  if (in_ECX[0xb7] != 5) {                            // not already dead (0xb7 = +0x2dc)
      if (*(int *)(*(int *)(DAT_006c3068 + 0x378) + 0x18c) == 0)
          FUN_004c6e10(param_1);                      // life delta (god mode gate at world+0x18c)
      if ((float)in_ECX[200] <= 0.0)
          (**(code **)(*in_ECX + 0x48))(5);           // state 5 = dead
  }
  ```

  **Dead marker for both races: character+0x2dc (`in_ECX[0xb7]`); NPC dies into state 3 / human into
  state 5, and the NPC state at +0x2dc also gates its AI (`in_ECX[3]` values 4/7/8/0xb/0xc in the hit
  machine).** The mod already streams `+0x2dc` as `anim` for humans (`net.c:35`).

## 3. The player's attack start (melee swing) (OBSERVED)

* **`FUN_004563a0` @ 0x4563a0** (decompile 50603-50700) is the swing/attack start of the melee weapon
  controller: it picks the hit points 90 units ahead of the character (fallback 30 units), plays the
  **"attack" animation event** (`FUN_0053f9c0("attack")`, `+0x14` = 1), takes the character's impact
  manager (`param_1[0xc3]`), sets `param_1[0xaf] = in_ECX` and the character state `in_ECX+0x14 = 4`
  and requests anim state `0x899` on the owner character (`(**(code **)(*param_1 + 0x48))(0x899)`).
* **`FUN_00456710` @ 0x456710** (decompile 50713-50760) is the swing end: it clears the "attack"
  event (`FUN_0053f9c0("attack")` → `+0x14 = 0`), removes the impact-manager owner and moves the
  controller to state 5; also resets the character's `+0x2bc` (`+700` field of the character).
* Registration site of the animation event: `strings.tsv:627-628` (`attack` at `FUN_004563a0` and
  `FUN_00456710`). Two more attack-like strings at `FUN_00509f70` / `FUN_00510810` are the ranged
  weapon path (`strings.tsv:1745-1755`), not chased further.
* **DERIVED**: the swing itself is player-local animation state; the *effect* on an NPC is the
  `CCharacterNPC::Hit` call in §2. Both copies simulate the same pads, so both copies run their own
  `FUN_004563a0` for the same press — the question is only whether the hit lands at the same time and
  on the same enemy. Measurement below answers that.

## 4. Enemy AI state and target (PARTIAL)

* **AI controller pointer = character+0x30c** (`in_ECX[0xc3]`), and its state is written by
  `FUN_004f61e0(param)` @ 0x4f61e0 (decompile 148436-148445): `*(int *)(*(int *)(in_ECX + 0x30c) + 0x98) = param`.
  The NPC hit machine calls it with 2 and 5 (decompile 148860, 150931, 152312, 153514, 164474) — so
  **controller+0x98 = AI state**. DERIVED from those writes; the exact state numbering is UNKNOWN
  (2/5 seen in the hit/death paths).
* **Target / last attacker = character+0x750** (`in_ECX[0x1d4]`), the character that last hit the NPC,
  and **+0x754** its consecutive-hit counter (OBSERVED in `FUN_004fa170`, decompile 150918-150934).
  `FUN_004f6280` (decompile 148456-148468) reads `controller+0x90 → +0x18 == 1 → returns +0xe4`, a
  pointer used as the AI's current object of interest; its meaning is UNKNOWN without more work.
* Not chased further (step budget): the full AI state enum and whether the AI target pointer is also
  written elsewhere. The measurement below records what is readable and what differs between copies.

## 5. Measured: two copies in J001 / J000 (OBSERVED, run_meas1/2/3, run_inp1/2, run_c1/c2)

Both copies were started by `tests/run_pair.sh` (duo: host `obscure2-test`, guest `obscure2-test2`,
save 01 = I100), then the HOST requested the door destination and the guest followed within 1 s.

### 5.1 Both copies hold the same enemies (OBSERVED)

`level J001 317 1` → both copies J001 (mode 1) after 1.0 s, party placed at (-793.6, 907.2, 0.7).
Per enemy, matched by class + nearest position, host | guest (run_c2.log):

```
  CCharacterNPC          .... host (362.9, -140.4, 27.7) life   80.0 st      0x0 | guest same life 80.0 st 0x0
  CCharacterNPCProgeny   .... host (607.6, 531.4, 12.7)  life    1.0 st      0x0 | guest same life  1.0 st 0x0
  CCharacterNPCProgeny   .... host (162.9, 329.5, 27.7)  life    1.0 st      0x0 | guest same life  1.0 st 0x0
  CCharacterNPCProgeny   .... host (919.0, -524.7, 0.7)  life    1.0 st      0x0 | guest same life  1.0 st 0x0
  CCharacterNPCProgeny   .... host (-731.2, 659.3, 0.7)  life    1.0 st      0x0 | guest same life  1.0 st 0x0
  CCharacterNPCProgeny   .... host (-968.6, -296.6, 0.7) life    1.0 st      0x0 | guest same life  1.0 st 0x0
  CCharacterNPC          ...A host (23.2, 415.1, 27.7)   life   80.0 st      0x0 | guest same life 80.0 st 0x0
```

`level J000 314 1` → both copies J000, 2 `CCharacterNPCRam`, life 120.0/120.0 each, identical
positions on both copies ((-513.0, -409.2, 15.5) and (-654.6, 426.2, 15.4)).

* **Position drift today: 0.0 units** before any fight (the existing PKT_NPC position sync does its job).
* **Life and state: identical because nothing has damaged them yet.** Before this task the NPC packet
  (`npc_state` in net.c) carried only class, tag, position and facing — **life (+0x320) was NOT streamed**,
  so the identity above is "both copies simulate the same HP", not sync.
* The enemies never moved during 40 s (positions byte-identical), and their AI/controller state
  (`controller+0x98`, §4) stayed 2 on both copies.

### 5.2 The combat levels give the player no control (OBSERVED — the blocker)

In J001 and again in J000 (run_c2.log):

```
control probe: player 1 best 1.2 s stick displacement 0.0 units
   tp host player 1 next to it: ok settled at (342.18, -121.64, 27.66) after 0.8 s
   X   enemy life 80.0 -> 80.0  last attacker .  state 0x0  player anim 0x0
   B   ... Y ... A ... LB ... RB ... RT ... LT  (all unchanged)
```

* `tp` works in these levels (the game thread runs, the safe tp settles).
* The pad is polled and delivered: `stats` shows `polls 2163 2163 2163 2163 virtual 1711 2134 0 0`
  and `padshow` shows `vpad1 … on 1` — the game reads the virtual pad.
* Yet **no stick direction moves player 1** (0.0 units over 1.2 s, all four directions) and **no button**
  (A, B, X, Y, LB, RB, both analog triggers) damages the enemy or changes the player's state; START does
  not pause either. So these two story levels sit in a scripted state that disables the player's control
  (`FUN_004cf940`, the character controller's input update, returns early when its `in_ECX[0x1d6]` is
  non-zero — decompile 126669-126690; DERIVED that this is the flag the level's intro sets).
  J003 (TASK 20) does give control: its A press collected the item, and its `level` replay is the same
  call — so this is the level, not the level-change path.
* Consequence: the task's real-swing proof (host hits enemy A, guest's player 2 hits enemy B) cannot be
  driven in J001/J000 with this harness. The check below therefore also falls back to the game's own
  save 06 (H000), a save-loaded world where TASK 18 measured the pads moving the characters.

### 5.3 What the new sync does (OBSERVED, run_c2 `sync` output)

After the level changes, with the new packet (`life`/`state` fields, NET_VERSION 10):

```
guest sync: … | npc sent 0 rcv 1700 applied 5744 snaps 0 blends 0 unmatched 0 life 1 dead 1 state 1 | …
```

The guest applied **one life correction, one death and one death-state write** during the run: some
enemy's life differed between the copies (a `CCharacterNPCProgeny` with 1 HP; its host copy reached 0
first), and the guest converged through the game's own life method (§6). Host `life 0 dead 0 state 0`
is expected (the host is the owner and never applies).

## 6. The fix: host-authoritative enemy life / death / state (IMPLEMENTED, m22.dll)

Smallest change, one owner:

* **Packet** (`net.c`): `npc_state` gains `life` (the float bits of character+0x320) and `state`
  (character+0x2dc, the same AI/death field the humans stream as `anim`). `NET_VERSION` 9 → 10 with the
  reason in the version comment.
* **Host** (`host_send_npcs`, sync.c): fills both from every NPC in `world+0x1760` — nothing else changes;
  the host is the owner and never applies a snapshot.
* **Guest** (`guest_apply_npcs`, sync.c), for each NPC matched by class + nearest position (the existing
  match):
  1. `delta = host_life - guest_life`; if `|delta| > 0.01` call **the character's own life method**
     (vtable slot 9 = `+0x24`, exactly what `FUN_004c0470`/`CharacterSetLife` calls) with `delta`. That
     method is `CCharacterNPC_s9_v` @ 0x4f5bf0 → `FUN_004c6e10` (life += delta, clamp to max +0x31c) and,
     when life reaches <= 0, the game's own death path (state 3, anim/`+0x2dc`).
  2. when the host says the enemy is dead (`life <= 0`), write the host's `+0x2dc` too, so both copies
     show the same death state.
* **One owner, no double damage**: the guest **never subtracts damage**; it only moves its life to the
  host's value by the difference. A hit that both copies simulated is already in both lives, so the
  difference is 0 and nothing is applied; a hit only the host simulated is applied once; a hit only the
  guest simulated is healed back to the host's value. Counters `life` / `dead` / `state` in `sync` show
  each application (guest: `life 1 dead 1 state 1` in run_c2, `life 1` in run_c3).
* **Player attack animation** needs no new code: `ch_state.anim` already carries human +0x2dc and
  `guest_apply_state` already writes it on the guest for both characters (sync.c:1267), so a swing that
  the pads drive on both copies shows on both. The check samples it (see §7) — it could not be exercised
  because no button reached the character in the levels tried.

## 7. Live runs (verbatim)

### 7.1 check_combat.py on the two-copy pair (run_c3.log, m22.dll) — COMBAT NOT PROVEN

```
== host level J001 317 1 -> ok
   waited 1.0 s for the level
arrived: host J001 (mode 1) | guest J001 (mode 1)
enemies host:  CCharacterNPC.... life 80.0 st 0x0, CCharacterNPCProgeny.... life 1.0 st 0x0, … (7)
enemies guest: CCharacterNPC.... life 80.0 st 0x0, CCharacterNPCProgeny.... life 1.0 st 0x0, … (7)
control probe: player 1 best 1.2 s stick displacement 0.0 units
   tp host player 1 next to it: ok settled at (342.18, -121.64, 27.66) after 0.8 s
   X   enemy life 80.0 -> 80.0  last attacker .  state 0x0  player anim 0x0
   B   enemy life 80.0 -> 80.0  last attacker .  state 0x0  player anim 0x0
   … (Y, A, LB, RB, RT, LT identical)
   no enemy could be hurt in J001 -> trying the next level
== host level J000 314 1 -> ok
…
control probe: player 1 best 1.2 s stick displacement 0.0 units
   … all eight buttons: enemy life 120.0 -> 120.0 …
== fallback: host loads save 06 (H000 …)
== host loadsave game6.sav (expecting H000) -> ok real load of "game6.sav" requested (the game thread runs it)
   waited 1.0 s for the load
arrived: host H000 (mode 1) | guest H000 (mode 1)
enemies host:  CCharacterNPCAura.... life 0.0 …, CCharacterNPC.... life 80.0 …, CCharacterNPCHomm.... life 200.0 …, CCharacterNPC.... life 80.0 …
enemies guest: identical
control probe: player 1 best 1.2 s stick displacement 0.0 units
   tp host player 1 next to it: ok settled at (-2332.83, 208.05, -0.97) after 0.8 s
   X/B/Y/A/LB/RB/RT/LT all: enemy life 200.0 -> 200.0
  !!! no enemy could be hurt in any combat level; the attack button was not identified
RESULT: no enemy could be hurt in any combat level -> combat not proven
sync host: … | npc sent 2389 rcv 0 applied 0 snaps 0 blends 0 unmatched 0 life 0 dead 0 state 0 | …
sync guest: … | npc sent 0 rcv 2389 applied 8287 snaps 0 blends 0 unmatched 0 life 1 dead 0 state 0 | …
```

OBSERVED in the same run: **the guest follows a host `loadsave game6.sav` within 1 s** (both copies
H000 mode 1) with identical enemy lists — the save-load path works for the pair.

The screenshots the check takes are black: the game renders nothing into its window while it runs
backgrounded (`duo.py` sets `OBSCOOP_BACKGROUND=1`); TASK 20 recorded the same for `probe_pause.py`.
No swing could be photographed because no swing happened.

### 7.2 The blocker, measured three times

`control probe: player 1 best 1.2 s stick displacement 0.0 units` appears in **every** level tried with
the pair: J001, J000 and the save-loaded H000 (run_c2.log, run_c3.log). The pad is polled and the
virtual pad is on (`stats`: `polls 2163 2163 2163 2163 virtual 1711 2134 0 0`, `padshow`: `vpad1 … on 1`),
the safe `tp` works in all of them, but no stick direction moves the character and no button (A, B, X, Y,
LB, RB, L/R trigger) changes anything — not even START (which opens the pause menu in TASK 16's probes).
The same DLL pair moves characters in the *menu* flow (`run_pair_menu.sh`, TASK 18/19/20) and TASK 20's
J003 A press collected an item, so this is specific to the `run_pair.sh`/duo worlds tried here, not to
the mod's pad path in general. UNKNOWN which of the two differences (the duo runner's backgrounded
windows vs. a level-script lock) is the cause; with the 16-process budget spent, not chased further.

## 8. Regression (verbatim)

`sh tests/run_pair.sh m22.dll check_combat.py check_party.py check_items.py check_hands.py` (run_c3):

```
party: host ['BOY3', 'GIR3'] guest ['BOY3', 'GIR3'] | inventory: host 35 guest 35
party OK
items: before host 35 guest 35
items: after host 36 guest 36
items OK
hands OK (2 characters checked)
```

and in run_c1 (same DLL, I100 → J001):

```
party: host ['BOY1', 'GIR1'] guest ['BOY1', 'GIR1'] | inventory: host 44 guest 44
party OK
items OK
hands OK (2 characters checked)
```

`check_entities.py` (run_c2, after the level changes): `entity count: host 43 guest 43` / `entities OK`.

`check_hands_visible.py` (run_c2, in the post-level-change world) **FAILED**:

```
differences host vs guest: [('BOY1', 'slot 1 wb8', 0, 1), ('BOY1', 'slot 3 wb8', 0, 1)]
AssertionError: weapon render state differs: [('BOY1', 'slot 1 wb8', 0, 1), ('BOY1', 'slot 3 wb8', 0, 1)]
```

which is a weapon render flag (`weapon+0xb8`) for the two *sheathed* slots, not an NPC field; the same
check passed in TASK 20's menu-flow regression, so this is very likely the post-level-change flow (a
different level, hands re-attached), not the NPC change — UNKNOWN until it is run in the standard menu
flow again.

**NOT RUN (16-process budget spent):** `run_pair_menu.sh` (check_movement included) and
`OBSCOOP_PICKUP_CLASS=MEDI OBSCOOP_PICKUP_SPAWN=1 run_pair.sh pair_j003.py check_pickup.py`.
The pickup path was not touched by this task's diff (PKT_PICKUP and its apply code are unchanged; only
NET_VERSION moved and both ends are rebuilt together), but it is not re-proven here.

## 9. DONE / NOT DONE / UNKNOWN

**DONE**
* Decompile: enemy life +0x320 / max +0x31c (`FUN_004c04d0`, `FUN_004c6e10`), damage entry
  `CCharacterNPC` vtable slot 21 `FUN_004fa170` → reaction slot 20 `FUN_004fa490`, life delta + death via
  vtable slot 9 (`FUN_004f5bf0`, human `FUN_004da180`), dead marker +0x2dc, last attacker +0x750/+0x754,
  player swing start/end `FUN_004563a0` / `FUN_00456710` with the "attack" animation event, AI controller
  +0x30c with state +0x98 (§1-§4).
* Measured on two copies in J001 and J000 (and H000 via the game's save 06): identical enemy class/pos/
  life/state/AI on both copies; position drift 0.0 units (§5.1).
* Host-authoritative enemy life/death/state streaming, `NET_VERSION` 10, one owner (the host), no double
  damage by construction (the guest applies only the difference through the game's own life method); the
  guest counters show the path applying (§5.3, §6). Builds with only the 3 known warnings.
* The guest follows a host `loadsave game6.sav` into H000 within 1 s (§7.1).
* Regression of the non-combat sync: party, items, hands, entities OK on the new DLL (§8).

**NOT DONE**
* **The real two-copy combat proof**: host player 1 kills enemy A, guest player 2 kills enemy B, life
  within tolerance during the fight, both dead on both copies, attack animation samples matching.
  No level tried with the duo harness accepts player input at all (J001, J000, save-loaded H000: 0.0
  units of movement in every direction, no button or trigger effect), so no swing could be driven and
  `tests/check_combat.py` reports `combat not proven` (§7.1-§7.2).
* `tests/check_combat.py`'s two-phase fight therefore never ran; the checks it would assert (life within
  tolerance, both dead, no alive/dead split, player life equality, attack-anim equality) are unexercised.
* Screenshots during a swing: none could be taken (nothing swung; and the window renders black while
  backgrounded — the two screenshots the check takes are black).
* Regressions not run for lack of game processes: `run_pair_menu.sh` (party/items/hands/hands_visible/
  entities/movement) and the `pair_j003.py check_pickup.py` pickup pair (§8).

**UNKNOWN**
* Why the duo-flow worlds give the pad no control while the menu-flow worlds do (level script lock vs.
  the duo runner's backgrounded windows). A next task should first settle this: if the duo game is
  unfocused, start `duo.py start` with the host window activated (or without `OBSCOOP_BACKGROUND`) and
  re-run `tests/check_combat.py`; nothing else needs to change for the fight to run.
* Which button is the attack in the shipped input map (`obscoop_o2.ipt` is binary; the check tries A, B,
  X, Y, LB, RB and both analog triggers).
* Whether the `check_hands_visible` wb8 difference is flow-related (§8).

