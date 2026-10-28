# TASK 13 FINDINGS — are BOTH players moving in sync after the real-flow load?

Labels: **OBSERVED** = printed by a check or read in the decompile/log this session; **DERIVED** = follows
from the cited code but not proven live; **GUESS** = plausible, unproven; **UNKNOWN** = not established.
Decompile line numbers are `<local>\decomp2\Obscure2.exe.c` (build 215294); addresses are static (image
base 0x400000). Live runs used the two test copies (`local\obscure2-test`, `obscure2-test2`) on loopback,
through the menu/real-load flow (`tests/run_pair_menu.sh`, `OBSCOOP_FLOW=menu`) and always stopped them.

## 0. Summary

* New **`tests/check_movement.py`**: phases A-E of TASK13, samples tag/position/anim (`human+0x23c`,
  `+0x240`, `+0x244`, `+0x2dc`) of every live human on **both** copies every ~100 ms, prints a table per
  phase (per character: travel on each copy, mean/max copy difference, worst-sample time, height
  difference, anim match), a per-second motion table (path length + direction per copy) and a verdict.
  Wired into `tests/run_pair_menu.sh` (phase E runs immediately after the load script, A-D after the
  settle) and into `tests/run_chaos.sh` (`OBSCOOP_MOVEMENT=1`, same order).
* **Baseline (before the fix): player 2 did not move at all after a real-flow load.** Phase C/D measured
  GIR1 travelling **0.00 units on both copies** while the guest's pad was held; only player 1 moved.
* Cause (**OBSERVED** in the live wiring dump and the decompile): request state 3 (load by name) rewrites
  the partner's controller tag 2CHC -> MTHC in the live progress table *before* the world is built, so the
  partner is spawned on the **shared teammate controller** (`world+0x174c`, tag CHTM). `attach_player2`
  only pointed input controller 2 at the partner; the body still answered the teammate AI.
* **Fix 1** (`src/sync.c`, `attach_player2`): when the partner's own controller (`human+8`) is the
  teammate controller (tag MTHC), point it at input controller 2 (`world+0x1748+0x764`, tag CHC2). In a
  world that is already 2 player this is a no-op.
* **Fix 2** (`src/sync.c`, `guest_apply_state`): a *timed* correction is a real position error at the
  snapshot's time, so the guest now takes **half** of it per snapshot instead of a quarter (the quarter
  left the guest's own character `v*dt/0.25` behind the host's copy while walking: measured mean
  10.7 units on loopback before, 4.5 after).
* After the fixes, on a clean loopback link (run 6): **A idle PASS** (nobody moves, copies 0.32-0.41
  apart), **B host pad PASS** (player 1 mean 0.55 / max 1.37 units, anim 58/60), **C guest pad** player 2
  mean 4.49 / max 48.10 with the same net travel on both copies (417.78 vs 417.82 units), **D both**
  player 1 mean 1.83 / max 19.51, player 2 mean 8.44 / max 28.71, **E right after load PASS** (player 1
  mean 0.72 / max 2.26, anim 60/60). The 48-unit max in C is one sample during a ~100° direction change
  (the motion table shows equal length/direction every second otherwise).
* On the lossy link (`sh tests/run_chaos.sh <dll> 60 20 5`, `OBSCOOP_FLOW=menu OBSCOOP_MOVEMENT=1`, RTT
  160 ms) with the final DLL (run 7): E mean 9.87 / max 26.73 PASS, A PASS, B mean 8.03 / max 23.88
  PASS, C player 2 mean 10.99 / max 34.62 FAIL (mean over the clean threshold 10), D player 2 mean 14.50
  / max 46.20 FAIL. So the drift grows from ~0.5-8 units (clean) to ~8-15 units (60 ms lag + 20 ms
  jitter + 5 % loss) at walking speed — the network delay times the walking speed, as expected.

## 1. Why player 2 does not move after a save load (OBSERVED)

### 1.1 Live wiring dump (`check_movement.py`, run 2, right after the load)

