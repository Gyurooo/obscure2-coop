# FINDINGS 38 — the post-load scripted-event crash, the guest pause-close, the watchdog on loads, two timing checks (TASK 38)

Labels: **OBSERVED** = printed by a run/check or read in the decompile/disassembly with a file:line or an
address; **DERIVED** = follows from the cited code but was not seen live; **GUESS**; **UNKNOWN**.
Base: `cb76aeb` (TASK 37: ordered host-authoritative transitions, protocol 20). No packet layout changes
in this task, so `NET_VERSION` stays 20.

## 1. The crash after a load + scripted event (item 1)

### 1.1 The report is a NULL receiver, not a stale vtable

The TASK 37 soak-2 report (`run_s37_soak2.log:243-260`) has `eax 00000000`, `ecx 19d41770`,
`params 00000001 00000008` (a **write** to address **0x8**), `eip Obscure2.exe+0xf16a9`. OBSERVED
(disassembly of `obscure2-test/Obscure2.exe`, the same build 215294):

```
4f16a0:  push %ebp
4f16a1:  mov  %esp,%ebp
4f16a3:  mov  0xc(%ebp),%ecx
4f16a6:  mov  0x8(%ebp),%eax
4f16a9:  mov  %ecx,0x8(%eax)      <-- fault: eax = 0
4f16ac:  test %ecx,%ecx
4f16ae:  je   0x4f16b8
4f16b0:  mov  (%ecx),%edx
4f16b2:  push %eax
4f16b3:  mov  0xc(%edx),%eax
4f16b6:  call *%eax
```

So `FUN_004f16a0(human, controller)` does `human->+8 = controller; if (controller) controller->vtbl[3](human)`.
The fault is `human == NULL`: the *first argument* of the call, not a dead object (TASK 37's "vtable call
on a dead object" was wrong; the vtable call would be the next line and never ran).

### 1.2 The call site: the world's state-7 (scripted event) branch

The crash report's stack (`[ebp+4]`) starts with `Obscure2.exe+0xb5b29`, i.e. VA 0x4b5b29. OBSERVED
(disassembly at 0x4b5b05):

```
4b5b0b:  mov 0x175c(%esi),%ecx      ; ecx = world+0x175c (the character manager)
4b5b11:  mov (%ecx),%eax
4b5b13:  mov 0x1c(%eax),%eax        ; eax = manager vtable slot 7
4b5b16:  add $0x764,%edx            ; edx = world+0x1748 + 0x764 (input controller 2)
4b5b1c:  push %edx
4b5b1d:  mov 0x174c(%esi),%edx      ; edx = world+0x174c (the teammate controller)
4b5b23:  mov 0x4(%edx),%edx         ; edx = its character  <-- 0 in the crash
4b5b26:  push %edx
4b5b27:  call *%eax
4b5b29:  ...                        ; the return address in the report
```

and the decompiled world update (decompile 110467-110476, inside the `world+0x12c == 7` branch - the
scripted event / noe scene, the same state the task names):

```
else if (*(int *)(in_ECX + 0x110) == 1) {          /* sub-state of the state-7 branch */
    iVar7 = FUN_004b2b30(9, *(undefined4 *)(*(int *)(in_ECX + 0x1748) + 0x14));
    if ((iVar7 != 0) || (iVar7 = FUN_004b2b30(9,0x50), iVar7 != 0)) {     /* the skip key */
        (**(code **)(**(int **)(in_ECX + 0x175c) + 0x1c))(
                *(undefined4 *)(*(int *)(in_ECX + 0x174c) + 4),           /* teammate character */
                *(int *)(in_ECX + 0x1748) + 0x764);                       /* input controller 2 */
        FUN_004d8130();
        (**(code **)(**(int **)(in_ECX + 0x174c) + 0xc))(0);
        ...
        *(undefined4 *)(in_ECX + 0x11c) = 1;                          /* back to normal play */
```

DERIVED: the vtable slot 7 at runtime is `FUN_004f16a0` (the crash proves the callee; the three manager
descriptor tables in `.rdata` at 0x667060/0x6670a8/0x667100 begin with it at slot 0 and are the same
family). OBSERVED: the register state matches the call exactly - `ecx` = 0x19d41770 = the controller
pointer (second argument), `eax` = 0 = the teammate character (first argument).

### 1.3 Why it is OUR null: `teammate_unlink` (TASK 35)

`src/sync.c:121` `teammate_unlink()` writes `0` into `*(world + 0x174c + 4)` - **exactly the first
argument of that call** - to keep the game's "stop what the other character is doing" sweep
(`FUN_0042ad70`) from cancelling player 2's door use. `attach_player2()` calls it every 500 ms on the
guest (sync.c:172) and both door paths call it right before the game's door call. OBSERVED in the logs of
every run: `teammate controller: unlinked GIR1 (it is player 2's own character; ...)`.

So the sequence of the crash is: a guest world in which GIR1 is unlinked (any earlier attach_player2) +
the level's scripted event (world state 7) + a skip key (the mod's own scene sync presses ESCAPE when the
peer left the event, or the player presses it) -> the game's skip path attaches the *null* teammate
character to controller 2 -> write to address 8. **The mod causes it.** TASK 37's "not in this task's
diff, `heal 0`, no pulse, no door use" was right about *that* diff but missed that the null comes from
TASK 35's unlink, which is always in effect on the guest.

