# FINDINGS 54 — effects on the partner's screen, stance exit, props in motion, the guest's carry-apply crash

Labels: **OBSERVED** = printed by a run/check in this task or read in the decompile (address cited);
**DERIVED** = follows from the cited code but was not seen live; **GUESS**; **UNKNOWN**.
Base: branch w/combat, HEAD e3e123e (TASK 53 WIP, protocol 27). Decompile `local\decomp2\Obscure2.exe.c`.

## 0. Read first (what TASK 53 / SYNC_AUDIT already measured — not re-derived here)

* FX relay implemented: `hk_effect` on `FUN_00591230` (hooks.c), `PKT_FX`, `fx_replay_tick` in the game-update
  hook, counters in `sync` (`fx local/sent/rcv/played/...`) — never verified live (FINDINGS_53 §4).
* Stance exit: `check_stance.py` measured LB in/out 5× each way IDENTICAL on both copies (FINDINGS_53 §3.1),
  i.e. LB alone is not the owner's "stuck stance"; the state the puppet's copy skips is 200/300
  (`puppet_attack`), and A1-4 lists the interaction states 0x708/0x6a4/0x452 as NOT on the puppet's
  safe list (the puppet holds its pose there).
* `pkt_prop kind 4` writes the entity position +0x6c raw; measured REVERTED on both copies (the collision
  body is the source of truth). `PKT_PROPMOVE` is declared in net.c but nothing sends or handles it.
* A1-1: the guest's last log lines are two carry packets for the chair BOY1 carries; 0.45 s earlier the
  host broke three chairs, the carried one among them; no break line on the guest, no crash report.

## 1. Plan (updated as the runs come in)

1. Reproduce A1-1 with a `check_breakables.py` phase (`break-while-carried`, 5×) on an instrumented HEAD
   build: log every `prop_apply_carry` step and put `hang_phase` markers around the game calls, so a
   crash/hang report names the call.
2. Fix the site the run names; the audit's mechanism (attach of a broken/just-broken prop) is the first
   candidate.
3. Statement family: extend `puppet_state_ok` with the interaction states the audit lists (0x708, 0x6a4,
   0x452), evidence from the setter decompile; verify with check_stance.py (and no "not on the safe list"
   line for them in the run logs).
4. Props in motion: send `PKT_PROPMOVE` with the collision body's own transform and apply it through the
   body's own setter (slot 5 of the CToeHoeEntity vtable 0x658384 = FUN_005ac670: position +0xcc..+0xd4,
   direction +0xd8..+0xe0, then slot 0x3c) instead of the raw +0x6c write.
5. Throw: search the decompile for the carry state's action before trying inputs.

## 2. Decompile notes

### 2.1 The chair attach/detach/break (OBSERVED, decompile)

* `FUN_00411f80` (chair vtable 0x653fdc slot 28, the attach the mod calls) sets chair+0xc4 = character,
  character+0x2bc = chair, then calls the CARRIER's vtable slot 0x48 (the state setter) with **300**
  (decompile 10247-10262) and disables the chair's collision body through its vtable slots 0x44/0x40.
* `FUN_00412010` (slot 29, detach) clears chair+0x14/+0x1c, character+0x2bc, and calls
  `FUN_005da5f0(chair+0x110, 1, world+0x1a0)` when +0x110 != -1 (10272-10290).
* `FUN_00412140` (slot 25, the game's own break) hides the mesh, spawns the "Splinter" effect
  (`FUN_00591230(0x42524348, ...)`, 10488), clears the drop's collected flag and +0x12c.
* State setter `FUN_004e3ed0` cases relevant to A1-4 (OBSERVED):
  - 0xa8c: plays the carry clip JMAO on the upper layer only (138552);
  - 0x6a4: stops the upper layer and clears +0x9b, then only clears `[+0x4a]+0x48` (138590);
  - 0x708: does NOTHING unless the held object is class 0x5350444f (138658), i.e. only a flag clear;
  - 0x452: plays clip CD25 on the upper layer (138782).
  None of the three has a gameplay side effect, so they are safe to add to the puppet's safe list; the
  owner's clip arrives in pkt_char.up and is played by `puppet_clip` anyway.

### 2.2 The prop's collision body (OBSERVED, byte-level)

The chair's +0x68 body is a `CToeHoeEntity` (check_breakables' RTTI dump). Its vtable is 0x658384
(COL 0x684d90 -> type descriptor 0x6a9ae8, which is `.?AVCToeHoeEntity@@`):

