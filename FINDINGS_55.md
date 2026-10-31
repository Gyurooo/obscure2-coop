# FINDINGS 55 — the partner's legs stay on the aim clip after the stance; pushed props drift

Labels: **OBSERVED** = printed by a run/check in this task or read in the decompile (address cited);
**DERIVED** = follows from the cited code but was not seen live; **GUESS**; **UNKNOWN**.
Base: HEAD 7fb7fdd (TASK 54 WIP, protocol 28). Decompile `local\decomp2\Obscure2.exe.c` (build 215294).

## 0. The reproduced stance failure (OBSERVED, `_archive/claude_verify_54_fx.log`, quoted by TASK 55)

```
-- BOY1: baseline on its own copy state 0    up PAUS lo WALK w 82/85 | partner copy state 0    up PAUS lo LPAU w 82/85
   cycle 1/5: owner    ['0/PAUS/WALK']
   cycle 1/5: partner  ['0/PAUS/LPAU']
   cycle 1/5: after release owner state 0    up PAUS lo WALK w 82/85 | partner state 0    up PAUS lo LPAU w 82/85 -> NOT IDLE
```
(BOY1 never entered the stance in those cycles - check_explosives had emptied its hand, the TASK 54 §3.6
artifact - so what the check measured is the state the AIM STANCE MIRROR LEFT BEHIND on the puppet.)

## 1. Why the puppet's lower layer never comes back (OBSERVED, decompile)

* the lower-body clip index is `character+0x224` (`in_ECX[0x89]`), the upper one `character+0x220`
  (`in_ECX[0x88]`, the state setter's); the animation table is `+0x210`, stride 0x28, tag at entry+0xc.
* the ONLY writer of `+0x224` for a human is the gait function `FUN_004e7420` (CCharacterHuman vtable
  slot 0x4c, decompile 139599-139621). It maps the GAIT INDEX (character+0x2e0) to a clip and stores the
  index slot 0x68 returns:
  ```
  case 0: uVar2 = 0x4c504155 ('LPAU'); case 1: 'LWAF'; case 2: 'LWAB'; case 3: 'LWAR'; case 4: 'LWAL';
  iVar1 = (**(code **)(*in_ECX + 0x68))(uVar2, -1, 0, 1.0);
  in_ECX[0x89] = iVar1;                       // 139616: +0x224
  ```
  `LPAU` is gait 0 (paused), i.e. what the game plays when the legs do not move - NOT a leftover per se.
* the state setter `FUN_004e3ed0` case 0 plays `PAUS` into the UPPER layer only; case 100 (aim) does not
  touch the lower layer either. So the state setter cannot restore the legs.
* the movement machine calls the gait function only in the aim/attack branch (decompile 142194-142199:
  `if (in_ECX[0xb8] != local_9c) { stop(+0x224 clip); slot 0x4c(new gait); }`). The LOCOMOTION cases
  (0/1/2/4, decompile 142018-142075) never call it - they only request states and let the state setter
  play the upper clip.
* the mod's `puppet_gait` (sync.c, TASK 46) mirrors the gait, but ONLY while the puppet's own state is
  an aim or carry state (`puppet_aim(st) || puppet_carry(st)`). When the owner leaves the stance the
  puppet's state becomes 0 and the mirror stops, leaving `+0x224` on whatever the aim stance set (LPAU)
  for good: the owner's own copy picks its normal lower clip again (`check_stance`'s `lo WALK`), the
  puppet's does not.
* the owner's `WALK` on the lower layer is the game's base locomotion clip: `+0x224 == 0` (never set by
  the gait function) reads as the table's first entry, `WALK` - measured by check_stance on the owner's
  own copy at baseline and after every release, on BOTH characters (`GIR1 ... 0/PAUS/WALK` on both copies
  before its first stance, `_archive/claude_verify_54_fx.log`).

### The fix (chosen)

Stream the LOWER clip TAG the owner is playing (`animtable[+0x224]+0xc`) with pkt_char, and apply it on
the puppet through the same two calls the game's gait function makes (stop the old clip with slot 0x6c,
play the new tag with slot 0x68, store the returned index in `+0x224`) whenever it differs. That is the
task's "the legs always follow the owner's lower clip":
* it covers the stance exit (owner back on `WALK` -> puppet plays `WALK`),
* it replaces the gait-index approximation (LPAU/LWAF/LWAB/LWAR/LWAL was only the 5-clip subset the
  machine knows; the owner's real lower tag is streamed now, so a carry gait or a special lower clip
  cannot be missed),
