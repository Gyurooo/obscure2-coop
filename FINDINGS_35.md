# FINDINGS 35 — the guest HANG, the two TASK 34 regressions, the falling-animation clue

Labels as in the shared context: **OBSERVED** = printed by a run/check or read in the decompile with a line
number; **DERIVED** = follows from the cited code but was not seen live; **GUESS**; **UNKNOWN**.
The owner's playtest material is private: read only, never copied, and no path from it appears below.
Base: `2eae261` (TASK 34, protocol 18, v1.7+). This task: protocol 19 (new hang/level diagnostics).

Section state while the work runs: §1-§2 are the hang (WATCHDOG, REPRODUCTION, CAUSE, FIX), §3 the
breakables regression, §4 the life/item-use regression, §5 doors guest->host, §6 movement phase E,
§7 the regression table. Every claim is marked when it is written; nothing is filled in ahead of the run.

## 0. What TASK 34 left (OBSERVED, from FINDINGS_34 §6.6 and the soak log)

* The soak ran 30 location changes on the ~90 ms relay; both processes stayed alive and no crash report
  was written - but the GUEST's game thread stopped logging after ~2 loads. Its last game-thread line was
  `guest: door objects: 2 watched in level 4a303032` (the frame after it applied the host's
  `ChangeLevel J002`); afterwards only the net thread wrote (`guest: host party stored ...`) and the pipe
  kept answering `ping`/`sync`. The `sync` counter `frames` (sync.c:4921) is the game-thread heartbeat:
  a frozen count with a live pipe is the definition of the hang.
* The owner's Steam playtest saw the same shape ("game froze with a static image"), also after an attack
  (crossbow) and, the owner thinks, around the FALLING animation. Those are inputs to reproduce, not
  proven causes.
* `soak34.py` only checked "both copies in a common level" and "both processes alive"; a hung guest
  stayed in J002 while the host alternated, so later "one level" rows were coincidences. The soak could
  pass with a dead game thread - that is why the frame-counter check is added (§2).

## 1. The watchdog (§1 item a)

OBSERVED: `src/hang.c` starts a thread at load (`hang_install`, obscoop2.c DllMain) that samples a
game-thread heartbeat. `frame_tick` calls `hang_note_frame()` first thing (sync.c) and increments it on
every presented frame; the same function also opens the game thread's handle once, so the watchdog knows
which thread to look at. When the counter has not moved for **3000 ms** the watchdog:

1. `SuspendThread(game thread)`, `GetThreadContext(CONTEXT_FULL)`;
2. copies the EBP chain (16 frames) and a raw 0x400-byte scan of the stack, keeping the values that fall
   inside the exe image;
3. `ResumeThread` - **before** formatting anything, so a game thread stuck in the loader lock cannot
   deadlock the report;
4. writes the report with `crash_write` (the crash handler's lock-free `WriteFile` path, never `logf`: the
   stuck thread may hold the log lock):
   `*** obscoop: GAME THREAD STALLED <s> s - no frame for <ms> ms (frames N, last mod step "<phase>")`,
   then `*** eip <module>+0x<offset>`, esp/ebp, the general registers and the stack lines in crash.c's
   format. Repeated every **5000 ms** while the thread stays stuck, and a `game thread running again`
   line when it moves.

OBSERVED: `frame_tick` also sets a phase string before each of its steps (`hang_phase`), so the report says
*whether the game thread never came back from a mod call* or stopped in the game's own code. `sync` still
prints `frames`, and `soak34.py`/`run_soak.sh` now fail on a frozen counter and on any stall report.

## 2. Reproduction on the ~90 ms link (§1 item b)

OBSERVED (`run_s35_soak1.log`, dll `chk35a.dll`, 2 relays lag 45 jitter 10 loss 1 %): attack animation
and controls PASS; `soak34.py` reached iteration 7 and then:

```
game threads: host frames 22207 -> 22550, guest 13347 -> 13347 (STOPPED)
     soak stops here: a game thread is not running any more (the watchdog report is in the log)
soak FAIL (30 iterations, alive True)
  guest: alive 1, FATAL EXCEPTION lines 1 (unhandled 0), game-thread stall reports 19
```

OBSERVED, the guest log: the last game-thread lines before the stall are the door phase of iteration 5
(`soak34.py` uses a door every 5th iteration):

```
22:21:25.837 usedoor: the game thread is running the request (player 1)
22:21:25.838 usedoor: placed player 1 55 units in front of door 193052c8 (was 421.1 away)
*** obscoop: GAME THREAD STALLED 3.2 s - no frame for 3203 ms (frames 13347, last mod step "in door_tick (guest)")
*** eip ntdll.dll+0x7867c
*** eip Obscure2.exe+0x2c51b          (later samples; ntdll/steam.dll between them)
```

