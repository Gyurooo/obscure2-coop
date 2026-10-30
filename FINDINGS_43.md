# FINDINGS 43 — puppet model, step 3: door trigger, puppet dropouts, per-player UI, reconnect

Base: `w/combat` HEAD 587c872 (TASK 42, the puppet model, protocol 21). Labels: OBSERVED (read in the
code / printed by a run), DERIVED, GUESS, UNKNOWN. Work in progress — this file is updated as the task runs.

## 0. Result in one paragraph

(filled in at the end)

## 1. The door regression: what the game's own door mechanism needs (decompile)

OBSERVED, `Obscure2.exe.c` (build 215294, decompile line numbers):

* The use path is `FUN_0042c2b0` (door vtable+0x70, decompile 25496): it stores the character in
  `door+0xc4` and the door in `character+0x2bc`, starts the walk-through animation
  (`character->vtable+0x48(0x708)`, 24514), and calls `FUN_0042ad70` (24768).
* `FUN_0042ad70` is the **partner pull**: it finds the *other* character (the one that is not the door's
  user - `world+0x174c` teammate controller first, else the two controller records at `world+0x1748`,
  stride 0x764) and walks/places them at the door (`character->vtable+0x38(target,2)`, and when that
  fails `character+0x6f0 = 1; character->vtable+0x20(0)`). For a **double door** (`0x444f444f` = "DODO",
  24837) the target point is `door+0x10c - normal*160`, else `-185`.
* The transition itself is `FUN_0042c0c0` -> `FUN_0042aa70` (24666): it waits while
  `FUN_004c5fa0() == 0 && character+0x2dc == 0x708 && FUN_004c5f30() < door+0x4e` (the deadline
  `FUN_0042a2a0` computes from the animation length), then, when `door+0x118` (the destination) is not the
  current level and `door+0x24` (enabled) is set, calls `FUN_004a1c00(dest, door+4, 1)` = ChangeLevel.
* `FUN_0042a870` (24588) is the abort/cleanup: `door+0xb8 = 0`, every *other* character in
  `world+0x1748` gets `vtable+0x88(0)` / `vtable+0x20(1)`, the user gets `+0x26c = 1`, `+0x2bc = 0`.

Consequence (DERIVED): the door's ChangeLevel needs (a) the door object's own update to keep running,
(b) `door+0xb8` (in use) still set, (c) the *user* character to leave state 0x708 or the deadline to
pass, and (d) `door+0x24` (enabled) still 1. The partner's own position is *not* read by the transition
code - only the pull in FUN_0042ad70 moves it.

## 2. The regression seen in the TASK 42 soaks (OBSERVED, logs)

* `run_s42_soak_default.log`: soak34 race A `the door reached its ChangeLevel: NO` (25 s), check_doors
  phase 2 `transition: dest J000 -> host J002 guest J002: FAIL`. Iteration 30 and both of those are in
  level J002 (CToeDoubleDoor "DODO", id 13a); iterations 5/15/25 (I100, CToeDoor "DORH") transition fine.
* TASK 41's default soak passed both (`run_s41_soak_default.log`: `the door reached its ChangeLevel: yes`,
  `doors OK (2 phase(s))`).

## 3. Live evidence (runs)

### 3.1 The regression reproduced and diagnosed - `run_s43_repro1.log` (`chk42h.dll`, TASK 42's build)

`OBSCOOP_SOAK_ITERS=2 sh tests/run_soak.sh chk42h.dll`, then the two copies' `obscoop.log`:

```
==== host (obscure2-test/obscoop.log) ====
23:33:36.795 usedoor: ok usedoor player 0 door DODO id 13a ent 196837b0 (55.3 units away, spot 0, door 1/2)
23:33:36.803 host: used door DODO id ???: at level 4a303032 (ent 196837b0): telling the peer
23:33:37.738 host: the guest asked for ChangeLevel J000 (0x4a303030) entry 314 flag 1: doing it here
23:33:37.998 host: world 19e68f20 in level J000 is settled: the entity tables are rebuilt from it
==== guest (obscure2-test2/obscoop.log) ====
23:33:36.859 guest: door DODO id ???: use replayed on ent 193052c8 for character BOY1
23:33:36.860 guest: own ChangeLevel J000 dropped (the host decides)      <- ONE MILLISECOND later
23:33:37.670 guest: asking the host for ChangeLevel J000 entry 314 flag 1
23:33:38.040 guest: host ChangeLevel J000 entry 314 flag 1
```

