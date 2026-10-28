# FINDINGS 27 — a guest's chair break reaches the host; the paused-link apply path

Labels: **OBSERVED** = printed by a run/check in this task or read in the decompile (address cited);
**DERIVED** = follows from the cited code but was not seen live; **GUESS**; **UNKNOWN**.
Base: branch w/combat HEAD 877bc15 (`PKT_PROP`, `NET_VERSION` 13 → **14**). Decompile:
`local\decomp2\Obscure2.exe.c` (build 215294).

## 0. Result in one paragraph

The guest's break **did** reach the host in the TASK 26 verification run (the host's log shows `prop break
applied ... broken now 1`), but the copy that *applies* a break stopped updating right after it: our sync
ran the game's own break routine (`vtable slot 25 = FUN_00412140`) from the frame hook and the game thread
stopped there (OBSERVED, own run: the guest's last game-thread line is that `prop break applied` line, then
nothing for 25 s while its network thread and pipe kept answering, and every later pad press on that copy
did nothing). All three symptoms the task listed come from that plus two smaller faults: the owner's
"nothing carried" heartbeat detached the chair on the peer *before* the peer's own swing arrived, and props
were identified only by a position that moves with the hand. Fixed by writing the **state** a break leaves
instead of running `FUN_00412140`, by identifying a carried prop **by the hand it is in**, by keeping props
in the table when the entity lists drop them, by never detaching a **broken** prop, and by not announcing
back a break this copy applied. `check_breakables.py` passes both directions on the same build (see §6).
The paused-link apply-path phase is **removed** with the measurement that shows why: neither `netpause` nor
a receive-only drop can make one copy miss the break while it stays able to play (§5).

## 1. The failing run of TASK 26 (OBSERVED, `claude_verify_26.log` + the two `obscoop.log` copies it left)

```
16:23:10.706 host: prop carry packet: prop CHAI id ???? -> ent 1a044188, character GIR1 19f9cf30 (holds 1a044188)
16:23:10.972 host: prop carry applied: ----- id ---- -> GIR1          <- the sync DETACHES the chair
16:23:11.107 guest: prop broken here: CHAI id ???? drop none           (the guest's own scan)
16:23:11.466 host: prop break applied: CHAI id ???? -> broken now 1    (the 350 ms deferral + a frame)
```
and the host copy then showed the chair whole for the whole 3 s wait, and its later pad presses did nothing.

1. **The detach race.** `prop_held_by` ignores a *broken* chair (right: the game keeps it linked in the
   hand), so as soon as the guest's own game broke it (~10.9) the guest's next kind-2 packet made the host
   detach the chair (10.972). The host's own copy of player 2 then squeezed A **with empty hands** ~0.1 s
   later - no local break (the host log has no `prop broken here` for that chair: OBSERVED).
2. **The announcement carried no identity but a position** (`prop_find`: same class tag, nearest within
   400 units) - and a carried chair's position is wherever the hand is, different on the two copies.
3. **Applying the break ran `FUN_00412140`** — see §2.

## 2. Running the game's break freezes the copy that runs it (OBSERVED, own run 1, `chk27.dll`)

Guest copy, applying the host's break through `vtable[25]`:

```
16:34:30.236 guest: prop break packet: ... (x3)
16:34:30.445 guest: prop break applied: CHAI id ???? ent 19cd8018 at (575.2,-194.9,-9.8) -> broken now 1
<no further line from the game thread (tid 5184) for the next 25 s; the network thread (38548) keeps
 logging "host party stored" every 0.28 s, the pipe keeps answering `props`/`sync`, and the check's three
 A presses on that copy do nothing: "the action button did not pick the chair up">
```
The call returns (the log line is printed after it), so the game does not lock up inside `FUN_00412140`; it
stops in the updates that follow. TASK 26 had already seen this ("calling the break while the game's own
action runs hung the host in an early run") and answered with the 350 ms deferral - which cannot help,
because the copy that applies a break is exactly the copy that did **not** run the action.

**Fix - `prop_break_state()`**: write what a break leaves, with no game routine that has side effects:
`+0xa4 = 1` (broken; can-interact refuses, the save records it), `+0x24 = 0` (not usable, what a real break
leaves), `+0x12c = 0` (the respawn timer `FUN_00413c00` counts to 20000), the mesh hidden through its own
vtable slot 33 (`(*(+0x84))(0)`, the break's own call) and the collision object's `vtable[17]`
(`(+0x44)(0)`, the call the attach already makes). Cost: no splinter particles and no sound on the copy
that applies a break - accepted, that is local dressing; the world state is the same. The drop item entity
is still enabled by `prop_align_drop` with the item's own slots 34/32/33, exactly as the break does.
(`FUN_00412080` @0x412080 is the reset - `+0xa4 = 0`, `+0x24 = 1`, drop `+0xa8 = 0`, show the mesh - and
`FUN_00413c00` @0x413c00 is its only caller: a broken chair with `+0x128 != 0` respawns 20 s after its
break. Both copies do that on their own timer, ~0.4 s apart; the sync does not mirror it.)

## 3. Prop identity (OBSERVED + DERIVED)

* Chairs carry **no id** (`entity+4` is 0: `props` prints `????`), so a packet had only the class tag and a
  position.
* The table was rebuilt from the manager's two lists every 150 ms and **dropped** a prop the lists no longer
  showed; a carried chair is re-parented, so the next packet could only match the nearest *other* chair.
  `prop_scan` now **keeps** a prop that left the lists while the object is alive and still the same class.
* A break announcement names the character that held it (`pkt_prop.ch_tag`, from `+0xc4`), and the receiver
  resolves the prop **through that hand** (`prop_held_chair`) before falling back to the position. `NET_VERSION` 14.
* A break this copy applied from a packet is not announced back (`prop_applied_here`, 2.5 s), and a packet
  whose prop is not in the table yet is retried for ~1.2 s instead of being counted missing at once.
* `prop_apply_carry` no longer calls the game's detach on a **broken** prop: the game keeps a broken chair
  in the hand on purpose, and the owner's twice-a-second "nothing carried" heartbeat used to detach it over
  and over.

## 4. `sync` now prints `frames` (OBSERVED, own run 3)

A copy whose game thread stops keeps its network thread and pipe answering, so a memory-reading check sees
a live process and a frozen game. `frame_tick` counts its calls and `sync` prints the count at the end
(`| frames 2069`): in run 3 the guest counted 911 → 997 while its game thread logged nothing.

## 5. The paused-link apply path - measured, and removed (OBSERVED)

The phase broke a chair while the peer could not hear it and then required the peer to converge from the
once-a-second `PKT_PROPS` resend. Two ways were tried:

* **`netpause` on both copies (TASK 26)** cannot work: `net_tick` returns at its first line while the link
  is paused, so the paused copy's own pad ring (`g_ring_p1`, the delayed input the game reads through
  `delayed_input_on`) is never fed and the copy cannot act at all. TASK 26's run printed exactly that:
  `during the pause: host broken 0 carry 0`.
* **A receive-only drop, `netdroprx <ms>` (new test switch in `src/net.c`)**: the receiver misses the
  announcement as intended (`during the drop: host broken 1 | guest broken 0`), but 3 s of silence makes
  the game see the partner's controller vanish. From then on that copy's `prop_tick` no longer runs: its
  `sync` prop counters stop (`applied` froze while `rcv` kept growing), its pad presses do nothing, and in
  run 3 the two chair phases after the drop both failed. So the phase cannot be made meaningful while the
  session stays usable, and `check_breakables.py` no longer runs it (the switch stays in the DLL, documented
  as a test tool, like `netpause`).

## 6. Runs (verbatim excerpts from this task)

| # | build | what | result |
|---:|---|---|---|
| 1 | chk27 | `check_breakables.py` (save 04) | host's break ok; guest applying the host's break **froze the guest's game thread** (§2) |
| 2 | chk27b | same, `prop_break_state` instead of `FUN_00412140` | both player phases pass; the apply-path phase (netdroprx) failed and left the guest out of play |
| 3 | chk27c | + broken-prop detach guard, + `frames`; apply path first | phases 1-2 failed because the apply-path drop had already taken the guest out of play (§5) |
| 4 | chk27c | breakables + the six menu checks | party/items/hands/hands_visible/entities OK; breakables failed on its own chair lookup (a carried chair had drifted 119 units) |
| 5 | chk27d | check matches the other copy's chair by **list index**, approach retries | phase 1 ok, phase 2 could not place the character (raw tp is unreliable, see below) |
| 6 | chk27d | same | **breakables OK**, both players, carry and break on the other copy at 0.00 s |
| 7 | chk27d | same | **breakables OK** (both players, both copies, 0.00 s) |
| 8 | chk27d | same | **breakables OK** (both players, both copies, 0.00 s) - three consecutive passes on one build |

The three passes ran `chk27d.dll`; after them, one comment block in `src/net.c` (`netdroprx`) was corrected
to say what the runs showed. No code changed with it (the build is not byte-reproducible anyway: two builds
of the same tree differ, so the binary cannot be compared for that).

Two test-side facts found on the way (both fixed in the check):

* A **carried** chair drifts (in run 4 the guest's copy of the host's chair was 119 units from where it was
  picked up, because the guest's own copy of player 1 walks away in J002 - `check_movement` shows the same
  135+ unit divergence there, and TASK 26 saw it too). `check_breakables.py` now identifies the other
  copy's chair by its **index in the entity list** (both copies build that list from the same level file in
  the same order) instead of by position, and never picks a carried chair as a target.
