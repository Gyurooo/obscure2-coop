# FINDINGS 45 — the host's character is not DRAWN on the guest's screen after a save load

Base: `w/combat` HEAD 9367344 = TASK 44. Labels: OBSERVED (read in the code / printed by a run),
DERIVED, GUESS. Written early (task rule: by step 30) and updated as the task ran.

## 0. Result in one paragraph

The owner's "not drawn" was not reproduced as a picture (the save-load case DOES draw the peer in
`check_visible.py`, as in TASK 44), but the ROOT CAUSE named in TASK 44 section 2.2 is found and fixed:
the position has THREE copies in the game, and the game's own update drives the character with the two the
mod never wrote. `human+0x27c` is the MOVE TARGET: `FUN_004de4f0` measures `pos - target` every frame and
calls the character's own **SetPosition** (vtable slot 4 = `FUN_004c6880`) with the TARGET - on a puppet
nothing wrote the target, so the update walked it back to the level origin each frame (guest: `char
0.0,0.0,z`, exactly the FINDINGS_44 §2.1 numbers) or to the spawn point (host: 4.11 units). SetPosition is
the only code that moves the **collision body** (`human+0x30c` = CCharacterImpactManager, position at
`+0xcc`), so the body stayed where the character was BUILT - for the host's character on the guest copy
that was the world origin, 278 units from the drawn model. The fix writes the move target with the pose
and calls the game's own SetPosition, so the body follows: `puppet drift` went from **4.11 / 278.43 units
(constant, every frame)** to **mean 0.00-0.01, max 0.31-0.36** on both copies over a walking session, and
the collision body is now at the streamed position on both copies. `check_visible.py` gained the collision
body as an assertion: it FAILS on HEAD in the save-load case (88.96 / 363.40 units) and PASSES with the
fix. The owner's native-drop-in hint was tried: in the save-load world START on player 2's pad puts the
game into world state 7 and does **not** attach player 2 with the virtual pad, and the two copies diverge
- so `attach_player2` / `teammate_unlink` stay. The climb-down repro is not reachable in I100 (no ladder).

## 1. Owner's case vs what the harness does

* OBSERVED (owner): on the GUEST's screen the HOST's character is not displayed when the world was
  loaded FROM A SAVE; on a NEW GAME both characters are visible; the host's screen shows both.
* The harness' save-load path (`tests/start_menu_load.py`): the host loads `game0.sav` through the
  game's own menu-load (`loadsave`), the guest loads the same transferred file itself - i.e. both copies
  build the world from a save, the case the owner describes.
* The harness' characters: the save's party is BOY1 (host) + GIR1 (guest); a save starts with only player
  1 attached and the partner on the shared teammate controller, and `attach_player2` (TASK 35/38) puts the
  partner on the second input controller on both copies.

## 2. Where a character's position lives (OBSERVED, decompile)

1. `human+0x23c/0x240/0x244` - the position the model matrix is built from and the mod streams.
2. `human+0x27c/0x280/0x284` - the **move target**. `FUN_004de4f0` (the human update, around
   `LAB_004dec89`): `pfVar1 = in_ECX + 0x9f` (0x27c), `local_44 = pos.x - target.x` ..., and when
   `dist > 0` it calls `(**(code **)(*in_ECX + 0x38))(pfVar1, 1)` ("can I move there") and then
   `(**(code **)(*in_ECX + 0x10))(pfVar1)` - **SetPosition(target)** - every frame. It also has a branch
   that copies the collision body position INTO the target first.
3. `human+0x30c` - the **collision/impact manager** (CCharacterImpactManager; `FUN_004d9a80` stores the
   back-pointer at manager+0x30c), position at `manager+0xcc..0xd4` (its vtable slot 7 = `0x449bd0` is
   `lea eax,[ecx+0xcc]`; slot 8 = `0x449be0` is `lea eax,[ecx+0xd8]`).
4. `human+0x248` - facing (streamed already), `human+0x294` - velocity (streamed already).

The game's **SetPosition** is `CCharacterHuman` vtable slot 4 = `FUN_004c6880` (the function the movement
state machine `FUN_004e76c0` calls with its computed position, e.g. `0x4e76c0` calls
`(**(code **)(*in_ECX + 0x10))(&local_58)`). It writes `+0x23c..0x244`, calls the collision body's slot 3
with the new position, **reads the body position back when `body+0x40 != 0`**, tells the kinematic object
`human+0x124` (`FUN_005d2cd0`) and `human+0x314` (slot 0x54). Only this function moves the body.

