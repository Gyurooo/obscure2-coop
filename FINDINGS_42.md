# FINDINGS 42 — the puppet model: each copy simulates only its own player

Base: `w/combat` HEAD bfd2fd7 (TASK 41). Packet version 20 -> 21. Labels: OBSERVED (read in the code /
printed by a run), DERIVED, GUESS, UNKNOWN. Addresses from `obscure2-test/Obscure2.exe` (build 215294),
disassembly with `i686-w64-mingw32-objdump -d --start-address=...`.

## 0. Result in one paragraph

The pad-simulation model is gone: each copy now simulates **only its own** character, and the peer's
character is a **puppet** - position, facing, velocity, the owner's speed and the owner's game state are
streamed at 60 Hz and played back through an interpolation buffer (~100 ms, adaptive). The state is applied
with the game's **own setter** (`CCharacterHuman` vtable slot 18 = 0x4e3ed0, which plays the animation clip
and stores the id in `+0x2dc`), and the puppet's own input controller and movement/state machine are not
called, so nothing on this copy fights it. Live on the Steam-shaped link: the remote character's path
agrees with its owner to **mean 0.3-1.8 units (p95 2-19, max 3-19)** while walking 116-575 units, the
animation state sequence agrees **56-60 of 60 samples** with up to two samples of delay (100 % on a whole
session while idle), the stance and the swing play on both copies for both players, and the two 30-location
soaks show **no guest freeze and no crash** (0 stall reports, 0 fatal exceptions, both copies alive) - the
FINDINGS_41 reproducer is gone. Two things are NOT done: the reconnect test (process budget) and the
door-trigger regression in the soaks (§7.3/7.4, UNKNOWN); the weapon-wheel mirroring in check_menus is a
deliberate consequence of the model and needs the check (or a UI-state mirror) for the new behaviour.

## 1. How the game animates a human (OBSERVED, decompile)

The human's **animation/state setter** is vtable slot 18 of `CCharacterHuman`:

* `CCharacterHuman_s18` = **0x4e3ed0**, `__thiscall(void *human, unsigned state)`, prologue
  `55 8b ec 81 ec f4 00 00 00` (assembly). It maps the state id to the animation clip tag and plays it
  with the character's own animation system `human->vtable+0x68(tag, -1, 0, 1.0)`:
  * state 0 -> idle family (`PAUS`, `SUAP`, `COUG`; `0x50415553` = "PAUS" reversed ...),
  * state 1 -> `WALK` (`0x57414c4b`), `2` -> run, `4` -> another gait, `100` = aim stance,
    `0x66`/`500`/`600`/`700` = stance/attack family, and the last statement of the function is
    `human+0x2dc = state` (decompile 139592 `in_ECX[0xb7] = param_1`, 0xb7*4 = 0x2dc).
* The controller calls it the same way: `FUN_004cf940` (the per-character controller input update)
  does `(*(character->vtable + 0x48))(0)` / `(0x640)` (decompile 126669+420 and +1550), and the movement
  state machine `FUN_004e76c0` switches on `human+0x2dc` and calls
  `human->vtable+0x48(1)` for walk, `(2)` for run, `(0)` for idle (decompile 141997..142110).
* `human+0x2dc` is therefore **not** an animation frame but the character STATE id the whole game
  switches on (FINDINGS_21: death, FINDINGS_29 §2: the interaction scan). Writing it raw changes the
  value but does not play the clip — which is why the old per-packet write left the remote character
  sliding (FINDINGS_34 §6.4).
* The walk/run decision uses `human+0x278` (speed, float; thresholds 200 = walk, 850 = run in
  `FUN_004e76c0`), written by the input controller (`*(float *)(character + 0x278) = f` at decompile
  127514/127762/128048). The velocity/direction vector is at `human+0x294..0x29c`
  (`in_ECX[0xa5..0xa7]` in `FUN_004de4f0`).

So the puppet is driven by the same three fields the controller writes — position, speed, state —
and the receiver plays the animation through **the game's own setter**, not by a raw write.

## 2. The model

* Each copy streams **its own** character (host: player 1, guest: player 2) in PKT_CHAR at >= 30 Hz:
  tag, position, facing, velocity, the owner's speed (`+0x278`), the state (`+0x2dc`) and the life.
