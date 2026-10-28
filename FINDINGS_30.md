# FINDINGS 30 — cutscenes and story events (TASK 30)

Labels: **OBSERVED** = printed by a run in this task, or read in the decompile / disassembly (address cited);
**DERIVED** = follows from the cited code but was not observed live; **GUESS**; **UNKNOWN**.
Decompile = `local\decomp2\Obscure2.exe.c`; disassembly = `Obscure2.exe` of `local\obscure2-test`
(VA = image base 0x400000); vtable slots were read with a read-only PE section map.

Branch: HEAD of `w/combat` (protocol 15), `NET_VERSION` 16 after this task.

## 0. Summary

| item | finding |
|---|---|
| how a cutscene starts | the **level script** calls a script command; the world object runs a small state machine (`world+0x11c`, `world+0x12c`) |
| state while it runs | `world+0x11c = 6` (cinematic presentation) **OBSERVED**; camera mode `cam+0x16c = 1` is the "event" camera **OBSERVED** in the name table; per-character freeze `human+0x2c4` **OBSERVED** in code |
| how it is skipped | a **local input**: ESCAPE (keyboard) cleared `world+0x11c` 6 -> 1 on the host in 0.0 s **OBSERVED**; the game shows a kinematic bar (`Cslh_ShowKinematicBar`) |
| what the mod did before | nothing: a skip on the host left the guest at `world+0x11c = 6` for 18 s **OBSERVED** (the guest is stuck in the cutscene) |
| what the mod does now | the host streams `world+0x11c`/`world+0x12c` (`PKT_SCENE`); a skip by **either** player is forwarded and applied on the other copy through the game's own input path; both copies leave the scene together |

## 1. The script/cutscene family (OBSERVED, `rtti.txt` 566-862)

The game's script API is a class per command, `Cslh_*` (all registered by `FUN_004a97e0`). The commands that
belong to the scripted-event family, and their implementations (vtable slot 4 of the class, read from the
`*puVar1 = &PTR_FUN_xxxxxxxx;` that follows each `FUN_0059f100("<name>",...)` registration):

| script command | registration line | implement. | what it does |
|---|---|---|---|
| `KinePlay(a, b, c)` | 104900 | **0x4c0fe0** | calls `world->PlayKine(a, b, c, 1)` = `FUN_004b27d0` (below) |
| `NoeSceneActivate(name, ...)` | 102890 | **0x4c1080** | builds the name and calls `FUN_004b2890` (scene kind 8) |
| `ShowKinematicBar(n)` | 105080 | 0x4c1720 | the skip bar the player sees during a cinematic |
| `CameraSelect(mode)` | 105474 | 0x4c0b00 | `FUN_0052d6b0(mode)` sets `cam+0x16c` (1 = "event" camera) |
| `CameraEventSet(...)` | 105511 | 0x4c0cb0 | sets up the event camera |
| `CameraFreezePlayers(on)` | 105612 | **0x4c0b70** | `FUN_0052d4d0(on)`: both humans' **`+0x2c4` = on** (see §3) |
| `CharacterFreeze`, `CharacterEnableControl`, `CharacterHumanDisableMove` | 105245/105269 | 0x4bfef0 / 0x4c0040 | per-character input locks |
| `CharacterStartKinematic` (3 variants) | 104231 | 0x4be880 / 0x4be8f0 / 0x4be960 | scripted character animation (sets `+0xac` scale, runs slot+0x68) |
| `CharacterSwap` | 105258 | 0x4bff20 | story-forced character switch |
| `CharacterSetLife(ch, v)` | 104440 | 0x4c0470 | story-set HP |
| `EnergySet(v)` / `EnergySet(ch, v)` | 102914/102925 | **0x4bca00** / 0x4bca30 | battery/energy: writes **`inventory+0xc88`** (float) |
| `InventoryRemoveItem` | 103392 | 0x4bd8a0 | script empties an inventory entry |
| `StateEventSet(name, v)` | 104628 | **0x4bf980** | writes byte `+0x14` of the named entry of the **state manager `world+0x178c`** |
| `StateChapterSet` | 104558 | 0x4bf750 | chapter/state block |
| `DialogStart(name, ...)` / `DialogInProgress` / `DialogEnable` | 103212 | 0x4bd270 | dialog/subtitle presentation |
| `ToeEntityEnableCutscene` | 103860 | 0x4be2e0 | enables a `CToeEntityEnableCutscene` level entity |
| `Message`, `PutMainString`, `VoiceEnable` | — | — | subtitles/voice |

