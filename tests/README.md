# Obscure II co-op tests

Bot-driven checks on two test copies of the game. They use the mod's named pipe for input and memory reads, so
no human plays and the desktop is not touched.

## Setup

- Two game copies (`OBSCOOP_HOST_DIR`, `OBSCOOP_GUEST_DIR`), each with `xinput1_3.dll` from `build/`.
- The host copy's `Save/` has the ten `gameN.sav` files; the guest gets them from the host in the mod (or copy them).
- `OBSCOOP_TEST_ROOT` is the folder that contains both copies; pids and snapshots are written in this `tests/` folder.
- Python 3 on PATH. `duo.py` starts/stops the copies; `suite.sh` runs the checks.

## Running

```
python -I duo.py start          # host + guest, UDP loopback
python -I duo_start_game.py     # both into a 2P new game
python -I start_save.py HOST_PID
python -I start_save.py GUEST_PID   # the guest's own save load now changes the level
```

Then the checks in `suite.sh` cover: save 01 -> I100 on both, inventory 44 on both, the item mirror, the life
mirror, the death pad swap, movement, doors, pause and free look. A failure prints the observed values.

## Test-only hook: `OBSCOOP_TEST_DELAY_PROGRESS_MS`

Setting this on the host makes the mod hold the party block (the host's character table at
`progress+0x1b0c`, sent as `PKT_REGION`) back for that many ms after every level request, so the request
reaches the guest before the table and the guest's "wait for the host's party table" branch runs. It is off
unless set, and only the host process acts on it (the variable reaches the guest too and is ignored there).
`duo.py` copies its own environment into both game processes, so the shell variable is enough:

```
OBSCOOP_TEST_DELAY_PROGRESS_MS=1200 sh tests/run_pair.sh <dll> check_party.py check_hands.py
```

The host log then shows `host: TEST holding the party block back for 1200 ms` and `host: TEST delay over
after ...`, and the guest log `guest: level request I100 deferred waiting for the party (up to 3000 ms)`
followed by `guest: level request I100 released after ... ms: host party arrived`. A value above the guest's
3000 ms wait makes the guest give up (`... no host party for it, the guest keeps its own`); the party may
then legitimately differ between the copies. Do not set it for normal runs.

## TASK 17 tools: safe teleport, the item/enemy gate, forward play

- **`tp` is safe now** (mod side). `tp <0|1> x y [z dx dy]` places the character on the game thread, watches
  the character's own physics for up to 3 s and accepts only a settle within 8 units of `z` and 6 units of
  the requested X/Y; otherwise it restores the old position and says why. Replies are
  `ok settled at (x, y, z) after N s` or `refused: ...; old position restored`. `tpsafe` is an alias,
  `tpraw` still does the old unchecked write. `bot.tp(pipe, player, x, y, z=None)` formats the command.
- **`tp_to_items.py`** — the gate every teleport into a room must pass: scans live items
  (`+0x20 != 0`, `+0xa8 == 0`, gates 0), enemies (`CCharacter*`, life > 0) and `CToeRespawn*` spawners
  within a radius, ALLOWs only `items >= 1` and no enemy/spawner, then runs the safe `tp` and proves the
  character stands still for 3 s. Importable (`gate_teleport`, `scan_room`, `room_verdict`).
  CLI: `python -I tp_to_items.py <pid> <player> <x> <y> [z] [--radius N] [--scan-only] [--json]`.
- **`check_tp.py`** — the Part A proof: player start, a door, a `CToeCharacterPos`, the breakable case and a
  random far point; each must stand still for 3 s or be refused with the old position restored.
- **`check_gate.py`** — shows the gate refusing a room that only has an inactive item and allowing it once
  the item is live (`wr item+0x20 = 1`, the only write, and it is printed).
- **`play_forward.py`** — Part C: walks with a measured stick basis (four probe directions) and the level's
  own `CToeCharacterPos` waypoints to its doors/loading zones, presses A, waits for the game's own
  transition, scans each new room and appends it to `SLOT_SCAN.md`; saves through `CToeSavePoint` only in a
  room with a live item and no enemy. It never teleports and never asks for a level tag.
- **`probe_control.py`** — measures whether the pad reaches the player in a save-loaded world.
- **`load_slot.py` / `run_solo_slot.sh`** — load one slot into ONE copy through the game's own menu-load
  path, wait for the world and for the character placement, then run checks against that single copy:
  `sh tests/run_solo_slot.sh chk17.dll 9 check_tp.py play_forward.py`