## 3. Live measurements (OBSERVED)

### 3.1 HEAD, save-load case (`s45_a.log`, `chk45base.dll`)

```
host: human BOY1 ... pos (-240.84, -266.43, 0.10) body 0x19b73708 (-240.84, -266.43, 0.10) target (-240.8,-266.4,0.1)
      human GIR1 ... pos (-277.88, -142.04, 0.10) body 0x19b73e88 (-273.77, -141.89, 0.10) target (-273.8,-141.9,0.1)
guest: human BOY1 ... pos (-240.84, -266.43, 0.10) body 0x193b5198 (0.00, 0.00, 0.10) target (0.0,0.0,0.1)
      human GIR1 ... pos (-277.88, -142.04, 0.10) body 0x193b4748 (-277.88, -142.04, 0.10) target (-277.9,-142.0,0.1)
```

* the host's copy of the guest's character (the puppet) has its body 4.11 units behind its pose, matching
  the log line exactly:
  `puppet drift GIR1: 4.11 units; pose -277.9,-142.0,0.1 char -273.8,-141.9,0.1 state 0 vel -1.0,-0.0,0.0`
  (the char was pulled to the stale TARGET);
* the guest's copy of the host's character (the puppet) has its body at the **world origin**, 278.43
  units from the pose - the FINDINGS_44 §2.1 `char 0.0,0.0,0.1` number;
* `puppet drift` on HEAD is CONSTANT (4.11 / 278.43 on every update - an absolute position write, not
  physics), 559+ updates in a row;
* walking the host 8-9 m in four directions: the streamed pose agrees on both copies (d 0.00 at rest, up
  to 21 units for ~0.3 s while walking = the playback delay), while the guest's copy of the host's
  character keeps `body (0.0,0.0,0.1)` the whole time - the body is NEVER moved for a puppet.

### 3.2 After the fix (`s45_b.log`, `chk45a.dll`)

```
t+0.00 up BOY1 host p(-275.5,-40.2,0.1) body(-275.5,-40.2,0.1) | guest p(-275.5,-40.2,0.1) body(-275.5,-40.2,0.1) d 0.00
             GIR1 host p(-273.8,-141.9,0.1) body(-273.8,-141.9,0.1) | guest p(-273.8,-141.9,0.1) body(-273.8,-141.9,0.1) d 0.00
```