```
slot  0 0x449c00   slot  4 0x5ac630  slot  8 0x449be0  slot 12 0x5acf10  slot 16 0x5acf70
slot  1 0x5ac4b0   slot  5 0x5ac670  slot  9 0x5acda0  slot 13 0x5acf50  slot 17 0x5ac5a0
slot  2 0x5ac580   slot  6 0x5ac6f0  slot 10 0x5acf00  slot 14 0x449bf0  slot 18 0x5ae210
slot  3 0x5ac5d0   slot  7 0x449bd0  slot 11 0x5ace00  slot 15 0x5ad0a0
```

`FUN_005ac670` (slot 5) is the body's own transform setter (decompile 271865-271890): it writes
+0xd8..+0xe0 (direction, the third component 0) and +0xcc..+0xd4 (position, the z through slot 0x18),
then calls slot 0x3c. That is the "game's own transform setter" A1-3 needs; +0xcc is also what slot 7
(`0x449bd0`, `lea eax,[ecx+0xcc]`) hands out as "the position".

## 3. Measurements

### 3.1 Run 1 (chk54a = HEAD + diagnostics, UDP): the sequence, and what a break while carried does

`check_breakables.py`'s new `break-while-carried` phase ran 5× (host player 1 picks a chair up, walks 1.4 s
so the 500 ms carry heartbeat is in flight, swings it broken, both copies must stay alive):

```
  break-while-carried 1/5: carrying chair #7 @1bd1d920 ... enabled 1 broken 0 carrier 1a0486f0
  break-while-carried 1/5: broken on the owner after 0.50 s; partner copy STILL WHOLE (3.02 s) | frames host 21656->22387 guest 21221->22002 | alive [('host', True), ('guest', True)]
  break-while-carried 2/5: ... partner copy broken (0.33 s) | ... alive [('host', True), ('guest', True)]
  break-while-carried 3/5: ... partner copy broken (0.43 s) | ... alive [('host', True), ('guest', True)]
  break-while-carried 4/5: ... partner copy broken (0.12 s) | ... alive [('host', True), ('guest', True)]
  break-while-carried 5/5: ... partner copy broken (0.33 s) | ... alive [('host', True), ('guest', True)]
```

The silent death itself did NOT reproduce in 5 cycles (both copies ticked and answered after every
break), but cycle 1 exposed the mechanism that makes it possible. OBSERVED in the two logs:

```
host: prop broken here: CHAI id ???? ent 1bd1d920 at (-nan(ind),-nan(ind),-nan(ind)) carrier none drop none
guest: prop break never turned up in this level (announced 9 times)          (three times, same chair)
guest: prop carry never turned up in this level (announced 9 times)          (player 2 phase, same chair)
```

* the owner's copy of the chair that was broken WHILE CARRIED has its entity position at NaN (the game's
  own break, no mod write involved: the log line is the first scan that sees +0xa4 = 1);
* `prop_find` compares distances, and every comparison with NaN is false, so the three break packets
  that named that chair matched NOTHING on the peer (`prop break never turned up`), and the peer's copy
  stayed WHOLE for the rest of the session (the props dump at the end: host `#7 ... BROKEN`, guest
  `#7 ... whole`);
* the TASK 26 phase then had player 2 pick exactly that whole chair on the guest copy; its carry packet
  met a BROKEN chair on the host - the audit's crash case (a carry applied to a broken prop) - and was
  saved only by the same NaN (the host could not match it either).

So the A1-1 family is: a break of a carried prop leaves the owner's copy at NaN, the peer never learns the
break, and the next carry of that chair on the peer names a prop the other copy has broken. The fix
(4 guards, section 4) removes the broken-prop attach and keeps the announced position finite.

### 3.2 The effect relay on HEAD (OBSERVED, run 1)

