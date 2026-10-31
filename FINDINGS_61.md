# FINDINGS 61 — the shared save at a save point: the game really writes it, byte-identical on both

Labels: **OBSERVED** = printed by a check/run in this task or read in the decompile/assembly (address
cited); **DERIVED** = follows from the cited code but was not observed live; **GUESS**; **UNKNOWN**.

Branch w/combat HEAD c11d61b (TASK 60 WIP). Worktree: `<worktree>`; decompile
`<local>\decomp2\Obscure2.exe.c` (build 215294). Final DLL `chk61a.dll` (built from the unchanged
`src/`, the 3 known warnings). Every game and relay this task started was stopped
(`remaining Obscure2.exe: 0, obscoop-relay.exe: 0`).

## 0. Summary

TASK 60 could not complete a save: it pressed pad A blind and the game's save state (`world+0x11c = 10`)
never finished. This task found the missing steps in the game's own save UI and then **observed a real
save being written** on the test copies (`remote FileWrite game0.sav (40960 bytes) -> local ok`) and
pushed to the peer byte-for-byte over the steam-like relay, by driving the panel the way a player does:

1. the save point's own machine wants pad A,
2. after `CLevel::Request_SaveGame` the panel shows its slot list (999 ms), A picks the highlighted slot,
3. the confirmation popup (SPOP) needs **DOWN + A** — the plain first button does not save,
4. after the write the game shows its own **completion popup**, which needs **one more A**; only then
   does the panel hide and world state 10 complete.

TASK 60 gave none of 3 and 4. Without 4 the panel stays at world state 10 forever, which also keeps the
host's world out of state 1 and therefore blocks the guest's request (`FUN_004b29d0` and
`CLevel::Request_SaveGame` only accept world state 1 or 0xb).

