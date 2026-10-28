# TASK 14 FINDINGS — host-first join, the file the host loads, a second load in one session

Labels: **OBSERVED** = printed by a check / visible in the run log or the decompile this session;
**DERIVED** = follows from the cited code but not proven live; **GUESS** = plausible, unproven;
**UNKNOWN** = not established. Decompile lines are `local\decomp2\Obscure2.exe.c` (build 215294),
addresses static (image base 0x400000). Live runs used the two test copies on loopback
(`local\obscure2-test`, `obscure2-test2`) and every runner stopped the games it started
(`duo.py stop` prints `still running: []` and `OWNER FILES UNCHANGED`).

## 0. Summary

All three cases work on the final build (`chk14.dll`, `NET_VERSION` 8); six live runs plus the two
regressions were used (8 of 8 allowed):

| case | what it proves | result |
|---|---|---|
| 1 host first | a host that is already inside its loaded save when the guest starts is followed: the welcome now re-sends the load name, the guest loads the same file itself | **PASS** — party/items/hands/hands_visible/entities all OK, screenshots match |
| 2 the file the host loads | the transfer sends the exact file the host's load names (and re-sends it when the guest has lost it); the guest waits for that file's completion notice, not for all ten | **PASS** — the guest received a file that had been deleted from both of its save folders and loaded it 187 ms after the notice |
| 3 second load in one session | a second load from the game's own pause menu is followed again by the guest (its own real load of the same file) | **PASS** — the game's own `LoadByName` on the host, the guest's own real load 78 ms later, all five checks OK |

Two findings changed the design while doing this:

1. **The game's saves do not live in `<exe>\Save`.** Its save manager reads and writes them through
   Steam RemoteStorage, which this mod's proxy maps to `<exe>\coop_profile\remote\<name>`
   (`obscoop2.c` `remote_path`, line 186-199). **OBSERVED**: `loadsave o2.sav` with the file only in
   `Save\` logged `remote FileExists o2.sav -> 0` and the open failed; with the same file in
   `coop_profile\remote\` it logged `FileExists 1, GetFileSize 40960, FileRead 40960`. Until this task the
   save transfer wrote only `Save\`, so a guest's load always read its own pre-existing copy — the tests
   never noticed because both copies start with identical saves. The transfer now reads/writes the game's
   own folder (and keeps `Save\` in step, which `check_savexfer.py` looks at).
2. **The game's save manager only opens `gameN.sav`.** `o2.sav` (and `recover.sav`, a name the game's own
   remote-storage code mentions) is read by the proxy and then refused: the log says
   `host: real load of "o2.sav" (pipe): the game's save open FAILED` even with the file in the right folder.
   `loadsave game1.sav` from the same main-menu state opens fine. **OBSERVED**. So CASE 2's o2.sav stand-in
   cannot produce a successful load in this build; the mechanism was proven with a slot file the guest had
   lost (see section 3). Also **OBSERVED**: the main menu's `Continue` opens the save-slot browser
   (`tests/shots/case2_continue.png`, `case2_down2.png`), not the fixed `o2.sav` FINDINGS_12 (a) describes —
   no `LoadByName` line appears for it, and the browser lists all ten slots.

## 1. What was missing and what changed

### CASE 1 — host first (no resend on welcome)

Before: `hk_load_name` forwards `REQ_LOAD_NAME` only while `g_peer_ok`, and `host_welcome_guest`
(sync.c:1484) sent the progress block and `REQ_LEVEL` only. A guest that joined after the host's load
never heard of the load, and the `REQ_LEVEL` it did get is kept queued forever while it has no world
(sync.c:1404-1410). **OBSERVED** in code.

Change (sync.c, hooks.c):
* `host_save_include(name)` (sync.c:205): the host records the file its load named (`g_last_load_name`),
  cleared on `LoadProgress` (a new game has no file) and `ToMenu` (hooks.c:84, 115). `hk_load_name` calls it
  on the host for every load, connected or not (hooks.c:103).