### 1.4 The fix

The unlink is only valid while this copy is in **normal play** (that is the only place the teammate sweep
can cancel a door use). `hk_game_update` now brackets the game's own update:

* before it, `teammate_game_guard(game, 1)`: if the copy is NOT in normal play (mode != 1, no world, or
  `world+0x11c != 1` / `world+0x12c != 0` - a load, a menu, a scripted event) and the pointer is 0, the
  teammate character is put back;
* after it, `teammate_game_guard(game, 0)`: back in normal play, the character is taken off again.

"Normal play" deliberately ignores `game+0x320`: a pending request (the `ChangeLevel` a door use just
started) is still the same world with the door use running in it, and restoring the teammate there would
let the sweep stop that door again (the TASK 35 bug). So the restore happens only where the world is not
playable. `attach_player2` also only unlinks while the copy IS in normal play, so the pointer is never
taken away in the middle of a menu/load frame (the guard has just put it back for the game there).

A rebuilt world (a new `game+0x378`) forgets the remembered character: the game's own pointer there is
the game's own business and `attach_player2` re-unlinks the new partner. The `sync` line gains
`teammate restores N`.

The guard runs on the game thread, in the same update as the game's world update, so the skip branch
always sees a real character. The door fix is untouched: in normal play the pointer is 0 at the end of
every frame.

### 1.5 Repro and live proof

`tests/repro_load_scene.py`: N iterations of "host loads game0/game3", wait for both copies in one level,
wait for the scripted event (state 7) on either copy, press the game's own skip (ESCAPE) on the copies in
it, wait for the world to leave the event, then require: both processes alive, both game threads' frame
counters rising, and no new `FATAL EXCEPTION` / `GAME THREAD STALLED` line in either log.
(Live results in §5.)

## 2. The guest's pause-close (item 2)