* the "only when the tag changes" guard keeps the game's own clock running (same rule as puppet_clip).

## 2. Pushed props (A1-3): what TASK 54 left

TASK 54 measured (`FINDINGS_54` §3.5/3.9): the position is owned by the physics simulation; the entity
setter FUN_00402930, the body setter FUN_005ac670 and a raw +0x6c write are all undone within a second.
New OBSERVED in the TASK 54 run 7 log (both copies, every second):

```
guest: prop move: 1a5d5220 corrected by 25.2 units (1162.8,-478.4,-11.9 -> 1171.8,-501.9,-11.9)
host:  prop move: 1aa74008 corrected by 25.2 units (1171.8,-501.9,-11.9 -> 1162.8,-478.4,-11.9)
```

The two numbers are the mirror images: BOTH copies apply the OTHER's position to their own prop, i.e.
`prop_own_here` (the "the character nearest the prop owns it" rule) answers "peer" on both sides for
the same prop. The 1-unit hysteresis is too small - the two copies' props are 25 units apart, so each
copy's own character is nearer to its own copy of the prop. That is the actual drift mechanism on a
lossy link: a ping-pong, not a slow physics divergence.

Two more pieces, both measured in TASK 54's runs and re-read in the decompile here:
* a prop is pushed by a character through its COLLISION BODY (`entity+0x68`, `CToeHoeEntity`), which
  registers itself in the character-collision grid; the game turns that off for a carried chair with
  `body vtable slot 0x44(0)` = `FUN_005ac5a0` (decompile 10260-10262 inside `FUN_00411f80`). `FUN_005ac5a0`
  is the enable flag +0x2c: on -> slot 0x3c enters the grid, off -> slot 0x40 leaves it (both decompiled:
  q_5ac5a0 / q_5ad0a0 / q_5acf70). A body that is out of the grid is pushed by no character.
* the entity setter `FUN_00402930` (which TASK 54 already uses) calls the body's slot 3 (+0xc) = q_5ac5d0,
  which calls slot 0x40 and then slot 0x3c - and slot 0x3c is GATED on the enable flag +0x2c. So a body
  disabled through slot 0x44 stays out of the grid while the streamed transforms keep being applied.

### The fix (chosen, A1-3)

* **Host authority** (Obscure 1 `host_send_props`): `prop_own_here` returns `g_role == 1`. The host streams
  every prop that moves; the guest never streams a prop transform and always applies the host's. This
  removes the ping-pong by construction.
* **Freeze on the receiver**: the guest calls the body's enable with 0 (`FUN_005ac5a0`, vtable slot 0x44),
  so its own physics cannot push the prop away from the streamed transform, and enables it again when it
  is no longer involved. Two triggers: `pkt_propmove.moving` (1 only on a packet whose prop really moved,
  0 for the 1 Hz heartbeat) sets a 700 ms lease; and a prop within 3 units of ANY human on this copy is
  frozen too (see 3.5 - the peer's character is a teleporting body there and ejects props the host never
  moved). Props nobody is near are never frozen, so the guest's world runs normally elsewhere.

## 3. Runs

### 3.1 Control: the NEW check on the OLD DLL (m54.dll, TASK 54 final) — the reported bug, reproduced

`OBSCOOP_LINK=steam sh tests/run_pair.sh <m54.dll> check_explosives.py check_stance.py` (`run_s55_ctrl54b.log`):

```
-- BOY1: baseline on its own copy state 0    up PAUS lo WALK w 82/85 | partner copy state 0    up PAUS lo LPAU w 82/85
   right after the previous check (its throw/attack): owner state 0    up PAUS lo WALK w 82/85 | partner state 0    up PAUS lo LPAU w 82/85 -> DIFFERENT
...
   FAIL: BOY1: right after the previous check (its throw/attack) (partner state 0    up PAUS lo LPAU w 82/85, owner state 0    up PAUS lo WALK w 82/85)
stance FAIL (5 stance cycles each way)
```

That is the reviewer's line from TASK 55, same clip tags and the same `w 82/85`. The trigger is the sequence
the reviewer ran: check_explosives ends with a weapon selection and a throw, the owner's own copy ends on
the base lower clip (`WALK` = table index 0), the puppet keeps the aim stance's `LPAU` - and nothing in
TASK 54 ever plays a lower clip on the puppet again.

### 3.2 The check (tests/check_stance.py, TASK 55 changes)