and the crash handler's report for the same tick:

```
*** obscoop: FATAL EXCEPTION access violation (0xc0000005) on the vectored path
*** fault at Obscure2.exe+0x2c51b  params 00000000 00000220
*** eax 00000000 ebx 00000000 ... esi 193052c8 edi 1a02e450
***   [ebp+4] XINPUT1_3.dll+0x1990b          <- the mod's door call
***   [esp+0x20] Obscure2.exe+0x2c2b0        <- FUN_0042c2b0, the door use
```

## 3. The cause and the fix (§1 item c)

### 3.1 The door crash (OBSERVED)

`FUN_0042c2b0` (the door use, decompile 25496-25608, disassembly 0x42c2b0-0x42c610) stores the using
character in `door+0xc4` and the door in `character+0x2bc` (0x42c3d8/0x42c3de), then calls
`FUN_0042ad70` (0x42c47e) - the game's "stop what the other character is doing" sweep. That sweep takes
the TEAMMATE controller's character when one is linked (decompile 24796-24820:
`piVar11 = *(int**)(*(int*)(world+0x174c)+4)`), and only when that is empty does it walk the two input
controllers and skip the door's own user. It then calls `(*(character+0x2bc)->vtable+0x74)()` - the stop
of whatever that character is using.

A world built from a one-player save (our test saves, and every save in the owner's game) keeps the
partner on the teammate controller, and `attach_player2` points player 2's input controller at that same
character. So when player 2 uses a door, the sweep picks exactly that character, sees
`character+0x2bc == the door being used`, and stops the door: `door+0xc4` goes to 0. Back in
`FUN_0042c2b0` the next use of `door+0xc4` (0x42c515 `movl 0xc4(%esi),%eax` / 0x42c51b
`movl 0x220(%eax),%ecx`) reads through the NULL character - the access violation at
`Obscure2.exe+0x2c51b` with `eax 00000000` in the report above. The game's own SEH swallows the fault and
then spins, which is the owner's frozen image (and the player-2 door use is exactly what the door
regression and the owner's "door use" both do).

The same sequence explains TASK 34's soak hang shape (game thread dead after a door/level change, net
thread alive): the mod's door path is new in TASK 34, and it is the only thing that calls the game's door
use on a copy whose teammate controller still points at the acting character.

Fixes (all in `src/sync.c`):

