# FINDINGS 58 — the shared pause menu: a press is never lost, and the newest state wins

Labels: **OBSERVED** = printed by a run/check or read in the decompile/code with an address/file:line;
**DERIVED** = follows from the cited code but was not seen live; **GUESS**; **UNKNOWN**.
Base: `w/combat`, HEAD = TASK 57 (`e1b7607`, protocol 29). Decompile `local\decomp2\Obscure2.exe.c`.

## 0. What the task reported

Reviewer run of TASK 57's build (`OBSCOOP_LINK=steam sh tests/run_pair.sh <m57.dll> check_menus.py`,
`_archive/claude_verify_57_menus.log`): step 4 (the GUEST opens the pause menu, the HOST presses START)
left **both copies in state 5 for the rest of the run** — a player who cannot leave the pause menu
blocks play. TASK 57's own run passed the same step, so it was taken for a race.

## 1. How the game's own pause key works (OBSERVED, decompile)

* **Open** (world update `FUN_004b4cb0`, 110577-110582): from world state 1, if the pad dispatch
  `FUN_004b2b30(0x23, 0x50)` or `FUN_004b2b30(0x23, ctl+0x14)` reports START pressed, it calls
  `FUN_004b2730()` — which requests state 5 only while `world+0x12c == 0` (108501-108510).
* `FUN_004b2b30` (108740-108766) is **level-triggered**: it returns 1 while the action record of the
  START slot has `record+0x10 != 0`. The record itself is per action slot (`FUN_0059b3e0(slot)` =
  `this->[0x34][slot]`, 0x59b3e0).
* **Close** (209305-209315): needs `FUN_0059b3e0(0x23)`'s record pressed **and** the menu manager's
  current screen (`in_ECX[0x25]`, tag at +0x10) to be `"PAUS"` (`0x50415553`); then `FUN_004b2770()`.
* `FUN_004b2770` (108518-108536) requests `world+0x180` (the state the pause saved when it opened) and
  clears it; if `+0x180` is neither 5 nor 1 it falls back to `FUN_004b25c0` (request state 1).

So the pause **open** depends on the pad-action record and the **close** on the menu manager's current
screen as well: neither is guaranteed for a pause this copy did not open with its own pad.

## 2. Reproduction (OBSERVED, `run_s58_diag1.log`, chk58a = TASK 57's code + logging)

`tests/check_pause_loop.py` (new): 10 rounds of the three orders that race — A the guest opens and the
host closes, B the host opens and the guest closes, C both press START within 100 ms — each round must end
with both copies in the same state within 1 s; every step logs both copies' `world+0x11c` (state),
`+0x12c` (requested), `+0x180` (saved state) and the pipe `menu` line (own/peer seq, reqs).
On the steam-like link (`OBSCOOP_LINK=steam sh tests/run_pair_menu.sh chk58a.dll check_menus.py
check_pause_loop.py`) check_menus **passed** and the loop failed **5/10** rounds. The mod's log lines
(temporary diagnostics, per copy) show what happened:

* the class of loss was plain to see: a round's **first press did nothing and its second press did the
  first press's action** — "host opens" did nothing and the following "guest closes" **opened** the pause
  (rounds 2, 5, 8), the same for the guest's presses in rounds 4 and 7. The log says why: those presses
  were sent **inside the previous press's 200 ms hold** (`press()` = set, sleep 200 ms, clear), so the
  pad never went up between the two, and both the game's pad action and the mod's edge counter saw ONE
  continuous hold (two guest presses produced no `player 2 START edge` line at all; the host's own opens
  in rounds 2, 5 and 8 left no `menu state 1 -> 5`). That is a **test artifact** — a player cannot press
  twice inside one hold — and `check_pause_loop.py` now keeps 350 ms between two presses of the same pad
  (`GAP`); with that and the fix below all 10 rounds pass (§4.1).
