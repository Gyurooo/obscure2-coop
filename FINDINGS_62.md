# FINDINGS 62 — the next-session reload, and a backup before a guest's own save slot is replaced

Labels: **OBSERVED** = printed by a check/run in this task or read in the decompile/assembly (address
cited); **DERIVED** = follows from the cited code but was not observed live; **GUESS**; **UNKNOWN**.

Branch w/combat HEAD a2c9b04 (TASK 61 WIP). Worktree: `<worktree>`; decompile
`<local>\decomp2\Obscure2.exe.c` (build 215294). Final DLL `chk62a.dll` (built from the unchanged `src/`
apart from the backup below; 3 known warnings: tick, watch_start, request_shot). Every game and relay
this task started was stopped (`remaining Obscure2.exe: 0, obscoop-relay.exe: 0`).

## 0. Summary

| part | what changed | result |
|---|---|---|
| **1 reload** | `tests/check_world.py`: a human's position is read at `+0x23c` (not `+0x6c`, a level entity's field — the TASK 61 run "walked 0.0" and read garbage because of it); the reload phase waits for the game's own level-ready state on both copies (mode 1, `world+0x11c == 1`, the same humans with finite positions, unchanged for 1 s) before comparing; the host really walks away (>10 units, measured) | **PASS twice on the pair** (§3.1, §3.2). The reload was not broken in the mod — the game's save carries no player position at all (§1.1) |
| **2 backup** | `src/sync.c`: before received save bytes replace a file that already exists with DIFFERENT bytes (both the save push `save60_store` and the join transfer `guest_on_save`), keep it once as `<name>.solo.bak` next to it; an existing `.solo.bak` is never replaced (`CopyFileA(..., TRUE)`, one log line) | **OBSERVED live in both paths** (§3.1–§3.3), the never-overwrite rule too (§3.2) |
| soak | 5-iteration soak | **NOT DONE**: every phase passed except check_world's save phase, which could not find the save point after the soak's J002→I100 load; the check-side fix is in, but the soak was not re-run (game-process budget, §4) |

## 1. The reload — what was actually wrong

`humans()` in `tests/check_world.py` read a human's position at `+0x6c`, which is where a *level* entity
(`CToe*`) keeps its position (`check_world.pos`, used for save points, items, pedestals). A human
(`CToeHuman`) keeps it at `+0x23c/+0x240/+0x244` — the field every other check uses (`check_movement.py`
`H_POS`, `check_combat.py`, `check_fight_pair.py`, `check_pickup.py`, `check_visible.py`). So the TASK 61
run's "the host walked 0.0 units away" and its garbage after the load
(`host {'BOY1': (0.0, 0.0, 0.0)} guest {'BOY1': (-4.78e-07, 1.4e-38, ...)}`) were the reader, not the
reload: it read a zero/garbage field of the right object.

The check now also waits for the game's own level-ready state on BOTH copies before comparing, as the
task asked: mode 1, world state 1 (`world+0x11c`), the same human tags present, positions finite, and
those positions unchanged for 1 s (`wait_ready`). The walk is measured with the corrected field and tries
the four stick directions until the host is more than 10 units from the saved spot (`walk_away`); a host
that stays put is a FAIL, not a silent pass.

### 1.1 The game's save does NOT store a player position (OBSERVED, one solo copy, `run_62probe.log`)

The task's "the next session puts both copies at the saved spot within 10 units" cannot hold for this
game: its save at a save point does not carry the characters' positions, and a load restarts the level at
the level's own start. A scratch solo probe (the same panel drive as the check, through
`tests/run_solo_slot.sh chk62a.dll 0`, host only) walked, saved at the save point, and loaded again:

```
P0 (the load's own start): world I100 state 1 humans {'BOY1': (-275.51, -40.17, 0.1), 'GIR1': (-353.22, -141.92, 0.1)}
walk -> 74.0 units
P1 (after the walk): BOY1 (-314.66, 23.63, 0.1)
P2 (after the save at the save point): BOY1 (-296.69, -1.75, 0.1), GIR1 (-413.7, -99.4, 0.1)
the file now: game0.sav 6089d8b5e88f68d5...
P3 (after the reload): BOY1 (-275.51, -40.17, 0.1), GIR1 (-353.78, -141.96, 0.1)
```

P3 is P0 to 0.01 units: the load restored the level start, 74 units from the walk. The 40 KB file has no
position in it either (float32 search of the file the game wrote after the walk+save: none of P0, P1, P2
or the save point's own position appears anywhere), and a save taken after the walk differs from the
previous one by only 18 bytes.

So the check's real question (the reviewer's FAIL) is whether both copies come up **in the same place**
from the save they both hold; the distance from the live saved spot is informational, and the reload is
**not broken in the mod**.

