# TASK 12 FINDINGS — bringing a guest that sits at the main menu into the host's save load

Status labels: **OBSERVED** = printed by a check / visible in the decompile or disassembly this session;
**DERIVED** = follows from the cited code but not proven live; **GUESS** = plausible, unproven;
**UNKNOWN** = not established. Decompile line numbers are `<local>\decomp2\Obscure2.exe.c`; addresses are
static (image base 0x400000). Disassembly was read from the test copy
`local\obscure2-test\Obscure2.exe` (same build, 215294).

## 0. Summary

* The save load is **two calls**, not one: the save manager at `game+0x3e4` must first **open** the file
  (`FUN_0053d9b0(name)`), and then the game object is asked to load it (`FUN_004a1bd0(name)` = request
  state 3). State 3 reads the chunks from the manager's already-open file into `game+0x318` and builds
  the level itself. **OBSERVED** (disassembly 0x5484ef..0x548514 and decompile 98981..99008).
* The main menu does have a Load item, but it loads the **fixed** file `o2.sav`; it cannot load save
  slot 01. **OBSERVED** (decompile 200155..200166, strings.tsv lines 2200-2206).
* Today a guest at the main menu **never follows** the host: `REQ_LEVEL` is kept queued while
  `mode != 1` / no world, and `REQ_LOAD_NAME` is applied as a bare state 3 without the file being opened,
  so the state machine re-loads whatever the progress object already held. **OBSERVED** in code
  (`guest_apply_requests`, `src/sync.c`).
* Fix: replay the menu's own two calls on the guest, on the game thread, once the save file named in the
  host's request is complete on disk. The guest then builds its own world from the same file; the host's
  level request for that level is dropped as "already loaded".

## (a) Does the main menu offer Load, and how can the host load save 01 from it?

**OBSERVED — the menu items are XML-driven and their handler is FUN_004a4060/FUN_005481c0.** The main
menu branch (decompile 200121..200167) reads an item's `state` attribute and acts on these values:
`newGame` -> `FUN_004a1ba0(0)` (state 2, LoadProgress), `newGame2` -> `FUN_004a1ba0(1)` (2-player new
game), `loadGame` -> `FUN_0053d9b0("o2.sav")` then `FUN_004a1bd0("o2.sav")`, `main_menu` -> back to the
main menu. So the main menu's Load Game is hard-wired to **o2.sav** (`strings.tsv` 2205/2206:
`0066bdb8 ... o2.sav`, `0066bdc0 ... o2.sav`), not a slot picker.

The test copies' `Save` folder holds only `game0.sav`..`game9.sav` (**OBSERVED**, `ls`), no `o2.sav`, so
the main menu's Load Game finds nothing. The slot list lives in the **pause menu** save browser
(decompile around 207650..207720): it selects the slot (`FUN_0053cfa0`), reads its name (`FUN_00592510`)
and then calls exactly `FUN_0053d9b0(name)` + `FUN_004a1bd0(name)`.

**OBSERVED — the two calls, from the disassembly of the menu (`FUN_005481c0`, main-menu branch):**

```
5484ef: movl 0x6c3068, %ecx          ; game
5484f5: movl 0x3e4(%ecx), %ecx       ; game+0x3e4 = the save manager
5484fb: pushl $0x66bdb8              ; "o2.sav"
548500: calll 0x53d9b0               ; manager->open(name)
548505: testl %eax, %eax
548507: je    0x54853b               ; no such save -> nothing happens
548509: movl 0x6c3068, %ecx          ; game
54850f: pushl $0x66bdc0              ; "o2.sav"
548514: calll 0x4a1bd0               ; LoadByName(name) -> request state 3
```

The pause-menu save list does the same at 0x553cf0/0x553d0a with the selected slot's name
(`FUN_0053cfa0(manager, slot)` + `FUN_00592510()` first). **OBSERVED.**

**Consequence:** the *host* can be brought from the main menu into save 01 only by replaying these two
calls with the name `game0.sav`. **Implemented as a test-only pipe command `loadsave <name>`**
(`src/obscoop2.c`): it does not poke game state, it calls the game's own open + LoadByName on the game
thread (the game update hook), i.e. the same path the menu takes.

Also **OBSERVED**: the request state machine runs from the game object's per-frame update
`FUN_004a5f20` (decompile 99259): its first action is `if (*(game+0x320) != 0) FUN_004a5520();` — no
mode test. `FUN_004a5f20` also handles mode 4 (the in-game pause menu), so a request made at the main
menu is executed there. Prologue `55 8b ec 56 8b f1` (6 whole bytes) — hooked.

**OBSERVED live (probe, run 2): at the front end `game+0x310` is 2, not 4.** Mode 4 is the in-game
pause menu (`FUN_004a5f20`: `if (mode == 4 && game+0x314 == 0) update the menu manager at game+0x3f4`).
Both copies sat at `mode 2, state 0, world 0` for the whole menu wait; the new game-update hook printed
`game update hook runs (mode 0 world 0)` at boot and ran in every mode. The live test scripts therefore
wait for **mode 2 and no world**.