* the **legacy pulse** made the host's pause come from two different places: when the guest pressed
  START, `net.c` turned it into a 120 ms START on the HOST's player 1 pad (`host: the guest's START
  pulses player 1's START ...`, 03:55:19.184, 21.794, 23.356, 30.731). It opened the host's pause on some
  presses (19.184, 21.794) and was dropped on others (23.356, 30.731) — there the pause only appeared
  through the mod's own request 170-190 ms later (`host: menu request: opening the pause menu (peer menu 5,
  this copy 1)`, 23.544, 30.902). So WHICH mechanism opened the host's pause depended on an unsequenced
  pulse, and the game's own CLOSE path depends on how the pause was opened (§1).

The reviewer's own order (guest opens, host closes) **passed** in this run, so the loop did not reproduce
its failure; what it did show is the two mechanisms above, which the fix removes or replaces.

## 3. The fix

1. **Every pause-menu open/close is the game's own world-state request, run on the copy that owns the
   player whose pad pressed** (`src/sync.c` menu_tick, `menu_press`): player 2's START on the guest
   (open in state 1, close in state 5) and player 1's START on the host (open/close decided by the
   world state **at the poll**, see §2).
2. `src/obscoop2.c`: `pad_finish` counts player 1's START edges against the state at the poll
   (`poll_world_state()` = `world+0x11c`; the world update of that frame has not run yet) into
   `g_p1_start_open_edges` (state 1) / `g_p1_start_close_edges` (state 5). The press that opens a menu
   is therefore never seen as a close, and a close can never depend on the game's menu-manager screen.
   `g_p1_start_at` and the 500 ms "held START" heuristic of TASK 57 are gone.
3. A press the game refuses (its world keeps one request in flight, `world+0x12c != 0`) is **retried for
   500 ms** (`MENU_PRESS_RETRY_MS`), so a press cannot be lost to a request that is still in flight; the
   retry stops as soon as the state has moved (the game's own path won).
4. **The legacy START pulse on the host is removed** (`src/net.c`, `g_pause_pulse_until`,
   `g_last_guest_buttons`): it was a second, unsequenced way into the shared menu and is what pressed
   START again on a pause the host had just closed (2). The guest's press now reaches the host through
   the sequenced state only.
5. **Ordering like TASK 37's level transitions** (`src/sync.c`): `g_menu_my_seq` is a Lamport clock —
   every local change is stamped one above the newest peer number received (`g_menu_peer_clock`,
   updated from every packet). A copy applies the peer's state only when the peer's number is **newer**
   than its own (`pseq > my_seq`); an older number is a stale packet sent before this copy's change, and
   acting on it is what re-opened a menu a copy had just left. An equal number is a tie (two presses
   that did not see each other) and there the **host's** state wins: only the guest applies it. The old
   `want == 1 && pseq < my_seq` guard (closes only) is subsumed — opens were re-requested on a stale
   packet, which is the same defect in the other direction.
6. Both copies now publish `PKT_MENU` in **every** state every 250 ms (it used to be gated on a menu
   session). The ordering above needs the clock to stay aligned: a copy that stops publishing in normal
   play lets the other's number run ahead, and a later press would look older than the peer's state.
   No packet layout changed, so `NET_VERSION` is unchanged.

## 4. Evidence — all on the final DLL `chk58c.dll` (full path
`<worktree>/chk58c.dll`), `OBSCOOP_LINK=steam`

After the runs one code COMMENT was corrected (it still said the game's own pause OPEN drops presses; the
loop showed that was the check's own press overlap, §2). No code changed: the `.text` section of the
rebuilt `chk58c.dll` is byte-identical to the one that ran (`llvm-objdump -s -j .text chk58c.dll | md5sum`
= `8c830f7d55657ce3accbae46fa6c7f49` before and after), so the evidence below is the evidence for this
build. Compiler output: the 3 warnings of the shared context (net.c `tick`, `watch_start`,
`request_shot`), no new ones.

### 4.1 The 10x pause loop — `run_s58_final1.log` (steam, `run_pair_menu.sh`)

`OBSCOOP_LINK=steam sh tests/run_pair_menu.sh <dll> check_menus.py check_pause_loop.py` — 60 PASS, 0 FAIL.

```
== round 1/10: guest-open-host-close
   04:05:16.927 press START on the guest pad
   04:05:17.478 after guest START (open) host (5, 0, 1) menu local st 5 ... seq 34 | peer st 5 ... seq 33 | guest (5, 0, 1) menu local st 5 ... seq 33 | peer st 5 ... seq 34
   the guest opens the pause menu on both within 1 s (0.00 s): PASS
   04:05:17.979 press START on the host pad
   04:05:18.529 after host START (close) host (1, 0, 0) menu local st 1 ... seq 35 | peer st 1 ... seq 36 | guest (1, 0, 0) menu local st 1 ... seq 36 | peer st 1 ... seq 35
   the host closes the pause menu on both within 1 s (0.00 s): PASS

== round 2/10: host-open-guest-close
   04:05:18.530 press START on the host pad
   04:05:19.081 after host START (open)  host (5, 0, 1) ... seq 37 | guest (5, 0, 1) ... seq 38
   the host opens the pause menu on both within 1 s (0.00 s): PASS
   04:05:19.582 press START on the guest pad
   04:05:20.133 after guest START (close) host (1, 0, 0) ... seq 40 | guest (1, 0, 0) ... seq 39
   the guest closes the pause menu on both within 1 s (0.00 s): PASS

