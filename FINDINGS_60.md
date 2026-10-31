# FINDINGS 60 — world state that was not shared yet: save points, item spawners / supply limits, containers

Labels: **OBSERVED** = printed by a check/run in this task or read in the decompile (address cited);
**DERIVED** = follows from the cited code but was not observed live; **GUESS**; **UNKNOWN**.

Branch w/combat HEAD dfc19a4, `NET_VERSION` 30 -> **31**. Worktree: `<worktree>`; decompile
`<local>\decomp2\Obscure2.exe.c` (build 215294). Every game and relay this task started was stopped.

## 0. Summary

| part | what changed | result |
|---|---|---|
| **A1-7 save points** | every save the game writes is caught in the DLL's `ISteamRemoteStorage::FileWrite` proxy (`obscoop2.c rs_FileWrite`) and pushed to the other copy (new `PKT_SAVEPUSH` / `PKT_SAVEPUSH_ACK`, both directions); the guest's save-point use is refused and sent as a request (`PKT_SAVEPT`), and the host performs the save through the game's own save-point use (`CToeSavePoint::use` 0x46e830 / `CToeSimpleSavePoint::use` 0x46ed80, hooked) | mechanism implemented; **live save proof NOT DONE** — the game's own save state (`world+0x11c = 10`) never completes in the ten test saves, so no save file was ever written to compare (§2). |
| **A1-8 items/spawners** | the host streams its item/container family table (`PKT_WORLD`, host-authoritative); the guest writes a field only where its own value is still the sender's "before" and its own game did not change it in the last 1.5 s | check_world phase B: **PASS** on the pair (an item activated on the host appears on the guest) |
| **A1-9 containers** | the same table carries `CToeContainer` / `CToeChest` / `CToeChestKey` / `CToePedestal` (+0x20/+0xa4/+0xa8/+0xb0/+0xc0/+0xc4/+0x128) | check_world phase C: **PASS** on H006's pedestals (§4) — no item-giving container exists in the ten test saves (FINDINGS_16 §6 + this task's ten-slot scan) |

## 1. Obscure 1 (`<local>\coopdll\src\sync.c`) — what it did for each

* **save points**: it did **not** sync them. The only save transfer was the host's loaded save at join
  (`host_start_save_xfer`, `sync.c:1070-1095`: the host sends `g_last_save` in chunks, the guest stores it
  as `game0.sav` in its own `coop_profile/remote`). A save made by either player afterwards stayed on that
  copy. TASK 60 adds the reverse direction and a save made at a save point.
* **items / spawners**: the host sent a table of the level's items (`PKT_ITEMS`, `item_state`
  {type, id, vtable, kind, a, b}; kind 1 door `+0x88/+0xfc`, 2 collected, 3 broken; `sync.c:47-48,
  host_send_items 382-417`), and the guest applied it with the game's own setters (SetVisible(0) via
  vtable slot 18, `sync.c:341-345`). That is exactly the model used here: the host decides, the guest's
  copy takes the host's state on the same entity. Obscure 2 already had the inventory (`PKT_ITEM`) and
  the pickup of a live entity (`PKT_PICKUP`); what was missing was **which items are live at all**.
* **team bag / containers**: the inventory was mirrored whole (`PKT_INV`, `sync.c:53-54`:
  `char_id, hand_type, hand_id` + items). Obscure 1 has no container class, so nothing to compare for
  chests/pedestals.

## 2. Save points (A1-7) — what the game does, measured

**The save files are written through the mod's proxy (OBSERVED)**: `rs_FileWrite` is the DLL's
`ISteamRemoteStorage::FileWrite`, and it maps `gameN.sav` into `g_remote` (obscoop2.c:222-265). So a save
made on either copy is caught with its exact bytes — that is what `save60_local_written` pushes.

**The save folder rule (OBSERVED, fixed)**: `save_game_path` in sync.c used `<exe>\coop_profile\remote`
unconditionally; the game's real folder is `g_remote`, which obscoop2.c already moves to
`%LOCALAPPDATA%\obscoop\coop_profile\remote` when the game sits under Program Files (obscoop2.c
DllMain, "Under Program Files ..."). sync.c now uses `g_remote`, so the join transfer, the new save
push and the game read the same folder on both copies.

