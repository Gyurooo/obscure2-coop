# obscure2-coop

Online co-op for Obscure II (Steam, app 254480, build 215294), built on the game's own local co-op.
Sister project of [obscure-coop](https://github.com/Gyurooo/obscure-coop) (Obscure 1).

**Status: prototype, version 1.3, protocol 17.** Two copies of the game stay in sync: each copy simulates
both players, the pads are streamed, and the host is authoritative for the world. Both players start at
the main menu, the host loads a save and the guest brings itself into the same level. It runs on two
copies on one PC (UDP loopback, what the bot tests use) and, through a small Steam relay, between two
PCs. Attacks, enemies and character abilities are not proven (see the table).

## What is synced

| feature | state | how it was tested |
|---|---|---|
| movement, facing, animation | synced; each player's own copy is the authority for its character, the peer follows with a blend (`PKT_CHAR` + snapshot) | `check_movement.py` phases A-E, loopback and a 60 ms / 20 ms jitter / 5 % loss relay (`FINDINGS_25.md`) |
| level change, doors, loading zones | synced; the host's request reaches the guest, which reloads the level | `check_save.py`, `check_door_pair.py`, `run_pair_menu.sh`, level scans (`FINDINGS_12`, `FINDINGS_19`, `FINDINGS_20`) |
| save load (the real flow) | the host loads from its own menu; the guest builds the same world from the transferred save file | `run_pair_menu.sh` + `start_menu_load.py` (`FINDINGS_12`, TASK 12) |
| save file transfer | synced in chunks with acks (`PKT_SAVE`, `PKT_SAVE_ACK`, `PKT_SAVES_DONE`); a reconnecting guest that has the files gets no second transfer | `check_savexfer.py` (byte-identical files), `run_chaos.sh --save-xfer` (`FINDINGS_14`, `FINDINGS_25`) |
| party (which characters play) | synced; the save's character records are applied on the guest | `check_party.py` (`FINDINGS_14`, `FINDINGS_28`) |
| inventory (all 44 items) and every change | synced | `check_items.py` (`FINDINGS_14`) |
| item use (first-aid kit, energy drink) | synced through the item object's own use path | `check_itemuse.py` (`FINDINGS_24`) |
| weapons in hand, selected slot | synced | `check_hands.py`, `check_hands_visible.py` |
| life / health | in the state snapshot, applied on the guest | `check_health.py` |
| death, and the pad handover to the alive partner | synced | `check_death.py` |
| world entities | the two copies build the same CToeManager list | `check_entities.py` |
| breakables (chairs picked up, carried, broken) | synced both directions | `check_breakables.py` (`FINDINGS_26`, `FINDINGS_27`) |
| world item pickup | synced both directions | `check_pickup.py` (`ITEMS_FINDINGS.md`) |
| scripted events / cutscenes | the scene state is streamed; a skip on **either** copy ends it on both, through the game's own skip | `check_cutscene.py`, `run_cutscene_pair.sh` (`FINDINGS_30`, `FINDINGS_31`) |
| late join (guest starts after the host is in a level) | the guest joins into the running level | `run_late_join.sh` (`FINDINGS_14`) |
| reconnect | an 8 s link drop resumes in ~0.5 s with no level reload; a restarted guest gets the saves again | `run_reconnect.sh` (`FINDINGS_25`) |
| pause and menus | START on either controller pauses both copies; the pause menu and the inventory (WEAPONS/ITEMS/TEAM, the documents and map panels they open) are shown on both screens and BOTH pads drive them; the weapon wheel and item menu show on both | `check_menus.py` (`FINDINGS_36`) |
| camera | free look stays local; `CAMERA=shared` makes the guest follow player 1 | `check_movement.py` |
| abilities (lock pick, heavy case) | **unverified**: `PKT_APT` result sync is in the build, but the game's use never linked in the tests | `check_abilities.py` (`FINDINGS_28`) |
| attacks, combat, enemies | **unproven**: the test levels' aim/target search accepts no NPC at all (with the mod passive too), so no attack could be driven; enemies are simulated twice | `check_combat.py`, `measure_combat.py` (`FINDINGS_21`, `FINDINGS_29`) |
| cases/chests, item drops from broken props | implemented on the same path as chairs, not exercised | `scan_abilities.py` survey (`FINDINGS_28`) |
| Steam transport (direct P2P) | ported, **untested between two Steam accounts** | never run with two accounts |
| Steam relay (app 480) | works over a simulated link; **not yet tried between two Steam accounts** | `run_chaos.sh` with `--udp-link` (lag/jitter/loss) |

## What is in the repo

| path | what |
|---|---|
| `src/obscoop2.c` | the proxy `xinput1_3.dll` (includes the other modules): DllMain, save/registry/RemoteStorage redirect to `coop_profile`, the command pipe, the input hook, the build check |
| `src/net.c` | packets, the UDP and Steam transports, roles, the pad/state exchange |
| `src/sync.c` | sync logic and the frame tick (state snapshot, party, inventory, props, scenes) |
| `src/hooks.c` | game hooks (`hook_entry`): level/load/menu requests, the input update |
| `src/steam.c`, `src/window.c` | the Steam flat API binding, the window mode (`OBSCOOP_WINDOWED=1`) |
| `relay/relay.c` | `obscoop-relay.exe`: carries the DLL's UDP packets over Steam as app 480 |
| `package/` | the player-facing release sources: INSTALL.txt, README.txt, install.ps1, uninstall.ps1, obscoop.ini, the `start_*.bat` files |
| `tools/build_release.sh` | builds the DLL and the relay, assembles and zips the package |
| `tests/` | the bot harness (see [tests/README.md](tests/README.md)) |
| `FINDINGS_*.md`, `*_FINDINGS.md` | the research notes, one per task; every claim there is labelled OBSERVED / DERIVED / GUESS / UNKNOWN against the decompile |

## How to build

The mod is 32-bit C, built with llvm-mingw (`i686-w64-mingw32-gcc`). Nothing about the build is
machine-specific; point the environment variables at your own toolchain.

A DLL for the tests:

```sh
"$OBSCOOP_LLVM_MINGW/i686-w64-mingw32-gcc.exe" -O2 -Wall -shared -static -static-libgcc \
    -o chk.dll src/obscoop2.c src/obscoop2.def -Wl,--kill-at -lws2_32 -ld3d9
```

Three warnings are known and expected (`tick`, `watch_start`, `request_shot`); anything else is new.

The release package (DLL + relay + the player files, zipped, with its SHA-256 printed):

```sh
OBSCOOP_LLVM_MINGW=<path to the llvm-mingw bin folder> \
OBSCOOP_STEAM_API=<path to a 32-bit steam_api.dll for the relay> \
sh tools/build_release.sh 1.3
```

`steam_api.dll` is the 32-bit Steamworks.NET **Standalone 2025.164.1** flat API DLL; it is not in the
repo. The package goes to `build/obscoop2-<version>/` and `build/obscoop2-<version>.zip`.

## How to run the tests

Two test copies of the game on one PC, driven by bots through the mod's command pipe; no human plays and
the desktop is not touched. Python 3 on PATH, Git Bash on Windows.

```sh
export OBSCOOP_TEST_ROOT=<folder that holds obscure2-test and obscure2-test2>
sh tests/run_pair_menu.sh <path to the built DLL> check_party.py check_items.py check_hands.py check_entities.py
```

`run_pair_menu.sh` is the real flow: both copies at the main menu, the host loads save 01, the guest
follows. It always stops the games and prints every check verbatim. Every runner and every check is
listed with one line in [tests/README.md](tests/README.md); one run in four may start with no world on
either copy (a known startup flake) - rerun before concluding anything.

## Playing it

`package/INSTALL.txt` (install and uninstall) and `package/README.txt` (hosting, joining, what is synced,
known issues, how to report a bug) are the player-facing files; the release zip contains them.
Both players must run the same version. There is no direct-IP/LAN transport in this build: two PCs go
through Steam (the relay, or the direct Steam link).

No game files are shipped. MIT license.

Research notes: [coop-anything games/obscure-2](https://github.com/cranebeaker/coop-anything).