== round 3/10: both-start
   04:05:20.133 press START on BOTH pads within 100 ms
   04:05:20.766 after both START (open)  host (5, 0, 1) ... seq 41 | guest (5, 0, 1) ... seq 42
   both pressing START within 100 ms pauses both copies within 1 s (0.00 s): PASS
... (rounds 4-10 the same three orders, all PASS)
== summary
   rounds in the same state on both copies within 1 s: 10/10
   at the end                 host (1, 0, 0) ... | guest (1, 0, 0) ...
   world+0x180 after the last close: host 0 guest 0
   every round ended in normal play on both copies within 1 s: PASS
pause loop OK (10 rounds)
```
(The very long pipe lines are cut here; the log keeps them verbatim, with each copy's `world+0x11c`,
`+0x12c`, `+0x180` and its pipe `menu` line at every step. `world+0x180` = 0 on both copies after the
last close: the pause's saved state is cleared again, so `FUN_004b2770` cannot leave a stale one.)

### 4.2 `check_menus.py` — three runs in a row, all PASS

| run | command | result |
|---|---|---|
| `run_s58_final1.log` | `OBSCOOP_LINK=steam sh tests/run_pair_menu.sh <dll> check_menus.py check_pause_loop.py` | `menus OK (39 checks)`, 60 PASS / 0 FAIL |
| `run_s58_final2.log` | `OBSCOOP_LINK=steam sh tests/run_pair_menu.sh <dll> check_menus.py` | `menus OK (39 checks)`, 39 PASS / 0 FAIL |
| `run_s58_final3.log` | the reviewer's command as written: `OBSCOOP_LINK=steam sh tests/run_pair.sh <dll> check_menus.py` | `menus OK (39 checks)`, 41 PASS / 0 FAIL |

The step that failed for the reviewer, verbatim from `run_s58_final3.log` (the reviewer's command; note
`run_pair.sh` does not read `OBSCOOP_LINK`, so that one is plain loopback — `run_pair_menu.sh` is the
runner that actually runs the steam-like relays):

```
== 4. the GUEST opens the pause menu (START) -> state 5 on both within 1 s; the HOST closes it
   after guest START (open) host st 5 ui (0, 0) cur (4294967295, None, None) | guest st 5 ui (0, 0) cur (4294967295, None, None)
   both copies show the pause menu after 0.00 s
   the guest opens the pause menu on both within 1 s: PASS
   after host START (close) host st 1 ui (0, 0) cur (4294967295, None, None) | guest st 1 ui (0, 0) cur (4294967295, None, None)
   both copies left the pause menu after 0.00 s
   the host closes the pause menu on both within 1 s: PASS
```

and the same step on the steam-like link, from `run_s58_final2.log`:

```
== 4. the GUEST opens the pause menu (START) -> state 5 on both within 1 s; the HOST closes it
   after guest START (open) host st 5 ui (0, 0) cur (4294967295, None, None) | guest st 5 ui (0, 0) cur (4294967295, None, None)
   both copies show the pause menu after 0.00 s
   the guest opens the pause menu on both within 1 s: PASS
   after host START (close) host st 1 ui (0, 0) cur (4294967295, None, None) | guest st 1 ui (0, 0) cur (4294967295, None, None)
   both copies left the pause menu after 0.00 s
   the host closes the pause menu on both within 1 s: PASS
```

Every one of the three runs also passes the rest of check_menus (the guest's START close, the inventory
from each side, the two cursors, the selection, "no cursor moves outside a menu", the per-player UI) and
ends with `remaining Obscure2.exe: 0, obscoop-relay.exe: 0` (`still running: []` in final3).

### 4.3 The soak — `run_s58_soak.log` (`OBSCOOP_LINK=steam OBSCOOP_SOAK_ITERS=5 sh tests/run_soak.sh`)

0 FAIL lines in the whole log; the steps: `attack animation OK`, `anim-sync OK`, `controls OK`,
`visible OK`, `attack-each-other OK`, `soak OK (5 location changes, both copies alive)`, `doors OK
(2 phase(s))`, then the crash-handler proof, then:

```
== race A: door use on the host, then a save load the moment the door asks for its level
   race A result: level I010/I010 after 0.3s -> one level
== race B: the same door used on the host and on the guest at the same moment
   race B result: level J000/J000 after 0.0s -> one level
== settling after the race phases (one level, no change for 3 s)
   settled: level J002/J002, quiet for 3.0 s (yes)