## 2. The `.solo.bak` rule

`src/sync.c` (new, next to the save paths): `save_solo_keep` copies `path` to `path.solo.bak` only when
`CopyFileA(..., bFailIfExists = TRUE)` succeeds (an existing `.solo.bak` is never replaced) and logs one
line; `save_has_bytes` says whether the target already holds the incoming bytes (`off 0, len` = whole
file, or the region one 512-byte chunk of the join transfer writes). Both write paths use them:

* `save60_store` (a `PKT_SAVEPUSH` file, either role): the whole file is compared, then both folders
  (`coop_profile\remote`, `Save`) are backed up before `CREATE_ALWAYS` overwrites them;
* `guest_on_save` (`PKT_SAVE`, the join transfer): every chunk is compared with the region it will
  replace, so a file is backed up the moment the incoming bytes differ anywhere.

`tests/check_world.py` now accepts `<slot>.solo.bak` in the four save folders (it is not a save slot:
`dir_snap` lists it, `save_snap`, which globs `*.sav`, does not), prints the guest's folder listing and
the backup's SHA-256, compares the backup's bytes with the copy that was there before the save, and
requires the guest's remote folder to hold it.

Installer/uninstaller naming (checked, no collision): `package/obscoop2.iss` and `package/install.ps1`
patch `game*.sav` (a `game0.sav.solo.bak` does not match `game*.sav`), back up `xinput1_3.dll` as
`.bak`/`<stamp>.bak` and a patched save as `.1p.bak`; nothing in either looks for or deletes
`*.solo.bak`.

## 3. Live evidence

### 3.1 `OBSCOOP_LINK=steam sh tests/run_pair_menu.sh chk62a.dll check_world.py` (`run_62b.log`) — PASS

The guest's `game0.sav` was put equal to the host's before the run and the guest's earlier
`game0.sav.solo.bak` moved out of the test folder, so the run's own save had to create the backup.

```
   the host's game wrote game0.sav after 0.0 s: sha256 6076ea34cfe99bb492fb7cfcb64c4b3d431fde0fece72c1f065e13ce864a3d8a
   guest remote game0.sav: both copies hold it -> sha256 6076ea34cfe99bb492fb7cfcb64c4b3d431fde0fece72c1f065e13ce864a3d8a
   the host (asked by the guest) wrote game0.sav after 0.0 s: sha256 4401becfbca356e44bdd16a505b1279ca5d98b6f24cc45199bab9b2229995da6
   guest remote game0.sav: both copies hold it -> sha256 4401becfbca356e44bdd16a505b1279ca5d98b6f24cc45199bab9b2229995da6
   after  host remote  1 files changed: ['game0.sav']
   after  guest remote 2 files changed: ['game0.sav', 'game0.sav.solo.bak']
   guest remote: game0.sav.solo.bak kept this copy's own game0.sav before the save replaced it (sha256 6089d8b5e88f68d5)
   after  host Save    0 files changed: none
   after  guest Save   2 files changed: ['game0.sav', 'game0.sav.solo.bak']
   guest Save: game0.sav.solo.bak kept this copy's own game0.sav before the save replaced it (sha256 6089d8b5e88f68d5)
   guest remote listing: ['game0.sav', 'game0.sav.solo.bak', 'game1.sav', ..., 'o2.ipt']
   guest remote game0.sav.solo.bak = the copy that was there before the save (sha256 6089d8b5e88f68d5)
   guest Save   game0.sav.solo.bak = the copy that was there before the save (sha256 6089d8b5e88f68d5)
   -- the next session: both copies load game0.sav
   the host walked 17.6 units away from the saved spot
   loadsave -> ok real load of "game0.sav" requested (the game thread runs it)
   both copies in level I100 after 4.0 s
   the level is ready on both copies after 1.0 s (mode 1, world state 1, BOY1/GIR1)
   both copies hold BOY1/GIR1 within 0.00 units after 2.0 s: {'BOY1': 0.0, 'GIR1': 0.0}
   distance from the live saved spot (the game restores the level start, not that spot): {'BOY1': 47.8, 'GIR1': 0.0}
   the load moved the host 26.8 units off the spot it walked to
save OK: every save file the game wrote on one copy is byte-identical on the other, and the file loads into the same place on both
...
summary: fails none
check_world: OK
```

`6089d8b5...` is the guest's `game0.sav` from the before snapshot: the backup holds exactly the file the
save replaced, in both of the guest's folders.

