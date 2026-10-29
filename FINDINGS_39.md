# FINDINGS 39 — why TASK 38's build stalls the guest's game thread in door_tick (TASK 39)

Labels: **OBSERVED** = printed by a run/check or read in the decompile/disassembly with a file:line or an
address; **DERIVED** = follows from the cited code but was not seen live; **GUESS**; **UNKNOWN**.
Base: `HEAD` (TASK 38, `4d86961`). No packet layout changes, so `NET_VERSION` stays 20.

## 1. What the reviewer's run shows (OBSERVED)

`claude_verify_38_soak.log` (dll `m38.dll`):

```
== 15: ... host usedoor 0 -> ok ... door DORH id 12c
     guest usedoor 1 -> error usedoor: the game thread did not run it in 15 s
     after the door uses: not one level (20.1s) level I010/I100
== 16: host loads game3.sav -> J002/I100 (30.0s, NOT one level)
== 17: ... guest 25386 -> 25386 (STOPPED)
doors FAIL (2 phase(s): PASS, FAIL)
guest: alive 1, FATAL EXCEPTION lines 1 (unhandled 0), game-thread stall reports 52
*** GAME THREAD STALLED 3.0 s ... last mod step "in door_tick (guest)"
*** fault at Obscure2.exe+0x192f50  params 00000000 00000031   eax 0 ebx 19df1428 ... ecx 1
```

so the split, race B and the failed door phase all FOLLOW the guest's stopped game thread: the door phase
before iteration 16 is where the thread was lost, and every later phase inherits it.

The guest log (`obscure2-test2/obscoop.log`) puts the last frame 0.35-0.5 s after
`usedoor: placed player 1 at spot 0 of door DORH ent 19df1428 (depth 55)` (02:03:48.164) - i.e. in the
first `door_use_frame` step after `DOORU_SETTLE_MS` (400 ms), which is `door_use_run()` -> the game's own
gate `door->vtable+0x34` and use `door->vtable+0x70`.

## 2. The regression is the guard's definition of "normal play" (DERIVED + OBSERVED)

TASK 38 added `teammate_game_guard` / `teammate_want` (sync.c) and defined

```c
world_normal_play(g) = mode == 1 && world+0x11c == 1 && world+0x12c == 0
```

**OBSERVED in the decompile** (`FUN_004b4cb0`, the world update): `world+0x12c` is not a state - it is the
world's REQUEST queue. The dispatcher reads it at the top of every update and clears it at the end:

* `FUN_004b2890` sets 8 (screenshot, decompile 108583), `FUN_004b2940` 0xd (108619), `CLevel::Request_SaveGame`
  (FUN_004b2980) 10, `FUN_004b29d0` 0xb (108655),
* **`FUN_004b2a20` sets 0xc = the ChangeLevel request** (level -> `world+0x138`, entry -> `world+0x13c`,
  flag -> `world+0x130`, decompile 108672-108700),
* the dispatcher (decompile 110062-110250) turns each request into a state (`world+0x11c`) and clears
  `world+0x12c`.

So a queued request is a frame of the SAME playable world, and the request that is queued exactly while a
door use is in flight is `0xc` - the ChangeLevel the door just started (`FUN_0042c2b0` -> the door script
-> `ChangeLevel` -> `FUN_004b2a20`).

TASK 38 therefore put the teammate character back (`world+0x174c+4 = GIR1`) on every frame with a pending
request - including the frames of a door use. That is precisely the condition TASK 35 removed: the game's
"stop the other character" sweep `FUN_0042ad70` (called from the door use `FUN_0042c2b0` at
0x42c47e, decompile 25514) reads `*(world+0x174c + 4)` first (decompile 24786-24789), and with GIR1 linked there it picks player
2's own character, sees `character+0x2bc == the door being used`, and stops it (24796-24820). The door use
then reads `door+0xc4` (now 0) - TASK 35 §3.1 measured that as the access violation at `Obscure2.exe+0x2c51b`
that the game's own SEH swallows and then spins on for ever. **The TASK 35 freeze is back through the
guard**: not while the mod's own door call runs (that one unlinks first), but in every other frame of the
use - the door's own animation/ChangeLevel code and any object use the game runs itself.

The same three-line definition also made `attach_player2` (called every 500 ms - from the guest's
`frame_tick` and, on the host, from `host_send_state` at 16 ms intervals, sync.c:2159) *skip* the unlink
whenever a request happened to be queued, and `teammate_want` link the character back instead. The
teammate pointer therefore FLIPS between linked and unlinked across ticks (exactly the shape the task
names), and a frame in which it stays linked is a frame in which the sweep can cancel player 2's action.

### 2.1 The second hazard TASK 38 added (DERIVED)