soak OK (5 location changes, both copies alive)
== check_doors.py --reset game3.sav (timeout 300s)
   image: PASS
   transition: dest J000 -> host J000 guest J000 after 0.0 s: PASS
doors OK (2 phase(s))
== liveness and crash reports
  host: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
  guest: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
== crash handler proof: the guest is asked to fault (pipe crash)
  ... (the soak's own crash-handler proof: a complete report, code 0xc0000005, eip module+offset, stack)
== stopping the two games
still running: []
OWNER FILES UNCHANGED (apart from Steam remotecache.vdf)
stopped obscoop-relay.exe pid 60904
stopped obscoop-relay.exe pid 57316
remaining Obscure2.exe: 0, obscoop-relay.exe: 0
=== soak run: PASS
```

## 5. Process budget

| runs | game processes |
|---|---|
| diagnosis: `run_s58_diag1.log` (chk58a = TASK 57's code + logging; check_menus + loop) | 2 |
| validation of the fix + logging: `run_s58_b1.log` (chk58b; check_menus + loop) | 2 |
| final: `run_s58_final1.log` (check_menus + loop), `run_s58_final2.log`, `run_s58_final3.log` | 6 |
| final: `run_s58_soak.log` (5 iterations) | 2 |

**12 of the task's 12**; every game and relay was stopped by the runner (`remaining Obscure2.exe: 0,
obscoop-relay.exe: 0` in each of the final logs).

## 6. DONE / NOT DONE / UNKNOWN

**DONE**

* The reported failure's order — the GUEST opens the pause menu and the **HOST closes it** — ends with
  both copies in normal play within 1 s on the steam-like link (§4.2) and in the 10-round loop (§4.1);
  `check_menus.py` passes three runs in a row (§4.2); the steam soak passes (§4.3).
* Every pause-menu open/close is the game's own world-state request (`FUN_004b2730` / `FUN_004b2770`)
  run on the copy that owns the player whose pad pressed, retried for 500 ms while the world has another
  request in flight, so a press cannot be lost. The game's menu-manager state, which its own pad path
  depends on, is no longer on the critical path.
* The legacy guest-START pulse on the host's pad is gone: one sequenced mechanism instead of two (§2, §3).
* Menu states are ordered like the level transitions of TASK 37: a Lamport clock on the wire, the newer
  state wins on both copies, a stale (older) packet is never acted on — in BOTH directions (the old rule
  only protected closes, so a stale "still in the menu" packet could re-open one) — and a tie goes to the
  host. `world+0x180` is 0 on both copies after the last close (§4.1).
* No regression: check_menus' 39 checks (pause from each side, inventory from each side, two cursors,
  the selection, the wheel/aim UI) and the soak's attack animation, controls, location changes, doors and
  crash-report steps all pass on the final DLL.

**NOT DONE**

* The **host's own press path in the mod** (the open/close `menu_press` issues when the game's own pad
  dispatcher does not act) was **not observed firing live**: in all three final runs and all 10 loop
  rounds the game's own pad path accepted every host press (the host's pipe `reqs` counter is unchanged
  across each host press — `4 -> 4`, `4 -> 4`, `7 -> 7`, `10 -> 10`, `13 -> 13` in §5.1), so that path is
  "same code path as the guest's press path — which does fire (the guest's `reqs` grows by one per
  press) — not exercised live on the host". It is the safety net for the reviewer's failure, not the
  mechanism that produced the passes.
* The exact game-side reason the reviewer's host close was lost is **not proven**. The explanation offered
  in §2 is DERIVED/GUESS: the legacy pulse (START held 120 ms on the host's pad) could open the pause and
  have the game's own close path shut it again inside the same hold (the "fresh pause" behaviour measured
  in TASK 57 §7), leaving the pause that remained opened by the mod's request — and that close needs the
  menu manager's current screen to be "PAUS" (decompile 209305-209315). What is proven is that the press
  no longer goes through that path at all.
* `run_pair.sh` ignores `OBSCOOP_LINK`, so the steam-like proofs use `run_pair_menu.sh` (as TASK 57 did);
  the reviewer's command as written was also run (§5.2, third run — loopback).
* The proof is on the relay's steam-like profile, not on two real PCs with Steam.

**UNKNOWN**

* A copy that reconnects starts its menu sequence at 0 while the peer's clock may be far ahead; it adopts
  the peer's number on the first packet, but a press made before that packet could be refused as
  "older". Not tested (no reconnect was run).
* Whether the owner's real controller reaches `pad_finish` (only then is the new player-1 START edge
  counted): DERIVED from TASK 57's real-device-path fix; the harness uses virtual pads only.
