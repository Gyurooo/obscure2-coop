# Chaos plan: save transfer, party, inventory and hands over a lossy link

## Harness: tests/run_chaos.sh

`sh tests/run_chaos.sh <dll> [lag jitter loss] [--save-xfer]`

- Paths are repo-relative: `OBSCOOP_TEST_ROOT` (default `<tests>/../..`) holds `obscure2-test` and
  `obscure2-test2`; the relay is `$OBSCOOP_RELAY` (default `$OBSCOOP_TEST_ROOT/obscure2-coop-repo/build/obscoop-relay.exe`);
  the interpreter is `$PYTHON` (default `python`). Release scratch goes under `$TMPDIR`.
- Starts two relays with the given `--lag/--jitter/--loss` on a plain-UDP link
  (`host 27961 --udp-link listen:28000`, `guest 27962 --udp-link 28000`) and records only the PIDs it started.
- Preflight: if any `Obscure2.exe` or `obscoop-relay.exe` runs that this script did not start, it aborts.
- Starts the pair through the relays (`duo.py start -- OBSCOOP_UDP=27962`), puts both in a 2P new game
  (`duo_start_game.py`), loads save 01 on the host (`start_save.py <host pid>`).
- `--save-xfer`: before starting, the guest's `Save/game*.sav` are deleted (the originals are kept in
  the guest's `Save.chaos.bak`, made only once), and `check_savexfer.py` runs at the end.
- Waits at most 60 s for convergence, polling memory (600 ms): both copies in `game+0x310 == 1`,
  `game+0x320 == 0`, the same level tag, the same inventory count on both, and the same party tags.
  Prints how long it took and, on timeout, exactly which condition was still false.
- Then runs the checks with a per-check timeout: `check_save.py`, `check_party.py`, `check_hands.py`,
  `check_items.py` (and `check_savexfer.py` with `--save-xfer`). Every check's output is printed verbatim.
- From the two `obscoop.log` files it prints the host's first save-load line and the guest's level/party
  lines with their timestamps and the difference (both copies share the PC clock), plus the guest's
  per-save file presence/size.
- `trap` on EXIT/INT/TERM always stops the games (`duo.py stop`) and kills only the relay PIDs it started.
  Every wait has a timeout (`timeout` around each helper, bounded polls, bounded log waits).

## Scenarios (one live run each, foreground)

| run | lag | jitter | loss | purpose |
|-----|-----|--------|------|---------|
| S0  | 0 ms | 0 ms | 0 % | control: does the harness itself work, and what is clean-link convergence time? |
| S1  | 60 ms | 20 ms | 5 % | real-internet-like link |
| S2  | 100 ms | 40 ms | 10 % | bad link |

Budget: at most 5 live runs in total (3 scenarios + up to 2 reruns of the known no-world startup flake).
A failing scenario is rerun once after a fix, not counted as a new scenario.

## Pass criteria (per scenario)

- `check_save.py` prints `save OK`: both copies in level `I100`, inventory count 44 on both.
- `check_party.py` prints `party OK`: identical party character tags and inventory counts.
  Additionally the guest log must show `guest: host party applied at level I100` (the party stash was
  delivered before the level change, not after it).
- `check_hands.py` prints `hands OK (N characters checked)` with N > 0 and identical slot tags/selected
  slot for every character present on both copies.
- `check_items.py` prints `items OK`: a host inventory change (44 -> 45) is mirrored to the guest within
  its 3 s window.
- `check_savexfer.py` prints `save transfer OK` (with `--save-xfer`): all ten `game*.sav` byte-identical.
- Convergence (level + party + inventory) within 60 s of the host's load.
- No stuck state: no game/relay left running; the guest is not left in another level, with a partial
  inventory, the wrong party, or a half-transferred save set.

## What I look for when a scenario fails

- Save transfer: `SAVE_RETRY_MS` stop-and-wait throughput vs the 60 s window; stale/duplicate acks;
  a lost first `PKT_SAVE`/`PKT_SAVE_ACK`; the guest re-writing/truncating files.
- Party: `PKT_REGION` is sent once per level change (and once on welcome) with no retransmission, so a
  lost party chunk means the guest changes level with the old party table. Check the guest log for
  `host party stored` vs `host party applied`.
- Inventory: chunk assembly (bitmask reset on chunk 0) under reordering; 1 s resend cadence.
- Hands: retry gate in `weapons_for` (5 s after a failure) vs the order inventory-then-hands.