## (b) What happens today when the guest (front end, world 0) gets the host's requests?

`src/sync.c: guest_apply_requests` (frame tick / Present):

* **REQ_LEVEL** — guard: `if (!g0 || game+0x310 != 1 || game+0x320 != 0 || !world_obj())` keep the request
  queued and return. At the front end `mode == 2` (not 1) and `world == 0`, so the request is **never
  applied** and the party wait restarts every frame. The guest stays at the menu. **OBSERVED** in code.
* **REQ_LOAD_NAME** — no guard: it calls the hooked `LoadByName` on the guest (state 3). But state 3
  (`FUN_004a5520`, decompile 98981..99008) does **not** open any file: it calls
  `(*(game+0x318)->vtable+4)()` = `FUN_005407a0` (CGameState slot 1, `vt_slots.tsv` 139), which reads
  already-open save chunks through the file object at `CGameState+0x810`
  (= `save_manager+0x118`; set once in the game object constructor, decompile 99759). Missing the
  menu's open call, the chunk reads return nothing, the progress object keeps its previous content, and
  the level it then loads is `game+0x318+0x1c4c` — whatever was there before (common_state / the level the
  guest was already in). At the main menu that is not the host's save. **OBSERVED** (decompile) —
  the live effect at the menu is what the baseline run measures.
* **REQ_LOAD_PROGRESS** — a menu-load does not produce one (state 2 is only the `newGame`/`newGame2`
  path, decompile 200154..200157), so it is irrelevant here.
* **`hk_party_table`** (0x4a20c0) is only called from state 4 (decompile 98936..98942), so a state-3 load
  does not go through the mod's party override — the guest builds its party from the file itself. That is
  what we want. **OBSERVED.**

State 3's exact work (**OBSERVED**, decompile 98981..99008): set state 1; `progress->vtable+4()`
(CGameState::load: chunk ids 5, 8, 7, 2, 6, 4, 0xb into `+0x1ad8/+0x1b00/+0x1c4c/.../+0x1b0c/...`,
decompile 193853..193955); rewrite the second character record's controller tag `2CHC` (0x43484332) to
`MTHC` (0x4348544d); `game+0x464 = 0`; level = `progress+0x1c4c`; `FUN_004a3c10(level,0)` and
`FUN_004a1fc0()` (wait for level resources), `FUN_004b2cc0(1000,0)`, then `mode = 1, state = 0`.
If a resource step returns 0 the state stays 1 and `FUN_004a3330` continues the load next frame.

## (c) The change implemented