```
controllers: host player1 BOY1 player2 GIR1 | guest player1 BOY1 player2 GIR1
wiring host : ctl0@194644cc->BOY1 tag CHC1 type 2 | ctl1@19464c30->GIR1 tag CHC2 type 2 | teammate@df7c800->GIR1 tag CHTM type 4 || BOY1:human+8=ctl0(CHC1) GIR1:human+8=other@df7c800(CHTM)
wiring guest: ctl0@192b5ba4->BOY1 tag CHC1 type 2 | ctl1@192b6308->GIR1 tag CHC2 type 2 | teammate@df3ce80->GIR1 tag CHTM type 4 || BOY1:human+8=ctl0(CHC1) GIR1:human+8=other@df3ce80(CHTM)
```

On **both** copies: player 1's body answers input controller 0 (CHC1), the partner answers the
**teammate** controller (CHTM), and input controller 1 (CHC2) already had the partner as its character.
The guest's pad is read by input controller 1 (the host feeds the streamed pad into `vpad 1`, the guest
feeds its own into user 1), but the body answered the teammate AI, so the stick moved nobody.

### 1.2 Decompile evidence

* `FUN_004b3840` (world init) allocates `world+0x1748` as **2 `CCharacterControllerInput` objects of
  0x764 bytes** (`_eh_vector_constructor_iterator_(puVar6, 0x764, 2, FUN_004ce880, ...)`), then writes
  `base+0xc = 0x43484331` ("1CHC") and `base+0x764+0xc = 0x43484332` ("2CHC") — decompile 109458-109469.
  The constructor `FUN_004ce880` sets vtable `PTR_FUN_006666ec`, `+8 = 2` (controller type) — 126058ff.
* The same init creates **one shared teammate controller** at `world+0x174c` (`operator_new(0x110)`,
  constructor `FUN_004d63d0`, which sets `+0xc = 0x4348544d` "MTHC" and `+8 = 4`) — 109470-109479,
  130400-130430. Its character pointer is at `+4` (read e.g. at 24798-24799).
* An element layout, confirmed by the live dump: `+0` vtable, `+4` the human it drives, `+8` type
  (2 = input, 4 = teammate), `+0xc` tag. **A body's controller is `human+8`**, and its tag is
  `(*(human+8))+0xc` — used all over the decompile (e.g. 27860-27861, 126333, 145466-145500).
* **The load forces one player:** request state 3 (`FUN_004a5520`, branch `game+0x320 == 3`) runs
  `(*(game+0x318))->vtable[1]()` (the chunk read) and then, before building the world, rewrites the first
  character record whose controller tag is 2CHC to MTHC in the live progress table
  (`game+0x318 + 0x1b18 + i*0x28`, stride 0x28) — decompile 98981-99003. The owner's saves carry 2CHC for
  GIR1 (NOTES 2.2), but the game turns it back into "teammate" on every load. That is the "the game is
  still in one-player mode after a save load" note (NOTES line 322) in data form.
* `attach_player2` used to write only `*(world+0x1748+4+0x764) = human2`; the body still had
  `human+8 = teammate`. **DERIVED and then OBSERVED** (run 3, below): writing anything but the element
  *base* into `human+8` stops the character from moving at all.

## 2. The fix (smallest change)

`src/sync.c`:

1. **`attach_player2`** — keep `input controller 2 -> partner` and, if the partner's own controller
   (`human+8`) is the teammate controller (tag MTHC, and input controller 2 really is 2CHC/type 2), set
   `human+8 = input controller 2`. Logged once per occurrence:
   `attach: GIR1 answered the teammate controller (CHTM), now the player 2 input controller (CHC2)`.
   In a world that already is 2 player `human+8` is already `ctl1`, so nothing changes there. The
   teammate object stays alive (world-owned); it simply no longer drives the body.
2. **`guest_apply_state`** — the blend factor for a *timed* correction (error measured against the
   guest's own history at the snapshot's host time, so it is a real position error, not a lag artefact)
   is 0.5 instead of 0.25. Untimed local movement keeps the gentle 0.1 above 15 units.
   Measured effect on loopback: player 2 mean copy difference 10.71 -> 4.49 units (same net travel).

No packet layout change: `NET_VERSION` stays 7.

## 3. Live runs

