# FINDINGS 44 — the remote character must be VISIBLE; then the playtest crashes

Base: `w/combat` HEAD ef7130f = TASK 43 (puppet model + follow-ups, protocol 22). Labels: OBSERVED (read
in the code / printed by a run), DERIVED, GUESS, UNKNOWN. This file is written early and updated as the
task runs (section 1 first).

## 0. Result in one paragraph

The "remote character is not drawn" report was NOT reproduced by static placement: both copies draw BOTH
characters when they are in front of the local camera (captures in `tests/shots44*/`, and the intro
captures), and the new `tests/check_visible.py` proves the peer is present in the other copy's render world
at the streamed position and state (PASS in the default soak). What the new `puppet drift` diagnostic did
find is the real defect behind the reviewer's drift numbers: the game's own update pulls the puppet back to
a STALE position every frame (guest copy: x=y=0; host copy: the position from the load) and the mod puts
the pose back after the update - the render uses the restored position (captures), so this is a body-sync
bug to fix next, documented with the tool to find the body. A world-to-screen through SetTransform is
impossible: the engine's scene camera is a shader constant (`vmat`: both copies report the same four
UI/shadow view+projection pairs, none of which matches the picture). The playtest crash at
Obscure2.exe+0xe812b is the swing state (200) dereferencing a null attack target inside the movement state
machine; the puppet model removes both halves of that (the machine is not called for the puppet, and the
target slot is pointed at the character itself), and the new attack-each-other repro plays state 200 on both
copies 3+3 times with 0 crashes. Default soak PASS (with the two new checks), steam soak: every other check
PASS, `check_visible.py` failed on a bug in the CHECK itself (the wiring comparison used the character
pointer instead of the controller-record address) that was fixed afterwards - the fixed check PASSES in the
default soak; there was no game process left to re-run the steam soak.

## 1. Are the two characters drawn? (owner report: "both characters do not show up")

### 1.1 What the test setup can capture (OBSERVED, runs)

`tests/run_pair.sh` + a probe that captures each copy's own client area with `PrintWindow(PW_RENDERFULLCONTENT)`:

* the **host** copy runs at **2560x1440** (`OBSCOOP_WINDOWED=1` turns the device windowed, but the
  configured back buffer is the full resolution; `obscoop.log: windowed: CreateDevice 2560x1440 -> 0`),
  the **guest** at 800x600 (`windowed: CreateDevice 800x600 -> 0`).
* PrintWindow returns a real frame for both (`nonblack 54%` host, `71-72%` guest); a **screen BitBlt**
  of the host window is useless (the window is the size of the desktop and the desktop is in front).
  The visual check must therefore use PrintWindow, always the same method, and never the screen.
* `tests/shots44*/host0.png` (probe 1, level I100) shows the host copy drawing **both** characters next
  to each other; `guest1.png`/`guest2.png` show the guest copy drawing only its own character, because
  the peer stood **1-1.5 m behind the guest's camera** (the placements in that probe were only 60-150
  game units = 0.6-1.5 m: one unit is one centimetre, "55.3 units away" for a door is 0.55 m).
* probe 2 (level B101, the save loaded at that moment), real placements of the peer **in front of the
  local camera** (local position + local facing x 150): the guest copy draws the host's BOY2 at the
  right edge of the frame (`shots44b/A_guest_front.png`) and the host copy draws the guest's GIR2 in
  the foreground (`shots44b/A_host_own.png`) - **both copies draw the puppet when it is in front of the
  camera**.

### 1.2 The camera frames BOTH characters (OBSERVED)