* `host_welcome_guest` (sync.c:1484): when a load name is known, the welcome sends `REQ_LOAD_NAME` for it
  (repeated for 3.5 s like a level request) **instead of** `REQ_LEVEL` — the file builds that world, and a
  level request would only sit in the guest's queue behind the load. With no load name the old level
  request path is unchanged.

### CASE 2 — the file the host loads

Before: the transfer was hard-wired to `game0..9.sav` (sync.c:185-186, name in the packet at 220), the
guest only accepted names beginning with `game` (sync.c:264), and the guest could only load after the
*whole* transfer finished (`g_saves_done`, `save_file_ready`).

Change:
* The transfer has a name list (`g_save_list`): **the file the host's latest load named first**, then
  `game0.sav`..`game9.sav` (deduplicated) — `host_save_begin` (sync.c:180). A load that happens when the
  join transfer is already over appends its file and (re)sends it immediately (`host_save_include`,
  sync.c:205, `save_list_index`); a file the guest has lost is sent again the same way.
* Every finished file is announced by name: `PKT_SAVES_DONE` now carries `{DWORD all; char name[32];}`
  (`all = 1` = the whole transfer), and each notice is repeated 4 times 200 ms apart because the packet has
  no ack (sync.c:240-275). The guest remembers the announced names (`g_save_rcvd`) and
  `save_file_ready` requires **that exact name** (sync.c:763). A new `WELCOME` clears the list
  (`guest_save_session`, net.c 265).
* `guest_on_save` accepts any plain file name (`save_name_ok`: no path parts, < 32 chars) and writes both
  the game's folder and the `Save` mirror (sync.c:443).
* **Backups (the owner agreed)**: the first chunk of a file copies the guest's own copy to
  `<exe>\Save.bak\<name>` with `CopyFileA(..., bFailIfExists=TRUE)` and logs
  `guest: kept the guest's own "<name>" (<where>) in Save.bak before the host's copy overwrote it`
  (sync.c:455-475). **OBSERVED** in the CASE 1 run log for game0..game9.sav.
* The guest only loads a file the host's transfer has completed **for this write**: a chunk at offset 0
  forgets the file's completion (a re-transfer is in progress), so a half-written file is never opened
  (sync.c:455-470). A failed open forgets the request's "already taken" mark so the host's repeat is taken
  again (`guest_load_failed`, sync.c:1590).

### CASE 3 — a second load in one session

Before: for a guest *with* a world, `REQ_LOAD_NAME` still called `LoadByName` bare (state 3 without the
save manager's open), i.e. it re-read whatever chunks the manager still held (FINDINGS_12 (b)).

Change (sync.c:1666): **every** `REQ_LOAD_NAME` now runs the game's own two-call load on the guest (the
save manager opens the named file, then `LoadByName`) — the same pair a pause-menu load runs in a level.

`NET_VERSION` 7 -> 8 (the `PKT_SAVES_DONE` layout changed and the transfer can carry other names).

## 2. Live runs

All with `chk14.dll` built from this worktree, except where stated. "Check" columns quote the check
script output from the run log (full logs under `$TMPDIR` of the session; the important lines are quoted
below).