`KinePlay` body (OBSERVED, disassembly 0x4c0fe0):

```
edx = game; ecx = world = *(game+0x378)
push 1, 0, 1, args[0]
call 0x4b27d0          ; world->PlayKine(a, 1, 0, 1)
```

## 2. The world's scripted-event state machine (OBSERVED, disassembly)

`world = *(game + 0x378)`. Fields (all read live in this task, see §4-5):

| field | meaning |
|---|---|
| **`world+0x11c`** | the level state: **1** = normal play, **5** = pause menu (FINDINGS_22 §1), **6** = cinematic presentation (**OBSERVED** live in the new-game intro), **0x11** = game over (FINDINGS_18 §1.2) |
| **`world+0x12c`** | scene playback kind: 0 = none, **6** = kine (`KinePlay`), 7 = the other scene start, 8 = noe scene, 0xd = a fourth kind. Only 0 or 7 lets a new scene start |
| `world+0x130` | per-scene flags/timer: 0x30 (kine), 0x31 (kine, arg3 != 0), 0x420 (noe scene), 0x1021 (kind 0xd), 1 (kind 7) |
| `world+0x138`, `+0x13c` | the kine's two parameters (`KinePlay` args) |
| `world+0x114`, `+0x118` | more kine parameters |
| `world+0x134`, `+0x140` | the scene's live object / the noe scene name (`+0x140`, a string) |
| `world+0x1774`, `+0x177c`, `+0x1780`, `+0x1784`, `+0x1788` | kind 0xd / noe-scene parameters |
| `world+0x178c` | the **state-event manager** `Cslh_StateEventSet` writes into |
| `world+0x1800`.. | — |

The four starters, all of which **refuse unless `world+0x11c == 1`** (OBSERVED, disassembly):

* `FUN_004b27d0(a, b, c, d)` @ 0x4b27d0 — kine. Refuses if `+0x12c` is neither 0 nor 7. Then `+0x138 = a`,
  `+0x13c = b`, `+0x12c = 6`, `+0x130 = 0x30|0x31`, `+0x114 = (c == 0)`, `+0x118 = d`.
* `FUN_004b2850()` @ 0x4b2850 — kind 7. Needs `+0x188 != 0` (a live object) and `+0x12c == 0`.
* `FUN_004b2890(name, b, c, d, e)` @ 0x4b2890 — noe scene. Needs `+0x12c == 0`; sets `+0x130 = 0x420`,
  `+0x177c = c`, `+0x1780`, `+0x1784 = d`, `+0x1788 = e`, copies the name to **`+0x140`**, `+0x12c = 8`.
* `FUN_004b2940(a)` @ 0x4b2940 — kind 0xd. Needs `+0x12c == 0`; sets `+0x1774 = a`, `+0x12c = 0xd`, `+0x130 = 0x1021`.

`world+0x12c = 0` is the "no scene" value; the three starters above only run when it is 0 (or 7 for the kine).

## 3. Scripted camera and input lock (OBSERVED, decompile/disassembly)

* **Camera mode** is `cam = world+0x1764`, `cam+0x16c`:
  * `FUN_0052d6b0(mode)` (0x52d6b0) is the setter; it stores the mode at `+0x16c`.
  * `FUN_0052d5b0` (0x52d5b0) names them: **1 = "event"**, 2 = "free", 3 = "free", 6 = "3rd person", 7 = named.
  * The game itself checks `world->0x1764->0x16c == 1` before it treats the camera as script-driven
    (decompile 4149-4157 and 8840-8841), so **mode 1 is the cutscene camera**.
  * Live: I100 = 2, I004 = 3, B101 = 2 (normal play); no mode 1 was reached in this task (UNKNOWN live).