```
breakables: sync host  ... | fx local 60 sent 58 rcv 96 played 103 dup 0 skipped 0 calls 61 | ...
breakables: sync guest ... | fx local 103 sent 96 rcv 58 played 60 dup 134 skipped 0 calls 240 | ...
host: effect from the peer played: CLL4 at (546.9,-59.0,-7.0) pos 1
host: effect from the peer played: HWLK at (536.6,146.9,-7.0) pos 1
```

The relay works both ways in normal play (58/96 effects sent and 60/103 played, each copy replaying the
other's tags at the streamed position, no duplicate played). `check_explosives.py` is the proof for the
explosion itself (run 3).

### 3.3 Push and carry-walk on HEAD (OBSERVED, run 1)

```
  carry-walk: 32 samples, 30 identical state+clips (94%); 32 samples in a non-locomotion carry state, 30 identical
    owner st 300 up CHAA lo WALK gait 0 | partner st 300 up CHAA lo WALK
    owner st 301 up CHAB lo LWAF gait 1 | partner st 301 up CHAB lo LWAF
  push: before: own (1146.1,-724.3,-11.9) | other (1145.9,-723.8,-11.9)
  push: after:  own (1137.8,-676.9,-11.9) moved 48.1 | other (1138.2,-678.6,-11.9) differs 1.7
  host : raw move of CHAI ent ... to (681.5,-840.2,-11.9): ok 12 bytes -> now (652.8,-841.7,-11.9) REVERTED (the physics body is the source)
  guest: raw move of CHAI ent ... to (666.6,-842.5,-11.9): ok 12 bytes -> now (646.4,-842.5,-11.9) REVERTED
```

The raw +0x6c write is still reverted (as TASK 53 measured), so the relay moved to the body setter; the
push converged on HEAD only because both copies simulate the push too. The two carry-walk misses are the
300->301 transition (the puppet is one send behind the owner).

## 4. The fix (chk54b)

* **A1-1, attach of a broken prop**: `prop_apply_carry` refuses an `ent` that is not a live prop of a known
  class or whose +0xa4 is set, and it detaches the held prop only when that prop's own +0xc4 points back
  at this character (a stale hand pointer is not passed to FUN_00412010).
* **A1-1, identity**: `prop_apply_packet` resolves a carry packet (kind 1) through the hand it is in when
  that hand's prop is within the packet's 400-unit radius, like kind 3 already did; prop_find (nearest
  same-class prop) is only the fallback for the first packet after a pickup.
* **A1-1, the NaN**: `prop_refresh` only stores a FINITE position, so a break announcement and a carry
  packet always carry a position the peer can match; `prop_move_tick` never streams a non-finite
  transform; `prop_apply_move` never writes one into the game; the carry sender falls back to the table's
  last finite position.
* **A1-4**: `puppet_state_ok` accepts 0x708, 0x6a4 and 0x452 (setter cases 138658, 138590, 138782; no
  gameplay path) - the owner's clip then plays on the puppet instead of it freezing in its old pose.
* **A1-3**: `pkt_propmove` (was declared, never used) carries the collision body's position (+0xcc) and
  direction (+0xd8); `prop_apply_move` applies them with the body's own setter FUN_005ac670 (body vtable
  0x658384 slot 5), verified by the slot address, and writes the entity +0x6c with it. `pkt_prop kind 4`
  is gone; NET_VERSION 28.
* **throw**: dropped - Obscure II has no throw control for a carried prop (section 5).

## 5. The throw control (OBSERVED, decompile)

A carried prop is a melee weapon: the action button swings it (GAME_MECHANICS, owner + guide), the
character state machine releases it when the swing ends (`case 0xa8d` -> the held object's slot 29 =
FUN_00412010 detach, then state 0; decompile 140706-140712), and that is all: `FUN_004c5c40`, the call the
chair's swing makes (FUN_00411420 line 9928), builds a controller/rumble word and calls FUN_004c5110
(decompile 120164-120200), not a physics impulse. No state or input gives a released prop a launch
velocity. The TASK 53 phase ("aim + attack") broke the CARRIED chair, exactly what the swing does; the
thrown-prop requirement is dropped (check_breakables now prints that line instead of trying inputs).

### 3.4 Run 2 (chk54b = the fix, UDP): the same 5 cycles, and the stance

