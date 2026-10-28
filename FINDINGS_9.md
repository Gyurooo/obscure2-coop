# TASK 9 findings: the guest rebuilds the world with its own party under loss/jitter

Status labels: OBSERVED = read from a log/memory this session; DERIVED = follows from code or decompile
with the address/line named; GUESS = plausible but untested; UNKNOWN = not established.

## 1. The failing run, re-read from the logs on disk

Source: `<test root>\obscure2-test\obscoop.log` (host) and
`...\obscure2-test2\obscoop.log` (guest), the run of 23:48:29-23:50:45, the same run the task quotes.
Both copies share one PC clock and one log format (`HH:MM:SS.mmm [thread] ...`).

OBSERVED timeline (verbatim lines, trimmed to the fields that matter):

```
23:49:41.767 [22636] host   request LoadByName "game0.sav" [mode 1]
23:49:41.849 [22636] host   host: level is now I100 without a ChangeLevel request (load or new game), telling the guest (entry 1120)
23:49:41.849 [23668] guest  guest: host LoadByName "game0.sav"
23:49:41.928 [23668] guest  guest: host ChangeLevel I100 entry 1120 flag 1
23:49:41.943 [17336] guest  guest: host party stored at level I100: first character BOY1
...
23:50:45.183 [17336] guest  guest: host party stored at level I100: first character BOY1   (236 such lines, ~4/s)
```

* OBSERVED: the guest applied the level request 79 ms after the host announced the level, and the FIRST
  stashed party record for I100 arrived 15 ms AFTER that (`stored` at 41.943 vs `ChangeLevel` at 41.928).
  The guest was still holding the table of the previous level (`stored at level B101`, from the host's
  2-player new game, lines 55-197), so `hk_party_table`'s `g_host_party_level == level` test failed and
  the world was rebuilt from the guest's own live party (BOY2/GIR2).
* OBSERVED: `guest: host party applied at level I100` never appears in the guest log; `stored` keeps
  repeating afterwards because the host's progress character block changes (~4/s), which matches the
  reviewer's 236 lines.
* DERIVED: the two packets that matter for a level change are sent in order by the host
  (`host_send_progress(1)` then `net_send_req(REQ_LEVEL)`, src/sync.c `host_watch_level` /
  `host_repeat_tick`), but the relay's jitter (20 ms in this scenario) delivered the request FIRST.
  This is exactly PARTY_FINDINGS 4.8.
* DERIVED: the race in this run was only 15 ms wide. Holding the level request until the stash is
  present would have fixed it without any other change.

## 2. Change implemented (src/sync.c, src/hooks.c)

1. `guest_apply_requests` (src/sync.c): a `REQ_LEVEL` is now deferred while `g_role == 2` and the stash
   is not valid for the requested level. The request is moved to the tail of the request ring so the
   other kinds (LoadProgress / LoadByName / ToMenu) are still applied while it waits; it is retried on
   every frame tick. After `REQ_LEVEL_PARTY_WAIT` (3000 ms, measured from the tick at which the request
   was first queued, stored in `g_req_seen[]`) it is applied anyway - the old behaviour - and logged.
   One loop pass per call (`looked_at`) prevents a ring of only deferred requests from spinning.
2. Logs: `guest: level request %s deferred: waiting for the host party (up to 3000 ms)`, and on release
   either `... released after %u ms: host party arrived` or `... released after %u ms: no host party for
   it, the guest keeps its own` (timeout fallback).
3. Stash ordering: `g_lvl_req_want` is the level of the newest level request (set in `guest_on_req`).
   `guest_on_region` no longer lets a packet for another level overwrite a stash that already matches
   `g_lvl_req_want` (one log line per ignored level). The stash is now read/written through
   `guest_party_ready` / `guest_party_copy` under `g_reg_cs`, so `hk_party_table` (main thread) never
   copies a table the UDP thread is halfway through writing (PARTY_FINDINGS 4.8).
4. Host: `REQ_REPEAT_FOR` 1500 -> 3500 ms so the repeat window (each repeat preceded by
   `host_send_progress(1)`) covers the guest's 3 s wait. The applied-duplicate window
   (`REQ_LEVEL_DONE_MS`) is now 4500 ms so the longer repeat tail is still suppressed.
5. The region ring grew 16 -> 64 slots (`REG_Q_SIZE`): with a deferred level request the guest cannot
   apply progress chunks for longer, so more of them queue up.
6. No packet layout changed: `NET_VERSION` stays 6.

DERIVED consequences to watch in the live runs: the guest now changes level only once the host's own
level change has produced the new progress block, i.e. its level change starts ~(host load time) later
than before. The host "player 2 is joining" auto-accept pulse (+4.5 s after a host load/change level)
is unchanged; if the guest's later arrival misses it, that would show as a join/timeout failure, not a
party mismatch.

## 3. Verification

### 3.1 Live runs (5 of the 5 allowed; all foreground, each ended with no process left)