* **`agree(side, who, label)`**: both copies must show state 0 AND the same upper and lower clip tags;
  called (a) right after the previous check (the state the reviewer's log failed on) and (b) after the
  check's own throw/attack warm-up.
* **`warmup_sequence`**: two swings from the stance plus a throw when the hand holds a throwable - the
  throw/attack sequence TASK 55 asks the check to run before the stance cycles.
* **`pick_weapon` / `stance_reachable`**: D-pad-steps the weapon slot until LB actually enters the stance.
  TASK 54's run failed for a test reason too: check_explosives leaves the emptied DYNA slot SELECTED and
  LB then enters no stance at all (`owner ['0/PAUS/WALK']` in every cycle).


### 3.3 The FIX on the final DLL (chk55b) - the same state now agrees

`OBSCOOP_LINK=steam sh tests/run_pair.sh <chk55b.dll> check_explosives.py check_stance.py`
(`run_s55_c1.log`): the very state the control run failed on, now:

```
-- BOY1: baseline on its own copy state 0    up PAUS lo WALK w 82/85 | partner copy state 0    up PAUS lo WALK w 82/85
   right after the previous check (its throw/attack): owner state 0    up PAUS lo WALK w 82/85 | partner state 0    up PAUS lo WALK w 82/85 -> same
   after the throw/attack: owner state 0    up PAUS lo WALK w 82/85 | partner state 0    up PAUS lo WALK w 82/85 -> same
...
stance OK (5 stance cycles each way)
explosives OK
```

The puppet's lower clip is `WALK` at the moment the owner's is (`g_pb_lows` counted the change; the
`sync` line now prints it). GIR1's five stance cycles went through `100/CSLK/LPAU` and back, matching on
both copies.

### 3.4 One check correction (check_explosives.py) - with the numbers

`run_s55_b1.log` / `run_s55_b2.log` failed check_explosives with

```
   BOY1: partner effect calls played +0 (owner local 142 sent 136), WDEX replays seen 1 nearest (-594.4,-43.8,195.3)
   BOY1: state match 100%  clip match 100%  (NO threw)
   FAIL: BOY1 throw 2: the partner copy played no effect of the thrower
```

The iteration is a NO-THROW one (the test save holds one DYNA; the second iteration re-selects the empty
slot). The effects it was asking for were the FIRST throw's blast, replayed by the partner copy at
01:34:54.911-01:34:55.927 (`obscure2-test2/obscoop.log`: `effect from the peer played: WDEX at
(-594.4,-43.8,195.3)` plus 15 more), i.e. inside the throw-1 window that already counted them (+19). The
"played" and "no WDEX" assertions now run only for an iteration that actually threw (`threw`); a real
throw still has to produce effects on the partner.

### 3.5 Props (A1-3), run 1: the lease-only freeze is NOT enough (OBSERVED, `run_s55_push1.log`)

`OBSCOOP_SLOT=3 sh tests/run_pair_menu.sh <chk55b.dll> check_breakables.py` (plain loopback), push phase:

```
  push: attempt 1: ... safe tp at 55 units ...
  push: before: own (749.4,-545.2,-11.9) | other (749.5,-545.3,-11.9)
  push: after:  own (749.4,-545.2,-11.9) moved 0.0 | other (747.8,-575.0,-11.9) differs 29.8
  push: the prop did not move on the host in this position - another approach
  push: attempt 2: ...
  push: before: own (719.6,-556.8,-11.9) | other (747.8,-575.0,-11.9)
  push: after:  own (729.6,-556.1,-11.9) moved 10.0 | other (738.1,-620.4,-11.9) differs 64.9
breakables FAIL:
  - push: the pushed prop is not in the same place on both copies (64.9 units apart)
```

The two copies START level (before attempt 1: 0.1 units apart) and the guest's copy then moves the
prop 30 units while the HOST's own copy does not move it at all (`moved 0.0`) - so no move packet is
sent and the lease never starts: the receiver's own physics is free to push it. The owner's counters say
the same (`prop sent 818 rcv 154 applied 154 ... moves 0 freezes 0` on the host, `... applied 487 moves
564 freezes 15` on the guest: the host streams, the guest applied 564 transforms and froze 15 times).
That is TASK 54's run-5 mechanism again, one level deeper: on the receiver's copy the peer's character is
a body that JUMPS (SetPosition to the streamed pose), and a deep overlap ejects the prop tens of units.

**The wider rule (chk55c, implemented, NOT yet measured live):** the guest also freezes a prop while ANY
human on this copy is within 3 units of it (`prop_near_human`, `prop_freeze_here`). A prop near a
character is exactly where the ejection happens, and the receiver may not simulate a push at all - the
host's copy has both characters (the guest's as the puppet) and streams the result.