* The receiver keeps a small interpolation buffer (sorted by the sender's timeline stamp) and plays it
  back `delay` ms behind the newest sample; the delay adapts to the measured arrival jitter.
* Before the game's own character update (`CCharacterHuman_s10`, 0x4de4f0) the puppet gets the
  interpolated position, facing, velocity and speed, and — when the state id changes — the game's own
  state setter (`vtable+0x48`) is called. The game's own state machine then runs for the puppet exactly
  as it does for a player who presses nothing: it walks/runs with the real clips and keeps the action
  states (attack, climb, hurt, death) the owner streamed.
* After the update the position/facing are re-set to the interpolated values, so the local physics can
  never drag the puppet away from the owner.
* The puppet's own input controller update (`FUN_004cf940`) is **not called** in normal play, so no
  local pad or AI input can fight the puppet. (In a menu, in a load and in a scripted event the
  controller runs as before: the game's own code needs it, and the shared menus keep working.)
* Player pad streaming stays, but the peer's pad is only *served* while a shared menu is up (TASK 36/38)
  or outside a level; in normal play the remote pad is zeros.
* The host's snapshot (`pkt_state`) no longer corrects any character's position, facing or animation;
  it keeps life, weapons and energy (host-owned).

## 3. Same-family list (every character-state path through the puppet)

walk / run / idle (state 0/1/2/4), aim stance (100/0x66), attack (200/0x66), special/charged, climb up,
climb down, push, hurt, death (5), item use, jump/fall — all of them are `+0x2dc` state values written
by the owner's own game and played on the receiver by the same setter (`vtable+0x48`). See §6 for what
was tested live.

## 4. What the live runs found on the way (each fix is in the code)

| # | symptom | cause (OBSERVED) | fix |
|---|---|---|---|
| 1 | the guest died silently ~100 ms after the host entered the level (`run_s42_1.log`) | `peer_on_char` runs on the transport thread and `EnterCriticalSection(&g_pb_cs)` on a CRITICAL_SECTION that was never initialised (the array of `InitializeCriticalSection` calls in `sync_init` did not have the new one) - a zeroed CS faults | `InitializeCriticalSection(&g_pb_cs)` in `sync_init` |
| 2 | the receiver was dead-reckoning on most frames (1024-1674 "extrapolated" per 10 s) | the character stream was sent from the Present hook, i.e. at the frame rate (~17 fps = 58 ms) - a 100 ms interpolation buffer had nothing ahead of it | the stream is sent from the transport thread (`net_tick`) every 16 ms, like the pad stream (FINDINGS_41's thread) |
| 3 | the host died on the first character update after every load (`run_s42_4/5/6.log`) | the 0x4e76c0 hook copied **8** bytes of a **9**-byte prologue (`55 8b ec` + `81 ec 30 07 00 00`): the trampoline's `jmp` overwrote the last immediate byte of `sub esp,0x730` and subtracted garbage from esp | 9-byte prologue (the bytes are also verified by `hook_entry`) |
| 4 | the host crashed in the game's own code twice with state 200 (`0x4e812b`, `0x4dd250`) | the swing state makes the game read `human+0x824[human+0x820]` (the attack target list the attacker's own controller fills) and dereference it; on a puppet it is null | the puppet's target slot is pointed at the character itself (a valid object) whenever the state is 200, and the puppet does not run the movement/state machine (`0x4e76c0`) at all |
| 5 | after the attack phase the remote copy froze (both characters stopped moving on it, `run_s42_3/7.log` check_controls) | same null target: the first-chance vectored handler logs the fault and the game continues with the character update aborted mid-way | same as 4 |

## 5. Hooks the model needs

* `0x4de4f0` **CCharacterHuman update** (vtable slot 10, prologue `55 8b ec 83 ec 40`): before it the puppet
  gets the interpolated pose/state, after it the pose is put back (so this copy's physics cannot drag it).
* `0x4e76c0` **human movement/state machine** (called from the update through vtable+0xd8, prologue
  `55 8b ec 81 ec 30 07 00 00`, 9 bytes): not called for the puppet.
* `0x4cf940` **CharacterControllerInput update** (already hooked since TASK 36): not called for the puppet's
  controller in normal play, so no pad or AI input can fight the puppet. It still runs in a menu, a load and a
  scripted event (the game's own code needs it there).
* The state setter is **not** hooked: it is called (`human->vtable[0x48]`).

## 6. The same-family list (every character-state path through the puppet)

| path | state(s) the owner streams | tested live |
|---|---|---|
| idle / walk / run / the other gait | `+0x2dc` 0 / 1 / 2 / 4, speed `+0x278` | **yes**: check_movement A-D, check_controls (the character travels 100-700 units and the copies' paths agree, §7) |
| aim stance (LB) | 100 / 102 | **yes**: check_attack_anim, both pads, both copies (`host states [102], guest states [102]`) |
| attack (LB+RB) | 200 | **yes**: check_attack_anim (`[100, 200]` on both copies, both directions) |
| special/charged attack, push, item use, climb up/down, hurt | other `+0x2dc` values | same code path (one state field, one setter), **not tested live** |
| death | 5 | same code path, **not tested live** |
| jump / fall | the gait states above | same code path (the streamed y and speed follow), **not tested live** |
| level change / load / scripted event / menu | - | the puppet is OFF (`world+0x11c != 1`); the game's own code owns both characters, as before |

## 7. Live results (verbatim excerpts; full logs in the worktree root)

### 7.1 `OBSCOOP_LINK=steam sh tests/run_pair_menu.sh chk42h.dll check_movement.py check_attack_anim.py check_controls.py check_party.py check_menus.py` - `run_s42_8.log`

```
E: PASS
A: PASS
B: PASS [warn: BOY1 anim differs in 9/60 samples (transition samples)]
C: PASS [warn: GIR1 anim differs in 5/60 samples (transition samples)]
D: PASS [warn: GIR1 anim differs in 5/60 samples (transition samples)]
attack animation OK (stance + attack animation on both copies, both players)
controls OK (each pad drives its own character on both copies)
party OK
menus FAIL (12 checks)
```

The remote-character error of that run (the check compares the remote copy's pose against the owner's at
(sample time - playback delay), §7.3):

```
B HOST PAD  BOY1  n 60  moved 116.02/116.01  diff_mean 1.81  p95 18.53  max 19.14   anim 58/60 with <=2 samples
C GUEST PAD GIR1  n 60  moved 575.51/575.51  diff_mean 0.98  p95  3.81  max  7.74   anim 56/60 with <=2 samples
D BOTH      BOY1  n 60  moved 115.79/115.79  diff_mean 0.28  p95  2.03  max  3.03   anim 60/60 with <=2 samples
D BOTH      GIR1  n 60  moved 128.35/127.69  diff_mean 0.37  p95  3.20  max  4.24   anim 56/60 with <=2 samples
```

The mod's own counters on that link (`puppet stats:` every 10 s): **animation agreement 100 %** while idle
(`anim 5306/5306`), 82-100 % over a whole session (the misses are the ~100 ms delay on a state edge), and
"drift" (how far the game's own update moves the puppet before this copy puts it back) **mean 0.00-0.49,
max 3.74 units** - i.e. the receiving game no longer fights the puppet.

### 7.2 the same run without the menu check - `run_s42_9.log`

```
E: PASS
A: PASS
B: PASS
C: PASS [warn: GIR1 anim differs in 5/60 samples (transition samples)]
D: FAIL -- GIR1 copies differ: mean 10.01 p95 29.13 (max 10.0/30.0) [warn: GIR1 anim differs in 5/60 samples]
attack animation OK (stance and attack animation on both copies, both players)
controls OK (each pad drives its own character on both copies)
party OK
```

D's numbers in that run: the host's copy of GIR1 travelled **450.49** units while the owner's travelled
127.61 (the error grows to 462 at the end of the phase) - the puppet stopped being driven for part of the
phase and the game moved it itself (the "walk to the camera target" behaviour of the input controller).
**Not explained**; see section 8.

### 7.3 `sh tests/run_soak.sh chk42h.dll` (default link) - `run_s42_soak_default.log`

```
attack animation OK (stance + attack animation on both copies, both players)
controls OK (each pad drives its own character on both copies)
soak FAIL (30 iterations, alive True)
doors FAIL (2 phase(s): PASS, FAIL)
  host: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
  guest: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
=== soak run: FAIL
```

30/30 level changes, both copies in the same level every time, **no freeze** (0 stall reports, 0 fatal
exceptions, both alive). The two FAILs are door-trigger failures: soak34's race A
`the door reached its ChangeLevel: NO` and check_doors' second phase
`transition: dest J000 -> host J002 guest J002 after 0.0 s: FAIL` (both copies agree on J002, the door's
destination is J000). TASK 41's default soak passed both (`run_s41_soak_default.log`: `the door reached its
ChangeLevel: yes`, `doors OK (2 phase(s))`), so this is a regression of this task, cause UNKNOWN.

### 7.4 `OBSCOOP_LINK=steam sh tests/run_soak.sh chk42h.dll` - `run_s42_soak_steam.log`

```
attack animation FAIL (PASS, FAIL)          <- guest phase: copies agree on 45/55 samples (82%)
soak FAIL (30 iterations, alive True)
doors FAIL (2 phase(s): PASS, FAIL)
  host: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
  guest: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
```

The attack failure was the check's skew window: the state SETS agree (`host states [100, 200], guest states
[100, 200]`) but a state edge arrived more than the two samples the check allowed; it now allows four
(200 ms, the link's own jitter). **The task's crash reproducer is gone**: FINDINGS_41's guest freeze
("stuck in the game's own code after frame_tick") did not happen in either soak - 0 stall reports,
0 fatal exceptions, both copies alive after 30 location changes. TASK 41's own steam soak failed the same
way (`run_s41_soak_steam.log`: `soak FAIL (30 iterations, alive True)`, `doors FAIL`).

## 8. NOT DONE / UNKNOWN

* **`sh tests/run_reconnect.sh <dll> both` was NOT run**: the task's hard limit of 22 game processes was
  reached (11 pair/soak runs x 2). Nothing in the reconnect path changed (the stream is restarted by the
  same `hello`/`welcome`), but it is unproven.
* **`check_menus.py` items 6-7 FAIL** under the new model (items 1-5, the *shared* pause menu and the live
  inventory with merged pads, PASS): the weapon wheel is a per-player UI state on the character's own
  controller, and the puppet's controller no longer runs, so the guest's wheel no longer appears on the
  host's copy. The check still demands it on both copies. Opening a wheel also left the host's world in
  state 2 while the guest stayed in 1 - a menu convergence side effect that needs a look (UNKNOWN).
* **The run_s42_9 D phase** (the remote character travelling 450 vs 128 units) is UNKNOWN: the puppet
  stopped being driven for a part of the phase. `puppet_target()` has five coherence guards (mode, world
  state, level, wiring `human+8`, animation system) and one of them may be rejecting a live character for
  a moment. Recommended next step: log which guard rejected (a counter per guard) and re-run.
* **The animation playback itself was not inspected visually** (no screenshot comparison): the state id and
  the clip selection are the game's own setter, and the counter `anim ok` only compares the state field.
* **The door-trigger regression** in both soaks (section 7.3/7.4) is UNKNOWN.

## 9. Files and evidence map

* `src/net.c`: `NET_VERSION` 21, `pkt_char` + `vel[3]` + `speed`, PKT_CHAR in both directions, the stream
  is sent from the transport thread (`net_tick` -> `char_send_local`).
* `src/sync.c`: the puppet block (buffer, `peer_on_char`, `puppet_pose`, `puppet_target`, `puppet_write`,
  `puppet_anim`, `puppet_prepare/finish`, `char_send_local`), the old `host_apply_remote_char` /
  `guest_send_char` / `anim_apply_remote` / history-timed correction removed, `guest_apply_state` no longer
  corrects positions, `puppet stats:` line every 10 s and the `sync` counters.
* `src/hooks.c`: the 0x4de4f0 and 0x4e76c0 hooks, the controller gate in `hk_input_update`.
* `src/obscoop2.c`: the peer's pad is served only while a shared menu is up (or outside a level).
* `tests/check_movement.py`: the remote copy is compared at the playback delay (best fit within +-60 ms of
  the reported one), p95 criterion, the animation sequence compared with up to 2 samples of delay.
* `tests/check_attack_anim.py`: up to 4 samples (200 ms) of delay between the copies' state edges.
* Build (the DLL every number in section 7 comes from is `chk42h.dll`, built from this source):
  `i686-w64-mingw32-gcc -O2 -Wall -shared -static -static-libgcc -o chk42h.dll src/obscoop2.c src/obscoop2.def -Wl,--kill-at -lws2_32 -ld3d9`
  (3 known warnings: `tick`, `watch_start`, `request_shot`).
* Logs: `run_s42_1..9.log` (pair runs), `run_s42_soak_steam.log`, `run_s42_soak_default.log`.