* `teammate_unlink(ch)` - a real two-player world has no teammate: the mod clears the teammate
  controller's character pointer when it is the character player 2's input controller owns, logs the
  first time, and `attach_player2` repeats it because the game re-links it after a load. This fixes every
  game path that runs that sweep (the door use, and any other object's use that ends in it), not the door
  symptom alone.
* both door call sites (`door_apply` for PKT_DOOR, `door_use_run` for the test path) now honour the
  game's own gate: `FUN_0042a480` returns 0 for "too far (> 80 units) / not facing / disabled / already
  in use", and the interaction scan does not call the use then either. They also unlink the teammate
  controller right before the call.

### 3.2 The stale prop (OBSERVED, `run_s35_soak2.log`)

The first fixed build still hung, now in `prop_tick` on the guest, at iteration 2 (a level change to
J002) - this one is the "apply path spinning on a stale entity" candidate:

```
*** obscoop: GAME THREAD STALLED 3.2 s ... (frames 9114, last mod step "in prop_tick (guest)")
*** obscoop: FATAL EXCEPTION access violation (0xc0000005) on the vectored path
*** fault at 0x44754000 (not in a module)  params 00000008 44754000     <- operation 8 = EXECUTE
*** eip 0x44754000   eax 44754000 ebx 169e8008 ecx 169e8008
```

The mod calls game vtable slots on entities it found by scanning. `IsBadReadPtr` only says the memory is
readable: when a level change frees a prop, the heap reuses that memory and the old "vtable" pointer and
its slots can hold heap data, so a call slot held `0x44754000` and the game thread tried to execute it.
The deferred break list made it worse: `prop_defer_break` holds an entity pointer for 350 ms, across any
level change in between.

Fix: `code_in_exe(f)` (sync.c) validates every game vtable entry against the exe image before the call;
used on the prop mesh/ collision slots, the item slots, the pickup collect slot, the lock-pick slots and
the weapon "show" slot. `prop_pending` now remembers class + id and re-checks with `prop_alive` before it
applies, and the list is flushed when the level changes.

## 4. Regression: breakables guest->host (§2)

OBSERVED (`run_s35_diag1.log`, dll `chk35g.dll`, `OBSCOOP_SLOT=3 ... check_breakables.py`):

```
breakables: player 2 (guest) -> chair #9 @19ccfa50 ...
breakables OK (chairs picked up, swung and broken on both copies; 2 chair(s) checked)
   host sync ... prop sent 97 rcv 65 applied 65 broke 1 ... | frames 7469
   guest sync ... prop sent 65 rcv 97 applied 102 broke 1 ...
```

and on the host, the guest's announcement arriving and being applied:

```
host: prop break packet: CHAI id ???? -> ent 1a4891e8 (1000.2,-131.1,-12.5) carrier GIR1 broken 0
host: prop break packet: ... (x3, the three copies of the announcement)
host: prop break applied: CHAI id ???? ent 1a4891e8 at (1000.2,-131.1,-12.5) -> broken now 1
```

OBSERVED (code): the announcement never named its carrier before this task.
`prop_announce_break` set `ch_tag` only when `prop_alive(carrier, cls)` - but `prop_alive` tests the
CLASS tag at +0x10, and a character's +0x10 is its own tag (GIR1), so the test was always false and every
break went out with `ch_tag = 0`. The receiver (`prop_apply_packet` kind 3) then had only the position to
match with. With the carrier named, the host takes the chair out of that character's hand exactly
(`prop_held_chair`), which is what a carried-and-broken chair needs - its world position is the hand's.
Fixed in `prop_announce_break` (validate the pointer as a character, not as a prop of that class).
TASK 34's failure ("player 2 (guest): the other copy does not show the broken chair") does not reproduce
with the fix. Same code path, not separately tested: a chair broken ON THE FLOOR (no carrier) - it still
goes by position, unchanged.

## 5. Regression: item use, life host -> guest (§3)

OBSERVED (`run_s35_diag1.log`, `check_itemuse.py`):

```
after charset (both copies)   life host 30.0 / guest 30.0 | MEDI 2/2 ENDR 1/1
host useitem MEDI 0 -> ok useitem MEDI on player 0: life 30.0 -> 90.0 (max 100.0), count 2 -> 1
after the use                 life host 90.0 / guest 90.0
life p2 host 70.0 guest 70.0
RESULT: item use OK (each use landed once on both copies, lives equal, inventories identical)
```

The new diagnostics written for this item show the value crossing the link and staying:

```
guest: writing the host's life for BOY1: local 100.0 -> 30.0
guest: writing the host's life for BOY1: local 30.0 -> 90.0
guest: writing the host's life for GIR1: local 100.0 -> 40.0
guest: writing the host's life for GIR1: local 40.0 -> 70.0
host: life BOY1 is 30.0 (sent in the snapshot) ... (the same four values)
```

and no `life came back to ... after the host's ...` line, so nothing on the guest took the value back.
UNKNOWN: why TASK 34's run left the guest at 100. The life write path is not part of TASK 34's diff and
the failure did not reproduce here (this run has the diagnostics that would have shown a refusal or a
revert); the most likely reading is the guest's game thread state in that run, but it is not proven. The
same test is run again in the final regression row below.

## 6. Doors guest->host and the pair_j003 allowlist (§5)

* OBSERVED: the guest's test door path (`usedoor 1`) now runs through the game's own gate. Two things
  were behind the earlier failures:
  - the guest's own character was placed, and `guest_apply_state` pulled it back to the host's snapshot
    (the > 80 unit "repair" against a snapshot that predates the move): the character was measured 600.5
    units from the door anchor after the placement. Fixed by the ownership rule the mod already states -
    this copy owns player 2, the host follows it (`host_apply_remote_char` snaps above 60 units), so the
    local position stays and a persistent disagreement is only logged (`guest: <tag> is N units from the
    host's snapshot: this copy owns it, the host follows`).
  - the retry after a refused check re-selected "the nearest door", which after a placement was a
    different one; the chosen door is now fixed for the whole request.
* OBSERVED: `check_doors.py --reset game3.sav` in `run_s35_soak5.log` - see §8 for the verbatim rows.
* OBSERVED: the guest-side allowlist is restored: `obscoop_levels.txt` in the guest test folder had only
  B101/B202 while the host's has the door destinations (`J003 157 1`, ...). The file is the mod's own
  record of real transitions (`src/hooks.c:52-68`), so copying the host's file to the guest test folder
  restores exactly the data `pair_j003.py` (`level J003 157 1`) needs; nothing was hand-invented.

## 7. Regression table (all with `chk35i.dll` unless named otherwise)

| run | command | result |
|---|---|---|
| reg1 | `run_pair_menu.sh ... check_party.py check_items.py check_hands.py check_hands_visible.py check_entities.py` | **PASS** - `party OK`, `items OK`, `hands OK (2 characters checked)`, `entities OK (host 43, guest 43)` |
| reg2 | `run_pair_menu.sh ... check_movement.py` | **PASS** - A/B/C/D PASS, **phase E PASS**: BOY1 `diff_mean 0.64 diff_max 1.97`, GIR1 `0.03` (threshold 10.0/55.0; TASK 34 measured 10.60) |
| reg3 | `run_pair_menu.sh ... check_attack_anim.py check_controls.py check_doors.py` | attack animation **PASS**, controls **PASS** (both pads drive their own character on both copies); `check_doors.py` **FAIL** on its transition comparison - see the note below |
| reg4 | `OBSCOOP_SLOT=3 run_pair_menu.sh ... check_breakables.py` | **PASS** - `breakables OK (chairs picked up, swung and broken on both copies; 2 chair(s) checked)` |
| reg5 | `OBSCOOP_PICKUP_CLASS=MEDI OBSCOOP_PICKUP_SPAWN=1 run_pair.sh ... check_itemuse.py pair_j003.py check_pickup.py` | **PASS** - `RESULT: item use OK`, `RESULT: both copies in J003 with 2 live items`, `pickup OK: both directions collected on both copies, inventories match, no echo` |
| reg6 | `run_reconnect.sh ... both` | **PASS** - `reconnect run (both): PASS` |
| reg7 | `run_cutscene_pair.sh ... --skip-by guest` | **PASS** - `PASS: the skip on the guest ended the event on the host (forwarded skip applied, skips 1)` |

The attacks/controls/doors row is the same set `run_soak.sh` runs; `chk35h`'s soak (`run_s35_soak6.log`)
also ran `check_attack_anim`/`check_controls` PASS.

**The `check_doors.py` FAIL in reg3, explained (OBSERVED):**

```
== phase host -> level I100: CToeDoor id ..<. at (-462.7, 488.8, 0.4) usable 1 user - dest I004
   usedoor 0 -> ok usedoor player 0 door DORH id 12c ent 1916a710 (55.3 units away)
   after 3.4 s: ... levels host I010 guest I100
   the door use started a level change on both copies (the entity is being rebuilt)
   image: PASS
   transition: dest I004 -> host I010 guest I010 after 0.5 s: FAIL
```

The check displays the NEAREST door (dest I004) and compares the resulting level with that door's
destination. The mod used a different door - `DORH id 12c` - because the nearest one is in the state
`FUN_0042c2b0` cannot use (`+0x120` set: that branch only plays the sound and clears the user). Both
copies were in the SAME new level (`I010/I010`) 0.5 s later, i.e. the sync worked; only the comparison
named the wrong door. `tests/check_doors.py` now reads the door out of the `usedoor` reply
(`ent <hex>`) and compares against THAT door's destination; the change is syntax-checked but was not
re-run (the process budget for this task is spent).

`check_doors.py` also passed cleanly twice with the earlier builds where nearest and used door were the
same: `run_s35_diag1.log` (`image: PASS`, `transition: dest J000 -> host J000 guest J000 after 0.5 s:
PASS`) and `run_s35_soak3.log` (`J002`, `J000`, both PASS).

## 8. Result in one paragraph

The guest's hang is found and fixed at its cause, not worked around: the game's door use
(`FUN_0042c2b0`) stops "the other character's" action through `FUN_0042ad70`, and in a world built from
a one-player save that other character IS player 2 - so a door use by player 2 stopped the door it was
using, cleared `door+0xc4` and faulted at `Obscure2+0x2c51b` (eax 0); the game's SEH swallowed the fault
and spun forever, which is the owner's frozen image. The mod now unlinks the teammate controller (a 2P
world has none), honours the game's own door gate, validates every vtable slot it calls against the exe
image (a stale prop made it execute heap data `0x44754000`), flushes its deferred break list across level
changes, and no longer pulls its own player back to the host's older snapshot. Proven by two soak runs of
30 location changes each with both frame counters rising to the end and no stall report, and by a new
watchdog that turns any future hang into a module+offset report. Both TASK 34 regressions are gone:
guest->host chair breaks apply on the host (the announcement had been sending `ch_tag` 0 - `prop_alive`
tested the class tag on a character), and both item uses leave equal lives on both copies with the new
life diagnostics showing the write. Guest-driven doors complete through `PKT_LEVELASK` (guest: own
ChangeLevel dropped -> asking the host; host: doing it here), the guest test copy has the levels
allowlist `pair_j003` needs, and movement phase E is back to `diff_mean 0.64`.