**The save-point flow (OBSERVED, decompile + live)**:

* `CToeSavePoint::use` = vtable slot 28 = `FUN_0046e830`: sets `+0xc4 = character`, `+0x154 = 1`,
  `+0x134 = 1`, then `FUN_004b29d0` = "request 0xb" (`world+0x12c = 0xb`). `CToeSimpleSavePoint::use` =
  `FUN_0046ed80` is the same with `+0x2bc` instead of `+0x134`.
* the world's request dispatcher turns request 0xb into `world+0x11c = 0xb` and clears `world+0x12c`
  (FINDINGS_39 §2 for the dispatcher).
* in state 0xb the save point's update `FUN_0046f330` runs a small state machine in `+0x14`:
  0 = wait for the pad **A** (`FUN_0059b3e0(9)`), 2 = character animation `0xc1c`, then after 3000 ms
  -> 1, then after another 3000 ms `CLevel::Request_SaveGame(level, savepoint)` -> 3.
* `CLevel::Request_SaveGame` @ 0x4b2980 (decompile 108636-108652) queues request **10**;
  `world+0x11c` becomes 10, which runs the panel at `world+0x1798` = `game+0x478`.

**OBSERVED live (solo host, save 01 = I100, `saveprobe60*.py`)**:

```
save point entity 195a38d0 state 3 -> 0
use: ok used SAVE at -223.8,-113.1,97.6 (world sub-state 11)
  t+ 0 (1, 11, 0, 0)      # mode, world+0x11c, world+0x12c, game+0x320
  t+ 1 (1, 1, 0, 0)       # the pad A press advanced the save point's own machine
  t+ 6 (1, 10, 0, 0)      # Request_SaveGame accepted: the save state
  ... 25 s later still (1, 10, 0, 0), no "remote FileWrite" line, no file changed
```

and the object the state drives:

```
world fields: +0x1748 1958555c +0x1778 0 +0x178c 16ca2f50 +0x1790 1925e518 +0x1794 e1b87f0 +0x1798 e1b88c0
game+0x478 e1b88c0   panel on 0  +0x14 0  +0x38 3  +0x40 e202128  +0x54 28
```