Moving the puppet 1.5 m -> 4 m and back changes 39-50 % of the guest's sampled pixels: the game camera
pulls back / moves to keep both players in frame (co-op camera). Consequence for the check: moving the
puppet away also moves the camera, so a whole-frame pixel difference cannot tell "the character was
drawn" from "the camera moved". The check must look at the **projected** position of the character
(the game's own view/projection matrices) and compare that crop against the rest of the frame.

### 1.3 The mod now can project (NEW, this task)

`IDirect3DDevice9::SetTransform` was already hooked for the camera yaw; it now also records the
**projection** that belongs to the scene view, and the pipe has `screen <x> <y> <z>` -> the client-area
pixel the game's own camera puts that world position at (`src/window.c`). This is the world-to-screen the
visual check uses.


### 1.4 The engine's scene camera is NOT in SetTransform (OBSERVED, `vmat` on both copies)

The mod hooks `IDirect3DDevice9::SetTransform`; a live run with the new pipe `vmat` shows **four** view
matrices per frame, and **both copies report the same four** (same floats) although their cameras follow
different characters:

```
views 4 projlast 1
 | 0 f 0.00,0.00,-1.00 up 0.00 proj 6.63,6.63,1.01,1.00
 | 1 f 0.00,0.00,-1.00 up 0.00 proj 6.63,6.63,1.01,1.00
 | 2 f 0.31,0.90,-0.30 up 0.95 proj 1.33,1.77,1.00,1.00   (host) / f -0.24,0.92,-0.30 (guest)
 | 3 f 0.00,1.00,0.00 up 1.00 proj 3.23,4.31,1.01,1.00
```

Projecting the *local* character with any of them puts it at the frame centre (view 0/1), far off screen
(view 3) or 500 px above the lower edge (view 2), while in the captures it stands at the lower third -
i.e. these are the UI/shadow passes, and the scene camera goes to the GPU as a **shader constant**. A
world-to-screen through SetTransform therefore cannot be used (`pipe screen`/`vmat` stay as diagnostics).

### 1.5 The check that is used (OBSERVED, runs)

`tests/check_visible.py` puts the peer 1.3 m in front of the local character (tp on the copy that OWNS it),
then verifies what makes it visible on the other copy: the character OBJECT is there, it is the stream-driven
one (tag + `human+8` wired to its controller record), it is at the streamed world position (within 2 units of
the owner's copy) and carries the streamed animation state, and the window is a live picture (a PrintWindow
grab that is not black and changes between two shots). It also measures the picture change of a pose (the
peer takes the aim stance on its own pad) and prints it as an ADVISORY.

Why the pose change is only advisory: the co-op camera and the game's dynamic lighting change a large part
of a frame between two shots of the SAME scene. Measured offline on `tests/shots44d/*.png` (8x8 block
average, per channel, threshold 18): moving the peer 0.25 m changes 24.9 % of the blocks, and putting it back
to the same spot still changes 13.0 % (ratio 1.9); on the guest window 35.6 % vs 22.9 % (ratio 1.6).
Per pixel the numbers are similar (13.8 % vs 11.5 % in the run). No threshold separates "drawn" from
"camera moved" in this game, so a pixel verdict would be a coin toss - the check says so and does not use
one. The evidence that the peer IS drawn is the captures below.

### 1.6 What the captures show (OBSERVED, `tests/shots44*/`)

* probe 1/2 (levels I100 and B101): both copies draw BOTH characters when they are in front of the local
  camera - the host window shows BOY1 and GIR1 side by side (`shots44b/A_host_own.png`), the guest window
  shows GIR2 and BOY2 (`shots44b/A_guest_front.png`). The TASK 43 "not drawn" report is NOT reproduced by
  a static camera placement in these levels.
* the co-op camera frames both players: moving the puppet 1.5 m -> 4 m changes 39-50 % of a window's
  sampled pixels, which is why a whole-frame pixel diff around a move cannot distinguish "the character
  is drawn" from "the camera moved" (it is the reason the stance test uses a pose change, not a move).

## 2. The "drift" statistic (what the reviewer saw in the TASK 43 soak logs)

`puppet stats ... drift mean 450-552` on the guest copy and `49-92` on the host copy. The number is
`|streamed pose - character position|` measured AFTER the game's own character update and before the mod
puts the pose back (src/sync.c `puppet_finish`), i.e. how far the game's own update moved the puppet.

* OBSERVED (probe 2, level B101): the host copy reports `drift mean 0.00 max 0.00 over 1382 updates`;
  the guest copy reports `drift mean 66.74 max 66.74 over 1516 updates` - the SAME distance every
  update, which is what an absolute position write looks like, not physics. A new diagnostic in
  `puppet_finish` logs one line per second when the error is > 1 unit, with the delta vector, the
  velocity and the state (`puppet drift ...`), so the TASK 43 numbers can be explained from a log.

### 2.1 Measured (OBSERVED, `puppet drift` lines, chk44e)

The diagnostic in `puppet_finish` now prints the pose target and the character position together:

```
guest copy: puppet drift BOY1: 278.43 units; pose -275.5,-40.2,0.1 char 0.0,0.0,0.1 state 0 vel -1.0,-0.0,0.0
            | buffered 32 newest -275.5,-40.2,0.1 prev -275.5,-40.2,0.1
host copy : puppet drift GIR1:  80.28 units; pose -354.1,-142.0,0.1 char -273.8,-141.9,0.1 ...
```

* the POSE TARGET is right (it matches the owner's position on the other copy) and the interpolation buffer
  is healthy (32 samples, newest == previous, no underrun);
* the CHARACTER POSITION is not: the guest copy has its puppet at **(0.0, 0.0, z)** (x and y zeroed, z
  kept) and the host copy has its puppet at **the position it had when the level loaded**.
* So the game's own character update pulls the puppet back to a STALE position every frame, and
  `puppet_finish` (right after the update) puts the pose back. The value the game uses INSIDE its update is
  the stale one - the character's kinematic body / cached position is never moved for a puppet, because
  the only code that moves it is the movement state machine that TASK 42 skips for the puppet.
* The RENDER still uses the corrected position: the captures below show the puppet standing exactly where
  the owner is (`tests/shots44b/A_host_own.png`, `tests/shots44d/guest_p1.png`), including after a
  teleport, so the model matrix is built from +0x23c at draw time and not from the stale body.

### 2.2 Why this matters and what the fix is

The stale body is what the game moves, collides with and frame the camera with inside the update. Two of
the owner's symptoms are consistent with it: the TASK 43 soak reported drift 450-552 units on the guest
copy (the puppet's body at (0,0) while the owner walked 4-5 m away), and a character that is "not where it
should be" for the frames the game computes anything from the body. Fixing it properly needs the second
copy of the position (the kinematic body inside the character or in the physics/kinematic object it
points to) to be written with the pose - the `puppet drift` line is the tool to find it (scan the character
and its sub-objects for the stale triple while the pose is elsewhere). **NOT done in this task** (the game
process budget of the task was spent on the verification runs below).

## 3. The playtest crash (owner's v1.9 Steam test): Obscure2.exe+0xe812b

### 3.1 The fault (OBSERVED, disassembly of `obscure2-test/Obscure2.exe`)

`0xe812b` is `0x4e812b`, inside **FUN_004e76c0** = the human movement/state machine (CCharacterHuman
vtable slot 54 = +0xd8, 26 420 bytes; found by dumping the vtable at 0x66683c):

```
4e810c: cmpl $0xc8, 0x2dc(%esi)          ; is the character in state 200 (the swing)?
4e811c: jne  0x4e8130
4e811e: movl 0x820(%esi), %ecx           ; attack target index
4e8124: movl 0x824(%esi,%ecx,4), %edx    ; attack target pointer
4e812b: cmpl %ebx, 0x64(%edx)            ; <- FAULT when edx == 0 (eax=ebx=ecx=edx=0 in the report)
```

The crash stack `0x4dea91 <- 0x4f1620 <- 0x4f2123 <- 0x4b532a` matches: the world update (0x4b4cb0) calls
the human manager slot 17 **FUN_004f2130** (0x4f2123), which calls **FUN_004f1600** (0x4f1620 is inside it),
which calls vtable+0x28 = **FUN_004de4f0** (the human update, 0x4dea91), which calls vtable+0xd8 =
**FUN_004e76c0**, where it dies.

So the crash is: **a character in the swing state whose attack-target slot is NULL**. Only the attacker's
own controller fills that list (the aim/attack search FUN_004e0750). In the old pad-simulation model both
copies ran the movement machine for the *remote* character, whose own controller never ran -> null list ->
the same crash on both PCs. This is exactly the crash TASK 42 fixed twice over: the movement machine is
not called at all for the puppet (the 0x4e76c0 hook skips it) and `puppet_write` points the target slot at
the character itself whenever the streamed state is 200 (FINDINGS_42 section 5).

### 3.2 Repro (a): the intro / scripted event - `run44_intro1.log` PASS

`sh tests/run_cutscene_pair.sh chk44e.dll` (2-player new game, B101 intro NOT skipped):

```
host : scene local state 6 scene 0 id 01_1 level B101 cine 1 | peer state 6 ... |
guest: scene local state 6 scene 0 id 01_1 level B101 cine 1 | peer state 6 ... |
== 3. both copies leave the scripted event
  PASS: the skip on the host ended the event on the guest (forwarded skip applied, skips 1)
== 4. both copies end in the same state
host : B101 level B101 state 1 humans [('BOY2', (-64.1,-18.5,0.9)), ('GIR2', (11.0,-134.5,0.9))]
guest: B101 level B101 state 1 humans [('BOY2', (-64.1,-18.5,0.9)), ('GIR2', (11.0,-134.5,0.9))]
cutscene sync: PASS
```

Both windows show the same intro frame (`tests/shots/cut30/host.png`, `guest.png`).
ONE repetition was run (the task's game-process budget: 22 processes, of which 4 were reserved for the final
soaks); the intro is also inside both final soaks' start-up (the new game is loaded on both copies).

### 3.3 Repro (c): the players attack each other - `check_fight_pair.py`

New check, run in both final soaks and twice on its own. It places the victim 0.7 m in front of the
attacker (facing it), then does the owner's attack (HOLD LB = aim stance, TAP RB = swing; the third
repetition HOLDS RB = the special attack) 3 times each way, sampling +0x2dc on both copies and both
characters' life. Result: the **aim stance (100/102 = the 0x64/0x66 family) appears on both copies every time**, and in the
steam soak the **swing state 200 plays on BOTH copies** (host copy `states host [100, 200] | guest
[100, 200]`), i.e. the very state the owner's crash was in - with the target list filled because the swing
belongs to the OWNER of that character. On the earlier I100 run only the stance appeared (that level's
weapon/state mix); both copies always agreed. No life was lost (the test levels have no enemies and the
hit detection found none), and 3+3 attacks with the two characters facing each other left both copies
alive with 0 FATAL EXCEPTION lines.

### 3.4 "Climb down" - NOT tested live

UNKNOWN: not exercised (game-process budget). By the code, the climb is a streamed state (+0x2dc) plus the
streamed position - the same puppet path as walk/run - and it does NOT touch the 0x4e812b code, which is
entered only for state 200. The same-family list (climb up, jump/fall, push, hurt, death) is "same code
path, not tested live".

## 4. What was added (files)

* `tests/check_visible.py` (new): the peer's character must be present in the other copy's render world at
  the streamed position and state, wired to its controller record, and the window must be a live picture.
  Prints the pixel numbers of a pose change as an advisory (see section 1.5/1.6 for why a pixel threshold
  cannot decide it). Wired into `tests/run_pair.sh` (always runs it) and `tests/run_soak.sh`.
* `tests/check_fight_pair.py` (new): the attack-each-other repro (3 swings each way + a charged one).
  Wired into `tests/run_soak.sh`.
* `src/window.c`: per-view projection capture, `world_to_screen`, `scene_pair` calibration, pipe `screen`
  and `vmat` (diagnostics that established section 1.4); `hk_dev_Present` resets them per frame.
* `src/obscoop2.c`: pipe `screen` / `vmat`, forward declarations.
* same-family (owner rule): what the other copy must DRAW for the peer is the character mesh (this check),
  the held weapon (the existing `check_hands_visible.py` compares every weapon slot's render fields and the
  mesh visibility word on both copies) and the prop it carries (PKT_PROP, `check_breakables.py`). The
  weapon/world flashlight beam is the weapon's own mesh on both copies (host-owned weapons). None of those
  were re-tested here beyond the soaks that run `check_hands_visible`-style state indirectly.
* `src/sync.c`: the `puppet drift` diagnostic in `puppet_finish` (pose vs character position, the buffer,
  the state, the velocity; one line per second when the error is > 1 unit).

## 5. Live results (verbatim)

### 5.1 `OBSCOOP_LINK=steam sh tests/run_soak.sh chk44e.dll` - `run44_soak_steam.log`

```
attack animation OK (stance + attack animation on both copies, both players)
controls OK (each pad drives its own character on both copies)
host window: FAIL -- the peer is not wired to the controller record the renderer/stream uses   <- the CHECK's bug
visible FAIL
host attacks guest rep 1: attacker BOY1 states host [100, 200] | guest [100, 200]
attack-each-other OK (3 swings each way, both copies alive)
soak OK (30 location changes, both copies alive)
   image: PASS
   transition: dest I010 -> host I010 guest I010 after 0.0 s: PASS
   image: PASS
   transition: dest J000 -> host J000 guest J000 after 2.0 s: PASS
doors OK (2 phase(s))
  host: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
  guest: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
=== soak run: FAIL
```

(the FAIL is only `check_visible.py`: `ctlrec` compared `human+8` with the character pointer instead of the
controller record address - fixed in the check after this run; every game-side number above is a PASS.)

### 5.2 `sh tests/run_soak.sh chk44e.dll` (default link) - `run44_soak_default.log` **PASS**

```
== check_visible.py (the peer character is drawn) (timeout 150s)
host window: local BOY1 at (-254.7, 357.7, 0.1) facing (0.24, 0.97); peer GIR1 is player 1 on its own copy
  tp GIR1 to (-261.7, 493.5), 1.30 m in front: ok settled at (-261.68, 493.51, 1.10) after 0.8 s
  peer on this copy at (-261.7, 493.5, 1.1) state 0, wired to its controller record: True
  peer on its own copy at (-261.7, 493.5, 1.1) state 0 -> the two copies differ by 0.00 units
  picture: 2560x1440, stance vs idle 17.71 % changed, idle vs idle (control) 4.05 % (advisory)
host window: PASS -- the peer character is present in this copy's render world at its streamed position and state, and the window draws
guest window: local GIR1 at (-261.7, 493.5, 1.1) facing (0.22, 0.97); peer BOY1 is player 0 on its own copy
  tp BOY1 to (-271.6, 629.2), 1.30 m in front: ok settled at (-271.61, 629.16, 1.10) after 0.8 s
  peer on this copy at (-271.6, 629.2, 1.1) state 0, wired to its controller record: True
  peer on its own copy at (-271.6, 629.2, 1.1) state 0 -> the two copies differ by 0.00 units
  picture: 800x600, stance vs idle 1.14 % changed, idle vs idle (control) 1.15 % (advisory)
guest window: PASS -- the peer character is present in this copy's render world at its streamed position and state, and the window draws
visible OK (the peer character is present in both copies' render worlds)
== check_fight_pair.py (players attack each other) (timeout 240s)
  guest attacks host rep 3 (charged): attacker GIR1 states host [100, 200] | guest [100, 200]
host pipe alive: True
guest pipe alive: True
FATAL EXCEPTION lines: host 0 -> 0, guest 0 -> 0
attack-each-other OK (3 swings each way, both copies alive)
soak OK (30 location changes, both copies alive)
   image: PASS
   transition: dest I010 -> host I010 guest I010 after 0.5 s: PASS
   image: PASS
   transition: dest J000 -> host J000 guest J000 after 0.5 s: PASS
doors OK (2 phase(s))
  host: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
  guest: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
=== soak run: PASS
```

### 5.3 Other runs (all in the session scratch dir, not in the repo)

`run44_vis1..vis7.log` (the captures and the check's development), `run44_proj.log` (the `vmat` dump),
`run44_intro1.log` (the intro repro). Screenshots under `tests/shots44*` in the scratch dir and
`tests/shots/cut30/` (gitignored).

## 6. DONE / NOT DONE / UNKNOWN

DONE
* The visual investigation: both copies draw BOTH characters in view (captures, levels I100 and B101, and
  the B101 intro); the engine's scene camera is a shader constant, proven with the new `vmat` dump.
* `tests/check_visible.py` (new, wired into `run_pair.sh` and `run_soak.sh`): PASS on both copies in the
  default soak, with the peer at its streamed position/state and wired to its controller record.
* The drift explained with a new diagnostic (`puppet drift`): the game's update pulls the puppet to a
  stale body position (guest: 0,0,z; host: the load position); the render uses the restored pose.
* The crash at 0x4e812b decoded (swing state + null attack target in the movement state machine) and shown
  to be covered by the puppet model (machine skipped for the puppet; target slot self-pointed).
* Attack-each-other: 3+3 in both soaks (state 200 on both copies, 0 crashes) + 2 earlier pair runs.
* Intro repro: 1 run, both copies in the cutscene, forwarded skip, same end state, no crash.
* Default-link soak: PASS with the two new checks.

NOT DONE
* The steam soak was not re-run with the fixed `check_visible.py` (the task's 22-game-process limit was
  reached); its game-side results were all PASS.
* The climb-down repro was not run (same budget); "same code path, not tested live".
* The intro repro was run once, not 3 times (same budget).
* The drift was measured, not fixed (the render is correct in the captures; see 2.2 for the next step).
* A pixel-level "the character is drawn here" proof: not achieved, with the measurement that explains why.

UNKNOWN
* Why the owner saw no characters: not reproducible by static placement in these levels; candidates are the
  drift (a stale body used inside the update), the two copies having walked apart (each camera frames both,
  but the peer can be out of view), or a window that was covered (screen grabs of the host window show the
  desktop, not the game - PrintWindow is required).
* Which code writes the stale body position and how to sync it (the `puppet drift` line is the tool: scan
  the character and its sub-objects for the stale triple).
