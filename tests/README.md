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