* `tpraw` is not usable for the guest's own player 2: the position is re-snapped from the host's stream, so
  the command says `ok` for a placement the game undoes a frame later (runs 1 and 4 stood next to nothing).
  The check now uses only the mod's safe `tp`, over more spots and up to four chairs, and re-places the
  character once if the first three presses do not pick a chair up.

## 7. DONE / NOT DONE / UNKNOWN

**DONE**
* The freeze: found (own run, §2), explained and removed (`prop_break_state`, §2).
* The detach race (§1.1), the position-only identity (§3) and the broken-prop detach loop (§3).
* `check_breakables.py` passes with **both** players breaking a chair, on both copies, in both directions,
  three consecutive pair runs on one build (runs 6-8, §6).
* The paused-link apply-path phase: measured, explained, removed from the check (§5).
* Process budget: **14 game processes in 7 pair runs** (runs 1-8 above; run 4 covered the menu regression
  too). All games stopped by their runners (`still running: []`), owner files unchanged.

**NOT DONE**
* The `run_pair.sh` (save 01) regression, the `run_pair_menu.sh` six-check regression and
  `run_reconnect.sh both` were **not** all run separately: the process budget (14 games) was spent on eight
  pair runs, five of them diagnosis. The menu regression fits in run 4 (party, items, hands, hands_visible,
  entities OK; **movement FAILED in J002**, the same level-specific failure TASK 26 recorded - the guest's
  characters do not move and the copies diverge by 135-1500 units). Reconnect and the save-01 regression
  are unverified on this build.
* The peer copy does not show the splinter effect or the sound of a break it applied (state-only break).
* The game's own 20 s chair respawn is not mirrored between the copies (each respawns on its own timer,
  ~0.4 s apart).

**UNKNOWN**
* Why the sync's break call froze the game thread (the call returns; the stall is in the updates after it).
  The state-only break avoids it, so this was not narrowed further.
* Why a raw `tpraw` of the guest's own player 2 is undone (the position stream is the likely reason; not
  investigated).
* Whether a chair with an `itemType` (a drop item) still needs the drop alignment proven live: no chair in
  slots 01-10 has one (TASK 26).