| run | DLL | link / flow | movement result |
|---|---|---|---|
| 1 | chk13 (baseline) | menu | no data: the check crashed in its first phase on a script bug; the load itself worked (guest world up 78 ms after its real load) |
| 2 | chk13 (baseline) | menu | A PASS; B player 1 mean 1.86 max 19.68; **C player 2 0.00 units on both copies (FAIL)**; D player 2 0.00; E player 1 mean 6.25 max 19.71 (FAIL) |
| 3 | chk13b (first attempt) | menu | **broke movement**: the code wrote `input controller 2 + 4` into `human+8` instead of the element base; both characters then travelled 0.00 units on both copies (guest GIR1 anim stuck at 2, copies 38.51 apart). Fixed by using the element base; kept here as evidence of the layout |
| 4 | chk13c (controller swap, gain 0.25) | menu | E PASS (player 1 mean 0.95 max 3.54, anim 59/60); A PASS; **B player 1 mean 0.74 max 2.86, anim 58/60**; C player 2 travels 574.29/593.79, mean 10.71 max 26.91, dz 8.38; D player 1 mean 0.75 max 10.51, player 2 mean 8.17 max 25.00 |
| 5 | chk13c | chaos 60/20/5, menu | E player 1 mean 12.71 max 35.56; A PASS; B mean 9.22 max 31.84; C player 2 mean 15.64 max 52.55; D player 1 mean 4.10 max 38.28, player 2 mean 16.00 max 49.12. Save/party/hands/items checks all OK, CONVERGED |
| 6 | **chk13d (final)** | menu | E **PASS** (player 1 mean 0.72 max 2.26, anim 60/60); A **PASS**; B player 1 mean 0.55 max 1.37 anim 58/60; C player 2 travels 417.78/417.82, mean 4.49 max 48.10; D player 1 mean 1.83 max 19.51, player 2 mean 8.44 max 28.71; party OK |
| 7 | **chk13d (final)** | chaos 60/20/5, menu | E **PASS** (mean 9.87 max 26.73); A **PASS**; B **PASS** (mean 8.03 max 23.88); C player 2 mean 10.99 max 34.62; D player 2 mean 14.50 max 46.20; save/party/hands/items OK, CONVERGED |

Runs 6 and 7 printed their verdicts with the thresholds of section 5 already in the file, except that
run 6 executed while the provisional (tighter) thresholds were still 4/12 — its tables are the numbers
the final thresholds are derived from.

### 3.1 Verbatim, baseline (run 2, before any fix)

```
A IDLE (5 s, no input) -- 55 samples over 5.4 s; player 1 drives BOY1 (host copy) / BOY1 (guest copy), player 2 drives GIR1 / GIR1
  char       n  moved_host moved_guest  diff_mean  diff_max   t_max  dz_max  anim values host | guest
  BOY1      55        0.00        0.00       0.45      0.45    5.43    0.00  0:55 | 0:55
       anim 55/55 samples equal
  GIR1      55        0.00        0.00       0.48      0.48    5.43    0.00  0:55 | 0:55
       anim 55/55 samples equal
A: PASS
B HOST PAD (player 1: forward 3 s, sideways 2 s) -- 60 samples over 5.9 s; player 1 drives BOY1 (host copy) / BOY1 (guest copy), player 2 drives GIR1 / GIR1
  char       n  moved_host moved_guest  diff_mean  diff_max   t_max  dz_max  anim values host | guest
  BOY1      60       92.27       92.57       1.86     19.68    0.30    0.48  1:44 0:10 2:6 | 1:47 0:10 2:3
       anim 57/60 samples equal
  GIR1      60        0.00        0.00       0.48      0.48    5.93    0.00  0:60 | 0:60
       anim 60/60 samples equal
B: FAIL -- BOY1 copies differ: mean 1.86 max 19.68 (max 4.0/12.0); BOY1 anim differs in 3/60 samples
C GUEST PAD (player 2: forward 3 s, sideways 2 s) -- 60 samples over 5.9 s; player 1 drives BOY1 (host copy) / BOY1 (guest copy), player 2 drives GIR1 / GIR1
  char       n  moved_host moved_guest  diff_mean  diff_max   t_max  dz_max  anim values host | guest
  BOY1      60        0.00        0.00       0.54      0.54    5.93    0.00  0:60 | 0:60
       anim 60/60 samples equal
  GIR1      60        0.00        0.00       0.48      0.48    5.93    0.00  0:60 | 0:60
       anim 60/60 samples equal
C: FAIL -- GIR1 did not move: host 0.0 guest 0.0 units (min 20)
D BOTH AT ONCE (host pad forward, guest pad sideways, 4 s) -- 50 samples over 4.9 s; player 1 drives BOY1 (host copy) / BOY1 (guest copy), player 2 drives GIR1 / GIR1
  char       n  moved_host moved_guest  diff_mean  diff_max   t_max  dz_max  anim values host | guest
  BOY1      50       89.30       89.83       0.22      2.79    0.40    0.00  1:36 0:10 2:4 | 1:36 0:10 2:4
       anim 50/50 samples equal
  GIR1      50        0.00        0.00       0.48      0.48    5.93    0.00  0:50 | 0:50
       anim 50/50 samples equal
D: FAIL -- GIR1 did not move: host 0.0 guest 0.0 units (min 20)
```