OBSERVED (`run_s37_menus.log:203-205`): after `press(GP, 0, 'START')` both copies stayed at `st 5`, the
host's menu line showed `pulses 1 correct 1` and the guest's `pulses 0`. The pause menu reads **player
1's** pad; the guest's START travels to the host, where `g_pause_pulse_until` pulses START on player 1
(120 ms) - the guest's own copy has no such pulse, it can only converge after `MENU_SETTLE_MS` +
`MENU_STABLE_MS` (~1.1 s) *if* the host actually closed. In that run the host did not close either
(the 120 ms pulse lost a race with the game's own menu debounce), so both stayed open until the check's
6 s timeout.

Fix (DERIVED, then live): `drop_remote_start` (obscoop2.c) counts every **rising edge** of player 2's
START (`g_p2_start_edges`) before dropping the bit; `menu_tick` (sync.c) turns an edge seen while a
shared menu is up into the same `menu_pulse(0, 0x0010, ...)` the convergence uses, **on the copy where
the edge happened**. It is an edge, not a held bit, so the press that *opened* the menu can never close
it again, and both copies close within one frame instead of waiting for the host or the convergence.
The 120 ms host pulse stays (it is what opens the menu from normal play).

## 3. The watchdog on loads (item 3)

`hang.c` reported any 3 s without a frame. A level load stops the frame loop for seconds by design
(the reviewer's 3.2 s, TASK 37's 8.4 s report was a dead thread, but the 3.2 s one recovered). The
watchdog now samples the game state itself (`hang_game_loading()`: no world / mode != 1 / `game+0x320`
request pending / `world+0x11c != 1` / `world+0x12c != 0`) and, while a load is in progress, keeps the
stall clock at "now" instead of counting. A frame counter that stands still for `HANG_LOAD_MAX_MS`
(30 s) **is** reported even while loading, so a load that wedged the thread is still visible. Real stalls
in normal play are reported exactly as before.

## 4. The two timing checks (item 4)

* `check_attack_anim.py`: the game's aim stance is a family - `0x64` (FINDINGS_22) and `0x66` (TASK 37 saw
  0x66 on both copies for a whole phase; FINDINGS_23 saw 0x66 in the stance's first frames). The check
  accepts both, requires the stance on both copies and the copies to agree sample by sample (>= 90 %, a
  transition sample may land on either side), and accepts an attack that adds no state of its own when
  both copies agree. Cross-talk and a non-zero base still fail.
* `check_movement.py` phase D: the old phase drove the host pad **forward** (from the end of phase B:
  blocked after 19.5 units) and the guest pad **sideways** (blocked immediately: 0.0 units) - both
  characters were pushing into walls (`run_s37_reg_all.log:276-280`). Phase D now uses the same legs as
  phases B and C (forward 3 s, then sideways 2 s) with **both pads at once**, which is what the phase
  tests; each character moves on a leg that is free from where it stands.

## 5. Live evidence

### 5.1 Repro loop (`tests/repro_load_scene.py`)

Three runs of 10 loads each on the two test saves (game0 = I100, game3 = J002), with a walk after every
load and the game's own skip pressed on any copy that enters the scripted event:

| run | dll | result |
|---|---|---|
| `run_s38_repro1.log` | `chk38a.dll` (guard, menu edge, watchdog) | `repro PASS (10 iterations)` - no crash, no stall, both game threads running in all 10 |
| `run_s38_repro2.log` | `chk38b.dll` (main-menu load flow) | `repro PASS (10 iterations)` |
| `run_s38_repro3.log` | `chk38b.dll` (walk 4 directions) | `repro PASS (10 iterations)` |

**Limitation (OBSERVED, stated plainly):** in these runs the level's scripted event never appeared
(`scene none` in every iteration; the only `scene:` lines in the game logs are B101's new-game intro,
state 6). So the state-7 branch itself was not re-entered live; the loop proves the load cycle (30 loads
in three runs) is clean, not that the game's skip path was exercised. The crash's cause and the fix are
proven by §1.1-1.4 (the exact NULL, the exact call site, the field `teammate_unlink` writes) and by
`check_menus.py`'s new assertion (§5.2), which reads the very pointer the game dereferences: the guard
puts the character back while a menu is up and takes it off again in normal play.

### 5.2 Soak

| run | dll | result |
|---|---|---|
| `run_s38_soak1.log` | `chk38b.dll` | **FAIL**: iteration 16 split (`J002/I100 (30.0s, NOT one level)` - the TASK 37 race, not this task) and the guest's game thread froze at frame 3723 during the iteration-10 door phase: a fault at `Obscure2.exe+0x192f50` (the game's file/parser code, `ecx` = 1 as the file object) inside a level load started by the mod's door replay, swallowed by the game's own SEH, then a wait forever. `check_doors` then failed (`NOT back in one level`). |
| `run_s38_soak2.log` | `chk38d.dll` | **soak body PASS**: `soak OK (30 location changes, both copies alive)`, every iteration one level, race A/B one level, `settled: level I010/I010, quiet for 3.0 s`, both game threads running, **0 FATAL EXCEPTION lines and 0 stall reports on both copies** (no load stall was reported, item 3), `check_attack_anim` PASS (stance 0x64 on both), `check_controls` PASS. The run still printed `=== soak run: FAIL` because the trailing `check_doors.py --reset game3.sav` guest phase found no door 1.3 s after the reset load (`GUEST FAIL: no door in this level`) - fixed in `check_doors.py` (the door scan now retries for up to 12 s while the world fills, like the existing `usedoor` retry). |

**About soak 1's freeze (OBSERVED + DERIVED):** `chk38b`'s guard also treated a pending REQUEST
(`game+0x320 != 0`, the `ChangeLevel` a door use has just started) as "not normal play" and put the
teammate character back before the next game update. The guest's `usedoor` replay is exactly such a case:
the door's ChangeLevel sets the request, and the next update would have restored the teammate while the
door use was still running - the TASK 35 sweep condition again. The fault stack is the game's file/parser
code inside the level load the door started, so the link is **DERIVED, not proven**. The narrowed guard
(`chk38d`: only a menu / a load / a scripted event restores the character; a pending request does not)
ran 30 iterations with 6 door phases and never froze. That is the reason for the narrowing, and it is
also what keeps the TASK 35 door fix intact.


## 6. Process budget

| runs | processes |
|---|---|
| TBD | TBD |

## 7. DONE / NOT DONE / UNKNOWN

(filled in at the end)
