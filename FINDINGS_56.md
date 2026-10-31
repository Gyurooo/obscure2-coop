# FINDINGS 56 — pushing boxes: the pusher owns the prop, the other copy follows

Labels: **OBSERVED** = printed by a run/check in this task or read in the decompile (address cited);
**DERIVED** = follows from the cited code but was not seen live; **GUESS**; **UNKNOWN**.
Base: HEAD 454d6c4 (TASK 55 WIP, protocol 29). Live runs: `run_s56_a1..a6.log`, DLLs chk56a..chk56e.

## 0. Design (implemented in src/sync.c, TASK 56 comments)

The prop's physics is leased to the copy whose player is **pushing** it; the other copy freezes exactly
that prop and follows the streamed transform.

* **Ownership (prop_own_tick)**: "pushing" = the character is within `PROP_TOUCH2` of the prop AND moving
  at `PROP_PUSH_SPEED2` or more TOWARD it (within 60 deg), and slower than `PROP_WALK_MAX2` (a teleport is
  not a push). A lease lasts `PROP_OWN_MS` (900 ms) past the last evidence, so a prop still sliding after
  the pusher stopped stays with the copy that holds its physics. When NOBODY pushes and no lease is live,
  the copy whose player stands at the prop takes it (`lt`/`pt`) - so a prop the peer's player stands at is
  not shoved by our copy's physics, and a prop our player stands at is never frozen here.
* **Tie**: both push it -> the host's simulation wins (the guest yields to a moving packet in
  peer_apply_moves; the host ignores a guest packet for a prop it pushes itself). Role is ONLY the tie-break.
* **Freeze (receiver)**: `prop_freeze_here` = the PEER holds the lease. Freezing is the game's own body
  disable, `FUN_005ac5a0` (body vtable slot 0x44 with 0), the call the game's own chair attach makes
  (`FUN_00411f80`, decompile 10260-10262); the body leaves the character-collision grid (slot 0x40).
  TASK 55 froze a prop near ANY human on the guest; TASK 56 freezes only what the peer is pushing/at.
* **Follow**: the receiver applies the streamed transform through the game's entity setter
  (`FUN_00402930`, vtable slot 34, PROP_ENT_SETPOS), the same call the game's own placement uses.
* **Hand back**: when the lease lapses (the pusher walked away / the prop is at rest) the receiver
  re-enables the body at the last streamed position; the owner's physics already stopped there.
* **No lease anywhere**: the old rule stays - the host streams the 1 Hz heartbeat (Obscure 1
  `host_send_props`), so a prop nobody touches still converges.

## 1. Why the host's push measured 0.0 in TASK 55's reviewer run (OBSERVED)

`_archive/claude_verify_54_break.log` (m54, no freeze at all) has the SAME first attempt:

```
push: attempt 1: tp next to @1a129c58 tag CHAI (634.91,-844.87,-11.91) ... safe tp at 55 units (ok settled at (717.19, -822.36, -7.00) after 0.8 s)
push: after:  own (634.9,-844.9,-11.9) moved 0.0 | other (615.6,-867.3,-11.9) differs 29.5
```

The old phase walked five BLIND 0.55 s stick segments in four fixed camera-relative directions (the stick
is camera-relative, `src/obscoop2.c` remap_stick) and never checked that the character reached the prop;
m54 needed attempt 2 to move it (60.2). So the host's `moved 0.0` in TASK 55 was not a regression of the
freeze (which is guest-only by its role test) but a phase that never measured a push. The phase now walks
INTO the prop with feedback (see 3).

## 2. The number that broke every threshold: the game's units (OBSERVED, run a4)

`check_pushdbg` printed a character pushing a CHAI and the prop at the same time:

```
pusher ptr 1b5ca5a8 tag BOY1 (615.3,-218.9,-7.0) | prop @1a4e75e0 CHAI (599.3,-304.3,-11.9) d 87.0
pusher ... (588.1,-282.6,-7.0) | prop (607.5,-352.5,-11.9) d 72.7
```

A character in contact with a chair stays ~70-100 units from its origin, and a shoved chair slides at
~150 units/s while a running character does ~200-300 units/s (`push lease` lines in run a5). The units are
centimetres - the thresholds TASK 55 wrote (3 units "near a human", 2 units/s "moving") meant 3 cm and
2 cm/s and could never fire. TASK 56 uses 1 m / 0.15 m/s / 15 m/s (teleport cut-off). With those,
the lease fires (`run_s56_a5.log`, host log):

```
host: prop 1a4884b8 push lease -> this copy (local 99.2 u 290.8 u/s, peer 1047.2 u 0.0 u/s)
host: prop 1a4884b8 push lease -> the peer (local 115.2 u 0.0 u/s, peer 81.6 u 0.0 u/s)
```

and a push that reached the prop ends with both copies agreeing:

```
push: host push 1/3: after:  own (532.6,-208.1,-11.9) moved 62.6 | other (533.4,-208.3,-11.9) differs 0.8
push: host push 2/3: after:  own (689.4,-138.1,-11.9) moved 52.7 | other (691.8,-140.6,-11.9) differs 3.5
```

## 3. The phase (tests/check_breakables.py, task53_push)

Three pushes per player (host player 1 on the host copy, guest player 2 on the guest copy). Each push:
safe-tp 1.8-2.6 m from the prop (a closer tp EJECTS the prop - run a1: a tp 7 units = 7 cm from the chair
sent it 60+ units away, and the "push" measured that ejection), measure the stick->world frame by pressing
both stick axes once (the camera is independent per copy and turns while walking), then home on the prop
every 120 ms until it has moved `PUSH_MIN` = 30 units; the other copy must be within `PUSH_AGREE` = 10.
An approach whose character teleports (>1 m between two samples - the level's own out-of-bounds/scripted
placement, seen in runs a3/a5) is abandoned and the next side/prop is tried.