```
  break-while-carried 1/5: broken on the owner after 0.30 s; partner copy broken (0.44 s) | ... alive [('host', True), ('guest', True)]
  break-while-carried 2/5: ... partner copy broken (0.32 s) | ... alive [('host', True), ('guest', True)]
  break-while-carried 3/5: ... partner copy broken (0.12 s) | ... alive [('host', True), ('guest', True)]
  break-while-carried 4/5: ... partner copy broken (0.32 s) | ... alive [('host', True), ('guest', True)]
  break-while-carried 5/5: ... partner copy broken (0.11 s) | ... alive [('host', True), ('guest', True)]
  push: before body: own (679.76,-854.88,-11.91 dir 1.00,0.00,0.00) | other (681.80,-855.49,-11.91 dir 1.00,0.00,0.00)
  push: after:  own (703.0,-858.5,-11.9) moved 23.6 | other (701.0,-859.5,-11.9) differs 2.3
  push: after body: own (703.05,-858.52,-11.91 dir 1.00,0.00,0.00) | other (700.97,-859.55,-11.91 dir 1.00,0.00,0.00)
stance OK (5 stance cycles each way)
```

The body's +0xcc equals the entity position on a whole prop (the first body_xf dump line), so the field is
the position the setter needs; the receiver's body followed the host's push to 2.3 units. That run still
failed two TASK 26 assertions because the carry-walk phase left the host's hand full and the next phase
took the already-carried chair for its target; the check now releases the chair at the end of carry-walk
(no mod change).

### 3.5 Run 3 (chk54b, UDP): effects and breakables together

```
== check_explosives.py
   BOY1: partner effect calls played +12 (owner local 71 sent 62), WDEX replays seen 1
   BOY1: partner effect calls played +29 (owner local 100 sent 91), WDEX replays seen 1 nearest (-554.0,-99.7,8.4)
   BOY1: state match 100%  clip match 89%  (yes threw)  life owner 100.0 puppet 100.0
copies: [('host', True), ('guest', True)] | crash lines since the start: 0
explosives OK
...
  break-while-carried 5/5: ... alive [('host', True), ('guest', True)]   (all five, from section 3.4)
  push: after:  own (1036.4,-453.6,-11.9) moved 10.0 | other (1031.5,-450.3,-11.9) differs 5.9
breakables OK (chairs picked up, swung and broken on both copies; 2 chair(s) checked)
```

No `prop break never turned up`, no `prop carry never turned up`, no `prop carry refused` and no `puppet:
state ... is not on the safe list` line in either copy's log of run 3.

### 3.6 Run 4 (chk54c, plain loopback, checks in the task's order): the stance order effect

`check_explosives.py` PASSed again (WDEX replayed to the partner, +9 and +7 effect calls, 0 crash lines),
`check_breakables.py` PASSed again (5/5 cycles, alive; carry-walk 30/32; the guest's carry and break both
reached the host), but `check_stance.py` FAILED on BOY1 in the same session:

```
-- BOY1: baseline on its own copy state 0 up PAUS lo WALK w 82/85 | partner copy state 0 up PAUS lo LPAU w 82/85
   cycle 1/5: owner    ['0/PAUS/WALK']
   cycle 1/5: partner  ['0/PAUS/LPAU']
   ... (all five cycles identical: the owner never left state 0)
```