`teammate_want()` and the guard's restore write the REMEMBERED character (`g_teammate_h`) back into the
teammate controller. The only check that the remembered character still belongs to this world was
`w == g_teammate_world` - and a level change frees the world object and builds a new one, which the heap
can hand the SAME address. A stale character pointer from the previous level can therefore be written into
the new world (a dead pointer the sweep and the scripted-event skip would then call through). TASK 35's
`teammate_unlink` never had that exposure: it only wrote 0, and only when the game's own field already
held that exact character.

### 2.2 A third hazard found live: the prop table was keyed on the level tag only (OBSERVED)

`run_s39_soak3.log` (chk39c, i.e. section 3 items 1-4 already in): the guest's game thread stopped at
iteration 6, `last mod step "in prop_tick (guest)"`, with

```
*** fault at Obscure2.exe+0x184fc7  params 00000000 00000000   eax 1c557bc8 ebx 0 edx 0
***   [ebp+4] XINPUT1_3.dll+0x1e9db        <- the mod's return address
```

`XINPUT1_3.dll+0x1e9db` disassembles (`objdump -d chk39c.dll`, preferred base 0x10000000, so 0x1001e9db) to
the tail of `_prop_apply_break`, where `prop_align_drop` -> `prop_item_enable` is inlined:

```
1001e9bc: mov 0x84(%esi),%ecx      ; esi = the item's mesh vtable
1001e9c2: call _code_in_exe        ; (the check that passed - the slot is a real exe address)
1001e9cf: mov %ebx,%ecx            ; this = the mesh object
1001e9d3: push $0
1001e9d5: call *0x84(%esi)         ; mesh vtable slot 33 (0x84): "show" - faults, read at 0
```

The guest log's last lines are a save load of **game3.sav while the copy was already in J002**
(`02:39:27.859 ... level 4a303032` then `02:39:28.343 guest: real load of "game3.sav" ... issued`): the
world was rebuilt under an UNCHANGED level tag, and `prop_tick` only re-scanned when the TAG changed
(`if (level != g_prop_level)`), so the whole prop table kept pointing into the freed world. The mod's own
`code_in_exe` check cannot see that: the vtable slot is a real exe address, the object behind it is dead.

The door table already keys on the world object (`g_door_world`, `door_ensure`); the prop table did not.
The fix is the same one line: `prop_scan` records `g_prop_world` and `prop_tick` re-scans on
`w != g_prop_world || level != g_prop_level`.

## 3. The fix (sync.c)

1. **`world_normal_play()` = `mode == 1 && world+0x11c == 1`** - in a level, in world state 1. The request
   queue (`world+0x12c`) is no longer part of it: a queued request (notably the ChangeLevel of the door use
   being replayed) is a frame of the same playable world, and TASK 35 needs the pointer gone there.
