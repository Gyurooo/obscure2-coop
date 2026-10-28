# Obscure II co-op tests

Bot-driven checks on two test copies of the game. The bots use the mod's own named pipe for input and
`ReadProcessMemory` for reading, so no human plays and the desktop is not touched. Every runner starts
and stops the game processes it owns; none of them touch the owner's install.

## Setup

- Two game copies: `OBSCOOP_HOST_DIR` and `OBSCOOP_GUEST_DIR` (default `$OBSCOOP_TEST_ROOT/obscure2-test`
  and `.../obscure2-test2`). `OBSCOOP_TEST_ROOT` defaults to two folders above `tests/`.
- Each copy gets the DLL under test copied in as `xinput1_3.dll` (`OBSCOOP_DLL`).
- The host copy's `Save/` holds the ten `gameN.sav` files; the guest receives them from the host.
- Python 3 on PATH (`PYTHON`), Git Bash on Windows; every script is started from the worktree root.
- Before a run: no `Obscure2.exe` or `obscoop-relay.exe` may be running that the runner did not start
  (`duo.py start` refuses). One run in four starts with no world on either copy - a known startup flake,
  rerun once before concluding anything.

## The runners

| runner | one line |
|---|---|
| `run_pair_menu.sh <dll> [checks...]` | **the real flow**: both copies at the main menu, the host loads save 01 with the game's own LoadByName, the guest follows by itself, then runs the checks |
| `run_pair.sh <dll> [checks...]` | the old flow (new 2P game, then load save 01 from the pause menu), then the checks |
| `run_cutscene_pair.sh <dll> [--skip-by host\|guest]` | both copies enter the intro cutscene, one copy skips, `check_cutscene.py` proves the other left it too |
| `run_reconnect.sh <dll>` | drops the link for 8 s with `netpause`, then kills and restarts the guest; both must recover without a level reload |
| `run_late_join.sh <dll>` | the host loads and settles first, only then does the guest start at the menu and join into the running level |
| `run_named_load.sh <dll>` | the file the host's load names (`o2.sav`) exists only on the host; the guest may only get it by transfer |
| `run_second_load.sh <dll> [checks...]` | a second load in one session, from the game's own pause menu, the guest must follow again |
| `run_chaos.sh <dll> [lag jitter loss] [--save-xfer]` | the pair through two relays with lag/jitter/loss on a plain-UDP link, then the convergence checks |
| `run_solo_slot.sh <dll> <slot> <check...>` | ONE host copy, load the slot through the game's menu-load path, run checks against that copy |
| `run_scan_slots.sh <dll> [slots]` | ONE copy, load every save slot and scan the live level of each |
| `run_scan_transitions.sh <dll> [slots]` | ONE copy, read every level-transition destination the entities of every slot carry |
| `run_explore.sh <dll> <slot> [tag:entry...]` | ONE copy, visit every level its doors point to and scan each |
| `run_jump.sh <dll> <slot> <TAG> <entry> <flag>` | ONE copy, one transition through the mod's `level` command (allowlisted from `obscoop_levels.txt` only) |
| `run_survey.sh <dll> <slot> [tag:entry...]` | ONE copy, survey the given door destinations for a live item / save point / enemy |
| `suite.sh` | the four basic checks on a pair that is already in the saved level (save, items, health, death) |

## The checks

Each takes `<host pid> <guest pid>` unless noted, prints what it observed and exits non-zero on a
mismatch.

| check | one line |
|---|---|
| `check_party.py` | both copies have the same party (character tags of the live humans) and the same inventory count |
| `check_save.py` | both copies are in the same saved level with the same inventory count |
| `check_items.py` | an inventory change on the host is mirrored to the guest |
| `check_health.py` | a character life change on the host is mirrored to the guest |
| `check_death.py` | after player 1 dies the host pad moves the alive partner |
| `check_hands.py` | both copies hold the same weapons in their hands (per live human) |
| `check_hands_visible.py` | the render-side fields of every weapon slot are equal, so the weapons are really drawable |
| `check_entities.py` | the CToeManager entity lists of the two copies are (nearly) the same |
| `check_movement.py` | both players move the same on both copies; phases A-D, `--early` runs phase E right after the load |
| `check_savexfer.py` | the guest's save files are byte-identical to the host's |
| `check_door_pair.py` | the door interaction in the pair flow, plus a side-by-side state dump of both copies |
| `check_pickup.py` | world item pickup sync, both directions, on live `CToeItem` entities |
| `check_itemuse.py` | using an item (healing) on one copy is applied on the other |
| `check_breakables.py` | a chair carried and broken on one copy shows carried and broken on the other; SKIPs where the save has no usable chair |
| `check_cutscene.py` | a skip on one copy ends the scripted event on both, and ends in normal play in the same level |
| `check_combat.py` | the real attack input (hold LB + press A) and the fight, synced; needs a level with live enemies |
| `check_abilities.py` | lock picking / heavy case driven on both copies; the result must reach the other copy |
| `check_tp.py` | proves `tp` is safe on five targets: each settles or is refused with the old position restored |
| `check_gate.py` | shows the item/enemy gate refusing a room and allowing it once the item is live |