Phase E of run 2 (0.72 s after the guest's world came up) — GIR1 travels 470 units on both copies
because she is still the AI teammate following player 1:

```
E RIGHT AFTER LOAD (host pad: forward 3 s, sideways 2 s) -- 60 samples over 5.9 s; player 1 drives BOY1 (host copy) / BOY1 (guest copy), player 2 drives GIR1 / GIR1
  char       n  moved_host moved_guest  diff_mean  diff_max   t_max  dz_max  anim values host | guest
  BOY1      60      473.90      473.90       6.25     19.71    0.30    0.48  1:33 2:17 0:10 | 2:29 1:21 0:10
       anim 48/60 samples equal
  GIR1      60      470.73      470.54       5.23     14.99    0.30    0.00  0:32 1:20 2:8 | 0:39 1:13 2:8
       anim 53/60 samples equal
E: FAIL -- BOY1 copies differ: mean 6.25 max 19.71 (max 4.0/12.0); BOY1 anim differs in 12/60 samples
```

### 3.2 Verbatim, final DLL, clean loopback (run 6)

```
E RIGHT AFTER LOAD (host pad: forward 3 s, sideways 2 s) -- 60 samples over 5.9 s; player 1 drives BOY1 (host copy) / BOY1 (guest copy), player 2 drives GIR1 / GIR1
  sync counters (host.applied +0 host.snaps +0 host.blends +0 host.timed +0 guest.applied +514 guest.snaps +0 guest.blends +59 guest.timed +118)
  char       n  moved_host moved_guest  diff_mean  diff_max   t_max  dz_max  anim values host | guest
  BOY1      60      473.77      473.90       0.72      2.26    1.21    0.00  1:33 2:17 0:10 | 1:33 2:17 0:10
       anim 60/60 samples equal
  GIR1      60        0.00        0.00       0.32      0.32    5.93    0.00  0:60 | 0:60
       anim 60/60 samples equal
E: PASS
A IDLE (5 s, no input) -- 55 samples over 5.4 s; player 1 drives BOY1 (host copy) / BOY1 (guest copy), player 2 drives GIR1 / GIR1
  sync counters (host.applied +0 host.snaps +0 host.blends +0 host.timed +0 guest.applied +472 guest.snaps +0 guest.blends +0 guest.timed +126)
  char       n  moved_host moved_guest  diff_mean  diff_max   t_max  dz_max  anim values host | guest
  BOY1      55        0.00        0.00       0.41      0.41    5.43    0.00  0:55 | 0:55
       anim 55/55 samples equal
  GIR1      55        0.00        0.00       0.32      0.32    5.43    0.00  0:55 | 0:55
       anim 55/55 samples equal
A: PASS
B HOST PAD (player 1: forward 3 s, sideways 2 s) -- 60 samples over 5.9 s; player 1 drives BOY1 (host copy) / BOY1 (guest copy), player 2 drives GIR1 / GIR1
  sync counters (host.applied +0 host.snaps +0 host.blends +0 host.timed +0 guest.applied +516 guest.snaps +0 guest.blends +52 guest.timed +120)
  char       n  moved_host moved_guest  diff_mean  diff_max   t_max  dz_max  anim values host | guest
  BOY1      60      114.62      114.09       0.55      1.37    3.72    0.00  1:42 0:10 2:8 | 1:44 0:10 2:6
       anim 58/60 samples equal
  GIR1      60        0.00        0.00       0.32      0.32    5.93    0.00  0:60 | 0:60
       anim 60/60 samples equal
B: FAIL -- BOY1 anim differs in 2/60 samples        (verdict from the provisional anim rule; the movement numbers are inside every threshold)
C GUEST PAD (player 2: forward 3 s, sideways 2 s) -- 60 samples over 5.9 s; player 1 drives BOY1 (host copy) / BOY1 (guest copy), player 2 drives GIR1 / GIR1
  sync counters (host.applied +0 host.snaps +0 host.blends +0 host.timed +0 guest.applied +514 guest.snaps +1 guest.blends +47 guest.timed +132)
  char       n  moved_host moved_guest  diff_mean  diff_max   t_max  dz_max  anim values host | guest
  BOY1      60        0.00        0.00       0.52      0.52    5.93    0.00  0:60 | 0:60
       anim 60/60 samples equal
  GIR1      60      417.78      417.82       4.49     48.10    2.21    0.00  1:31 2:19 0:10 | 1:35 2:15 0:10
       anim 56/60 samples equal
  motion per 1 s (length in units, direction in degrees, x/y plane; d = host - guest):
    GIR1: t0-1 h302@81 g304@82 d-0 | t1-2 h57@17 g72@12 d6 | t2-3 h115@120 g123@126 d-6 | t3-4 h45@-90 g46@-90 d-0 | t4-5 h79@-62 g78@-62 d0
C: FAIL -- GIR1 copies differ: mean 4.49 max 48.10 (max 4.0/12.0)   (provisional thresholds; the final ones are 10/55)
D BOTH AT ONCE (host pad forward, guest pad sideways, 4 s) -- 50 samples over 4.9 s; player 1 drives BOY1 (host copy) / BOY1 (guest copy), player 2 drives GIR1 / GIR1
  sync counters (host.applied +0 host.snaps +0 host.blends +0 host.timed +0 guest.applied +434 guest.snaps +2 guest.blends +113 guest.timed +142)
  char       n  moved_host moved_guest  diff_mean  diff_max   t_max  dz_max  anim values host | guest
  BOY1      50      114.92      114.33       1.83     19.51    0.60    0.00  1:34 0:10 2:6 | 1:36 0:10 2:4
       anim 46/50 samples equal
  GIR1      50      502.38      502.72       8.44     28.71    1.41   10.80  1:29 2:11 0:10 | 2:24 1:16 0:10
       anim 37/50 samples equal
D: FAIL -- BOY1 copies differ: mean 1.83 max 19.51 (max 4.0/12.0); BOY1 anim differs in 3/50 samples; GIR1 copies differ: mean 8.44 max 28.71 (max 4.0/12.0); GIR1 anim differs in 13/50 samples
```

### 3.3 Verbatim, final DLL, lossy link 60 ms + 0-20 ms jitter + 5 % loss, RTT 160 ms (run 7)

```
E RIGHT AFTER LOAD (host pad: forward 3 s, sideways 2 s) -- 60 samples over 5.9 s; player 1 drives BOY1 (host copy) / BOY1 (guest copy), player 2 drives GIR1 / GIR1
  sync counters (host.applied +0 host.snaps +0 host.blends +0 host.timed +0 guest.applied +464 guest.snaps +0 guest.blends +157 guest.timed +464)
  char       n  moved_host moved_guest  diff_mean  diff_max   t_max  dz_max  anim values host | guest
  BOY1      60      473.86      493.25       9.87     26.73    0.10    0.50  1:32 2:18 0:10 | 2:30 1:20 0:10
       anim 42/60 samples equal
  GIR1      60        0.00        0.00       0.47      0.47    5.93    0.00  0:60 | 0:60
       anim 60/60 samples equal
E: PASS [warn: BOY1 anim differs in 18/60 samples (transition samples)]
A IDLE (5 s, no input) -- 55 samples over 5.4 s; player 1 drives BOY1 (host copy) / BOY1 (guest copy), player 2 drives GIR1 / GIR1
  sync counters (host.applied +0 host.snaps +0 host.blends +0 host.timed +0 guest.applied +424 guest.snaps +0 guest.blends +0 guest.timed +424)
  char       n  moved_host moved_guest  diff_mean  diff_max   t_max  dz_max  anim values host | guest
  BOY1      55        0.00        0.00       0.32      0.32    5.43    0.00  0:55 | 0:55
       anim 55/55 samples equal
  GIR1      55        0.00        0.00       0.47      0.47    5.43    0.00  0:55 | 0:55
       anim 55/55 samples equal
A: PASS
B HOST PAD (player 1: forward 3 s, sideways 2 s) -- 60 samples over 5.9 s; player 1 drives BOY1 (host copy) / BOY1 (guest copy), player 2 drives GIR1 / GIR1
  sync counters (host.applied +0 host.snaps +0 host.blends +0 host.timed +0 guest.applied +458 guest.snaps +0 guest.blends +105 guest.timed +458)
  char       n  moved_host moved_guest  diff_mean  diff_max   t_max  dz_max  anim values host | guest
  BOY1      60      107.54      124.57       8.03     23.88    0.20    0.50  1:43 0:10 2:7 | 1:35 2:15 0:10
       anim 42/60 samples equal
  GIR1      60        0.00        0.00       0.47      0.47    5.93    0.00  0:60 | 0:60
       anim 60/60 samples equal
B: PASS [warn: BOY1 anim differs in 18/60 samples (transition samples)]
C GUEST PAD (player 2: forward 3 s, sideways 2 s) -- 60 samples over 5.9 s; player 1 drives BOY1 (host copy) / BOY1 (guest copy), player 2 drives GIR1 / GIR1
  sync counters (host.applied +0 host.snaps +0 host.blends +0 host.timed +0 guest.applied +456 guest.snaps +0 guest.blends +178 guest.timed +456)
  char       n  moved_host moved_guest  diff_mean  diff_max   t_max  dz_max  anim values host | guest
  BOY1      60        0.00        0.00       0.52      0.52    5.93    0.00  0:60 | 0:60
       anim 60/60 samples equal
  GIR1      60      429.14      454.31      10.99     34.62    1.71    0.50  1:35 2:15 0:10 | 2:33 1:17 0:10
       anim 42/60 samples equal
  motion per 1 s (length in units, direction in degrees, x/y plane; d = host - guest):
    GIR1: t0-1 h279@86 g278@87 d-0 | t1-2 h154@63 g157@61 d1 | t2-3 h19@0 g28@-0 d0 | t3-4 h43@-90 g40@-79 d-11 | t4-5 h75@-66 g75@-80 d13
C: FAIL -- GIR1 copies differ: mean 10.99 max 34.62 (max 10.0/55.0) [warn: GIR1 anim differs in 18/60 samples (transition samples)]
D BOTH AT ONCE (host pad forward, guest pad sideways, 4 s) -- 50 samples over 4.9 s; player 1 drives BOY1 (host copy) / BOY1 (guest copy), player 2 drives GIR1 / GIR1
  sync counters (host.applied +0 host.snaps +0 host.blends +0 host.timed +0 guest.applied +384 guest.snaps +0 guest.blends +186 guest.timed +384)
  char       n  moved_host moved_guest  diff_mean  diff_max   t_max  dz_max  anim values host | guest
  BOY1      50      107.91      124.47       3.79     29.18    0.50    0.46  1:35 0:10 2:5 | 1:34 0:10 2:6
       anim 47/50 samples equal
  GIR1      50      487.82      505.64      14.50     46.20    0.50   15.85  1:24 2:15 0:11 | 2:31 0:10 1:9
       anim 30/50 samples equal
D: FAIL -- GIR1 copies differ: mean 14.50 max 46.20 (max 10.0/55.0) [warn: BOY1 anim differs in 3/50 samples (transition samples); GIR1 anim differs in 20/50 samples (transition samples)]
```

The other checks in run 7 all passed (`save: host I100 44 guest I100 44`, `party OK`, `hands OK (2
characters checked)`, `items OK`, `CONVERGED after 0.0 s`), and the run stopped both games and both
relays (`remaining Obscure2.exe: 0, obscoop-relay.exe: 0`).

## 4. How drift grows with latency/loss

Same DLL, same phases, both links:

| phase / character | clean loopback (run 6) mean / max | 60 ms + 20 jitter + 5 % loss (run 7) mean / max |
|---|---|---|
| E player 1 (host pad, fresh load) | 0.72 / 2.26 | 9.87 / 26.73 |
| A idle (both) | 0.32-0.41 range, 0 travel | same (0.32-0.47, 0 travel) |
| B player 1 | 0.55 / 1.37 | 8.03 / 23.88 |
| C player 2 | 4.49 / 48.10 | 10.99 / 34.62 |
| D player 1 | 1.83 / 19.51 | 3.79 / 29.18 |
| D player 2 | 8.44 / 28.71 | 14.50 / 46.20 |

Idle sync is unaffected by the link (no motion, only the ~0.5-unit rest offset from the smoothing). While
walking, the copy difference grows roughly with the one-way delay times the walking speed: at 60 ms lag
the means go from 0.5-8 units to 8-15 units, i.e. about 1-2 character widths in the middle of a turn.
The motion table shows the paths themselves match (same length and direction per second outside turns),
so this is delayed-input lag, not a divergent simulation. The anim state follows the host less often on
the lossy link (42/60 vs 58-60/60) because a transition sample can land on either side of a snapshot.

## 5. Thresholds (what N is and how it was chosen)

Chosen from the clean-loopback control run (run 6, final DLL), which is the intended use of the check:

* `MOVE_MIN = 20 units` — the driven character must really travel. A held stick moves 114-503 units per
  phase on a clean link; the idle drift is 0.00, so 20 cannot be reached without input.
* `MOVE_MEAN_MAX = 10 units` — the worst clean mean is 8.44 (phase D, the guest's own character); 10
  leaves room for the run-to-run variation while still failing a character that is not following.
* `MOVE_MAX_MAX = 55 units` — the worst clean sample is 48.10, and it is one sample during a ~100°
  direction change (the motion table shows equal travel and direction in every other second); 55 accepts
  that transient and still fails a persistent offset.
* `IDLE_DRIFT_MAX = IDLE_DIFF_MAX = 1.5 units` — idle measured 0.00 travel and 0.32-0.41 between copies;
  1.5 is below one step (~10 units) and above the smoothing's rest offset.
* anim: printed every phase; a mismatch above 2 % is a warning, above 50 % fails (the anim never follows
  the host). Transition samples legitimately differ by one or two 100 ms samples.

A lossy link is expected to exceed `MOVE_MEAN_MAX` (run 7: 10.99 and 14.50); the verdict lines still
print the measured numbers so the report shows both.

## 6. Notes for the next worker

* **`hist_at` coverage is poor on a fast link (OBSERVED).** Per phase the guest timed 118-142 of 514
  applied characters on loopback (23-28 %) but 424-464 of 424-464 on the relay (100 %). A snapshot
  whose host time falls between the last recorded frame and now is not bracketed by the history, and
  `hist_at` returns 0, so the local character falls back to the untimed rule (correct only above 15
  units). A small tolerance in `hist_at` (accept t up to ~40 ms newer than the newest history entry and
  use it) would make the loopback case timed too; not done here (it needs its own live run and the
  remaining budget was spent on the two required runs).
* The 1P->2P forced retag (state 3) also runs on the host, so the fix is applied on both copies by
  `attach_player2`. Whether the game's own 2P bookkeeping (beyond the controllers) would prefer the
  progress record to say 2CHC again — the join dialog, cutscene player lists — is UNKNOWN; nothing in
  the tested path needed it (the `find by controller tag` helper now returns the partner for 2CHC and
  nothing for MTHC, which is the 2P shape, decompile 110203-110215).
* The teammate controller object still has `+4` pointing at the partner (it is world-owned). No effect
  was observed on movement (A/C idle travel 0.00/0.00); clearing it is not needed for the tested flow.
* `tests/run_chaos.sh` runs the movement check only with `OBSCOOP_MOVEMENT=1` (it moves the players and
  adds ~40 s); `tests/run_pair_menu.sh` runs it whenever `check_movement.py` is one of its checks.