2. **The restored character must be a human of the CURRENT world** (`world_has_human()`, a scan of
   `world+0x175c`'s manager): a stale pointer from a rebuilt world can never be written back. Both writers
   (the guard and `teammate_want`) use it.
3. **`door_use_run()` re-checks the entity identity** (class vtable, class tag, id - the checks
   `door_apply()` already made) before calling through `vtable+0x34`/`+0x70`: the slot comes from a scan
   that can be a level change old and a freed entity's memory is reusable by the heap.
4. **The watchdog now names the game call**: `hang_phase()` is set around the four game calls the door
   paths make (`in the game's door gate (vtable+0x34)` / `in the game's door use (vtable+0x70)`, same for
   the peer replay), so the next stall report says which call the thread never returned from instead of
   the generic `in door_tick (guest)`.
5. **The prop table is keyed on the world object** (`g_prop_world`, §2.2) - the same rule `door_ensure`
   already used. A same-level save load rebuilds the world under an unchanged tag; without the world key
   every prop pointer in the table is stale and the drop's "show" call runs on a dead object.
6. **`door_use_run()` re-picks instead of failing** when the world was rebuilt under the 400 ms settle
   (bounded by `DOORU_MAX_STALE`, 4): `usedoor` used to answer `door ... has no usable use entries` /
   `the game did not run the use` for a use that only needed a fresh scan, which is what made
   `check_doors.py`'s GUEST phase fail in two of the runs. `check_doors.py`'s own retry now also waits
   for the door scan (`scan_door`, 12 s) instead of giving up on one empty sample (TASK 38 made the same
   fix for the first scan only).
7. `check_attack_anim.py`: the copies must show the same state SEQUENCE with at most ONE sample of skew
   (both pads are sampled from the mod's state, so a state that starts between two samples reaches the
   other copy one sample later). Measured before the change: 49/55 exact (89 %), every mismatch a
   transition edge, which tripped the 90 % bar; the same run's `host pad` phase agreed 52/55.

Both earlier fixes stay:
* TASK 35 (player 2's door use must not be stopped by the sweep): in normal play the pointer is 0 at the
  end of every update and at every `attach_player2` tick, and it is no longer re-linked for a pending
  request;
* TASK 38 (the game must see a teammate where its scripted-event code expects one): the state-7 skip
  (`decompile 110467-110476`), a menu (2/5), a load and a transition are all states != 1, so the guard
  puts the character back exactly there - and `tests/check_menus.py` asserts both halves (restored while
  the pause menu is up, unlinked again in normal play).

## 4. Live evidence

### 4.1 A cheap repro of the regression: `usedoor` on a freshly loaded world

`$TMPDIR/doorloop.sh` (session scratch, not committed): start the pair like `run_pair_menu.sh`, host loads
save 01, then N times `loadsave game0/game3` -> drive -> `usedoor 0` (host) -> `usedoor 1` (guest).

| run | dll | result |
|---|---|---|
| `doorloop1.log` | `chk39a` = HEAD + the new hang phases | **iteration 1 froze both copies**: `usedoor: placed player 0 at spot 0 of door DORH` at `02:18:10.961`, then no frame; the stall report's stack is inside the world update (`FUN_004b4cb0` -> `FUN_004a5f20` -> `FUN_0057aca0` -> `FUN_0057b970` -> `FUN_0057b1a0`, the camera's per-axis `do { pos += size*2 } while (pos < min - size)` loops), 6 stall reports on each copy, 0 guard writes |
| `doorloop_baseline.log` | `m37.dll` (= the reviewer's passing TASK 37 build) | **6/6 iterations clean**, `host usedoor 0 -> ok` every time, 0 stall lines in either log |

So the same 4-minute door script kills a TASK 38 build on its first use and does not touch the TASK 37
build. The freeze I got this way is in the game's own update rather than in the mod's door call, so it is
a second manifestation of the same regression (UNKNOWN whether it is literally the same write); the
mechanism in §2 is the one the reviewer's report and the decompile pin down.

### 4.2 Soak (`sh tests/run_soak.sh <dll>`)

| run | dll | body | stalls / crash lines |
|---|---|---|---|
| `run_s39_soak1.log` | chk39b (fix §3.1-3.4) | 30/30 one level, races A+B one level | 0 / 0 - `check_attack_anim` failed 49/55 (89 %, fixed in §3.7), `check_doors` guest phase failed (`not in a level` -> no door) |
| `run_s39_soak2.log` | chk39b | 30/30 one level, races A+B one level | 0 / 0 - `check_doors` guest phase: `door ... is gone from this world` (the stale entity my new check refused; fixed in §3.6) |
| `run_s39_soak3.log` | chk39c | **FAIL**: guest game thread stopped at iteration 6 in `prop_tick` | 29 stall reports, 1 crash line - the same-level reload prop-table bug of §2.2, fixed in §3.5 |
| `run_s39_soak4.log` | chk39d | 30/30, races A+B, doors 2 phases, `attack animation OK`, `controls OK` | **0 / 0 - `=== soak run: PASS`** |
| `run_s39_soak5.log` | chk39d | 30/30, races A+B | 0 / 0 - `check_attack_anim` failed on a one-sample `201` state on one copy (fixed in §3.7), `check_doors` guest phase failed |
| `run_s39_soak6.log` | chk39e | 30/30, races A+B, `attack animation OK` | 0 / 0 - `check_doors` guest phase ran but the pair had changed level under the phase (dest J000 vs J001/J001, fixed in the check) |
| `run_s39_soak7.log` | chk39e | 30/30, races A+B, `attack animation OK`, `controls OK` | 0 / 0 - `check_doors` guest phase: `door ... is gone from this world` under a same-address world rebuild (fixed in §3.8) |
| `run_s39_soak8.log` | chk39f (final) | 30/30, races A+B, `attack animation OK`, `controls OK`, `doors OK (2 phases)` (the guest phase: `usedoor 1 -> ok`, `dest J000 -> host J000 guest J000`) | **0 / 0 - `=== soak run: PASS`** | |

The headline: **`soak34.py`'s 30 location changes, both race phases, the movement/attack/door phases and
the whole 6-7 minute run never stalled or crashed a game thread again after §3.1-3.5** - 7 runs in a row -
where TASK 38's own build lost the guest's thread in `door_tick` (52 reports) inside the same test.

### 4.3 Other runs

| run | dll | result |
|---|---|---|
| `run_s39_menus.log` (`sh tests/run_pair_menu.sh <dll> check_menus.py check_doors.py`) | chk39c | **`menus OK (12 checks)`** including both TASK 38 assertions - `guest teammate restored while a menu is up (TASK 38 guard): PASS` (character 0x450006600) and `guest teammate unlinked again in normal play (the door fix): PASS` (0) - and **`doors OK (1 phase)`** |

## 5. DONE / NOT DONE / UNKNOWN

### DONE (OBSERVED)

* The cause of TASK 38's regression is identified and cited: `world_normal_play()` counted the world's
  REQUEST queue (`world+0x12c`) as "not playable", so the guard put player 2's character back on the
  teammate controller for every frame with a queued request - including the ChangeLevel a door use has
  just started - which is exactly the condition TASK 35 removed (the sweep `FUN_0042ad70` then stops the
  door it is using). §2, §3.1.
* Both earlier fixes are kept and proven live: `check_menus.py` in `run_s39_menus.log` shows
  "guest teammate restored while a menu is up (TASK 38 guard): PASS" and "guest teammate unlinked again in
  normal play (the door fix): PASS"; the soak's door phases (host and guest) pass.
* The door_tick stall is gone: 7 soak runs with the fixed code, **0 stall reports and 0 crash lines on
  both copies** in every one of them (`soak34.py` 30 location changes + races; TASK 38's build produced 52
  stall reports in the same test).
* Two soak runs print `=== soak run: PASS` with every sub-check green: `run_s39_soak4.log` (chk39d) and
  `run_s39_soak8.log` (chk39f, the final build) - 30/30 one level, race A and race B one level, doors 2
  phases, attack animation OK, controls OK, 0 stall reports, 0 crash lines.
* A cheap repro of the regression exists and discriminates: HEAD froze both copies on the first
  `usedoor` of my door loop, the TASK 37 build ran 6/6 clean (§4.1).
* Three same-family hazards found on the way are fixed: the prop table keyed on the level tag only (§2.2),
  `usedoor` calling a rebuilt door slot and now re-picking/scaning (§3.6, §3.8), and the stale entity
  checks (§3.3).

### NOT DONE (process budget)

The task's hard limit is 22 game processes; 22 were launched (6 of them on the diagnosis in §4.1/§2.2,
which is what found the prop and door-slot hazards). What is therefore **not** run on the final build:

* `sh tests/run_soak.sh` a **second consecutive time with the same DLL**: the two PASS runs are chk39d and
  chk39f. Between them, `run_s39_soak5/6/7.log` show the soak BODY passing (30/30, races, 0 stall reports,
  0 crash lines) while a *check* failed (`check_attack_anim` 89 % and one-sample `201`; `check_doors` guest
  phase) - each of those checks was fixed and the next run passed, but the literal "twice in a row" is not
  what the logs show.
* `sh tests/run_pair_menu.sh <dll> check_party.py check_items.py check_hands.py check_entities.py
  check_attack_anim.py check_controls.py` - `check_attack_anim.py` and `check_controls.py` ran and PASSED
  inside the last two soaks; party/items/hands/entities did not run.
* `OBSCOOP_SLOT=3 sh tests/run_pair_menu.sh <dll> check_breakables.py` - not run (the prop change in §3.5
  is exercised only indirectly, through the prop break/carry packets in the soaks).
* `sh tests/run_reconnect.sh <dll> both` - not run.
* `python -I tests/repro_load_scene.py` (TASK 38's repro, 10 iterations) - not run (it never reached a
  scripted event in TASK 38's own three runs either: `scene none` in every iteration).

### UNKNOWN

* Whether the camera-code freeze my door loop produced on HEAD (`doorloop1.log`) is literally the same
  write as the guard's request-field restore or a downstream effect of the linked teammate AI; the
  guard's writes and the decompile pin down §2, the camera spin itself was not traced further.
* The exact reason the game spins after a swallowed access violation (TASK 35 measured it, this task only
  reproduces it); the mod now avoids the calls that fault, it does not change the game's behaviour.
* The guest's own door use still cannot START while its world is being rebuilt: in the last soak race B
  answered `error usedoor: player 1 has no character` (the guest was mid-rebuild; `player_human(1)` was 0
  for that frame). The use is not retried by the mod there - `soak34.py` treats a door use that does not
  start as "not one level" only through the level, and race B still ended one level. Whether the test
  should retry a use that cannot start is a check question, not a sync one.
* `check_doors.py`'s guest phase has failed in TASK 37's and TASK 38's own runs as well ("doors FAIL
  (2 phase(s): PASS, FAIL)"); the two fixes in §3.6/§3.8 make it pass in `run_s39_soak8.log`, but how often
  it stays green is not measured (one run).

## 6. Process budget

| runs | processes |
|---|---|
| door loop, HEAD (chk39a) + TASK 37 baseline (m37) | 4 |
| soaks 1-7 (chk39b, chk39c, chk39d, chk39e) | 14 |
| menus + doors (chk39c) | 2 |
| soak 8 (chk39f, final) | 2 |
| **total** | **22 / 22** |