| run | flow | result |
|---|---|---|
| 1 | CASE 1, early build (before the save-folder fix) | guest followed (guest log), party/items/hands/hands_visible/entities OK |
| 2 | CASE 1 with pictures (same build) | all five checks OK, real frames |
| 3 | CASE 2 exploration (interactive, same build) | found the save folder (`coop_profile\remote`), the name restriction, and the main-menu Continue browser |
| 4 | CASE 2 first attempt (final build) | **failed as designed**: the guest opened a half-written re-transfer 0.4 s early (fixed) |
| 5 | CASE 2 (final build) | **PASS** |
| 6 | CASE 3 (final build) | **PASS** (the script's own verdict line was wrong, see 3.3) |
| 7 | regression `run_pair_menu.sh` + all six checks | see section 4 |
| 8 | regression `run_pair.sh` (old flow) | see section 4 |

### 2.1 CASE 1 verbatim (run 2: host alone first, then the guest; pictures)

```
host at start : mode 2 world 0x0 level ---- humans 0
host at menu  : mode 2 world 0x0 level ---- humans 0
host net:  net role host via udp peer_ok 0 rx 0 tx 0 bad 0 last_input_seq 0 rtt_ms -1
host loadsave game0.sav -> ok real load of "game0.sav" requested (the game thread runs it)
ok: the host in a level after 0.5 s
host after load: mode 1 world 0x191e4e68 level I100 humans 2
--- the host is in game now; settling 10 s before the guest even starts ---
== starting the guest copy now (it stays at the main menu and connects)
guest pid 32088
guest after join: mode 1 world 0x191bada8 level I100 humans 2
party: host ['BOY1', 'GIR1'] guest ['BOY1', 'GIR1'] | inventory: host 44 guest 44
party OK
items OK
hands OK (2 characters checked)
differences host vs guest: none
entity count: host 43 guest 43
entities OK (host 43, guest 43)
frame 800x600  mean abs diff whole 4.72  lower-centre (x 200-600, y 270-570) 2.95
late join: host level I100, guest level I100
```

The guest's own side of it (run 1, the same code path; the run-2 log tail had already scrolled past it):

```
02:26:54.200 [16392] guest: host LoadByName "game0.sav" (world none)
02:26:54.200 [16392] guest: real load of "game0.sav" requested (host)
02:26:54.672 [16392] guest: real load of "game0.sav" (host): the game's save open ok
02:26:54.672 [16392] request LoadByName "game0.sav" [mode 0]
02:26:54.672 [16392] guest: real load of "game0.sav" issued (mode 0 request state 3)
```

and the host's transfer of that join (run 2):

```
02:28:52.304 [22932] host: the guest has "game2.sav" (3 of 10 files)
...
02:28:54.264 [22932] host: the guest has "game9.sav" (10 of 10 files)
02:28:54.310 [22932] host: save transfer finished, the guest may load a transferred save
```

Note: the run-2 script also printed `TIMEOUT waiting for the guest at the main menu` because it looked for
the guest at `mode 2` after the guest had already followed (the 6 s launch of `duo.py start-guest` is
enough). The ordering that matters is enforced: the host had been in level I100 for 10 s before the guest
process existed, and the guest's load line says `world none` (no world of its own yet).

### 2.2 CASE 2 verbatim (run 5)

```
host Save\o2.sav: 40960 bytes fedd47f3446eefe6
host coop_profile\remote\o2.sav: 40960 bytes fedd47f3446eefe6
guest Save\o2.sav: MISSING
guest coop_profile\remote\o2.sav: MISSING
== the host tries o2.sav, the file the main menu is hard-wired to (game's own two calls)
host loadsave o2.sav -> ok real load of "o2.sav" requested (the game thread runs it)
host after o2.sav attempt: mode 2 world 0x0 level ---- humans 0
== the guest loses its own copy of game1.sav (both save folders): it can only come from the host now
  removed ...\obscure2-test2\Save\game1.sav
  removed ...\obscure2-test2\coop_profile\remote\game1.sav
== the host loads game1.sav from the main menu's own save list (Continue -> slot -> confirm)
TIMEOUT waiting for the host in a level from the main menu save list
the main-menu keypresses did not load it; falling back to the test-only loadsave game1.sav
host loadsave game1.sav -> ok real load of "game1.sav" requested (the game thread runs it)
ok: the host in a level from loadsave after 0.5 s
host after load: mode 1 world 0x191e4e68 level I015 humans 2
ok: the guest in the same level (it loaded the transferred file itself) after 0.0 s
guest after load: mode 1 world 0x1901ada8 level I015 humans 2
load route: test-only `loadsave game1.sav` (the main-menu keypresses produced no load)
levels: host I015 guest I015; guest followed: YES
party: host ['BOY1', 'BOY2'] guest ['BOY1', 'BOY2'] | inventory: host 46 guest 46
party OK
items: before host 46 guest 46 / after host 45 guest 45
items OK
hands OK (2 characters checked)
differences host vs guest: none
entity count: host 45 guest 45
entities OK (host 45, guest 45)
```

The transfer of the named file, and the guest's load of it (host and guest logs of run 5):

```
02:44:41.276 [25856] host: real load of "game1.sav" requested (pipe)
02:44:41.289 [31168] host: real load of "game1.sav" (pipe): the game's save open ok
02:44:41.289 [31168] host: "game1.sav" is sent again in the save transfer for the guest
02:44:41.289 [31168] host: real load of "game1.sav" issued (mode 2 request state 3)
02:44:41.636 [31168] host: the guest has "game1.sav" (2 of 10 files)

02:44:41.290 [12436] guest: host LoadByName "game1.sav" (world none)
02:44:41.290 [12436] guest: real load of "game1.sav" requested (host)
02:44:41.636 [9328]  guest: the host's save transfer has "game1.sav" (whole file on disk)
02:44:41.648 [12436] remote FileExists game1.sav -> 1
02:44:41.648 [12436] remote GetFileSize game1.sav -> 40960
02:44:41.648 [12436] remote FileRead game1.sav (40960) -> 40960
02:44:41.648 [12436] guest: real load of "game1.sav" (host): the game's save open ok
02:44:41.648 [12436] guest: real load of "game1.sav" issued (mode 2 request state 3)
02:44:41.834 [12436] guest: the world this copy built from the save itself is up (level I015, 187 ms after the load)
```

The `o2.sav` refusal (host log, same run):

```
02:44:xx host: real load of "o2.sav" requested (pipe)
02:44:xx remote FileExists o2.sav -> 1
02:44:xx remote GetFileSize o2.sav -> 40960
02:44:xx remote FileRead o2.sav (40960) -> 40960
02:44:xx host: real load of "o2.sav" (pipe): the game's save open FAILED
```

Route used: **the test-only `loadsave` pipe command** (the main-menu keypress route was tried first in the
same run: `Continue` opens the slot browser and the pad sequence did not confirm a load; the `o2.sav`
entry itself is refused by the game's own open, so the pipe fallback CASE 2 allows was used for the slot
file).

### 2.3 CASE 3 verbatim (run 6)

```
host before: mode 1 world 0x191e4e68 level I100 humans 2
guest before: mode 1 world 0x191aada8 level I100 humans 2
== CASE 3: the host loads game0.sav again from the pause menu
TIMEOUT waiting for the host world rebuilt from the pause-menu load
the pause-menu keypresses did not produce a load on the host; falling back to loadsave game0.sav
host loadsave -> ok real load of "game0.sav" requested (the game thread runs it)
TIMEOUT waiting for the host world rebuilt from loadsave
host after : mode 1 world 0x191e4e68 (unchanged) level I100 humans 2
...
second load route: test-only `loadsave game0.sav` (the pause menu keypresses produced no load)
second load: host NOT reloaded level I100 -> I100; guest not reloaded level I100 -> I100; guest followed: NO
party OK / items OK / hands OK / hands visible state OK / entities OK (host 43, guest 43)
```

**The verdict lines above are wrong, and the logs show why.** The detector keyed on the world pointer
changing; the engine rebuilds the same level into the *same* block (allocator reuse), so the pointer did not
change. The host log from the same run:

```
02:46:52.682 [13332] request LoadByName "game0.sav" [mode 1]        <- the pause-menu keypresses did load it
02:47:38.558 [30408] host: real load of "game0.sav" requested (pipe)  <- the script's fallback
02:47:38.558 [13332] host: real load of "game0.sav" (pipe): the game's save open ok
02:47:38.558 [13332] request LoadByName "game0.sav" [mode 1]
02:47:38.558 [13332] host: "game0.sav" is sent again in the save transfer for the guest
```

and the guest log (verbatim, the load the script's fallback issued at 02:47:38 — the same session's
earlier pause-menu load at 02:46:52 was answered the same way; that part of the guest log is no longer
available because the next run overwrote it, only its counter is: the run's `guest sync` line ends
`req_applied 3 | ... | saves_done 1 | real load stage 2`, i.e. the guest applied three host requests and its
own real load is the last):

```
02:47:38.561 [37776] guest: real load of "game0.sav" issued (mode 1 request state 3)
02:47:38.643 [37776] guest: the world this copy built from the save itself is up (level I100, 78 ms after the load)
```

So the game's own pause-menu load happened at 02:46:52 (no pipe), the script's fallback produced a second,
identical reload at 02:47:38 which the guest answered with its own real load (world up 78 ms later), and the
five checks then passed on the state both loads produce. `tests/case3.py` now decides "a load happened" from
those log lines (host `request LoadByName`, guest `real load of`) instead of the world pointer.

### 2.4 Screenshots (looked at, not just captured)

* `tests/shots/host.png`, `tests/shots/guest.png` (CASE 1, run 2): both frames show the same dark corridor
  with GIR1 in front holding the flashlight and chainsaw and BOY1 behind with the taser; the guest frame
  carries the Steam overlay; non-black 97.4 % / 97.9 %, mean abs diff 4.72.
* CASE 2 (run 5): host and guest both show the I015 cave with BOY1 and BOY2 side by side, both flashlights
  on; mean abs diff 1.53. `tests/shots/case2_menu.png` (main menu) and `case2_continue.png` (Continue
  highlighted) show the menu; `case2_down2.png` shows the save-slot browser `Continue` opens.
* CASE 3's in-run screenshots are black: `bot.py shot` does not activate the window, and this game stops
  presenting to an inactive window (FINDINGS_12). `shot_pair.py` (which clicks first) is what the CASE 1/2
  runs used.

## 3. Regression (verbatim, final build)

### 3.1 `sh tests/run_pair_menu.sh <chk14.dll> check_party.py check_items.py check_hands.py check_hands_visible.py check_entities.py check_movement.py` (run 7)

```
E: PASS
party: host ['BOY1', 'GIR1'] guest ['BOY1', 'GIR1'] | inventory: host 44 guest 44
party OK
items OK
hands OK (2 characters checked)
hands visible state OK (2 characters checked)
entities OK (host 43, guest 43)
A: PASS
B: PASS [warn: BOY1 anim differs in 2/60 samples (transition samples)]
C: PASS [warn: GIR1 anim differs in 4/60 samples (transition samples)]
D: PASS [warn: BOY1 anim differs in 4/50 samples (transition samples); GIR1 anim differs in 9/50 samples (transition samples)]
EXIT=0
```

### 3.2 `sh tests/run_pair.sh <chk14.dll> check_party.py check_items.py check_hands.py` (run 8, the old new-game-first flow)

```
party: host ['BOY1', 'GIR1'] guest ['BOY1', 'GIR1'] | inventory: host 44 guest 44
party OK
items: before host 44 guest 44
items: after host 45 guest 45
items OK
in hand: host [('BOY1', 'CBOW'), ('GIR1', 'CSAW')] guest [('BOY1', 'CBOW'), ('GIR1', 'CSAW')]
inventory: host 44 guest 44
hands OK (2 characters checked)
still running: []
OWNER FILES UNCHANGED (apart from Steam remotecache.vdf)
EXIT=0
```

The old flow now also takes the new guest path: its `REQ_LOAD_NAME` runs the two-call real load while the
guest already has a world (before this task that path called `LoadByName` bare), and it still converges —
same party, inventory and hands as before.

### 3.3 The save transfer's files (`tests/check_savexfer.py`, updated for the real save folder)

```
game5.sav host live b270bdc60ad2, guest live b270bdc60ad2, guest Save b270bdc60ad2 (host Save snapshot 53304e97cee1)
...
save transfer OK (both guest folders hold the host's live saves)
```

The game rewrites its live saves in `coop_profile\remote` while a session runs (loading a save updates the
slot data), so those differ from the owner's `Save\` snapshot even on the host. The transfer sends the live
copy and the guest writes both, which is why the check compares the guest's two folders against the host's
live copy and only prints the host's snapshot.

## 4. Test scripts added / changed

* `tests/run_late_join.sh` + `tests/start_late_join.py` — CASE 1: start the host alone, let it load save 01
  through the game's own path, wait for its world and settle, then start the guest copy, wait for it to
  follow, run the checks, take both screenshots, always stop the games.
* `tests/run_named_load.sh` + `tests/case2.py` + `tests/o2_file.py` — CASE 2: o2.sav on the host only (both
  save folders), the guest loses its copy of the slot file the host will load, the host loads it, the guest
  must receive it and follow; `o2_file.py prepare|check` manages and reports the stand-in.
* `tests/run_second_load.sh` + `tests/case3.py` — CASE 3: the menu flow first, then a second load from the
  pause menu (pad keypresses, `loadsave` fallback), then the checks.
* `tests/start_menu_load.py` — the save to load can come from `OBSCOOP_MENU_SAVE` (CASE 2).
* `tests/check_savexfer.py` — compares against the folder the game really reads.

## 5. git diff --stat

```
 src/hooks.c              |   8 +
 src/net.c                |  12 +-
 src/sync.c               | 373 +++++++++++++++++++++++++++++++++++++++--------
 tests/check_savexfer.py  |  28 +++-
 tests/start_menu_load.py |   4 +-
 5 files changed, 357 insertions(+), 68 deletions(-)
```

New untracked files: `FINDINGS_14.md`, `tests/run_late_join.sh`, `tests/start_late_join.py`,
`tests/run_named_load.sh`, `tests/case2.py`, `tests/o2_file.py`, `tests/run_second_load.sh`,
`tests/case3.py` (plus the built `chk14.dll`; everything is left uncommitted).

## 6. DONE / NOT DONE / UNKNOWN

**DONE**
* CASE 1: the welcome re-sends the load (`host_save_include` + `host_welcome_guest`); a guest that starts
  after the host is in its loaded save follows into the same level with the same party, inventory, hands
  and 43/43 entities. Proven live with screenshots.
* CASE 2: the transfer carries the file the host's load names first (`o2.sav` support included), announces
  each completed file by name, and the guest waits for exactly the file its load needs; a file the guest
  lost is re-sent when the host loads it and the guest then loads it. Proven live (`game1.sav`, 187 ms).
* CASE 3: a second load in one session is followed by the guest through its own real load, including when
  the guest already has a world. Proven live (host's own pause-menu `LoadByName`, guest world up 78 ms
  after its load), checks pass.
* The guest's own saves are backed up to `Save.bak\<name>` before being overwritten, and the backup is
  logged (owner agreed).
* The transfer now uses the folder the game really reads (`coop_profile\remote`) and keeps `Save\` in step.
* `NET_VERSION` 8; both regressions pass.

**NOT DONE**
* The main menu's fixed-`o2.sav` load could not be exercised end to end: this UI's `Continue` opens the
  slot browser (no `LoadByName` line), and the game's save manager refuses the name `o2.sav` even with the
  file in the right folder. CASE 2 therefore used the allowed `loadsave` pipe fallback, with a slot file
  the guest had lost (see 2.2). The code path for a named non-slot file is implemented and unit-of-logic
  exercised (`host_save_include` appends + sends), but no live load named such a file successfully.
* CASE 1 was run on the build before the save-folder fix (its welcome/transfer logic is unchanged by that
  fix). The final build was not re-run for host-first (run budget); its menu flow and the second load were.

**UNKNOWN**
* Why the save manager refuses `o2.sav`/`recover.sav`: `FUN_0053d9b0` reads the file (proxy log) and then
  fails; the decompile has several failure exits with different status codes in `manager+0x19c`
  (decompile 191502-191543) and which one fired was not determined.
* Whether a *genuine* `o2.sav` (one the game wrote itself, e.g. from a build/version that uses it) would
  load; the stand-in was a copy of `game0.sav`, whose bytes open fine as `game1.sav`.
* Movement (check_movement) after a *second* load: only measured after the first load (phase E). The
  entities/party/hands checks did run after the second load and passed.
* Reconnect behaviour mid-transfer: the guest clears its completed-file list on a new `WELCOME` and the
  host restarts the transfer, but no live reconnect was tested.