OBSERVED cause: `check_explosives.py` ends by consuming BOY1's only throwable (DYNA was the only
throwable in the save) and leaves the hand EMPTY, so LB cannot enter the aim stance any more - the owner's
own copy never changes state, and the two copies then differ only in the locomotion lower clip (WALK vs
LPAU). The same check order failed the same way at TASK 53 (run_s53_b1.log, "BOY1 ... ['0/PAUS/WALK'] |
partner ['0/PAUS/LPAU']"); run 2 (breakables then stance, hand full) and the final run (stance first)
pass. This is a test-order artifact, not a mod bug; the final proof runs the stance check before the
explosives check.

### 3.7 Runs 5/6 (chk54c on the steam-like relay): the check timing, and a push that the receiver's own physics moved

Run 5 (`OBSCOOP_LINK=steam sh tests/run_pair_menu.sh ... check_stance.py check_explosives.py
check_breakables.py`): stance OK, explosives OK (WDEX replayed), breakables failed once:

```
  TASK 53: both copies in J002 (11 props each)          <- the guest's world was still NOT in normal play
  carry-walk: 32 samples, 4 identical state+clips (12%)
  push: attempt 1: ... own (1199.5,-700.0,-11.9) moved 0.0 | other (1220.5,-699.7,-11.9) differs 21.0
  push: attempt 2: ... own (1192.6,-734.0,-11.9) moved 11.2 | other (1224.0,-714.1,-11.9) differs 37.2
  breakables FAIL:
  - carry-walk: the partner plays a different animation while the owner walks carrying (4/32 identical)
  - push: the pushed prop is not in the same place on both copies (37.2 units apart)
```

OBSERVED causes, both outside the mod's sync logic:
* the guest's build of J002 kept its world out of normal play for 26.6 s after the level tag was already
  J002 (`puppet: driving the peer's character again after 26641 ms (was: world state)`), and the puppet is
  (correctly) not driven while the world is not normal - the carry-walk compared a gated copy's old pose.
  The check now waits for `world+0x11c == 1` on both copies after the level load.
* the receiver's copy of the pushed prop was shoved 21 units by the PUPPET's own collision body (the
  host's copy never touched the prop), and nothing ever corrected it: on that copy `prop_own_here` is
  false (the owner is the sender), so it does not stream, and the sender only sent when its own prop
  moved - which it did not. Result: 37 units apart after the next attempt. Fixes in the mod: `prop_own_here`
  now gives the host the tie (two characters about equally close used to leave BOTH copies as receivers,
  i.e. no sender at all), and `prop_move_tick` re-sends every prop it owns once a second even when the
  prop did not move (Obscure 1 `host_send_props` did the same). The check also waits 2 s after the walk so
  the 1 Hz heartbeat lands.

### 3.8 Check-side changes in this task (tests only)

* new `break-while-carried` phase (5 cycles, both copies alive/ticking/agreeing after each break);
* `task53_level` waits for normal play on both copies (`world+0x11c == 1`), not only the level tag;
* carry-walk first waits until the partner mirrors the carry pose (the puppet can be gated right after a
  load), and gives the hand back at the end (otherwise the next phase takes the already-carried chair);
* push retries up to three positions and fails (instead of silently skipping) when the prop never moves;
* the throw phase is a note that no throw exists (section 5);
* the body transform (`ent+0x68: +0xcc`, direction `+0xd8`) is printed for every prop, so the field the
  relay uses is visible in the output.

### 3.9 Run 7 (chk54d): the body setter reverted too - the game's real setter is the ENTITY's slot 34

chk54d added the 1 Hz heartbeat and the host-wins tie; the stance and explosives checks passed again, and
the push failed once more:

```
  push: attempt 1: ... own (1169.5,-501.0,-11.9) moved 2.5 | other (1162.8,-478.4,-11.9) differs 25.2
  breakables FAIL:
  - push: the pushed prop is not in the same place on both copies (25.2 units apart)
```

The new log line shows WHY (§4's body setter was wrong): every second the receiver applied the sender's
position and the game put it back, on both copies at once:

```
guest: prop move: 1a5d5220 corrected by 25.2 units (1162.8,-478.4,-11.9 -> 1171.8,-501.9,-11.9)   (repeated every second)
host:  prop move: 1aa74008 corrected by 25.2 units (1171.8,-501.9,-11.9 -> 1162.8,-478.4,-11.9)
```

So the collision body's own +0xcc (written through body vtable slot 5, FUN_005ac670) is a CACHE the physics
overwrites as well. The engine's real "move this entity" is the ENTITY's vtable slot 34 (bytes +0x88),
FUN_00402930 (chair vtable 0x653fdc slot 34 = 0x402930, OBSERVED in the dump; it is the function the base
entity update FUN_00402260 calls through slot 0x88):

```
  *(float *)(in_ECX + 0xcc) -= *(float *)(in_ECX + 0x6c);   // body follows the delta
  ...
  *(float *)(in_ECX + 0xcc) += *param_1;
  *pfVar1 = *param_1; ...                                    // entity position +0x6c
  FUN_005d2cd0(&local_20);                                   // mesh node +0x34
  (**(code **)(*(int *)(in_ECX + 0x68) + 0xc))(pfVar1);      // the BODY's slot 3 gets the position
  (**(code **)(*(int *)(in_ECX + 0x38) + 0x54))(pfVar1);     // the +0x38 node's slot 0x54
```

`prop_apply_move` now calls that slot (only when vt[34] is exactly 0x402930) and writes the facing +0x78
with it; `prop_xf` streams the entity position again (the body's +0xcc is only a cache). The check's push
retries up to three approaches and waits 2 s for the heartbeat.

### 4b. Final implementation (chk54e = the final DLL)

src/net.c:
* NET_VERSION 28; `pkt_propmove` = { level, cls, id, pos[3] (entity +0x6c), dir[3] (facing +0x78) }.
* PKT_PROPMOVE is dispatched for BOTH roles (host receives the guest's pushes too).

src/sync.c:
* **A1-1 guards**: `prop_apply_carry` refuses a broken / non-prop `ent` (deduped log line
  `prop carry refused: ... is broken or not a prop any more`), and detaches only a held prop whose
  +0xc4 points back at the character. `prop_apply_packet` resolves a KIND 1 carry through the hand
  (when its position is within prop_find's 400-unit radius of the packet's) before prop_find.
* **A1-1 NaN policy**: `prop_refresh` keeps only a finite +0x6c in the table (so announcements and
  matching always carry a usable position); `prop_xf`/`prop_apply_move`/the carry sender refuse
  non-finite values; the carry sender falls back to the table's last finite position.
* **A1-4**: `puppet_state_ok` now accepts 0x708, 0x6a4 and 0x452 (setter cases 138658/138590/138782, no
  gameplay path); the owner's clip then plays through `puppet_clip` instead of the puppet freezing.
* **A1-3**: `prop_move_tick` streams a moved prop's entity position/facing (PKT_PROPMOVE) and re-sends
  every owned prop once a second even when it did not move; `peer_on_propmove`/`peer_apply_moves` queue
  and apply it on the game thread through the entity's own setter FUN_00402930 (vtable slot 34, only when
  the slot is exactly that function); `prop_own_here` gives the host the tie so exactly one copy is the
  sender; `pkt_prop kind 4` and its raw +0x6c write are gone.
* diagnostic lines kept for this bug family: one per carry apply (not per packet), an entry per detach /
  attach with the game call, one per large (>20 units) prop correction, and `hang_phase` markers around
  every game call of the prop path.

tests/check_breakables.py: `break-while-carried` phase, normal-play wait, carry-walk release + puppet
readiness, push retries, no throw phase, body transform in the dump (§3.8).

## 6. What is proven and what is not

PROVEN on chk54e (steam-like relay, OBSCOOP_LINK=steam):
* check_stance.py PASS (5+5 cycles, the partner shows the owner's state and both clips and returns idle);
* check_explosives.py PASS (DYNA throw, a WDEX replay on the partner, +effect calls, 0 crash lines);
* break-while-carried 5/5, both copies alive and agreeing after every break (runs 2, 3, 6, 7, 8);
* carry-walk 30-31/32 identical, the TASK 26 chair phases (pickup/carry pose/mesh follow/break/drop) on
  both players; the final run's only failure is the pushed-prop distance below.

NOT PROVEN / FAILING:
* A1-3's "a pushed prop ends within 10 units on both copies": the relay, the game's own setter, the 1 Hz
  heartbeat and the single-authority rule are in place and the receiver calls the setter (log: corrections
  of 20-150 units every second), but the props still drift apart in the lossy runs (2.3 / 5.9 units in two
  loopback runs; 25.2 / 37.2 / 149.9 units on the relay). OBSERVED: the correction is undone within one
  second on BOTH copies - entity +0x6c, collision body +0xcc and mesh stay where the local physics put
  them, so the write (raw +0x6c, body slot 5, or entity slot 34) does not survive the physics step of a
  DYNAMIC prop. The next place to look is the Havok body's velocity/pose API (the body's slot 3 the
  setter calls is not enough), or freezing the prop's simulation on the receiver while the peer owns it.
* The exact silent death of the 2.1 guest was not reproduced in 5+5 cycles (both copies survived); what
  was reproduced is its precondition (a broken carried chair staying whole on the peer + a NaN position
  that no announcement can match) and that is fixed (runs 2/3/6/7/8: every break now reaches the peer).