So the request **is** accepted (world state 10), but the panel never closes and the game never writes.
`FUN_00542d00` (the panel's vtable+0x24) only runs its children when `panel+0x10 != 0`, and its child
update `FUN_00542c30` iterates the FX entries at `+0x14`/`+0x12` (`FUN_00542db0` parses them from config).
The pad (0 and 1), the keyboard (Enter/Space/Down) and START changed nothing (saveprobe60b).

Two things this also settles:

* **the ten test saves store every save point in its POST-SAVE state `+0x14 = 3`** (scan of all ten slots:
  `p14=3` on every `CToeSavePoint`). The game's own can-use check `FUN_0046e6c0` (vtable+0x34) requires
  `+0x14 == 0`, so a save point cannot even be *used* by the interaction scan in these levels until the
  state is put back. That is why FINDINGS_19 ("save points never fired in any of the ten slots") saw what
  it saw: the save that produced each of these files was itself made at a save point.
* **the save file's own content cannot be produced by the mod**: only the game's save manager builds it.

**Consequence for the task's proof (a)**: the host *can* be made to perform the save request
(`savepoint` -> Request_SaveGame accepted), but the game's save state never completes in these saves, so
no file exists on either copy to compare. The mechanism (host performs the guest's save, every written
save is pushed to the peer byte-for-byte) is implemented and both halves are exercised by the code paths
that already run (`rs_FileWrite` -> `save60_local_written` -> `PKT_SAVEPUSH` -> `save60_store`), but the
end-to-end save at a save point **was not observed live**. Reported NOT DONE, not papered over.

## 3. Items and spawners (A1-8)

What the game actually has (**OBSERVED**): the 44 `CToeItem*` classes are *level entities* created with
the level; "a spawn" is the game clearing their interaction gates — `CToeContainer::slot28` (0x41b220)
clears `+0xb0` on up to ten item entities (FINDINGS_16 §3.1), and `CToeBreakableCase` calls it on break.
`CToeRespawner` (tag `RESP`, constructor 0x46cd70, update 0x46ce90) spawns **NPCs** (`FUN_004f22e0`),
not items — the audit's "CToeRespawner + the 44 CToeItem* classes" is half right.

So "the host decides which items exist" is the state of the same entity instances on both copies. The new
`PKT_WORLD` carries the family table (class, id, position, and the fields the game's own interaction check
`FUN_0044d6a0` reads: `+0x20` active, `+0xa4` broken/opened, `+0xa8` collected, `+0xb0`, `+0xc0`,
`+0xc4` the using character, `+0x128` a pedestal's placed item, plus the same fields as the receiver's
"before" values). The guest applies a field only where its own value still equals the sender's before, and
never within 1.5 s of its own last change (its own pickup wins and travels back as `PKT_PICKUP`). A forced
resend every 2 s converges a guest that missed a packet.

## 4. Containers (A1-9)

The family the audit names: `CToeContainer` (CONT), `CToeChest` (CHES), `CToeChestKey` (CHKE),
`CToePedestal` (PEDE). The ten test saves contain **no** `CToeContainer` and **no** `CToeChest`; they have
2 + 1 `CToeChestKey` (J002, I007, both already collected: `+0xa8 = 1`, `+0x20 = 0`) and **3
`CToePedestal`** in H006 (save 08) on the floor at z = 0.5. A pedestal is where a statuette (`STAT`) is
placed: `FUN_00449e90` sets `pedestal+0x128 = 1` when it is handed a `STAT` entity, and the use
`FUN_00449df0` only plays a sound when `+0x128 != 0`. No class in these saves gives an item when opened,
so "its item landed once" cannot be shown here (see §6).

The sync is the same table as A1-8 (the container classes are in `world_class`), with `+0x128` added
exactly for the pedestal's placed state.

**Same-family list** (every class this task touched, and whether it ran live):

| class (tag) | how it is covered | live? |
|---|---|---|
| `CToeSavePoint` (SAVE) | hooked use 0x46e830 + the guest request; the save push covers its file | use + request observed; the save did not complete (§2) |
| `CToeSimpleSavePoint` (SAVE) | hooked use 0x46ed80 (same code path) | **not tested live** - the ten saves have no `CToeSimpleSavePoint` (the ten-slot scan lists only `CToeSavePoint`) |
| `CToeItem*` (26 tags, MEDI/ENDR/...) | live-item state in `PKT_WORLD` | **tested live** (ENDR in I100, phase B) |
| `CToeContainer` (CONT) | state table | **not tested live** - no such entity in any of the ten saves (FINDINGS_16 §6 + §5.2) |
| `CToeChest` (CHES) | state table | **not tested live** - not in any save |
| `CToeChestKey` (CHKE) | state table | **not tested live** - J002/I007 only, both already collected (`+0xa8 = 1`, `+0x20 = 0`) |
| `CToePedestal` (PEDE) | state table (`+0x128` placed flag) | **tested live** (H006, phase C) |
| `CToeRespawner` (RESP) | **not touched**: it spawns NPCs (`FUN_004f22e0`), not items; NPCs are already `PKT_NPC` | n/a |

A `CToeBreakableCase` break releases its items through `CToeContainer::slot28` (FINDINGS_16 §2), i.e. it
changes the item entities' `+0xb0` - which is exactly the field `PKT_WORLD` carries. The break itself is
already synced by the prop table (`PKT_PROP` kind 3), so nothing new was needed for it.

## 5. Live evidence

### 5.1 `sh tests/run_pair_menu.sh chk60b.dll check_world.py` (loopback, run_c60final2)

```
== check_world.py

== A save: the same file on both copies
   host remote 10 saves, guest remote 10 saves
   host: save point +0x14 = 3 (the state the save that made these saves left); setting 0
   host: savepoint (player 1) -> ok used SAVE at -223.8,-113.1,97.6 (world sub-state 11)
   the host's game did NOT write a save in 40 s (world state 10, request 0)
   guest: save point +0x14 = 3 (the state the save that made these saves left); setting 0
   guest: savepoint (player 2) -> ok used SAVE at -223.8,-113.1,97.6 (world sub-state 0)
   no save file was written for the guest's request in 40 s
save: NOT DONE - the game's own save state (world+0x11c = 10) does not complete in these saves, so no save file exists to compare (see FINDINGS_60)
   host save counters:  [' saves sent 0 rcv 0 acked 0 failed 0 ', ' savept asked 0 applied 1 ']
   guest save counters: [' saves sent 0 rcv 0 acked 0 failed 0 ', ' savept asked 1 applied 0 ']
```

The counters are the guest->host half **OBSERVED working**: the guest's own player 2 used its save point,
the guest's hook refused the local save and sent `PKT_SAVEPT` (`savept asked 1`), and the host ran the
game's own use on its copy of that save point (`savept applied 1`). The save itself then stops in the
game's save state 10 (§2), so no file exists.

```
== B items: both copies list the same live world items
   host live items: none
   guest live items: none
   live item lists equal: True
   host: activate item ENDR 1a1b3dc8 (+0x20 = 1, the test write check_pickup.py uses)
   wr -> ok 4 bytes
   guest shows the same live item after 1.0 s: ENDR at -570.8,-248.7,0.6
   host worlds: worlds 1 in level 49313030
   guest worlds: worlds 1 in level 49313030
items OK: the guest's live item set follows the host's

== C containers: the same opened/used state on both copies
   level I100 has no container-family entity: loading game7.sav (H006, 3 CToePedestal)
   loadsave -> ok real load of "game7.sav" requested (the game thread runs it)
   both copies in level H006 after 3.0 s
   3 container-family entities in level H006
   host uses PEDE 197ed898 at 125.0,-50.0,0.5: ok used PEDE at 125.0,-50.0,0.5 (world sub-state 0)
   host  fields (1, 0, 0, 0, 0, 0, 1)
   guest fields (1, 0, 0, 0, 0, 0, 1)
   (the game's own use changed none of the synced fields in this save)
   guest uses PEDE 19b81780 at 125.0,-50.0,0.5: ok used PEDE at 125.0,-50.0,0.5 (world sub-state 0)
   host  fields (1, 0, 0, 0, 0, 0, 1)
   guest fields (1, 0, 0, 0, 0, 0, 1)
   (the game's own use changed none of the synced fields in this save)
   host: PEDE +0x128 = 1 -> 0 (its "placed" flag; no STAT entity exists in these saves)
   wr -> ok 4 bytes
   guest shows PEDE +0x128 = 0 after 1.0 s
containers OK: the same state on both copies after each player used them

summary: fails none
check_world: OK
```

The container fields are `(0x20, 0xa4, 0xa8, 0xb0, 0xc0, 0xc4, 0x128)` = `(1,0,0,0,0,0,1)` on both copies
before and after each use; the last step flips the pedestal's `+0x128` (the flag its own use checks)
on the HOST only and the guest shows the same value after 1.0 s.

### 5.2 The ten-slot family scan (`tests/scan_world.py`, one solo host, `loadsave game0..9.sav`)

Every `CToeSavePoint` in all ten slots: `p14=3`, `p20=1`, `p24=1`, `p150=1` — the post-save state (§2).
Container family: `CToeChestKey` x2 in J002 (slot 04) and x1 in I007 (slot 10), all `+0xa8 = 1`,
`+0x20 = 0`; `CToePedestal` x3 in H006 (slot 08) at z = 0.5 with `+0x20 = 1`; **no `CToeContainer`, no
`CToeChest` anywhere**. Items: 0-2 per level, every one `+0x20 = 0` (inactive), as FINDINGS_16 saw.
`CToeRespawner` x2 in H000 only (tag `RESP`).

### 5.3 Regression soak

`OBSCOOP_LINK=steam sh tests/run_soak.sh chk60b.dll` (30 iterations, the steam-like relay profile,
~2400 s cap), final DLL = the one the soak ran (copied back from the test folder, `cmp` identical):

```
== 30: host loads game3.sav -> load done, level I100 -> J002/J002 (0.0s, one level) (mode (1, 0) / (1, 0))
== race A: door use on the host, then a save load the moment the door asks for its level
== race B: the same door used on the host and on the guest at the same moment
== settling after the race phases (one level, no change for 3 s)
soak OK (30 location changes, both copies alive)
== check_doors.py --reset game3.sav (timeout 300s)
== phase host -> level I100: CToeDoor id ..., at (-93.8, -571.8, -5.5) usable 1 user - dest I010 (door scan after 0.0 s)
   image: PASS
   transition: dest I010 -> host I010 guest I010 after 0.0 s: PASS
== reset: the host loads game3.sav again (back to I100)
== phase guest -> level J002: CToeDoubleDoor id ...: at (-161.6, 842.5, -12.9) usable 1 user - dest J000 (door scan after 0.0 s)
   image: PASS
   transition: dest J000 -> host J000 guest J000 after 0.0 s: PASS
== liveness and crash reports
  host: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
  guest: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
== crash handler proof: the guest is asked to fault (pipe crash)
== the guest's crash report
  FATAL EXCEPTION: 2 line(s)
*** obscoop: FATAL EXCEPTION code 0xc0000005 at 0x5a51404c (minimal line; full report follows)
*** obscoop: FATAL EXCEPTION access violation (0xc0000005) on the vectored path
== stopping the two games
remaining Obscure2.exe: 0, obscoop-relay.exe: 0
=== soak run: PASS
```

The earlier phases of the same soak (verbatim): `check_attack_anim.py`, `check_anim_sync.py`,
`check_controls.py` ("host: PASS ... guest: PASS"), `check_visible.py` ("host window: PASS ... guest
window: PASS"), `check_fight_pair.py` ("attack-each-other OK (3 swings each way, both copies alive)"),
no `FAIL`, no `-- ... exit` line.

Both new save-point hooks install in every copy (host log, this soak):
```
05:48:55.030 [40564] hook: CToeSavePoint::use (0x46e830) hooked
05:48:55.031 [40564] hook: CToeSimpleSavePoint::use (0x46ed80) hooked
```

## 6. DONE / NOT DONE / UNKNOWN

**DONE**
* Save files: every save the game writes on either copy is pushed to the other through the DLL's own
  `FileWrite` proxy and written to both folders the game may read; the guest's save-point use is a request
  the host performs with the game's own use function; the save folder rule is now the same one the proxy
  uses on both copies.
* Items: host-authoritative live-item state (`PKT_WORLD`), proven on the pair.
* Containers: the same state table for CONT/CHES/CHKE/PEDE, proven on H006's pedestals.
* `tests/check_world.py` (new) covers the three phases; `tests/scan_world.py` (new) is the read-only
  ten-slot inventory of the families.

**NOT DONE**
* The live save-at-a-save-point proof (a): the game's save state 10 never completes in the ten test
  saves, so no save file exists to compare (§2). The transfer code is in place and its receive half is
  the same `save60_store` used by the push; nothing about it was observed end to end.
* "The item goes to whoever opened the container, once": no item-giving container exists in the ten test
  saves (FINDINGS_16 §6 + the ten-slot scan), so the release path (`CToeContainer::slot28`) was not
  exercised live. Same code path, not tested live.

**UNKNOWN**
* Why the save panel (`game+0x478`) never closes after `Request_SaveGame` in these worlds. Its own
  update `FUN_00542d00` runs only with `panel+0x10 != 0` and iterates the FX entries it parsed from
  config; in the idle state the panel is `+0x10 = 0`. Whether a save point in its normal idle state
  (`+0x14 = 0`) on a *non-save-loaded* level would complete — UNKNOWN, not reachable with these saves.
* Whether a real (non-test) save made by the owner at a save point writes through `rs_FileWrite` with the
  slot name the check expects: DERIVED from the proxy design, not observed (no save has ever been written
  in any test session: no `remote FileWrite` line in any log).
