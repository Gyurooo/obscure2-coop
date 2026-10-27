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