### 3.2 the same command again (`run_62c.log`) — PASS, and the backup is kept once

```
   before guest remote 12 files: ['game0.sav', 'game0.sav.solo.bak', ...]
   after  guest remote 1 files changed: ['game0.sav']
   guest remote game0.sav.solo.bak = an earlier copy, not the one there before this save (sha256 6089d8b5e88f68d5)
   the host walked 18.6 units away from the saved spot
   the level is ready on both copies after 1.0 s (mode 1, world state 1, BOY1/GIR1)
   both copies hold BOY1/GIR1 within 0.00 units after 2.0 s: {'BOY1': 0.0, 'GIR1': 0.0}
   the load moved the host 51.0 units off the spot it walked to
save OK: ...
summary: fails none
check_world: OK
```

This run replaced `game0.sav` with different bytes twice, and the backup stayed the copy from 3.1
(`sha256sum` after the run: `6089d8b5...` in both guest folders): "never overwrite an existing
`.solo.bak`", OBSERVED.

### 3.3 the join-time transfer (PKT_SAVE) makes the same backup — OBSERVED

Before the first 5-iteration soak the guest's `coop_profile\remote\game9.sav` was replaced with a copy of
its `game8.sav` (both 40960 bytes, different bytes; the host's `game9.sav` was untouched), so the join
transfer had to replace a file whose bytes differ. After the run:

```
$ sha256sum <guest>/coop_profile/remote/game9.sav.solo.bak
62d0ff7397d9c2e178fb2929c57541e43beb822cec3eb692f5cadfdaa0e175fa   (= the game8 copy put there)
$ sha256sum <host>/coop_profile/remote/game9.sav
3897d7472eb55241056771d0cfc2e9c3a1b97026fd7f36033f9ee0aff6f34b06   (= the guest's game9.sav now)
```

and the soak's check_world before-snapshot lists it:
`before guest remote 13 files: ['game0.sav', 'game0.sav.solo.bak', ..., 'game9.sav', 'game9.sav.solo.bak', 'o2.ipt']`.
Files that were already identical were not backed up (no `game9.sav.solo.bak` in `Save`, where the
guest's `game9.sav` already matched the host's): the byte comparison decides, not the fact of a transfer.

## 4. The soak (5 iterations): one phase failed, and the check fix

### 4.1 run 1 (`run_62soak.log`)

Every phase passed except check_world's save phase:

```
== check_fight_pair.py (players attack each other) (timeout 240s)
[...]
== soak34.py (5 location changes) (timeout 1500s)
[...]
soak OK (5 location changes, both copies alive)
== check_world.py (shared save at a save point, items, containers) (timeout 420s)
== A save: the same file on both copies
[...]
   host: save point +0x14 = 3 (the state the save that made these saves left); setting 0
   host: savepoint (player 1) -> error savepoint: this level has no save point
   host: the save point use did not reach world state 11 (state 1)
[...]
save FAIL
[...]
  host: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
[...]
=== soak run: FAIL
```

(`[...]` is elision.) No other phase failed: `grep -n FAIL run_62soak.log` finds only check_world's
`save FAIL` / `check_world: FAIL (save)` and the final `=== soak run: FAIL`.

The pair was in J002 (the soak's last location change). The check's "has a save point" guard used
`entities()`, which returns ONE of the entity manager's three lists; it found J002's save point (so no
guard), but the mod's own `savepoint` lookup (the list at `mgr+8`, within 400 units of the character) did
not reach it. The guest's own use in the same level succeeded (`ok used SAVE at 356.7,835.1,85.2`).

### 4.2 the check fix, and run 2 (`run_62soak2.log`)

The check now (a) enters the save phase in I100 even when the level is not I100, and (b) has
`find_save_point`, which scans all three manager lists. Run 2 got into I100 but still failed:

```
   level J002 is not I100: loading game0.sav (the pair's start slot)
   loadsave -> ok real load of "game0.sav" requested (the game thread runs it)
   both copies in level I100 after 3.0 s
   level I100 has no save point
save: NOT DONE - the level with the save point did not load
```

The host's own log shows the level really was rebuilt (`world 1a4272d8 in level I100 is settled: the
entity tables are rebuilt from it`), so this was still the one-list `entities()` scan (the guard was
updated only afterwards). The guard is now `find_save_point` (all three lists, polled up to 30 s after a
load) and it is the same function `reset_savepoint` uses.

`find_save_point` was then validated on one solo copy in the same situation (`run_62probe2.log`: slot 3 =
J002, so a save-loaded, non-I100 level): it found the save point at `356.7,835.1,85.2`, the mod's
`savepoint` command accepted it, the panel wrote `game0.sav`, and the reload went back to the level
start. See §5. The **exact** J002→I100 soak scenario was **not** re-run: the task's game-process budget
(12) was reached (2+1+2+2+2+2+1 = 12 processes). Reported NOT DONE, not papered over.

## 5. The solo validation of the check's save point lookup (`run_62probe2.log`)

The probe ran on one host that `tests/run_solo_slot.sh` had just put in J002 (slot 3 = game3.sav). Its
own output, verbatim (`run_62probe2.log`):

```
P0 (the load's own start), file game0.sav 6089d8b5e88f68d540f9e372bdef2ca23db6d17a7b3e303554ec0e268f61ee52
P0: world J002 state 1 humans {'BOY1': (296.43, 757.31, -7.0), 'GIR1': (403.67, 757.31, -7.0)}
walk -> 51.5 units
P1 (after the walk): world J002 state 1 humans {'BOY1': (345.38, 774.6, -7.0), 'GIR1': (403.72, 676.62, -7.0)}
save point 194a51c0 at 356.7,835.1,85.2
savepoint -> ok used SAVE at 356.7,835.1,85.2 (world sub-state 11)
   probe: the save panel opened
   probe: slot list ready: pad A
   probe: confirmation up: pad DOWN, then A
   probe: completion popup: pad A
   probe: the save panel closed after 8.4 s
P2 (after the save): world J002 state 1 humans {'BOY1': (350.44, 743.99, -7.0), 'GIR1': (361.02, 616.18, -7.0)}
the file now: game0.sav 972cabfe991d0e05a43ffdc5df6eb0e87e892b113611280af6c4c967265be707
loadsave -> ok real load of "game0.sav" requested (the game thread runs it)
P3 (after the reload): world J002 state 1 humans {'BOY1': (296.43, 757.31, -7.0), 'GIR1': (403.67, 757.31, -7.0)}
```

The all-three-lists lookup found the save point the check's `entities()` scan had missed, and the game's
own save flow completed (this is also a second, independent confirmation of §1.1: the reload is back at
the level start, not at P2).

That probe left `game0.sav` as a J002 save; both test copies' `game0.sav` were then restored to the I100
save `6089d8b5...` (the copy kept in the guest's `game0.sav.solo.bak`), so the next run starts from the
same I100 state as §3.

## 6. DONE / NOT DONE / UNKNOWN

**DONE**
* (1) The reload FAIL in TASK 61 was the check's reader (`+0x6c` instead of `+0x23c`), not the mod:
  `check_world.py` PASS twice on the pair over the steam-like relay, with the level-ready wait, a real
  measured walk (17.6 / 18.6 units) and both copies within 0.00 units after the load (§1, §3.1, §3.2).
  The game's save at a save point stores no player position, so a load returns to the level start
  (OBSERVED, §1.1); the check now asserts what the game can show (both copies in the same place, the
  load moved the host off the walked spot) and prints the live-spot distance as information.
* (2) `<name>.solo.bak` before a received save replaces differing bytes, **both** in the save push
  (`PKT_SAVEPUSH`/`save60_store`, both roles) and in the join transfer (`PKT_SAVE`/`guest_on_save`); the
  backup keeps exactly the file that was there, is visible in the guest's folder listing, and is never
  replaced by a later save (§2, §3.1–§3.3).
* Installer/uninstaller naming does not collide with `.solo.bak` (checked in `package/obscoop2.iss`,
  `install.ps1`, `uninstall.ps1`).

**NOT DONE**
* `OBSCOOP_LINK=steam OBSCOOP_SOAK_ITERS=5 sh tests/run_soak.sh chk62a.dll` did not PASS: run 1 failed
  only in check_world's save phase (§4.1, the save point lookup in J002), run 2 only in the same phase
  (§4.2, the one-list scan after the J002→I100 load). The check-side fix (all-lists `find_save_point`,
  polled, plus the I100 guard) is in and was validated solo (§5), but not re-run as a soak: the 12-game
  budget was reached.
* The "the next session puts both copies at the saved spot within 10 units" wording cannot be proven for
  this game: the save has no position in it (§1.1). The check asserts the equivalent, stronger-for-sync
  fact (both copies at the same place, the load really ran) and says so in its own output.

**UNKNOWN**
* Whether the reviewer's 5-iteration soak passes with the all-lists lookup: DERIVED from §5's solo
  result, not observed on the pair.
* Why the check's `entities()` "best list" did not contain I100's save point after the soak's
  J002→I100 load while it did after the pair's menu load (the entity manager's list layout after a
  location change): UNKNOWN; the all-lists scan does not depend on the answer.