| # | command | result | deferral line |
|---|---------|--------|---------------|
| 1 | `sh tests/run_chaos.sh <chk.dll> 60 20 5 --save-xfer` | PASS, CONVERGED 4.2 s, all five checks OK | no (stash +0.07 s, request +0.08 s) |
| 2 | `sh tests/run_chaos.sh <chk.dll> 60 20 5 --save-xfer` | PASS, CONVERGED 4.2 s, all five checks OK | no (stash +0.07 s, request +0.09 s) |
| 3 | `sh tests/run_chaos.sh <chk.dll> 100 40 10 --save-xfer` | PASS, CONVERGED 0.0 s, all five checks OK | no (stash +0.12 s, request +0.13 s) |
| 4 | `sh tests/run_pair.sh <chk.dll> check_party.py check_items.py check_hands.py` | party OK, items OK, hands OK | clean link, not expected |
| 5 | `sh tests/run_chaos.sh <chk.dll> 0 250 0 --save-xfer` | PASS, CONVERGED 4.2 s, all five checks OK | no (stash +0.03 s, request +0.23 s) |

The guest log of every run contains `guest: host party applied at level I100: first character BOY1`
and no `deferred` / `released` / `ignored, keeping` line.

OBSERVED: the deferral branch did not run in any live run. In all five the host's party packet won the
race (by 7-200 ms), so the guest applied the level request immediately, exactly as before the change.
The reviewer's failing log (§1) has the opposite order with a 15 ms margin; replaying that timestamps
against the new code (DERIVED): at 23:49:41.928 the stash for I100 is not there yet
(`g_host_party_level` is still B101), so the request is deferred and re-checked every frame; at
41.943 the first I100 stash is stored, `guest_party_ready(I100)` becomes true, and the next frame tick
releases and applies it - 15-30 ms later than the old code, with the host party in place. That is the
one gap in the live evidence: the branch is not observed, only replayed.

### 3.2 Offline test of the exact queue text

Because the live budget was spent without hitting the race (it is a ~30-50 % per-run coin flip, and the
host sends the party packet 2-3 times per level request), the two functions under test were extracted
**verbatim** from `src/sync.c` (everything from `static CRITICAL_SECTION g_req_cs;` up to
`// ---- independent camera (guest)`) into a console harness with stubs for `game_obj`/`rd32`/
`world_obj`/`guest_party_ready`/`logf`/`tag4`/the four game request functions and a controllable clock.
Result (scratch file in `$TMPDIR`, not committed):

```
1. level request waits for the host party, then goes
  ok   request queued
    log: guest: level request I100 deferred: waiting for the host party (up to 3000 ms)
  ok   not applied without the party table
  ok   marked deferred
    log: guest: level request I100 released after 10 ms: host party arrived
    log: guest: host ChangeLevel I100 entry 1120 flag 1
  ok   applied once the table arrived
  ok   queue drained
  ok   deferral flag cleared
2. the host's repeats are dropped while it waits and after it applies
  ok   duplicate while queued dropped
    log: guest: level request I200 deferred: waiting for the host party (up to 3000 ms)
  ok   still waiting
  ok   repeat while waiting dropped
    log: guest: level request I200 released after 410 ms: host party arrived
    log: guest: host ChangeLevel I200 entry 5 flag 1
  ok   applied after 410 ms
  ok   repeat after applying dropped
3. other request kinds are not blocked by the wait
    log: guest: level request I100 deferred: waiting for the host party (up to 3000 ms)
    log: guest: host LoadProgress 1
  ok   LoadProgress applied while the level request waits
  ok   level request still held
  ok   level request still queued
    log: guest: level request I100 released after 20 ms: host party arrived
    log: guest: host ChangeLevel I100 entry 7 flag 1
  ok   released when its table arrived
4. the timeout falls back to the old behaviour
    log: guest: level request I200 deferred: waiting for the host party (up to 3000 ms)
  ok   held at 0 ms
  ok   held at 2999 ms
    log: guest: level request I200 released after 3000 ms: no host party for it, the guest keeps its own
    log: guest: host ChangeLevel I200 entry 9 flag 1
  ok   applied at 3000 ms without the table
  ok   deferral flag cleared after the timeout
5. the stash target follows the newest level request
  ok   newest requested level remembered
  ok   updated by the newer request

ALL PASSED (0 failures)
```

## 4. Open items

* UNKNOWN: whether a level change that is started while the host is still loading (the in-game
  `ChangeLevel` path, not the save-load path) always produces the new progress block inside the 3.5 s
  repeat window. If it does not, the guest falls back to its own party and logs the timeout line.
* UNKNOWN: the auto-accept pulse interaction noted above (only a live run can tell; all five runs
  converged and the clean-loopback party/items/hands checks pass, so it did not break anything that
  was exercised).
* GUESS: the 64-slot region ring is enough for the worst case (3.5 s of forced progress resends while
  the guest waits and then loads); if a check still sees stale story data, the ring is the first thing
  to look at (packets are dropped, not overwritten, when it is full).
* DERIVED, accepted trade-off: while a level request waits, a request of another kind that arrives
  behind it is applied first (the level request is moved to the tail). Before the change the queue was
  strictly FIFO. A host `ToMenu` sent within those 3 s would therefore reach the guest before the
  pending level change; the task explicitly asked not to block the other kinds.
* Note on the code/test timeline: the single-queued-request case of the deferral was simplified after
  the five live runs (it no longer rotates the request to the tail when it is the only one), because
  rotating 8x per tick was pointless. No live run ever entered that branch; the offline test in 3.2
  was run on the final text and the rebuild used the final source.
* The full live-run logs of the last run are in `local/obscure2-test/obscoop.log` and
  `local/obscure2-test2/obscoop.log`; the harness output of each run is in `$TMPDIR/run{1..5}.log`
  (session scratch, removed with the session).