## Helper tools

| tool | one line |
|---|---|
| `bot.py` | send commands to a running copy through the mod's named pipe (`python -I bot.py <pid> <cmd>`) and take window screenshots |
| `peek.py` | read-only memory peeking into a running copy (`ReadProcessMemory`, no debugger attach) |
| `win.py` | window helper: min / restore / info for a copy |
| `duo.py` | start / stop the host and guest copies on one PC (`start`, `stop`, per-side env in `K=V` form) |
| `duo_start_game.py` | drive both copies into a 2-player new game by game state, not fixed sleeps |
| `start_menu_load.py` | the real flow: both at the menu, the host loads a save through the game's own LoadByName, wait for the guest |
| `start_save.py` | start one copy into save 01 via the pause menu (new 2P, Load, slot 01, YES) |
| `start_newgame.py` | put the pair into a 2P new game and stop with the intro cutscene still running |
| `start_late_join.py` | host first, guest started later at the menu (late join) |
| `load_slot.py` | load one save slot into ONE copy through the game's menu-load path and wait for character placement |
| `o2_file.py` | prepare / check the `o2.sav` stand-in the main menu's Load Game is hard-wired to |
| `ipt_table.py` | decode an `.ipt` input map into a table (the format the mod's `obscoop_o2.ipt` uses) |
| `tp_to_items.py` | the item/enemy gate every teleport must pass (`gate_teleport`, `scan_room`, `room_verdict`, importable and CLI) |
| `play_forward.py` | walk with a measured stick basis through the level's own doors and loading zones, scanning each new room |
| `scan_items.py` | read-only listing of the level's entities (class, id, collected/active flags, position) |
| `scan_slots.py` | load every save slot on one copy and print the live level of each |
| `scan_transitions.py` | read every transition destination in every slot |
| `scan_abilities.py` | load every slot, print the party, the progress character records and the aptitude objects |
| `explore_levels.py` | visit the levels the game's own doors point to, one after another, and scan each |
| `jump_probe.py` / `pair_j003.py` | one transition with the mod's `level` command / put both copies into J003 and prove the guest followed |
| `j003_pickup.py` | pick an item up in J003 (the level with live items and no enemies) in the game's own flow |
| `survey_levels.py` | survey the remaining door destinations for a live collectable, a save point and no enemy |
| `measure_combat.py` / `probe_combat_input.py` | put both copies in a combat level and print every enemy's state, and whether the pad reaches it at all |
| `probe_control.py` / `probe_move.py` / `probe_slots19.py` | does the pad reach the character after a save load (per slot) |
| `probe_door.py` / `probe_door2.py` / `probe_interact.py` / `probe_face.py` / `probe_use.py` | why a door or save point is not usable after a save load (interaction target, facing, the entity's own "user" field) |
| `probe_pause.py` | what the pause menu offers in a level reached through a door (screenshots) |
| `jump_probe.py` | see above |
| `shoot_breakables.py` / `shot_pair.py` | screenshots of a carried/broken chair, and of what both copies draw |
| `case2.py` / `case3.py` | the scripts behind `run_named_load.sh` and `run_second_load.sh` |

## Test-only switches in the mod (never set in a release run)

- `OBSCOOP_PASSIVE=1` - behave like a plain proxy: no net, no input-hook writes. Proves a difference is
  the mod's doing.
- `OBSCOOP_LEVELS_LOG=1` - append every real level transition to `obscoop_levels.txt`, the allowlist the
  pipe's `level` command replays (a guessed tag is refused; requesting an unknown tag crashes the game).
- `OBSCOOP_TEST_DELAY_PROGRESS_MS=<ms>` - host only: hold the party block back for that long after every
  level request, so the guest's "wait for the host's party" branch runs. The host log then shows
  `host: TEST holding the party block back for ... ms`, the guest
  `guest: level request <tag> deferred waiting for the party (up to 3000 ms)`. Above 3000 ms the guest
  gives up (`... no host party for it, the guest keeps its own`) and the party may legitimately differ.
- `netpause <ms>` (pipe command) - send and receive nothing for that long, exactly like a dead link.
- `tp` - teleport that watches the character's own physics and restores the old position if it does not
  settle; `tpraw` is the old unchecked write. Everything that teleports goes through `tp_to_items.py`.
- `OBSCOOP_SCAN_ONLY`, `OBSCOOP_DEBUG_SYNC`, `OBSCOOP_DROP_HOSTPAD`, `OBSCOOP_INPUT_DELAY` - see the
  comments at their use in `src/`.
