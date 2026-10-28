# FINDINGS 22 — the "frozen world" after a level change, and the fight (TASK 22)

Labels: **OBSERVED** = printed by a run/check in this task (log quoted) or read in the decompile / the
exe (address cited); **DERIVED** = follows from the cited code/data but was not observed live; **GUESS**;
**UNKNOWN**. Decompile line numbers refer to `local\decomp2\Obscure2.exe.c`.

Branch `w/combat` (6704c30 + this task's uncommitted changes). Runs: `run_f1..run_f5` (probes), `run_c1`
(check_combat.py), `run_c2`/`run_c3` (check_combat.py, both died on a harness hang), `run_r1`
(check_party/check_items/check_hands + probe_swing2.py). Every run ended with no game left
(`still running: []`); 18 game processes were used, the task's cap.

## 1. The world was never frozen: the combat probe pressed the D-pad (OBSERVED)

FINDINGS_21 §5.2 reported `control probe: player 1 best 1.2 s stick displacement 0.0 units` in every
level of the pair. The old `tests/check_combat.py` `stick()` called `press_btn(pipe, btn)` →
`pipe.cmd('pad 0 %x' % BTN[btn])` with `BTN['LEFT'] = 0x4`, `0x1/0x2/0x8` — the **D-pad buttons**. In
Obscure II the D-pad is the weapon quick-select, not movement. Run `run_f4` (live pair in J001):

```
== D-pad directions (0.4 s each)
  dpad RIGHT         ... | weapon states changed: -
     now slot 1 CToeWeaponTaser (weapon state 0x0, anim 0x0)
  dpad DOWN          ...
     now slot 2 CToeWeaponUberBeat ...
  dpad LEFT          ...
     now slot 3 CToeWeaponDynamite ...
  dpad UP            ...
     now slot 0 CToeWeaponCrossBow ...
```

so RIGHT/DOWN/LEFT/UP select slots 1/2/3/0, and the same run's foreground screenshot
(`j001_dpad_down.png`) shows the weapon wheel with the four slot icons around the character portrait.
The old check's first action (four D-pad presses for the "stick probe") therefore opened the weapon
wheel, and every later button press went into it.

The analog stick moves the character in exactly the same world (`run_f2`, probe_fight1.py):

```
== I100 baseline: analog left stick on the host player 1
     player 1 stick: up 364.8, down 321.7, left 140.1, right 139.4 -> best 364.8
== host level J001 317 1 -> ok
  arrived after 1.0 s, mode host 1 guest 1
== J001 + 8 s: analog left stick
     player 1 stick: up 57.4, down 337.8, left 92.7, right 205.6 -> best 337.8
```

and with the corrected probe the check itself reports it (`run_c1`):

```
   stick: LEFT 157.0, RIGHT 182.9, UP 64.7, DOWN 400.1
control probe: player 1 best 1.2 s stick displacement 400.1 units
```

**No mod change is needed for the "freeze".** The dialog hypothesis (task §1a) does not hold for the
level-change path either: a foreground screenshot of both copies 8 s after the host's
`level J001 317 1` shows two normal characters in front of doors — no dialog, no cutscene, no pause menu
(`j001_host.png` / `j001_guest.png`, 95.9 % non-black), and `world+0x11c` = 1 (normal). The only thing
that changed `world+0x11c` was START (1 → 5, the pause menu), i.e. the pad reaches the game (run_f1).

The backgrounded-window hypothesis (task §1c) is not the cause of the 0.0 units, but it does explain
black screenshots: `bot.shot` (PrintWindow only) returns black while `OBSCOOP_BACKGROUND=1` keeps the
window unfocused. Activating a window first (topmost + a real click, then PrintWindow) gives a normal
picture — that is what `check_combat.py` now does (`capture()`), and what every screenshot quoted here
used.

## 2. What the real inputs do in a combat level (OBSERVED)

`run_f2`/`run_f3`/`run_f4`/`run_f5` tried every real input next to a live `CCharacterNPC` (80 HP, 22-28
units away, character facing it):

| input | effect |
|---|---|
| analog left stick | moves player 1 (up to 400 units / 1.2 s) |
| D-pad U/D/L/R | selects weapon slots 0/2/3/1 (opens the weapon wheel) |
| START | pause menu (`world+0x11c` 1 → 5) |
| LB | character state `+0x2dc` = 0x64 while held |
| A, B, X, Y, RB, LT, RT, BACK, LS, RS | nothing (no enemy life change, no `weapon+0x14` change, no anim change) |
| left/right/middle mouse button (with and without movement) | nothing; `mouse` reads ≈ 20 000, `kbd_data_reads 0` |
| 12 DirectInput keys (SPACE, E, F, X, C, Z, R, LSHIFT, LCTRL, RCTRL, RETURN, TAB) | nothing |

The swing state that FUN_004563a0 writes is `weapon+0x14 = 4`; no input ever produced it, with the ranged
CrossBow (slot 0) or with the melee UberBeat (slot 2) selected (`run_f5`). **The attack input is
UNKNOWN.** Two candidates remain: the shipped `obscoop_o2.ipt` gamepad map may not bind the game's attack
action (the profile's `o2.ipt` is a 724-byte file the game wrote, not the game's 728-byte
`data/o2_input.ipt` default), or the attack action is gated by a character/level state this task did not
find. The game's own action table (`input manager +0x34`, `FUN_0059b3e0`) was not decoded.

## 3. The test-only `swing` command (IMPLEMENTED, src/obscoop2.c)

Because no input reaches the game's attack, `tests/check_combat.py` needed a way to start the *game's own*
swing. The attack entry of FINDINGS_21 §3, `FUN_004563a0`, is a vtable slot: in the exe the dword
0x004563a0 sits at RVA 0x25ae34, directly followed by the swing end 0x00456710 (OBSERVED by scanning
`Obscure2.exe`).

`swing <0|1>` (src/obscoop2.c, next to `life`): finds the player's character, takes the selected weapon
(`character+0x704 + 4*+0x714`), scans that weapon's vtable for 0x4563a0 and calls the entry with the
weapon as `this` and the character as the argument — the call the game makes when a player attacks: it
queries the character's impact manager (`character+0x30c`), sets `character+0x2bc`, the weapon state
(`+0x14 = 4`) and the "K3LA" swing animation. Test-only, documented in the pipe command comment; the
check sends it to **both** copies for the same player index, so both simulate the same swing (what the
pad path does through the pad stream).

**It does not work yet:** on the pair the reply was (`run_c1`)

```
   first swing reply: error swing: slot 0 weapon 1C712848 has no attack entry
   guest reply: error swing: slot 0 weapon 1B853FB8 has no attack entry
```

i.e. the selected weapon (`CToeWeaponCrossBow`, slot 0) has no 0x4563a0 in its vtable. DERIVED: 0x4563a0
belongs to the *melee* attack path (its .rdata neighbours also hold the `fight`/`attack` strings at
0x65ad88/0x65adb0), so the melee slot has to be selected first — `check_combat.py` now does that with the
D-pad (`select_melee()`, run_f4's mapping). That path was **not** exercised live: the two runs that would
have tried it (`run_c2`, `run_c3`) hung on the harness (see §4.3), and the only remaining pair
(`run_r1`) had no live enemy (see §4.4).

## 4. Live runs (verbatim)

### 4.1 `run_c1` — check_combat.py, attack input not found, fight not proven

```
== host level J001 317 1 -> ok
arrived: host J001 (mode 1) | guest J001 (mode 1)
enemies host:  CCharacterNPC.... life 80.0 st 0x0, CCharacterNPCProgeny.... life 1.0 st 0x0, … (7)
enemies guest: (identical)
   stick: LEFT 157.0, RIGHT 182.9, UP 64.7, DOWN 400.1
control probe: player 1 best 1.2 s stick displacement 400.1 units
   enemy A CCharacterNPC .... at (362.9, -140.4, 27.7) life 80.0 | enemy B CCharacterNPC ...A at (23.2, 415.1, 27.7) life 80.0
   tp host player 1 next to it: refused: no floor at (344.2, -128.9, 27.7) - the character fell 27.0 units (z 0.7); old position restored
   X    enemy life 80.0 -> 80.0  state 0x0  attacker anim max 0x0  weapon state max 0x0
   B    … Y … A … (all 0x0)
   LB   enemy life 80.0 -> 80.0  state 0x0  attacker anim max 0x64  weapon state max 0x0
   RB … RT … LT … LMB (all 0x0)
   no pad button, trigger or mouse button started a swing (all 9 tried above)
   -> using the test-only `swing` command (the game's own attack entry 0x4563a0) on both copies
   first swing reply: error swing: slot 0 weapon 1C712848 has no attack entry
…
   swing  1 ok    : host life   80.0 ->   80.0 st 0x0 | guest life   80.0 ->   80.0 st 0x0
   … (14 swings, all unchanged)
  !!! phase 1 (host player 1): CCharacterNPC is not dead on the guest copy (life 80.0)
  !!! phase 1 (host player 1): CCharacterNPC is not dead on the host copy (life 80.0)
   phase 1 (host player 1): worst life difference between the copies 0.00 (tolerance 1.0)
   phase 1 (host player 1): per-swing life drop (host | guest): 0.0|0.0 … (14×)
   phase 1 (host player 1): attack samples equal on both copies anim 84/84 (non-zero 0), weapon state 84/84 (non-zero 0)
```

The screenshots of that run are 89.8 % (host) and 95.2 % (guest) non-black — normal pictures of the J001
scene taken from outside the game — but no swing is in them, because no swing happened.

### 4.2 The sync assertions that did run

* Both copies carry the same 7 enemies with identical positions/life/state before the fight (§4.1).
* The control probe drives the character (400.1 units) — the "frozen world" is gone.
* With no damage anywhere, every life/anim/weapon-state sample agreed (84/84 samples equal): the check's
  new sample path (attacker `+0x2dc`, selected weapon `+0x14`, both copies) works.

### 4.3 `run_c2` / `run_c3` — the harness hung (OBSERVED, no game-process evidence)

Both runs printed the level line and then nothing for 7 and 15 minutes: the first pipe command of the
check (`level J001 317 1`, which calls ChangeLevel on the *pipe* thread, src/obscoop2.c) never returned.
The games kept running and syncing (host log `sync stats: sent 3917 snapshots … guest rtt 0 ms`), so this
is a pipe/game-thread race, not a game freeze; `run_c1` with the same DLL answered the same command in
milliseconds. Two of the task's game processes were spent on this.

### 4.4 `run_r1` — the trio regression PASSED; I100 has no live enemy

`sh tests/run_pair.sh <chk22.dll> check_party.py check_items.py check_hands.py probe_swing2.py`:

```
party: host ['BOY1', 'GIR1'] guest ['BOY1', 'GIR1'] | inventory: host 44 guest 44
party OK
items: before host 44 guest 44
items: after host 45 guest 45
items OK
in hand: host [('BOY1', 'CBOW'), ('GIR1', 'CSAW')] guest [('BOY1', 'CBOW'), ('GIR1', 'CSAW')]
hands OK (2 characters checked)
== probe_swing2: level host I100 (mode 1) guest I100
  player 1 before: slot 0 CToeWeaponCrossBow state 0x0
  enemies in this level: 2
   CCharacterNPCAura      (  -223.8,   -113.1,   22.6) life    0.0/   0.0 st 0x0
   CCharacterNPCHomm      (  -480.0,    271.4,    0.0) life    0.0/ 200.0 st 0x0
  no live enemy here; nothing to swing at
```

so the saved world of slot 01 (I100) cannot host the fight either (both enemies are at 0 life — Aura is a
trigger, Homm has max life 200 but life 0).

## 5. DONE / NOT DONE / UNKNOWN

**DONE**

* The "frozen world" is explained and removed at its cause: the combat probe pressed the D-pad, which
  selects weapon slots and opens the weapon wheel. The analog stick moves the character in I100 and in
  J001 (364.8 / 337.8 / 400.1 units per 1.2 s), on the host and through the level change (§1).
* The join-dialog / cutscene / background hypotheses are disproved for the level-change path, with
  foreground screenshots of both copies and `world+0x11c` readings (§1).
* `check_combat.py` now uses the analog stick, takes foreground screenshots itself (topmost + real click
  + PrintWindow, `tests/shots/`), samples the attacker's animation *and* the selected weapon's swing
  state on both copies, compares the per-swing life drop of the two copies and asserts life equality,
  both-dead and no alive/dead split (§4.1-§4.2).
* The input map question is measured end to end: every XInput button and trigger, the mouse buttons with
  movement, and 12 DirectInput keys do nothing but the D-pad, START and LB (§2).
* A test-only `swing <0|1>` command starts the game's own attack entry for a player, on both copies; it is
  built and answers (`error swing: … no attack entry` for the ranged weapon, §3).
* Regression: `check_party.py`, `check_items.py`, `check_hands.py` OK on the new DLL (§4.4), and the
  earlier task's checks were unaffected by the changes (only a new pipe command and the check script
  changed; no packet layout, `NET_VERSION` untouched).

**NOT DONE**

* **The fight**: no enemy was ever damaged. No real input reaches the attack, and the `swing` command
  found no 0x4563a0 entry in the *ranged* weapon the check had selected; the melee-slot variant was never
  run live (the two runs for it hung on the pipe race, §4.3). So: life-within-tolerance during a fight,
  both enemies dead on both copies, no alive/dead split, damage-not-applied-twice and the attack-animation
  equality are all **unexercised**.
* Foreground screenshots **during a swing**: none (nothing swung). The foreground capture path itself is
  proven (`j001_host.png`, `j001_guest.png`, `combat_host.png`, `combat_guest.png`, `i100_host.png`,
  `j001_dpad_down.png`, in `$TMPDIR`, plus `tests/combat_*.png` from run_c1).
* `run_pair_menu.sh` (party/items/hands/hands_visible/entities/movement) and the
  `OBSCOOP_PICKUP_CLASS=MEDI … pair_j003.py check_pickup.py` pair: **not run** — the 18-process cap was
  reached (two pairs were lost to the pipe hang of §4.3). The `check_hands_visible` wb8 question of
  FINDINGS_21 §8 is therefore still open.
* The enemy-life code from 6704c30 was not put under a real fight, so "is it needed / does it do harm"
  stays unanswered except that it applies nothing while both copies agree (§4.1).

**UNKNOWN**

* Which input starts the game's attack (all 16 pad buttons/triggers, 3 mouse buttons and 12 keys tested),
  and whether the shipped `obscoop_o2.ipt` gamepad map binds it at all.
* Whether `swing` works once a melee weapon is selected (the code path exists: `select_melee()` +
  `swing`), and whether the 0x4563a0 entry is present in the melee weapon classes at all.
* Why `level <tag>` on the pipe thread sometimes never returns (run_c2/run_c3) — it blocks the pipe
  server, not the game.

## 6. What the next session should run first (no game spent yet)

1. **One pair, one command**: `sh tests/run_pair.sh <chk22.dll> check_combat.py`. It now selects the
   melee slot with the D-pad before swinging (`select_melee`) and prints the `swing` reply; if the reply
   is `ok swing ... state 0 -> 4`, the game swing works and the rest of the check (life within 1.0,
   both dead, per-swing drop equal on both copies, animation/weapon-state samples) runs by itself.
2. If the reply is again `no attack entry`, dump the weapon vtable from the pipe (extend `swing` to
   print `vt[24..34]`) and compare with the melee class table in `.rdata` (the 0x4563a0/0x456710 pair
   at RVA 0x25ae34/0x25ae38): the melee classes may override the attack, in which case the base-table
   slot index (28 or 29) is the one to call on the weapon object.
3. Then the two regressions not run here: `run_pair_menu.sh` (handles the open `check_hands_visible`
   wb8 question of FINDINGS_21 §8) and the `OBSCOOP_PICKUP_CLASS=MEDI OBSCOOP_PICKUP_SPAWN=1
   run_pair.sh <dll> pair_j003.py check_pickup.py` pair.
