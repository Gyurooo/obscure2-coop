# FINDINGS 59 — the carried prop: the owner's transform is streamed (DONE); the push lease is NOT fixed

Labels: **OBSERVED** = printed by a run/check in this task or read in the decompile (address cited);
**DERIVED** = follows from the cited code but was not seen live; **GUESS**; **UNKNOWN**.
Base: HEAD 35e7134 (release 2.2, protocol 29). Worktree `<worktree>`. Final DLL: `chk59e.dll`
(release 2.2 + the carried-transform stream, protocol 30). Runs: `run_s59_diag1/a1/b1/c1/d1/final1.log`.

## 0. What the reviewer measured (quoted, TASK 59)

```
  push: guest push 1/3: after:  own (692.4,-427.3,-11.9) moved 0.0 | other (684.4,-431.6,-11.9) differs 9.1
  push: guest push 2/3: after:  own (653.1,-501.5,-11.9) moved 41.4 | other (647.7,-498.8,-11.9) differs 6.1
  push: guest push 3/3: after:  own (662.4,-544.4,-11.9) moved 43.8 | other (654.8,-552.6,-11.9) differs 11.2
  carried prop mesh: own set | other set -> max difference 1.41 units (follows)      [host player 1]
  carried prop mesh: own set | other set -> max difference 3.98 units (DOES NOT follow)   [guest player 2]
```

## 1. DONE - the carried prop: the differing input is the game's SIDE selection (OBSERVED)

`FUN_00412720` (the chair's vtable slot 27, decompile 10583-10790) writes exactly two things into the
mesh: `mesh+0x1c8` = a **constant** 3-float hand offset and `mesh+0x1e0` = a **constant** quaternion
built from a constant 3x3 matrix (`FUN_00596870(&local_b0)`, 10778-10784). The offset is one of eight
hardcoded variants: two families of four (the carrier's tag class, 10602
`*(int *)(*(int *)(in_ECX + 0xc4) + 0x14) + 0xb8b6adcfU < 4`), and inside a family by

* `ABS(dot(prop_dir, normalize(prop_grip - carrier_pos)))` vs `FUN_00613220()` (10604-10611), where
  `prop_dir` = prop+0x78..0x80 and `prop_grip` = prop+0x104..0x10c (10627-10629), and
* the sign of `prop_dir.y*dx - prop_dir.x*dy` (10642, 10715) - the LEFT/RIGHT side of the body.

Decoding the eight constant sets and taking the max over the seven floats the check compares gives:

| pair | max difference |
|---|---|
| A1 vs A2 | **2.960** |
| A3 vs A4 | **3.980** |
| B2 vs B3 | 1.270 (the game's `FUN_00596870` sign convention) |

The reviewer's `2.96` and `3.98` are exactly the mirrored-side pairs A1/A2 and A3/A4; the host-carried
`1.41` is the B2/B3 pair. So the two copies do not disagree about the hand: **they take opposite
left/right branches of the same function**, and the values never converge because each call recomputes
the branch from that copy's own fields. The hand bone enters only at the end
(`FUN_005da330(mesh,"RHand")` -> `+0x110`, 10800-10803), not in the written transform.

The diagnostic probe (`run_s59_diag1.log`, scratch `probe59.py`, the 2.2 DLL) measured the inputs on
both copies during a carry:

```
  own   : ... pos(588.79,-248.61,-11.57) dir(-0.984,-0.177,-0.011) grip(588.79,-248.59,-11.57) ... branch B3
  other : ... pos(589.51,-252.58,-11.80) dir(-0.999,-0.050,-0.003) grip(588.85,-248.58,-11.59) ... branch B2
  max difference over the 7 compared floats: 1.270
  ...
  own   : ... dir(-0.535,-0.845,-0.011) grip(1002.88,-133.63,-12.88) ... branch A3
  other : ... dir(-0.620,-0.785,-0.003) grip(1003.40,-132.82,-12.79) ... branch A4
  max difference over the 7 compared floats: 3.980
```

The carrier's position is identical on both copies (the puppet is SetPosition'd to the owner's stream)
and the grip differs by under 1 unit; **the prop's own direction +0x78 differs by 5-7 degrees**, which is
what moves the dot/angle test across its threshold. `+0x104` is initialised from `+0x6c` at construction
(decompile 15738-15742) and written by neither the entity setter `FUN_00402930` (1408-1450) nor the
carry attach `FUN_00411f80` (10247-10268), so on the applying copy both fields stay at whatever they
were when the carry began.

**The fix (delivered):** the owner sends the seven floats its own call produced
(`mesh+0x1c8` 3, `mesh+0x1e0` 4) in the carry packet (`pkt_prop.cdir`, protocol 30, NET_VERSION bumped);
the receiver still calls slot 27 (that is the `RHand` binding) and then writes the owner's seven values
in `puppet_finish` (`prop_mesh_remember` / `prop_mesh_for`). Measured on the final DLL, both directions:

```
  carried prop mesh: own set | other set -> max difference 0.00 units (follows)     [player 1, host]
  carried prop mesh: own set | other set -> max difference 0.00 units (follows)     [player 2, guest]
```

(The same `0.00 / 0.00` was measured first in `run_s59_a1.log` and again in `run_s59_d1.log` and
`run_s59_final1.log`.) The check's 2.0 tolerance is untouched; the two copies are now identical by
construction instead of by luck of the branch.

Final run on `chk59e.dll` (`run_s59_final1.log`, `OBSCOOP_LINK=steam OBSCOOP_SLOT=3 sh
tests/run_pair_menu.sh <worktree>/chk59e.dll check_breakables.py`), verbatim:

```
  carry pose: own state 300 clips CHAA/WALK | other state 300 clips CHAA/WALK (equal after 0.00 s)
  carried prop mesh: own set | other set -> max difference 0.00 units (follows)
  carry pose: own state 301 clips CHAB/LPAU | other state 301 clips CHAB/LPAU (equal after 0.80 s)
  carried prop mesh: own set | other set -> max difference 0.00 units (follows)
```

The same run's push phase (2.2's lease code, unchanged) still shows the drift this task was asked to
remove, and again with a pre-existing gap in the `before:` line:

```
  push: guest push 1/3: before: own (521.8,-382.0,-11.9) | other (518.2,-366.4,-11.9) | pusher 180.1 units away
  push: walk 1.6s: pusher (726.1,-1639.8) prop (521.8,-382.0) 1274.3 units apart, moved 0.0
  push: walk: the character JUMPED 179 units between two samples - giving this approach up
  push: guest push 1/3: after:  own (521.8,-382.0,-11.9) moved 0.0 | other (490.6,-393.7,-11.9) differs 33.3
  push: host push 3/3: after:  own (667.6,-810.1,-11.9) moved 71.5 | other (619.6,-804.8,-11.9) differs 48.3
```

## 2. NOT DONE - the guest's pushes: four lease designs measured, none holds the two copies together

I implemented and measured four variants on this branch (all reverted; the final DLL keeps 2.2's push
code, so nothing that worked before is regressed). The measurements:

* **chk59a** (`run_s59_a1.log`): TASK 56's lease + "contact (130 units) also takes the lease" + "a packet
  cannot take the lease from a local player at the prop".
  `host push 1/3 ... moved 43.9 | other ... differs 0.2`, `2/3 ... 40.2 | 0.6`, `3/3 ... 45.8 | 0.5`
  (**host 3/3 good**) but the guest's phase failed: `guest push 1/3: no prop could be pushed` (every
  approach abandoned: `push: walk: the character JUMPED 183 units between two samples`) and
  `guest push 2/3 ... moved 38.0 | differs 54.5` on a chair that was already 40 units apart before the
  push (`before: own (1186.8,-860.3) | other (1206.5,-824.9)`).