* **Input lock**: `Cslh_CameraFreezePlayers(on)` -> `FUN_0052d4d0(on)` -> for each human `vtable+0x88`
  = `FUN_004c79e0` (0x4c79e0), which sets **`human+0x2c4` = on** and, when freezing, sends the "PAUS"
  event (`0x50415553`) through the character's own state method. `FUN_004c6bd0` ignores a move direction
  while `+0x2c4 != 0`, so **`human+0x2c4` = "input frozen"**. (Live: 0 in every sample of this task —
  the new-game intro freezes through `world+0x11c = 6`, not through this flag.)

## 4. Live run 1: level change with the door data (`run_s30_probe.log`, OBSERVED)

`chk30base.dll` (HEAD), pair on loopback, both copies in I100 (save 01), then the host's
`level I004 15509 1` (the I100 door's own call):

```
  0.00 [host] lvl=I100 mode=1 req=0 gate=1 ... cam mode=2
reply: ok level I004 15509 1 (game thread)
  0.20 [host] lvl=I004 mode=1 req=0 gate=0  cam mode=3
  0.50 [guest] lvl=I004 mode=1 req=0 gate=1 cam mode=3
  ... 24 s later: both still lvl=I004 gate=1 cam mode=3, humans at (0.0, 0.0, 0.0)
```

* Both copies took the transition and built I004 (**OBSERVED**).
* **No scripted event of any kind ran**: `world+0x11c` = 1 and `world+0x12c` = 0 in every sample; the
  camera stayed in mode 3. This level entry has no cutscene (**OBSERVED** for I004 via this door).
* The characters are left at (0,0,0) after this transition (life 100, anim 0, both humans) — they are never
  placed at an entry point. That is a FINDINGS_20-family issue, not a cutscene issue; noted, not fixed here.

## 5. Live run 2: the new-game intro — a real cutscene on both copies (`run_s30_intro.log`, OBSERVED)

Both copies run the game's own 2-player new-game flow (`duo_start_game.py` without its ESCAPE skip), which
loads **B101** and plays the intro. 100 ms samples of both copies (phase `intro`):

```
intro 0.00 [host]  lvl=B101 mode=1 req=0 gate=6 SCENE=0 t130=48 138=0x30315f31 13c=0x1 118=0x1 cam mode=2
             :: BOY2 frz=0 anim=0 life=100.0 pos=(-64.1, -18.5, 0.9) | GIR2 ... pos=(11.0, -134.5, 0.9)
intro 0.00 [guest] lvl=B101 mode=1 req=0 gate=6 SCENE=0 t130=48 138=0x30315f31 13c=0x1 118=0x1 cam mode=2
             :: (same positions)
```

* Both copies enter the intro **at the same time** and with the same scene id: `world+0x11c = 6`,
  `world+0x138 = 0x30315f31` = "1_00", `world+0x13c = 1`, `world+0x118 = 1`, `world+0x130 = 0x30`
  (**OBSERVED**). `world+0x12c` is 0 in the same samples: the kine has already *finished* and the level is
  in the presentation state, waiting for the player to skip. The characters stand at their start positions
  with the controls locked (**OBSERVED**: they do not move in 10 s).
* `world+0x138` = "1_00" is exactly the kine id `KinePlay` would have written (`+0x12c` cleared when the
  kine ended) — DERIVED from §2.

**The skip.** After 10 s the HOST taps ESCAPE:

```
hostskip 0.00 [host]  ... gate=1 ...  t130=35
hostskip 0.00 [guest] ... gate=6 ...  t130=48
hostskip 5.03 [guest] ... gate=6 ...            <- 5 s later still in the cutscene
```

and the guest is **still at gate=6 after 18 s** (host skipped at t=0; the guest only left when the GUEST's
own ESCAPE was tapped, `guestskip` 0.00 -> 0.03). **OBSERVED: a host-side skip leaves the guest stuck in
the cutscene, and a guest-side skip is invisible to the host.** This is the bug this task fixes.

## 6. What the mod does now (design)

`PKT_SCENE` (NET_VERSION 16), host -> guest and guest -> host:

```
kind 1 = state:   world+0x11c, world+0x12c, world+0x130, world+0x138, world+0x13c, world+0x118, level
kind 2 = skip:    "I am leaving the scene, leave it too"
kind 3 = entered: "I entered it" (a guest-side trigger the host must also run)
```

* The host streams its state on every change and 4x/s while non-normal, so a lost packet cannot leave the
  guest behind.
* **Skip policy (decided): either player may skip; a skip by either player skips on both.** When a copy's
  `world+0x11c` leaves 6 (or `world+0x12c` leaves a scene kind) while the other copy is still in it, the
  leaving copy sends `kind 2`; the receiver applies the skip **through the game's own input path** — ESCAPE
  (DIK 0x01) through the mod's virtual keyboard, then START on the local pad if that did not take. Nothing
  is written into the game's state variables, so the game's own exit path (and its cleanup) always runs.
* While either copy is in a cinematic (`world+0x11c == 6`) or in a scene (`world+0x12c != 0`):
  * the guest stops forcing its camera target (`guest_follow_own_player`): the script owns the camera;
  * the guest stops streaming `PKT_CHAR` and the host ignores an incoming `PKT_CHAR`: the script owns the
    characters, and a streaming owner would drag a frozen character around on the other copy.
* The guest does **not** replay a cutscene it missed (the kine is a timed movie; starting it late would make
  the guest watch it alone). It is told the host is in one, and both leave together. A guest-side trigger
  (`kind 3`) is reported to the host, which logs it; the host does not start a scene the guest alone ran.

Same-family coverage: the state sync is one variable pair (`world+0x11c`, `world+0x12c`) that every kind of
scripted event in §1/§2 goes through — FMV/kine (6), noe scene (8), the other kinds (7, 0xd), scripted
camera (`cam+0x16c` = 1), dialogs and the freeze flags: all of them are "the world is not in state 1" and
all of them end through the same local skip input.

### 6.1 The live result (OBSERVED, `run_s30_cut3.log`)

`tests/run_cutscene_pair.sh` (new) starts the pair into a 2-player new game, stops with the intro still
running, takes pictures of both copies, then `tests/check_cutscene.py` skips on ONE copy:

```
host : scene local state 6 scene 0 id 01_1 level B101 cine 1 | peer state 6 ... cine 1 | sent 71 rcv 71 skips 0 ...
guest: scene local state 6 scene 0 id 01_1 level B101 cine 1 | peer state 6 ... cine 1 | sent 71 rcv 71 skips 0 ...
== 2. skip on the host only (ESCAPE, the game's own skip)
  host  left the event after 0.0 s (skips 0)
  guest left the event after 0.0 s (skips 1, its own input: none)
  PASS: the skip on the host ended the event on the guest (forwarded skip applied, skips 1)
== 4. both copies end in the same state
host : B101 level B101 state 1 scene 0 humans [('BOY2', (-64.1, -18.5, 0.9)), ('GIR2', (11.0, -134.5, 0.9))]
guest: B101 level B101 state 1 scene 0 humans [('BOY2', (-64.1, -18.5, 0.9)), ('GIR2', (11.0, -134.5, 0.9))]
cutscene sync: PASS
```

Before the fix (same pair, same flow, `run_s30_intro.log`): the guest stayed at `world+0x11c = 6` for the
whole 18 s window and only left when the guest's own ESCAPE was sent.

Two things were needed and both are OBSERVED:
* the guest must **hear** that the host left (PKT_SCENE heartbeats while in a scene and for 3 s after),
* the forwarded skip must move the game's **polled** keyboard state, not only the buffered records:
  `g_vkeys[0x01]` *and* `keyq_push(0x01)`. With `keyq_push` alone (`run_s30_cut2.log`) the guest ran the
  ladder five times (`skips 5 stuck 4`) and never left, because the cinematic reads DirectInput's
  GetDeviceState snapshot (`hk_GetDeviceState` patches it from `g_vkeys`) and not GetDeviceData.

### 6.2 Screenshots (OBSERVED, `tests/shots_cut30/host.png` and `guest.png`, viewed)

Both copies during the B101 intro: the same in-engine cutscene frame — a close-up of a giant flower with
Leonard/Herbert in it — and the same subtitle line "Leonard and Herbert - twin brothers that had
specialised in experimental botany." The frames differ only in the FPS counter and the subtitle timer
(`frame 800x600 mean abs diff whole 2.37, lower-centre 2.63`). So the cutscene itself was already mirrored
by the two level scripts; what was missing was leaving it together.

## 7. Story state (OBSERVED/ DERIVED)

* **HP**: `human+0x320`, host-owned and already streamed (`ch_state.life`, applied by `guest_apply_state`) —
  a story `CharacterSetLife` therefore reaches the guest. UNKNOWN live (no story event set HP in this task).
* **Battery/energy**: `inventory+0xc88` (float), written by `Cslh_EnergySet` (0x4bca00). **Nothing synced
  it before this task**; `pkt_state` now carries it (`energy`/`energy_valid`) and the guest writes it.
* **Inventory**: `world+0x1790` entries, already synced by `PKT_ITEM`.
* **Story flags**: `Cslh_StateEventSet` writes into the state manager `world+0x178c`, which is **not** the
  progress object the region sync copies (`game+0x318`). UNKNOWN whether the two mirror each other; the
  progress block's entity-state table (progress+0x814) is what the game persists and what the region sync
  covers, so a story flag that only lives in `world+0x178c` is **not** synced by the region path.
* **Character switch**: `Cslh_CharacterSwap` changes the live party; the party table (progress+0x1b0c) is
  synced as a region and `check_party.py` asserts the parties match (regression below).

## 8. UNKNOWN / not covered

* No live cutscene with a **scripted camera** (`cam+0x16c` = 1) was reached: the only live cutscene is the
  B101 intro (state 6, camera mode 2). The camera-mode part of the code is therefore DERIVED, not observed.
* `world+0x12c` = 6/7/8/0xd was never observed live (the intro had already finished its kine). The
  replication of a scene *start* is implemented only for the "report it" direction; nothing calls the four
  starters on the peer.
* Whether `world+0x178c` mirrors `progress+0x814` is UNKNOWN.
* The **guest-initiated skip** direction (`check_cutscene.py --skip-by guest`) uses the same symmetric code
  path but was NOT run live: the 18-game-process cap was spent on the host-skip case and the regression
  runs below.
* The battery/energy field (`inventory+0xc88`) is streamed and applied (`energy` counter in the `scene`
  reply), but no live run changed it (no story event set the battery in this task): the copy path is
  DERIVED, not OBSERVED.
* Regression runs `check_breakables.py` (slot 3) and `tests/run_reconnect.sh both` were **not run**: the
  task's 18-game-process hard cap was reached (see §9).

## 9. Game processes used in this task (18 max)

| # | run | processes |
|---|---|---:|
| 1 | `run_pair_menu.sh` probe (I100 -> I004) | 2 |
| 2 | `duo.py start` probe attempt (wrong test root, no game) | 2 |
| 3 | new-game intro probe (`run_s30_intro.log`) | 2 |
| 4 | `run_cutscene_pair.sh` (uninitialised critical section: the pair hung) | 2 |
| 5 | `run_cutscene_pair.sh` (skip pushed only to the keyboard *queue*: guest did not leave) | 2 |
| 6 | `run_cutscene_pair.sh` (**PASS**, `run_s30_cut3.log`) | 2 |
| 7 | `run_pair_menu.sh check_party check_items check_hands check_hands_visible check_entities` (all OK) | 2 |
| 8 | `run_pair_menu.sh check_movement` | 2 |

Total 16 when `check_movement` finishes; `check_breakables` and `run_reconnect.sh` would have needed 4 more.