soak34 then printed `the door reached its ChangeLevel: NO` - **the host's own door never got there**. The
chain (OBSERVED): the host's own use starts at 36.795; the guest replays it 64 ms later; on the guest the
door's own "wait for the walk-through" (`FUN_0042aa70`: `character+0x2dc == 0x708 && now < door+0x4e`) is
skipped, because the replayed user is a PUPPET whose state is the owner's state 100 ms ago (still 0 at
that instant); the guest's ChangeLevel is dropped (the host decides) and ASK_DELAY_MS (800 ms) later the
guest asks the host; the host applies it at 37.738 and rebuilds the world at 37.998 - 1.2 s after the use,
while its own door animation (measured 2.3 s in run 2) was still running. The host's door object was
destroyed mid-use, so its own ChangeLevel never happened.

In TASK 41's model this could not happen: the guest's copy also simulated the host's character from pads,
so its door saw a real 0x708 state and waited for the same animation; both copies changed the level at
about the same time and the host's own `request ChangeLevel` came first.

### 3.2 The fix and its verification - `run_s43_repro2.log` (`chk43b.dll`)

`host_apply_guest_level` (hooks.c) now defers a guest ask while THIS copy's own door use is still running,
the same rule the guest already had for its own animation (`g_role == 2 && door_animation_running()` in the
level-request apply path). `door_animation_running()` also ends as soon as the game clears the used
object (`character+0x2bc == 0`), so the deferral cannot outlive the actual use. Same run:

```
== race A: door use on the host, then a save load the moment the door asks for its level
     host usedoor 0 -> ok usedoor player 0 door DODO id 13a ent 1aa86eb0 (55.3 units away, spot 0, door 1/2)
   the door reached its ChangeLevel: yes
   issuing loadsave game0.sav right now (2.3 s after the door use)
   race A result: level J000/J000 after 0.3s -> one level
...
soak OK (2 location changes, both copies alive)
   transition: dest J000 -> host J000 guest J000 after 2.0 s: PASS
doors OK (2 phase(s))
```