**No mod code was changed**: the TASK 60 mechanism (guest use refused -> `PKT_SAVEPT` -> the host runs
the game's own use -> every written file pushed with `PKT_SAVEPUSH`) works; what was wrong was the test
driver. The changes are `tests/check_world.py` (the save phase now drives the panel) and
`tests/run_soak.sh` (runs check_world).

## 1. The save flow, decoded and observed (OBSERVED)

Save point (`CToeSavePoint`, update `FUN_0046f330` / 0x46f330, state at `+0x14`):

| `+0x14` | what the game does |
|---|---|
| 0 | idle: with the player in range and pad A (`FUN_0059b3e0(9)` or 0x31) it starts animation `0xc1c` and sets its own state 2 |
| 2 | animation; after 3000 ms -> state 1 |
| 1 | after 3000 ms -> `CLevel::Request_SaveGame(level, this)` and state 3 |
| 3 | post-save; when the panel closed (`+0x14c = 1`) it fades out and tries `FUN_0053f9c0("savepoint")` -> `+0x14 = 0` only when `world+0x178c != 0` |

The ten test saves store every save point in `+0x14 = 3` (FINDINGS_60 §2), and a finished save leaves it
there (measured after the save below: `+0x14 = 3 +0x14c = 1`), so the check writes `+0x14 = 0` first.

`CLevel::Request_SaveGame` (0x4b2980) queues request 10; the world dispatcher (`FUN_004b4cb0`, request 10
branch, decompile 110159-110170) then:
```
world+0x180 = world+0x11c; world+0x11c = 10;
panel(game+0x478)->show(1);                         // vtable +0x20 = FUN_00542f40
panel->select(0x53464c4f, 0);                       // vtable +0x1c = FUN_005429a0, tag "SFLO"
```
and the state-10 branch (decompile 110510-110525) updates the panel and finishes only when
`panel+0x10 == 0` (the panel hid itself). The panel (`FUN_00543de0`, layout from `menus\save.xmc`) has
exactly the three items `SBGD`, **`SFLO`** (the save panel, vtable 0x66c71c, update `FUN_00553a20`) and
**`SPOP`** (the popup, vtable 0x66b924; OBSERVED on the live panel).

`FUN_00553a20`, the save item's state at `+0xe0` (int index 0x38), read from the assembly at
0x553a20-0x5543c0:

| state | code (assembly address) |
|---|---|
| 1 | after `999 < +0xe4` it scans the slots (`FUN_0053d660`, `game%d.sav`) and goes to 2 (0x553b50) |
| 2 | `FUN_00552e10()` is `mov eax,1; ret` (0x552e10), so every frame it calls `FUN_00553350` (slot highlight) and, once `+0xe8` (the picked slot) is >= 0, `FUN_00553520(0x17)` (save) or `(0xc)` (load) (0x553c49) |
| 0x17 | waits until `SPOP+0x34 == 0` (the popup is closed); then `SPOP+0xb8 != 0` -> `FUN_00553520(0x18)`, else back to 2 (0x554144) |
| 0x18 | after 50 ms: `FUN_004a25e0(name)` = the game's own SaveGame builder (0x4a25e0) -> state 0x1a |
| 0x1a | `FUN_0053ea80` (the save manager's result); ok -> `FUN_00553520(0x19)` |
| 0x19 | shows the "save complete" popup (`FUN_00546af0(0x8100005, 0x4000006)`); waits until `SPOP+0x34 == 0`, then `FUN_00553520(0)`, hides its parent and the panel (`panel+0x10 = 0`), sets the save point's `+0x14c = 1` |

`SPOP` (activation `FUN_00546050` at 0x546050) sets `SPOP+0xb8 = (focused child == the second text)`;
its show/hide owns `SPOP+0x34`. The first button at state 0x17 does **not** save (`+0xb8 = 0`).

**Observed on one test copy** (`probe61d`, solo host, `loadsave game0.sav`, level I100):
```
0x11c=11 (save point used) -> wr save point +0x14 = 0 -> pad A
t+6   world state 10, panel on 1, SFLO state 2 (slot list)
t+11  pad A            -> SFLO state 0x17, slot 0
t+14  pad DOWN, t+16 pad A -> SFLO state 0x19 (the save ran: FUN_004a25e0)
t+20  pad A            -> panel off, world state 1
mod log: remote FileWrite game0.sav (40960 bytes) -> local ok
         host: save file "game0.sav" written here (40960 bytes): pushed to the peer
```

Every smaller recipe was tried and failed live (quoted in §2):
* A only in state 0x17 (3.5 s and 5.5 s after the popup): `SPOP+0xb8 = 0` -> back to the slot list, or
  the popup stays open; **no file** (`probe61e`, `run_61b`).
* DOWN + A (save written) but **no A on the completion popup**: world stayed 10 for 70 s
  (`run_61c`, `run_61d`: item state 25, panel on 1, the file written and received by the guest).

## 2. Live evidence

### 2.1 The steam-link pair (`OBSCOOP_LINK=steam sh tests/run_pair_menu.sh chk61a.dll check_world.py`, `run_61steam1.log`)

The panel now completes and the game writes the save (verbatim):
```
   host: savepoint (player 1) -> ok used SAVE at -223.8,-113.1,97.6 (world sub-state 11)
   host: the save panel opened 6.0 s after the pad A
   host: t+0 save item state 2, panel on 1, world 10
   host: the slot list is ready (item state 2): pad A
   host: the save confirmation is up (item state 0x17): pad DOWN, then A
   host: the save was written, the completion popup is up (item state 0x19): pad A
   host: the save panel closed after 8.4 s
   the host's game wrote game0.sav after 0.0 s: sha256 fdbb094a16e97723a1621b8fef5cde27eee32b1bd9479648af4c7efff95d897e
   guest remote game0.sav: both copies hold it -> sha256 fdbb094a16e97723a1621b8fef5cde27eee32b1bd9479648af4c7efff95d897e
```
That is (a): the host's save is on the guest with the same SHA-256, over the steam-like relay.

The guest's own save point (the host performs it; verbatim):
```
   guest: savepoint (player 2) -> ok used SAVE at -223.8,-113.1,97.6 (world sub-state 0)
   host (asked by the guest): the save panel opened 6.0 s after the pad A
   host (asked by the guest): the slot list is ready (item state 2): pad A
   host (asked by the guest): the save confirmation is up (item state 0x17): pad DOWN, then A
   host (asked by the guest): the save was written, the completion popup is up (item state 0x19): pad A
   host (asked by the guest): the save panel closed after 8.4 s
   the host (asked by the guest) wrote game0.sav after 0.0 s: sha256 b729fb94fca30d66a6c6d10957f1043fa32f7c7b8bc9eb9483f420fb596427f8
   guest remote game0.sav: both copies hold it -> sha256 b729fb94fca30d66a6c6d10957f1043fa32f7c7b8bc9eb9483f420fb596427f8
```
That is (b), including the guest->host half TASK 60 could only show as counters.

Folders after both saves (verbatim):
```
   after  host remote  1 files changed: ['game0.sav']
   after  guest remote 1 files changed: ['game0.sav']
   after  host Save    0 files changed: none
   after  guest Save    1 files changed: ['game0.sav']
   guest Save: ['game0.sav'] is the mod's mirror of the slot (sync.c save60_store), not a game write
```
Only the saved slot changed, and no other slot in any folder (§3 for the mirror).

### 2.2 The next-session half (c): NOT PASSED in this run, check fixed

The same run's reload reached the level but the position read was garbage right after the load:
```
   -- the next session: both copies load game0.sav
   the host walked 0.0 units away from the saved spot
   loadsave -> ok real load of "game0.sav" requested (the game thread runs it)
   both copies in level I100 after 4.0 s
   the two copies are NOT in the same place after the load (host {'BOY1': (1.99e+18, 2.4e-38, 8.5e-39), 'GIR1': (0.0, 0.0, 0.0)} guest {'BOY1': (0.0, 0.0, 0.0), 'GIR1': (0.0, 0.0, 0.0)})
```
`humans()` read the humans while the load was rebuilding them (the position was a float pattern, not a
coordinate). The check now drops positions outside +-1e6 and requires the same two humans on both copies,
within 2.5 units, stable for 1.5 s (`tests/check_world.py`, phase (c)). **This fixed code was not run
again**: the game-process budget (14) was reached (§4).

### 2.3 The soak (`OBSCOOP_LINK=steam OBSCOOP_SOAK_ITERS=5 sh tests/run_soak.sh chk61a.dll`, `run_61soak.log`)

All the soak's own phases PASSED (attack animation, animation layer sync, controls, visibility,
fight-pair, 5 location changes, doors, liveness, crash handler):
```
  host: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
  guest: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
```
The run failed only because check_world (added to the soak by this task) ran after `soak34.py`'s races,
which leave the pair in **J002** — a level with no save point:
```
   host: no save point in level J002
   guest: savepoint (player 2) -> error savepoint: this level has no save point
save: NOT DONE - no save file was written by the game
check_world: FAIL (save)
-- check_world.py (shared save at a save point, items, containers): exit 1
```
`check_world.py` now loads `game0.sav` (I100) itself when the current level has no save point, so the
order in the soak no longer matters. **This fix was not run either** (same budget).

## 3. The save folders

The game writes the slot through `ISteamRemoteStorage::FileWrite`, which the mod's proxy maps into
`coop_profile\remote` (OBSERVED, log line). The mod's `save60_store` also writes its own `<exe>\Save`
mirror of a *received* file (`sync.c`: "Writes one received save to the folder the game reads and to the
Save mirror"): the game itself only writes the remote folder; the mirror is the mod's and predates this
task (the transfer's fallback source, FINDINGS_60 §2). The check reports exactly which file changed in
all four folders and fails on anything but the saved slot.

## 4. DONE / NOT DONE / UNKNOWN

**DONE**
* The save at a save point is real and reproducible: the game's own panel, driven with A (slot list),
  DOWN+A (confirmation) and A (completion popup), writes `gameN.sav` and closes the panel (§1).
* (a) The host's save reaches the guest with the same SHA-256 over the steam-like relay (§2.1).
* (b) The guest's save point becomes a host-performed save; both copies hold the same SHA-256 (§2.1).
* (d) No file other than the saved slot changed anywhere; the guest's `<exe>\Save` entry is the mod's own
  documented mirror (§2.1, §3).
* `tests/check_world.py` drives the panel; `tests/run_soak.sh` includes it.

**NOT DONE**
* The two proof commands did not end in PASS on the final DLL:
  * `run_pair_menu.sh ... check_world.py`: the save half printed its PASS numbers, but the phase failed
    on (c)'s reader; the fix is in the check, not re-run (§2.2).
  * `run_soak.sh` (5 iterations): every other check PASSED; check_world failed because it ran in J002
    with no save point; the check now loads I100 itself, not re-run (§2.3).
* (c) "the next session loads that save on both and both are in the same place": the reload did put both
  copies in I100 (`both copies in level I100 after 4.0 s`), but the position equality was not measured.

**UNKNOWN**
* Whether the fixed (c) comparison passes on the pair: DERIVED from the reader fix, not observed.
* Why the save point's `+0x14` stays 3 after a save in these save-loaded levels (the game's own
  `FUN_0053f9c0("savepoint")` reset needs `world+0x178c != 0`, which these levels do not set): UNKNOWN,
  and the reason the check (like TASK 60) writes `+0x14 = 0` before each use.