1. **`src/sync.c` — real load machinery** (`request_real_load`, `game_load_tick`):
   * a pending real load is stored under a small critical section; the actual calls happen on the game
     thread in the new game-update hook (`FUN_004a5f20`), never on the pipe/UDP/render thread (the save
     manager allocates and reads inside the game's memory — the same reason the weapon apply runs in the
     input-update hook);
   * `game_load_tick` waits for the named file to be complete: it must exist in `<exe>\Save\` **and**, on
     the guest, the host's windowed save transfer must have finished for it (new `PKT_SAVES_DONE`, sent
     by the host when the last chunk of `game9.sav` is acked; the guest clears the flag when a new
     transfer starts at `game0.sav` offset 0). Deferral is 10 s, then one log line and the request is
     dropped (**no** partial-file load).
   * then: `manager = *(game+0x3e4)`; `manager->open(name)` (`FUN_0053d9b0`, prologue checked with
     `code_ok`); if it returns non-zero, call **the hooked** `0x4a1bd0` (so the host's `hk_load_name`
     forwards `REQ_LOAD_NAME` to the guest exactly as a menu load does; on the guest that hook does not
     forward, it only logs and runs the game's function).
2. **Guest request handling** (`guest_apply_requests`): `REQ_LOAD_NAME` on a guest **without a world**
   now asks for a real load instead of calling LoadByName bare. With a world (the old new-game-first
   flow) the old call is kept unchanged.
3. **Verification instead of rebuild**: after the guest's own real load, a host `REQ_LEVEL` for the level
   this copy is now in (within 25 s) is dropped with a log line — the world was already built from the
   same file. The party table hook, inventory mirror, state snapshots and weapon mirror keep running and
   only top up.
4. **Reliability**: `REQ_LOAD_NAME` is repeated every 250 ms for 3.5 s like `REQ_LEVEL` (PKT_REQ has no
   ack) and the guest drops duplicates (same name queued or applied within 4.5 s).
5. `NET_VERSION` 6 -> 7 (new packet type `PKT_SAVES_DONE = 15`).

## 1. Live runs

All runs used the two test copies (`local\obscure2-test`, `local\obscure2-test2`) on loopback and always
stopped them. "New DLL" = the tree in this worktree built as `chk12.dll`; "old DLL" = `git archive HEAD`
built as `chk_base.dll`.

| run | DLL / flow | host action | guest result |
|---|---|---|---|
| 1 (baseline) | old DLL, `--host-newgame` | New 2P game, then pause -> Load save 01 | **the host action itself failed**: the host stayed in B101 (start_save.py never reached the pause-menu Load), so this run says nothing about the guest; the old flow's documented baseline is FINDINGS_11 run 2 (guest 8 entities vs host 43, empty hands). The run's checks are in the report. |
| 2 (new) | new DLL, both at the main menu | `loadsave game0.sav` (the game's own open + LoadByName) | **guest followed by itself**: `guest: host LoadByName "game0.sav" (world none)` -> real load -> I100, 2 humans (BOY1+GIR1). check_party/items/hands/hands_visible OK, **entities 43 vs 43**. Screenshots black (capture problem, see below). |
| 3 (new, repeat) | same | same | same result: party OK, items OK, hands OK, hands_visible differences **none**, **entities 43 vs 43**. Screenshots still black. |
| 4 (new, pictures) | same | same | hands OK, entities 43/43; screenshots now **real frames**: host and guest both show GIR1 holding the chainsaw and BOY1 the taser; non-black 97.2 % / 97.1 %, mean abs diff 3.18 (whole frame), 1.58 (lower centre). |
| 5 (lossy) | new DLL, `OBSCOOP_FLOW=menu`, relays 60 ms lag / 20 ms jitter / 5 % loss, `--save-xfer` | `loadsave game0.sav` after the guest was emptied of saves | **PASS**: guest waited for the transfer (`saves_done` at 01:39:00.425), loaded `game0.sav` at .819, world up 93 ms later; CONVERGED (level I100, inventory 44, party BOY1/GIR1); check_save/party/hands/items/savexfer all OK. |

Verbatim guest log of the real load (run 4):

```
01:36:59.420 [37136] guest: host LoadByName "game0.sav" (world none)
01:36:59.420 [37136] guest: real load of "game0.sav" requested (host)
01:36:59.463 [37136] guest: real load of "game0.sav" (host): the game's save open ok
01:36:59.463 [37136] request LoadByName "game0.sav" [mode 2]
01:36:59.463 [37136] guest: real load of "game0.sav" issued (mode 2 request state 3)
01:36:59.633 [37136] guest: the world this copy built from the save itself is up (level I100, 172 ms after the load)
```

**OBSERVED, run 4 memory (check_hands.py):** host and guest both have BOY1 `['CBOW','TASE','UBET','DYNA']`
slot 0 and GIR1 `['SHOT','47554e00','CSAW','FLBA']` slot 2, i.e. the weapon in the hand is CBOW and CSAW on
both; inventory 44 on both. `check_hands_visible.py`: `differences host vs guest: none`.
`check_entities.py`: host 43, guest 43, the same tags in the same order.

**OBSERVED, run 4 pictures:** the host frame and the guest frame show the same room and the same pose:
GIR1 stands with the chainsaw held in both hands, BOY1 behind her holds the small bright taser. The guest's
hands are **not** empty any more (FINDINGS_11 run 2 had the guest's arms down and nothing in the hands).

The black frames in runs 2/3 were a capture problem, not a game problem: `PrintWindow(PW_RENDERFULLCONTENT)`
and a screen `BitBlt` both returned an all-black client area while the window was in the background. Making
the window topmost did not help; a real left-click into the window (which activates it) did — **OBSERVED**:
after the click the very next PrintWindow gave 97 % non-black. The likely reason (**DERIVED/GUESS**) is that
this game stops presenting while it is not the active window. `tests/shot_pair.py` now retries: topmost, then
a click, then captures (`SetWindowPos` needed `argtypes`, otherwise `HWND_TOPMOST` was passed as 0xFFFFFFFF
and the call silently failed).

## 2. What the old flow does now (unchanged)

A guest that already has a world keeps the old behaviour: `REQ_LOAD_NAME` still calls `LoadByName` bare
(state 3), and the host's `REQ_LEVEL`/party/inventory path is untouched. Only a guest **without a world**
takes the new real-load branch. The new level-drop rule (`guest_owns_level`) is inert for the old flow
because it requires a real load to have happened in the last 25 s.

## 3. Still UNKNOWN / not covered

* Whether a host that loads a save *before* the guest connects can still be followed (the host's
  `hk_load_name` only forwards while `g_peer_ok`, and the welcome path does not resend the name; the guest
  would then only get the level request, i.e. the old rebuild path). Not tested.
* The `guest_owns_level` drop (a *second* save load in the same session, where the host also sends
  `REQ_LEVEL`) never triggered in these runs — both copies' first load has `g_last_level == 0` on the host,
  so no level request is sent at all. It is DERIVED from the code, not observed live.
* Whether the game's own load from the main menu restores *everything* the pause-menu load does beyond what
  the checks read (cutscene/story flags beyond the region mirror) — the region and save checks matched.