and the diagnostic the build carries (`doorprobe`, one line per change of the door's own state) shows the
use running its full animation on the host and then the level change:

```
23:37:55.361 doorprobe host ent 1aa86eb0 DODO: user 19d08e90 state 1800 clip 94 | in use 1 enabled 1 d120 0
             dest 4a303030 | level 4a303032          (1800 = 0x708, the walk-through state)
23:37:57.299 doorprobe host: the door ent 1aa86eb0 is gone 8 s watch end (level 4a303030)
```

The ask side of the same run: `host: the guest's ask for J000 waits: this copy's own door use is still
running` - the deferral fired and the host's own ChangeLevel won.

## 4. Puppet dropouts (`puppet_target()` guards)

OBSERVED (`run_s43_repro2.log` runs, `puppet guards (last 10 s)` line every 10 s): the guards that reject
during a normal session are **level** (the stream still says the peer's old level while a level change is
in flight: 86-650 calls per 10 s right after a transition), **no character** (controller record +4 empty
while the world is rebuilt: 12-72) and **no link/stream** at startup. The window logger printed
`puppet: the peer's character is NOT driven for 812 ms (guard: level)` on both copies around every level
change.

DERIVED: a guard rejecting a LIVE character was not the only problem - TASK 42 also gated the CONTROLLER on
the same function (`puppet_is(ch) == ch == puppet_target()`), so every frame in which `level` (or any
other) guard fired, the game's own controller update ran for the puppet again and walked it towards the
camera target (the D-phase dropout: 450 vs 128 units, FINDINGS_42 section 8).

Fix: `puppet_active()` - the controller and movement-machine gate now uses the STRUCTURAL identity only
(the tag the peer streams, the game mode, the world state), not the pose guards (level, wiring, animation
system). A guard that fails still stops the pose writes (right: a pose from another level must not be
applied) but can no longer hand the character back to the game's input. `puppet_target()` keeps all
guards and counts each rejection per guard (a `puppet guards (last 10 s)` line, plus one log line when a
rejection lasts > 800 ms).

## 5. Per-player UI

OBSERVED (decompile): the controller update `FUN_004cf940` ends with

```c
FUN_00552360(character, ui == 3);                                  // the weapon wheel of that player (126846)
FUN_00551b70(character, *(world+0x1790) /* inventory */, ui == 4); // the shared item panel    (126847)
```

with `ui` = `controller+0xa4` (`in_ECX[0x29]`: 1 = aim stance, 2 = the aim/attack layer, 3 = weapon wheel,
4 = item menu) and ECX = the HUD manager (`game+0x470`, the same object the world keeps at `world+0x17a0`,
decompile 109388; its `+0x88` / `+0x8c` are the two players' wheel panels and `+0x90` the shared item
panel - `FUN_00552440` at 206581 and `FUN_00551b70` at 206141 read exactly that layout).

Under TASK 42's model the puppet's controller no longer runs on the other copy, so nothing raised that
state there and check_menus items 6-7 failed. The fix (NET_VERSION 22):

* `pkt_char` carries `ui` (the owner's `controller+0xa4`) and `wsel` (`character+0x714`, the wheel's
  selection) - `char_send_local` reads them, `peer_on_char`/`puppet_pose` interpolate them with the state;
* `puppet_ui()` (sync.c, called from `puppet_prepare`) writes them onto the puppet's own controller record
  and makes the two calls above with the HUD as ECX - i.e. exactly what the owner's controller did.

First attempt passed the wrong ECX (the controller record instead of the HUD): the host crashed in the
game's own code (`Obscure2.exe+0x151e17`, run_s43_menu1.log) and its game thread then hung (8
`GAME THREAD STALLED` reports, frames stuck at 3078), which failed check_movement E. With the HUD as ECX
the same run passes everything (`run_s43_menu2.log`, `menus OK (15 checks)`, `attack animation OK`,
E/A/B/C/D PASS).

Same family (the other per-character UI): the aim stance is `ui == 1` and is now checked live as well; the
flashlight is a weapon object in the hand (`character+0x704[slot]`, HANDS_FINDINGS) whose *drawn* beam is
the weapon's own mesh on both copies (the weapons are host-owned and already synced, `pkt_state` +
`weapons_for`); the held/carried item is the prop carry (PKT_PROP, already synced and covered by
check_breakables). Both are "same code path, not separately tested live".

## 5b. The door's same-family list

Which of the owner's world interactions relied on the remote character's state machine (the question the
task asks), and what the peer does now:

| interaction | how the peer learns it | needs the puppet's controller/state machine? |
|---|---|---|
| door / level-transition object | PKT_DOOR, replayed through the game's own `vtable+0x34` + `vtable+0x70` **on the puppet** | no, but the replayed use changes the level at once (the puppet's state lags), so the OWNER's copy must be allowed to finish - **fixed here** |
| loading zone (no door object) | the synced movement + the guest's ChangeLevel ask | no |
| ladder / climb | the owner streams the climb state (`+0x2dc`) and the path; the receiver plays the same clip | no (state + position only) - same code path, not tested live |
| push / pull, hurt, death | same state channel | no - same code path |
| item pickup | PKT_PICKUP: the *entity's* own collect method (slot 26) with the character | no character animation is run - tested live (check_pickup) |
| chairs / breakable cases | PKT_PROP: the object's own slots 28/29/25 (attach/detach/break) + the drop entity | no - tested live (check_breakables) |
| aptitudes (lock pick, heavy case, aura) | PKT_APT: the fields/position the result changed | no |
| switches | same entity-result path as aptitudes | no |

## 6. Reconnect

`sh tests/run_reconnect.sh chk43f.dll both` - **PASS** (`run_s43_reconnect.log`): `before: IN SYNC after
0.5 s (level I100, 2 characters, worst copy difference 0.0 units)`, an 8 s `netpause` on both copies,
`resume: IN SYNC after 0.5 s`, `CASE 1: no level or load request reached the guest (no reload)`; then the
guest killed and restarted: `late join: IN SYNC after 0.5 s (level I100, 2 characters, worst copy
difference 0.0 units)` with the host's save loaded on the new guest, `=== reconnect run (both): PASS`.