* **chk59b** (`run_s59_b1.log`): + the host applies only what its lease names + `PROP_OWN_MS` 1500 +
  contact 110. The guest's pushes became `5.1 / 1.9 / 1.9` and the host's became `43.7 / 42.5 / 56.7` -
  the other way round, with the guest applying the host's transforms only in one late burst
  (`04:54:58.860 prop move: 19e73548 corrected by 57.3 units ... 83.7 units`, six packets in 240 ms).
* **chk59c** (`run_s59_c1.log`): the HOST arbitrates (the guest streams only props the host's
  `pkt_propmove.lead` gives it). Both sides still failed (`host 48.1 / 59.9 / 43.0`, `guest 27.4 / 20.7`)
  and the follower's corrections did not stick:
  `host: prop move: 19f8b3a8 corrected by 20.7 units (715.5,-512.2 -> 730.0,-526.9)` repeated every
  second with the same "from" - the applied transform is undone unless the body is disabled.
* **chk59d** (`run_s59_d1.log`): + freeze whenever the lease is the peer's (`prop_freeze_here` =
  `owner == 2`, TASK 56's rule) and the carry moved to the streamed seven floats. The carry reached
  `0.00` both ways, but the pushes were the worst yet (`47.3 / 28.1 / 75.5` host, `47.0 / 88.0 / none`
  guest), with the gap growing over the run (25 -> 45 -> 88 -> 111).

**What the runs show (OBSERVED / DERIVED):**

1. An applied transform **only sticks while the follower's prop body is disabled**. With the body
   enabled the same correction is applied every second and undone by the physics (c1's repeated
   `corrected by 20.7 units` with an unchanged "from"; TASK 54 saw the same for raw writes).
2. With the freeze tied to the lease, a follower that is frozen cannot be pushed by its own player, and
   an unfrozen follower cannot follow - the two requirements collide on the copy whose player is not
   pushing.
3. The deeper cause is that the two copies' *props* drift apart before a push starts, by tens to
   hundreds of units (`before: own ... | other ...` 40 units apart), because the check's abandoned
   approaches teleport the character and the game's own physics shoves the prop on one copy only. Once
   the copies' props and characters are apart, a per-copy ownership rule (any variant of it) has states
   where both copies claim the prop or neither does; the host-arbitrated variant removes the *decision*
   disagreement but not the underlying drift, so the measured differences persist.
4. **UNKNOWN:** why the corrections did not stick in c1 even while the lease was the peer's and the
   body should have been disabled; a per-prop probe of the freeze flag (`body+0x2c`) and of the entity
   setter's return would answer it. That is the next step, not something this task's step and process
   budget allowed.

## 3. Findings that will matter to the next task

* The `prop_freeze_here` freeze (body slot 0x44 = `FUN_005ac5a0`) is the only thing that makes
  `PROP_ENT_SETPOS` (vtable slot 34 = `FUN_00402930`) persist (section 2.1 above).
* A follower must apply *and* stay frozen for the whole follow, so the copy that does NOT own a prop is
  out of the collision grid for as long as the other one owns it. Any design must answer the resulting
  walk-through / ejection (TASK 55 measured a 60-unit ejection when the body came back).
* The push check's own approaches can be abandoned (`the character JUMPED ... giving this approach up`);
  a chair shoved during an abandoned approach keeps the copies apart for the rest of the run, so a red
  push phase is not by itself proof of a lease bug - the `before:` line of each attempt shows whether
  the copies were already apart when the push started.