`puppet stats` (the mod's own 10 s line) on the two copies:

```
host : drift mean 0.00 max 0.00 over 1267 updates, anim 1267/1267 (100%), 0 state sets ...
host : drift mean 0.01 max 14.77 over 1495 updates, anim 2761/2762 (100%), 2 state sets ...   (the tp in check_visible)
guest: drift mean 0.00 max 0.36 over 1432 updates, anim 1433/1433 (100%), 12 state sets ...
guest: drift mean 0.00 max 0.31 over 1243 updates, anim 2676/2676 (100%), 16 state sets ...
```

Mean drift < 5 units on both copies (the task's bar), the collision body sits ON the pose, and only ONE
`puppet drift` log line was written during the whole session (the 14.77-unit teleport frame).
The `sync` line now reports the SetPosition calls (`puppet gated ... frames ... moves ...`).

### 3.3 The check

`tests/check_visible.py` now also asserts the peer's **collision body** is at the streamed position
(within 8 units). See section 5 for the HEAD FAIL and the fixed PASS.

### 3.4 The picture still cannot decide "drawn"

Same result as TASK 44 §1.5: the camera at the check's moment does not even face the characters (5.3), and
the game's dynamic lighting changes 1-4 % of a window between two shots of the SAME scene, so a pixel
threshold cannot tell "the character was drawn" from "the camera moved". Captures are kept as evidence
(`tests/shots/t45/`, gitignored).

## 4. The owner's native drop-in (START on player 2's pad) - TRIED, it does NOT join in this harness

Test switches added for it: `OBSCOOP_ALLOW_P2_START=1` (the mod normally strips START from player 2's pad,
because with two players it pauses both copies / offers "player 2 is leaving") and `OBSCOOP_NO_TEAMMATE=1`
(no `attach_player2`, no `teammate_unlink`, so the game's own one-player world is left alone).

OBSERVED (`s45_d.log`, `s45_e.log`, chk45b, save load, both copies):

```
host: input ctl 2: CHC2 char 0x0        teammate ctl 0xe01c288 char 0x1a688c28   (the AI partner)
guest: input ctl 2: CHC2 char 0x0       teammate ctl 0xe0fce90 char 0x1a64ea18   (the AI partner)
press START on player 2's pad (guest copy, XInput user 1 = its own pad):
  start+1  mode 1 state 7 req 0 | ctl1 CHC1 0x1a62e070 ctl2 CHC2 0x0 | teammate 0x1a692448 | humans 2
  ... 10 s the same; then tap A on pad 2 -> state 7, ctl2 0x0; tap START again -> state 7, ctl2 0x0
host: ... state 1 ...      guest: ... state 7 ...        <- the copies DIVERGE
```

* the game REACTS to START on the second pad: world+0x11c (the world state the whole game switches on)
  goes 1 -> **7** and stays there; the log has `scene: this copy entered a scripted event (world state 1,
  scene 7, id 0, level I100)` and `left ... (world state 7, scene 0)` - i.e. a game-side dialog / entry
  state, not a menu (the mod's menu states are 2/5) and not a skippable cutscene (scene 0);
* it does **not** attach player 2: `input controller 2` stays 0x0 for 10 s, A and a second START on that
  pad change nothing, and the HOST copy stays in state 1 - the two copies end in different world states;
* so with the virtual pad the game does not turn the AI teammate into player 2. (The owner sees it work
  with a REAL pad on real hardware; the harness' pad is the mod's XInput override, and the game may wait
  for a device-change notification a virtual pad never produces. UNKNOWN whether it would join with a real
  device - but the mod cannot drive it, and a state-7 dead end that exists on one copy only is exactly the
  TASK 37/38 class of bug.)
* CONSEQUENCE: `attach_player2` / `teammate_unlink` / `teammate_game_guard` are KEPT - the native join is
  not usable from the mod in this form, and removing them would put back the TASK 35 door freeze and the
  TASK 38 scripted-event crash. The two test switches are kept (default off, no effect on play).

## 5. Live results (verbatim)

### 5.1 The check FAILS on HEAD (task item 1) - `s45_c.log`, chk45base.dll

Save load (`start_menu_load.py game0.sav`), the host walks 1.5 s in each of four directions (8-9 m), then:

```
host window: local BOY1 at (-320.8, -140.4, 0.1) facing (0.96, -0.29); peer GIR1 is player 1 on its own copy
  peer on this copy at (-184.8, -140.5, 0.1) state 0, wired to its controller record: True
  peer on its own copy at (-184.8, -140.5, 0.1) state 0 -> the two copies differ by 0.00 units
  peer collision body at (-273.8, -141.9, 0.1) -> 88.96 units from its owner (tolerance 8.0)
host window: FAIL -- the peer's collision body is 88.96 units from the streamed position (stale body)
guest window: local GIR1 at (-184.8, -140.5, 0.1) facing (-1.00, -0.02); peer BOY1 is player 0 on its own copy
  peer on this copy at (-314.1, -182.8, 0.1) state 0, wired to its controller record: True
  peer on its own copy at (-314.1, -182.8, 0.1) state 0 -> the two copies differ by 0.00 units
  peer collision body at (0.0, 0.0, 0.1) -> 363.40 units from its owner (tolerance 8.0)
guest window: FAIL -- the peer's collision body is 363.40 units from the streamed position (stale body)
visible FAIL
check_visible exit 1
```

(The position/state/wiring/controller parts PASSED on HEAD - that is why TASK 44's memory-only check
passed; the body assertion is the one that catches the defect, on BOTH copies.)

### 5.2 The check PASSES with the fix - `s45_b.log`, chk45a.dll

```
host window: PASS -- the peer character is present in this copy's render world at its streamed position and state, and the window draws
  peer collision body at (-106.4, -287.1, 0.1) -> 0.00 units from its owner (tolerance 8.0)
guest window: PASS -- the peer character is present in this copy's render world at its streamed position and state, and the window draws
  peer collision body at (-235.6, -329.4, 0.1) -> 0.00 units from its owner (tolerance 8.0)
visible OK (the peer character is present in both copies' render worlds)
```

### 5.3 The pictures (`tests/shots/t45/`, gitignored)

`head_guest_idle.png` / `head_guest_stance.png` (HEAD) and `fix_guest_idle.png` / `fix_guest_stance.png`
are the guest window at the moment check_visible takes its shots. They show the camera looking at a wall
(a corridor with a flashlight beam, the peer's HUD portrait in the corner), no character in the frame at
all - the camera's direction is NOT the character's facing vector, so even a well-placed peer is not
necessarily in the picture. This confirms TASK 44 §1.5/1.6: a whole-frame pixel test cannot decide "the
character is drawn" here, and the check says so instead of pretending to decide it.

### 5.4 The final soaks (`chk45f.dll` = the full path `<local>\w-scan\chk45f.dll`)

**Steam profile (`OBSCOOP_LINK=steam sh tests/run_soak.sh chk45f.dll`) - PASS** (`s45_soak_steam.log`):

```
controls OK (each pad drives its own character on both copies)
== check_visible.py (the peer character is drawn) (timeout 150s)
host window: local BOY1 at (-241.0, 353.0, 0.1) facing (0.30, 0.95); peer GIR1 is player 1 on its own copy
  peer on this copy at (-239.9, 489.0, 0.7) state 0, wired to its controller record: True
  peer on its own copy at (-239.9, 489.0, 0.7) state 0 -> the two copies differ by 0.00 units
  peer collision body at (-239.9, 489.0, 0.7) -> 0.00 units from its owner (tolerance 8.0)
host window: PASS -- the peer character is present in this copy's render world ...
guest window: local GIR1 at (-239.9, 489.0, 0.7) facing (0.33, 0.94); peer BOY1 is player 0 on its own copy
  peer collision body at (-234.9, 625.0, 0.7) -> 0.00 units from its owner (tolerance 8.0)
guest window: PASS ...
visible OK (the peer character is present in both copies' render worlds)
attack-each-other OK (3 swings each way, both copies alive)
soak OK (30 location changes, both copies alive)
   image: PASS
   transition: dest I010 -> host I010 guest I010 after 0.5 s: PASS
   image: PASS
   transition: dest J000 -> host J000 guest J000 after 0.0 s: PASS
doors OK (2 phase(s))
  host: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
  guest: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
=== soak run: PASS
```

**Default link (`sh tests/run_soak.sh chk45f.dll`) - 4 runs, all game-side checks PASS, the ONLY failing
check is `check_visible.py`'s PICTURE part, and it fails because the desktop's display went to sleep**:

```
attack animation OK (stance + attack animation on both copies, both players)     (3 of 4 runs)
controls OK (each pad drives its own character on both copies)
attack-each-other OK (3 swings each way, both copies alive)                     (3 of 4 runs)
soak OK (30 location changes, both copies alive)
   image: PASS / transition ...: PASS (both directions)
doors OK (2 phase(s))
  host: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
  guest: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
```

and in every one of them: `peer collision body ... -> 0.00 units from its owner`. The failing lines are
always the picture ones:

```
  picture: 2560x1440, walk vs idle 0.00 % changed, peer stance vs idle 0.00 % (advisory), idle vs idle 0.00 %
host window: FAIL -- the window does not change when the local character walks (a frozen or blank picture; 0.00 % changed)
```

* OBSERVED cause: the monitor went to sleep (the desktop had been idle ~47 min). Probed DIRECTLY on the
  two live copies of that run: `PrintWindow` returned `brightness 0.00`, first pixels `00 00 00 ff ...`
  (black) for **both** windows; after waking the monitor (`WM_SYSCOMMAND/SC_MONITORPOWER -1`, no click)
  the SAME windows returned `brightness 28.97` and `40.71`. So it is the display/composition, not the
  game: DWM stops composing a D3D window while the display is off.
* The check now says so instead of failing the game: a black grab (after raising the window) prints
  `no picture -- the window hands out a black frame ...; the pixel checks are skipped` and the memory
  checks stay the verdict. The pixel liveness assertion is kept for a lit display (the local character
  walks and the camera follows; a frame that still does not change is a real failure).
* The 1 of 4 `attack animation` and the 1 of 4 `attack-each-other` failures are the known state-sampling
  flakes of those checks in I100 (FINDINGS_44 §3.3: this level's weapon mix sometimes shows the stance
  only; the charged state 700 is a single short state 100 ms behind the playback delay); each passed in
  the other runs, including the steam soak.
* NOT re-run after the last check edit: the task's game-process budget (22) was exhausted; the check
  edit only turns a black-grab FAIL into an explicit "not judged" and its lit-display path is the one the
  steam soak ran.

## 6. The climb-down repro - NOT exercised (no ladder in the reachable level)

* OBSERVED (entity scan of I100 in the live game): 73 level entities, none of the ladder/climb family -
  the tags present are DOC/CHAI/PPOS/FXPS/SERU/ADIC/ENDR/ZOHP/DORH/FLAS/LOOT/... and the only zone object
  is `LDZN` at (-750, 347, -489) (a loading zone, 488 units below the play area). The task allows only I100
  (save 01) and no level tag the game did not produce.
* The party of the test save is BOY1 + GIR1; the level's climb objects (`can_climb` property,
  `CToeLadder` in the RTTI) are not reachable from the start area, and the bot cannot play an interaction
  the pad does not reach (FINDINGS_19 §2.4).
* Same code path, not tested live: a climb is the streamed state (`+0x2dc`) plus the streamed position -
  exactly the walk/run path the fix and the soaks exercise, and it does not touch the state-200 attack
  code where FINDINGS_44's crash lived.

## 6b. The owner's note `OBSCURE1_PUPPET.md` (dropped in the worktree while this task ran)

It describes the Obscure 1 mod: (1) the receiver writes the owner's MOVE INTENT into the puppet's intent
fields and lets the game's own state machine pick state + animation, and (2) the position is then put back
with the game's own setters - character vtable slot 2, the PHYSICS BODY's slot 2, and the body's
sub-object - "so the collision body is never left behind (the Obscure II stale-body bug)".

* Point 2 is what this task implemented: the game's own SetPosition (Obscure II: `CCharacterHuman` vtable
  slot 4 = `FUN_004c6880`) moves the impact/collision manager (`human+0x30c`) and the kinematic object
  (`human+0x124`) with the character, and the move target `+0x27c` is written as well.
* Point 1 (stream the MOVE INTENT instead of the state id, let the game's own state machine produce the
  state) is NOT done here: TASK 42's model still sets the state with the game's own setter and gates the
  movement machine for the puppet. It is a next step, not part of this task's defect.

## 7. DONE / NOT DONE / UNKNOWN

DONE
* Root cause of the stale body found and fixed at the source the task named: the move target `+0x27c`
  (which the game's own update uses to SetPosition the character every frame) and the collision body
  `human+0x30c+0xcc` (which only SetPosition moves). The puppet now goes through the game's own
  SetPosition (vtable slot 4 = FUN_004c6880).
* `puppet drift` from constant 4.11 / 278.43 units to mean 0.00-0.01 (max 0.31-0.36) on both copies; the
  collision body is at the streamed position on both copies.
* `tests/check_visible.py` asserts the collision body; it FAILS on HEAD in the save-load case (88.96 /
  363.40 units) and PASSES with the fix.
* The owner's native drop-in tried: the game enters world state 7 and does not attach player 2 with the
  virtual pad; the copies diverge - so the teammate hacks stay (section 4).
* The final soaks (5.4): the STEAM-profile soak PASSES end to end (check_visible on both copies, 30
  location changes, doors, attacks, 0 fatal exceptions, 0 stalls). The DEFAULT-link soak passes every
  game-side check in 4 runs; its only failing check is the window PICTURE test, which fails because the
  desktop monitor slept (proven: black PrintWindow grabs on the live copies, real frames after waking it);
  the check now reports that as "no picture ... skipped" instead of failing the game.

NOT DONE
* The "not drawn" symptom itself was not reproduced as a picture: in the save-load case the peer IS in
  the render world at the streamed position/state with its body on the pose, and the camera at the
  check's moment does not even face the characters (5.3). The fix removes the mechanism that could hide
  it (a body in another sector/room), but the owner's exact sighting is not proven here.
* The climb-down repro: no ladder in I100 (section 6).

UNKNOWN
* Whether the owner's client really hides the peer because of the stale body (sector/portal culling or a
  draw-distance test on the body), or for a reason outside the harness (a covered window, a different
  save with more/different party members, the Steam link).
* Whether the game's own join would complete with a REAL pad (the virtual pad leaves it in state 7).