## 7. Live results (verbatim excerpts)

Every run below is in the worktree root (`run_s43_*.log`); the game copies' own `obscoop.log` was copied
for the two failures that needed it.

### 7.1 `OBSCOOP_LINK=steam sh tests/run_pair_menu.sh chk43e.dll check_movement.py check_menus.py check_attack_anim.py` - `run_s43_menu2.log` **PASS**

```
E: PASS
A: PASS
B: PASS
C: PASS [warn: GIR1 anim differs in 3/60 samples (transition samples)]
D: PASS
...
   host's wheel on both copies (player 1): PASS
   guest's wheel on both copies (player 2): PASS
   back to normal play on both: PASS
   host's aim stance (UI 1) on both copies: PASS
   guest's aim stance (UI 1) on both copies: PASS
   still normal play on both: PASS
   both normal, same level: PASS
   guest teammate unlinked again in normal play (the door fix): PASS
menus OK (15 checks)
...
attack animation OK (stance + attack animation on both copies, both players)
```

### 7.2 `sh tests/run_soak.sh chk43f.dll` - `run_s43_soak_default2.log` **PASS**

```
attack animation OK (stance + attack animation on both copies, both players)
controls OK (each pad drives its own character on both copies)
   the door reached its ChangeLevel: yes
   race A result: level J000/J000 after 0.3s -> one level
   race B result: level I010/I010 after 0.9s -> one level
   settled: level I010/I010, quiet for 3.0 s (yes)
soak OK (30 location changes, both copies alive)
   image: PASS
   transition: dest I100 -> host I100 guest I100 after 0.5 s: PASS      (phase 1)
   transition: dest J000 -> host J000 guest J000 after 2.0 s: PASS      (phase 2)
doors OK (2 phase(s))
  host: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
  guest: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
=== soak run: PASS
```

(a first attempt with the same build, `run_s43_soak_default.log`, failed from the first check: the host
copy was rendering at ~7 fps - `host stats: polls 1676 ...`, `foreground_is_game 0` - so `check_attack_anim`
and `check_controls` saw no movement at all; the 30 loads still worked. The retry above is the same build
on the same machine. An earlier TASK 42 note calls this shape a startup flake.)

### 7.3 `OBSCOOP_LINK=steam sh tests/run_soak.sh ...` - `run_s43_soak_steam.log` (chk43f), `run_s43_soak_steam2.log` (chk43f), `run_s43_soak_steam3.log` (chk43g)

All three runs: `attack animation OK`, `controls OK`, 30/30 level changes with both copies in one level,
`doors OK (2 phase(s))` (both phases!), 0 FATAL EXCEPTION lines, 0 stall reports, both copies alive.
`soak FAIL` comes from soak34's own 1.5 s frame sample (`threads_running`) and, in run 2, from race A:

* run 1: `game threads: host frames 35001 -> 35001, guest 36779 -> 36779 (STOPPED)` right after race B
  (both copies in a simultaneous level change). One such sample in the whole run.
* run 2: `the door reached its ChangeLevel: NO` for race A, and the host log shows why:

```
00:09:44.823 usedoor: ok usedoor player 0 door DORH id 12c ent 1ac528c8 (55.1 units away, spot 0, door 1/2)
00:09:44.843 doorprobe host ent 1ac528c8 DORH: user 1a614120 state 1800 clip 93 | in use 1 enabled 1 ...
00:09:45.712 host: the guest's ask for I010 waits: this copy's own door use is still running
00:09:47.719 host: the guest's ask for I010 waits: this copy's own door use is still running
00:09:47.839 host: the guest asked for ChangeLevel I010 ... doing it here      <- exactly 3.0 s after the use
```

i.e. the same regression, one guard too narrow: the 3000 ms cap of `door_animation_running()` expired
while the host's own door was still in its 0x708 walk-through (this level's door needs 3.0-3.4 s on the
shaped link), so the ask cut it off again. Fixed in `chk43g`: the cap is 6 s, and the guard still ends
the moment the game clears `character+0x2bc` (the end of the use).
* run 3 (chk43g): (filled in below)

## 8. DONE / NOT DONE / UNKNOWN

(filled in below)
