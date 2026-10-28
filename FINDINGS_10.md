# TASK 10 findings: forcing and proving the "wait for the host's party table" fix

Status labels: OBSERVED = read from a log/memory this session; DERIVED = follows from code (src/*.c line) or
decompile with the address named; GUESS = plausible but untested; UNKNOWN = not established.

This file was started before the first live run (§4 is filled in afterwards).

## 1. Review of the task-9 diff (`git diff` against HEAD, src/hooks.c + src/sync.c)

### 1.1 What the diff does

* `guest_apply_requests` holds a `REQ_LEVEL` back while the guest's stash has no party table for that level,
  retries it every frame, and applies it after `REQ_LEVEL_PARTY_WAIT` (3000 ms) anyway.
* Host repeat window `REQ_REPEAT_FOR` 1500 -> 3500 ms; the guest's applied-duplicate window 2500 -> 4500 ms.
* Region ring 16 -> 64 slots. Stash access under `g_reg_cs`.
* No packet layout changed: `NET_VERSION` stays 6 (DERIVED: no field in any `pkt_*` struct in src/net.c changed).

### 1.2 Bugs found and fixed

**(a) The "stale stash" guard dropped the NEXT level's party table (real, would have delayed every level
change after the first by >= 250 ms and made the deferral branch the normal path).**
The task-9 code kept one stash plus `g_lvl_req_want` and ignored any incoming table for a level other than
`want` once the stash already matched `want`:

```c
if (g_host_party_valid && want && g_host_party_level == want && r->level != want) { stale = 1; ... }
```

The host sends `host_send_progress(1)` BEFORE the level request (src/sync.c `host_watch_level`,
`host_welcome_guest`). In the common order (table first, request second - the order task 9 measured in all
five of its runs) `want` is still the OLD level when the NEW table arrives, the stash matches `want`, so the
new table was classified as stale and thrown away. Only the next 250 ms repeat would store it, so every
level change after the first would have waited ~250 ms and logged "deferred". In a lossy run whose repeat
is lost too, the wait could reach the 3 s timeout. The guard cannot tell a late packet of the old level
from an early packet of the new one, which is why it cannot be fixed by tuning: there is no ordering field
in `pkt_region` (`src/net.c:35-36`, only `h.seq`, which the guest does not use for this).
Fix: the stash is now ONE SLOT PER RECENT LEVEL (4 slots, 0x140 bytes each, `src/sync.c` `PARTY_SLOTS`).
`party_store` overwrites the slot of the same level or takes the next one round-robin; `guest_party_ready`
and `guest_party_copy` look the level up. A reordered old table now cannot touch the new one, and a table
that arrives before its request is usable, so the `want`/`stale` machinery and its log line are gone.

**(b) The party wait clock started while the guest was still loading.** `g_req_seen[]` was stamped when the
packet was queued; the `REQ_LEVEL` branch returns early (without touching the clock) until the guest's world
exists. A guest that takes > 3 s to load would therefore enter the new branch with `waited > 3000` already
and apply at once without ever waiting - the old behaviour, but not the intended one.
Fix: the branch that waits for the world now re-stamps `g_req_seen[head] = GetTickCount()`.

**(c) Checked, not changed:** queue rotation (`looked_at` one-pass bound, `only_one` case, ring full case -
7 entries max, rotation keeps the count), duplicate suppression (queued copy + 4500 ms applied window vs the
3500 ms repeat window: the last repeat is at +3500, so it is always inside the 4500 ms window), lock order
(`g_req_cs` -> `g_reg_cs` in `guest_apply_requests`; nothing takes them the other way round, `hk_party_table`
runs after `g_req_cs` is released), and `hk_party_table`'s copy (now under `g_reg_cs` through
`guest_party_copy`; the old direct read of the 0x140-byte stash could tear).

**(d) Kept from task 9:** the 64-slot region ring (DERIVED from the 3.5 s repeat window: a forced send is
~6 packets at 250 ms = ~24/s while the guest queues), `REQ_REPEAT_FOR` 3500 (covers the 3000 ms wait plus one
repeat interval), `NET_VERSION` 6.

Files touched: `src/sync.c` (queue + stash + test knob), `src/hooks.c` (the three stash globals moved into
sync.c; `hk_party_table` already used `guest_party_copy`).

## 2. TEST-ONLY knob: `OBSCOOP_TEST_DELAY_PROGRESS_MS`

DERIVED from src/sync.c `test_delay_progress_init` / `test_hold_party` / `host_send_progress`:

* read once in `sync_init`; 0/unset = the hook is a no-op (two `if` checks on a zero global);
* host only (`g_role == 1`), armed at the two places that send a level request (`host_watch_level`,
  `host_welcome_guest`) just before `host_send_progress(1)`;
* while armed, `host_send_progress` still sends the story-entity blocks but returns before the
  `PROG_CHR_OFF` (party) block until the window expires - so the level request overtakes the party table,
  which is exactly the race this task must exercise;
* logs `host: TEST holding the party block back for <ms> ms ...` and
  `host: TEST delay over after <n> ms, sending the party block`.

How to run (the env is inherited by `duo.py`, which passes `dict(os.environ, ...)` to the game process):
`OBSCOOP_TEST_DELAY_PROGRESS_MS=1200 sh tests/run_pair.sh <chk.dll> check_party.py check_hands.py`
Documented in tests/README.md.

## 3. Predictions (written before the live runs; DERIVED)

* 1200 ms run: guest log shows `guest: level request I100 deferred waiting for the party (up to 3000 ms)`,
  then `guest: level request I100 released after ~1.2-1.5 s: host party arrived`, then
  `guest: host party applied at level I100: first character ...`; `check_party.py` and `check_hands.py` pass.
* 4500 ms run: `released after 3000 ms: no host party for it, the guest keeps its own`; the party may
  legitimately differ between the copies; no crash, both worlds up, the run must not hang.
* clean run_pair + chaos: no deferral line (the table wins the race), checks pass, no regression.

## 4. Live runs (4 of the 6 allowed; every one foreground, each ended with no game/relay left)

### 4.1 Run 1 - the proof: `OBSCOOP_TEST_DELAY_PROGRESS_MS=1200 sh tests/run_pair.sh <chk.dll> check_party.py check_items.py check_hands.py`

OBSERVED, harness output (trimmed to the result lines):

```
guest sync role guest sent 0 recv 343 applied 686 snaps 0 blends 0 skipped_level 0 timed 204 req_sent 1 I100
== check_party.py
party: host ['BOY1', 'GIR1'] guest ['BOY1', 'GIR1'] | inventory: host 44 guest 44
party OK
== check_items.py
items: before host 44 guest 44
items: after host 45 guest 45
items OK
== check_hands.py
host humans:  [('BOY1', ['CBOW', 'TASE', 'UBET', 'DYNA'], 0), ('GIR1', ['SHOT', '47554e00', 'CSAW', 'FLBA'], 2)]
guest humans: [('BOY1', ['CBOW', 'TASE', 'UBET', 'DYNA'], 0), ('GIR1', ['SHOT', '47554e00', 'CSAW', 'FLBA'], 2)]
in hand: host [('BOY1', 'CBOW'), ('GIR1', 'CSAW')] guest [('BOY1', 'CBOW'), ('GIR1', 'CSAW')]
hands OK (2 characters checked)
still running: []
OWNER FILES UNCHANGED (apart from Steam remotecache.vdf)
```

OBSERVED, host log (`local/obscure2-test/obscoop.log`):

```
00:23:19.598 [25372] request LoadByName "game0.sav" [mode 1]
00:23:19.714 [25372] host: level is now I100 without a ChangeLevel request (load or new game), telling the guest (entry 1120)
00:23:19.714 [25372] host: TEST holding the party block back for 1200 ms (the level request goes now)
00:23:20.961 [25372] host: TEST delay over after 1250 ms, sending the party block
```

OBSERVED, guest log (`local/obscure2-test2/obscoop.log`) - the deferral branch runs for the first time in
any live run of this worktree:

```
00:23:19.601 [5676] guest: host LoadByName "game0.sav"
00:23:19.717 [5676] guest: level request I100 deferred waiting for the party (up to 3000 ms)
00:23:20.961 [34044] guest: host party stored at level I100: first character BOY1
00:23:20.965 [5676] guest: level request I100 released after 1250 ms: host party arrived
00:23:20.965 [5676] guest: host ChangeLevel I100 entry 1120 flag 1
00:23:20.967 [5676] guest: host party applied at level I100: first character BOY1
```

OBSERVED: one single `host ChangeLevel I100` line although the host repeated the request every 250 ms for
3.5 s (~5 copies while it waited) - the duplicate suppression holds. The guest waited 1250 ms: the party
block arrived 1247 ms after the request, and the level change started 4 ms after the table was stored. The
22000 ms "TEST delay over" line earlier in the host log belongs to the hold armed by the join
(`host_welcome_guest`) while there was no world and therefore no party block to send; cosmetic only.

### 4.2 Run 2 - the timeout fallback: `OBSCOOP_TEST_DELAY_PROGRESS_MS=4500 sh tests/run_pair.sh <chk.dll> check_party.py check_items.py check_hands.py`

OBSERVED, harness output:

```
== check_party.py
party: host ['BOY1', 'GIR1'] guest ['BOY2', 'GIR2'] | inventory: host 44 guest 44
Traceback (most recent call last):
  File "...\tests\check_party.py", line 24, in <module>
    assert ph and ph == pg, 'parties differ'
AssertionError: parties differ
== check_items.py
items: before host 44 guest 44
items: after host 45 guest 45
items OK
== check_hands.py
host humans:  [('BOY1', ['CBOW', 'TASE', 'UBET', 'DYNA'], 0), ('GIR1', ['SHOT', '47554e00', 'CSAW', 'FLBA'], 2)]
guest humans: [('BOY2', ['-', '-', '-', '-'], 0), ('GIR2', ['-', '-', '-', '-'], 0)]
...
AssertionError: the weapon in the hand differs
still running: []
OWNER FILES UNCHANGED (apart from Steam remotecache.vdf)
```

OBSERVED, host log:

```
00:25:03.883 [33964] host: level is now I100 without a ChangeLevel request (load or new game), telling the guest (entry 1120)
00:25:03.883 [33964] host: TEST holding the party block back for 4500 ms (the level request goes now)
00:25:08.381 [33964] host: TEST delay over after 4500 ms, sending the party block
```

OBSERVED, guest log:

```
00:25:03.887 [8764] guest: level request I100 deferred waiting for the party (up to 3000 ms)
00:25:06.884 [8764] guest: level request I100 released after 3000 ms: no host party for it, the guest keeps its own
00:25:06.884 [8764] guest: host ChangeLevel I100 entry 1120 flag 1
00:25:08.381 [32736] guest: host party stored at level I100: first character BOY1
```

OBSERVED: the timeout fires at exactly 3000 ms, the guest changes level with its own party (BOY2/GIR2, the
new-game party), and the late host table (4500 ms) is stored afterwards without crashing or hanging anything.
Both copies stay alive and the run ends cleanly (games stopped, owner files unchanged). The two failed
checks are the legitimate consequence named in the task: the guest spawned its own party, so `check_party`
sees BOY1/GIR1 vs BOY2/GIR2 and `check_hands` finds no weapons on the guest's own new-game characters.
`check_items` (44/44 -> 45/45) still passes: inventory sync is independent of the party table.

### 4.3 Run 3 - clean regression: `sh tests/run_pair.sh <chk.dll> check_party.py check_items.py check_hands.py`

OBSERVED: `party OK`, `items OK`, `hands OK (2 characters checked)`, `still running: []`,
`OWNER FILES UNCHANGED`. Guest log after the anchor - no deferral, the table wins the race by 5 ms:

```
00:26:43.911 [12984] guest: host party stored at level I100: first character BOY1
00:26:43.916 [36444] guest: host ChangeLevel I100 entry 1120 flag 1
00:26:43.919 [36444] guest: host party applied at level I100: first character BOY1
```

`grep -a 'deferred\|released'` on the guest log printed nothing. This is also the path that task 9's
stale-stash guard would have broken on a second level change (see 1.2a) - here `want` was still 0 (the first
level of a game is not announced), so the old code would have behaved the same; the multi-slot stash is
nevertheless what keeps the "table first" order working after the first announced change.

### 4.4 Run 4 - chaos regression: `sh tests/run_chaos.sh <chk.dll> 60 20 5 --save-xfer`

OBSERVED (abridged to the result lines; the full output was 102 lines):

```
== waiting up to 60 s for convergence
host : level I100 inv 44 party ['BOY1', 'GIR1'] (mode 1 state 0) hands [...]
guest: level I100 inv 44 party ['BOY1', 'GIR1'] (mode 1 state 0) hands [...]
CONVERGED after 4.2 s (level I100, inventory 44, party ['BOY1', 'GIR1'])
== check_save.py
save: host I100 44 guest I100 44
save OK
== check_party.py
party: host ['BOY1', 'GIR1'] guest ['BOY1', 'GIR1'] | inventory: host 44 guest 44
party OK
== check_hands.py
hands OK (2 characters checked)
== check_items.py
items: before host 44 guest 44
items: after host 45 guest 45
items OK
== check_savexfer.py
... all ten gameN.sav hashes identical (host == guest)
save transfer OK
-- guest timeline:
  level request reaches the guest        +0.09 s  00:28:28.630 guest: host ChangeLevel I100 entry 1120 flag 1
  host party stored on the guest         +0.09 s  00:28:28.630 guest: host party stored at level I100: first character BOY1
  host party applied at the level change +0.10 s  00:28:28.631 guest: host party applied at level I100: first character BOY1
remaining Obscure2.exe: 0, obscoop-relay.exe: 0
=== chaos run lag60-jit20-loss5: PASS
```

### 4.5 Budget

Four live runs used (6 allowed): 1200 ms proof, 4500 ms timeout, clean pair, chaos 60/20/5 + save transfer.
No run had to be repeated (no startup flake).

## 5. DONE / NOT DONE / UNKNOWN

DONE
* Reviewed the task-9 diff; found and fixed two bugs (stale-stash guard dropping the next level's party
  table; party-wait clock starting while the guest was still loading) and kept the lock discipline
  (`g_req_cs` -> `g_reg_cs`, `hk_party_table` copies under the lock).
* Added the TEST-ONLY `OBSCOOP_TEST_DELAY_PROGRESS_MS` host knob (no effect unless set) and documented it in
  tests/README.md.
* Proved the wait branch live: 1250 ms deferral, release, `host party applied at level I100`, party/items/
  hands checks OK (4.1).
* Proved the timeout fallback live: release at exactly 3000 ms with the fallback log, no crash, no hang (4.2).
* Clean regression run_pair (party/items/hands) and chaos 60/20/5 with save transfer: both PASS (4.3, 4.4).
* Compiles with `-O2 -Wall`; only the three expected old warnings (tick, watch_start, request_shot).
  `NET_VERSION` stays 6 (no packet layout changed).

NOT DONE
* No live run exercised the request-queue ROTATION (a deferred level request moved behind another request
  kind): in these flows the level request is alone in the queue at that moment. The rotation code is
  unchanged from the version task 9 tested offline; my only edit in that loop is the re-stamp and the log
  wording.
* Bug 1.2(a) is fixed by review only, not observed: all four runs contain a single announced level change
  (the first level of a game is not announced), which is the case where the old guard did not trigger.
  Triggering it needs a second announced level change in one session (host loads another save) - not part of
  the harness, and requesting a level tag the game did not produce is forbidden.

UNKNOWN
* Whether the late host party table that lands after a timeout fallback (4.2) can make the guest's next save
  inconsistent (PARTY_FINDINGS 4.9) - not checked by any script here.
* How many region packets the 64-slot ring actually drops in the worst case (4500 ms hold); the guest's logs
  do not report a drop counter. Nothing visible went stale in run 2 (the level change and the item checks
  were unaffected).
* GUESS: on a real (not loopback) link with loss, a lost party block could push the deferral to the 3 s
  timeout even though the host repeats it; the repeat window (3500 ms) covers the wait plus one repeat, which
  would need two lost copies in a row.

Working tree: `src/hooks.c`, `src/sync.c`, `tests/README.md` modified, `chk.dll`, `FINDINGS_9.md`,
`FINDINGS_10.md`, `TASK*.md`, `tests/duo_*.pid` untracked, two `tests/__pycache__/*.pyc` files already
modified before this task. Nothing committed or pushed.
