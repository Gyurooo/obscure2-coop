# FINDINGS 46 — drive the remote character the Obscure 1 way (move intent + the game's own update)

Base: `w/combat` HEAD = TASK 45 (`git log`: the HEAD commit is the TASK 45 WIP commit).
Labels: OBSERVED (read in the decompile / printed by a run), DERIVED, GUESS. Written early (task rule:
by step 30) and updated as the task runs. Decompile addresses: `decomp2/Obscure2.exe.c` (build 215294).

## 0. The fields (OBSERVED, decompile)

### 0.1 What the input controller writes before the human update (the MOVE INTENT)

`FUN_004cf940` = `CCharacterControllerInput` per-frame update (`in_ECX` = the controller, `in_ECX[1]` =
the character it drives). The walking branch (`decompile 127509..127516`, the `AUR2` pad action):

```
local_40/3c/38 = piVar6[0x92..0x94];                  // the stick direction the controller computed
fVar11 = FUN_004cf4e0(&local_40);                     // its magnitude
*(float *)(character + 0x278) = (float)fVar11;        // SPEED / magnitude
(**(code **)(*character + 0x60))(&local_40);          // MOVE DIRECTION, vtable slot 0x60
```

`CCharacterHuman` vtable slot 0x60 (byte) = `CCharacterHuman_s24` = `FUN_004c6bd0`
(`vt_slots.tsv` line 83), which stores the vector into `character+0x288/0x28c/0x290` when
`character+0x2c4 == 0`:

```
void FUN_004c6bd0(undefined4 *param_1) {           // decompile 121046
  if (*(int *)(in_ECX + 0x2c4) == 0) {
    *(undefined4 *)(in_ECX + 0x288) = *param_1;     // intent direction x
    *(undefined4 *)(in_ECX + 0x28c) = param_1[1];   // ... y
    *(undefined4 *)(in_ECX + 0x290) = param_1[2];   // ... z
  }
}
```

So the intent the game consumes is: **direction `+0x288..0x290`, speed `+0x278`** (already streamed as
`speed`), and the **requested state `+0x2e8`** (`FUN_004e3ba0` = vtable slot 0x64 = "request state":
validates and stores `param` into `+0x2e8`, decompile 138020..138148; the movement machine reads it as
`in_ECX[0xba]`). `+0x2dc` stays the CURRENT state, set by the state setter.

### 0.2 How the movement machine uses it (OBSERVED, decompile 139708..142438)

`FUN_004e76c0` = `CCharacterHuman_s54` (vtable+0xd8), called from the human update
`FUN_004de4f0` at decompile 135201:

* it starts by copying the intent direction into the velocity: `in_ECX[0xa5..0xa7] (=+0x294) =
  in_ECX[0xa2..0xa4] (=+0x288)` (decompile 139905..139908);
* the locomotion cases 0 / 1 / 2 / 4 pick the gait from **the speed `+0x278` (`in_ECX[0x9e]`)**:
  `> 850` -> run, `> 200` -> walk, else idle (decompile 142018..142075);
* every branch ends by writing the MOVE TARGET `+0x27c..0x284` (`in_ECX[0x9f..0xa1]`) =
  position + this frame's displacement (label `switchD_004e7879_caseD_3`, decompile 142431);
* the human update then does `pos - target`, calls slot 0x38 ("can I move there") and **slot 0x10
  SetPosition(target)** (decompile 135221..135256 - FINDINGS_45 section 2);
* the machine also APPLIES the requested state at the end: `if (in_ECX[0xb7] != 100) ... else if
  (in_ECX[0xba] != 100) { ... (**(code **)(*in_ECX + 0x48))(in_ECX[0xba]); }` (decompile 142404..142428),
  and the attack block `if (in_ECX[0xb7] == 200) { ... }` (decompile 142332) is the 0x4e812b crash path
  FINDINGS_44 section 3 describes.

### 0.3 What is actually PLAYED (the animation system)

* the state setter `CCharacterHuman_s18` = `FUN_004e3ed0` (vtable+0x48) maps a state id to a clip TAG
  and calls `human->vtable+0x68(tag, -1, 0, 1.0)`; `FUN_004c74e0` (slot 0x68) finds the tag in the
  character's animation table and returns its INDEX, which the setter stores in `human+0x220`
  (`in_ECX[0x88] = iVar5`; decompile 138235 / 138268 / 138297).
* the animation table: pointer `human+0x210`, count `human+0x20c`, stride **0x28**, the clip tag at
  entry+0xc (`FUN_004c76e0`, decompile 121599: `iVar1 = human+0x210; if (*(int*)(iVar1+0xc) == tag)
  return iVar1; iVar1 += 0x28;`).
* entry+8 = the animation INSTANCE pointer; its **current playback time** is `instance+0xc`
  (`FUN_004c5f30`, decompile 120343: `return *(undefined4 *)(*(int *)(in_ECX + 8) + 0xc)`; the
  movement machine compares it against 500 and against table thresholds - a millisecond clock).
* so for any human: **clip tag = `*(uint*)( animtable + index*0x28 + 0xc )` with
  `animtable = *(uint*)(human+0x210)`, `index = *(int*)(human+0x220)`; playback time =
  `*(uint*)( *(uint*)(animtable + index*0x28 + 8) + 0xc )`**.
* the state -> clip mapping (OBSERVED, FUN_004e3ed0 cases): 0 idle -> `PAUS`/`PAHU`/`COUG`/`PAUC`,
  1 walk -> `WALK`/`WAHU`/`WALC`, 2 run -> `RUN\0`/`RUHU`/`RUNC`, 4 -> `SPRT`.

## 1. Plan (from the Obscure 1 mod, `local/coopdll/src/sync.c`)

1. `host_record_wanted` (sync.c ~97) + the `hk_human_update` host path record every requested-state
   change with a sequence number; the receiver replays missed ones in order (sync.c ~1741).
2. `hk_human_update` (sync.c ~1737) writes the owner's intent into the puppet before the game's own
   Update and calls the real Update; `puppet_state_ok` (sync.c ~1694) whitelists the states a puppet may
   run.
3. `put_char` (sync.c ~1587) puts the pose back through the game's own setters after the Update.

Obscure II port: stream `+0x288` (intent direction), `+0x2e8` (requested state) and the event ring in
PKT_CHAR; on the receiver write them into the puppet before its update and let `FUN_004e76c0` run (it
picks the gait from the speed and applies the requested state), then put the pose back with SetPosition
(TASK 45's path). The attack path inside the machine (state 200) stays gated as in TASK 42/45.

## 2. Live measurements

### 2.1 HEAD: what each copy plays (OBSERVED, `animprobe.py` / `animprobe2.py`, chk46base = HEAD)

Reading, for every human on both copies, `state +0x2dc`, `want +0x2e8`, `speed +0x278`, intent
`+0x288`, velocity `+0x294` and the clip tag + clock of both animation layers:

```
-- walk 1
host  BOY1 state 1  want 0  idx 0 clip WALK inst 1b6cf414 t 223 dt +121  p -289.3,-21.7
guest BOY1 state 1  want 0  idx 0 clip WALK inst 1bb6b4cc t 123 dt +116  p -287.6,-29.2
-- left 3  (the host's pad turns the stick left)
host  BOY1 st 1 want 0 sp 648.0 int -0.99,+0.14 vel -1.0,+0.1 clip WALK t 448
guest BOY1 st 1 want 0 sp 648.0 int -1.00,-0.02 vel -1.0,+0.1 clip WALK t 356
-- down 2
host  BOY1 st 1 want 0 sp 648.0 int +0.01,-1.00 vel +0.0,-1.0 clip WALK t 161
guest BOY1 st 1 want 0 sp 648.0 int -1.00,-0.02 vel +0.0,-1.0 clip WALK t 68
```

* the PRIMARY layer (+0x220, the state clip) DOES follow on HEAD: same clip tag, its clock advances at
  the same rate, ~100 ms behind (the playback delay). So "the state setter plays the clip" is not the
  defect - the check the task asks for must look at the SECOND layer to catch anything.
* the puppet's MOVE INTENT `+0x288` is STALE: the owner's turns smoothly (-0.99,+0.14 -> -0.01,-1.00)
  while the puppet keeps -1.00,-0.02, the facing it had when it was built.
* the LOWER-BODY layer `+0x224` (the gait layer FUN_004e7420 = vtable slot 0x4c, called only by the
  movement machine) is frozen on the puppet: `lo WALK t 0` on every sample, clock 0, while the owner's
  lower layer runs (`LPAU t 94..910` in the aim phase, `WALK t 104..1072` while walking). Section 2.2 has
  the verbatim check output.

### 2.2 The check on HEAD (OBSERVED, `check_anim_sync.py`, chk46base.dll, `s46_base4.log`)

```
aim-walk   upper clip 100%  lower clip   0%  upper plays 100%  lower plays 100%  clips seen NO  FAIL
aim-strafe upper clip 100%  lower clip   0%  upper plays 100%  lower plays 100%  clips seen NO  FAIL
aim-run    upper clip 100%  lower clip   0%  upper plays 100%  lower plays 100%  clips seen NO  FAIL
anim-sync FAIL (what is played, not the state id)
```

The samples behind it (owner = the host's own BOY1, puppet = the same character on the guest copy):

```
-- aim-walk (host pad 0x100 lx 0 ly 24000)
   BOY1 owner st 100  up CBLK t 89     lo LWAF t 89     | puppet st 100  up CBLK t 461    lo LPAU t 461
-- aim-strafe (host pad 0x100 lx -24000 ly 0)
   BOY1 owner st 100  up CBLK t 95     lo LWAL t 87     | puppet st 100  up CBLK t 892    lo LPAU t 892
-- aim-run (host pad 0x100 lx 0 ly 32767)
   BOY1 owner st 100  up CBLK t 92     lo LWAF t 92     | puppet st 100  up CBLK t 333    lo LPAU t 333
```

* the state id and the UPPER-body clip agree (CBLK on both), the puppet looks "correct" to
  check_movement / check_attack_anim / check_visible - which is why the owner's report could pass them;
* the LOWER-BODY clip is `LPAU` (lower body PAUSED) on the puppet while the owner's is `LWAF` (walk
  forward) / `LWAL` (walk left): **the remote character's legs stand still while it slides along the ground
  in the aim stance**. That is "animations are not properly synced on screen", now measurable.
* walk / run / turn / aim-in-place / swing PASS on HEAD (the state setter plays those clips); only the
  aim+move combination fails, because the lower-body layer is driven exclusively by the movement state
  machine the puppet does not run.


## 3. What changed (files)

* `src/net.c`: `NET_VERSION` 23; `pkt_char` carries `intent[3]` (character+0x288), `wanted` (the owner's
  state +0x2dc), `ev_seq` + `ev_val[4]` (the last four state CHANGES, Obscure 1 `host_record_wanted`).
* `src/sync.c`:
  * `psample` carries the same fields; `peer_on_char` copies them, `puppet_pose` takes them at the
    playback instant (like `anim`/`speed`/`ui`);
  * `puppet_write` writes the intent into `+0x288/0x28c/0x290` behind the same guard the game's own
    setter uses (`+0x2c4 == 0`, FUN_004c6bd0);
  * `host_record_state` (the owner, before its update) + `puppet_wanted` (the receiver: replays one
    missed change per update, in order) + `puppet_state_ok` (the whitelist) + `puppet_locomotion`;
  * `puppet_prepare`: in the locomotion states it writes the owner's state into the machine's request
    field `+0x2e8` and leaves the state to the machine; an action state (or coming back from one) still
    goes through the state setter;
  * `puppet_finish` no longer forces `+0x2dc` in the locomotion states (the machine's own choice stands);
  * `char_send_local` sends the intent, the state and the event ring; the 10 s stats line gained one
    `puppet intent:` line (events recorded/replayed, machine ran/gated, the puppet's intent vector);
  * `own_char` / `puppet_move_ok` helpers.
* `src/hooks.c`: `hk_char_move` lets the game's own movement/state machine run for the puppet in the
  locomotion states (it was gated for every state since TASK 42); `hk_char_update` records this copy's
  own state changes before the update.
* `tests/check_anim_sync.py` (new): compares the played CLIPS (upper +0x220 and lower +0x224, their
  table tags and clocks) between the owner and the puppet over walk / turn / walk-down / run / aim /
  aim-walk / aim-strafe / aim-run / swing / guest-walk / guest-turn phases. It is wired into
  `tests/run_soak.sh` next to check_attack_anim.
* `src/net.c`/`src/sync.c`: `gait` (character+0x2e0, the owner's lower-body gait index). In the aim
  stance the movement machine stays gated (its action path is TASK 42's), so `puppet_gait` makes the two
  calls the machine makes when that layer changes (decompile 142194..142199: slot 0x6c stop the old layer
  clip, slot 0x4c = FUN_004e7420 play the new one) using the OWNER's gait. The gait itself is
  FUN_004da570's answer from the intent AND the aim target (+0x750, set by FUN_004db0e0) - the aim target
  is not streamed, so the owner's index is streamed instead of recomputed here.

Why the aim state does not simply let the whole machine run (tried, `chk46b`): with the movement machine
running at state 102 the lower-body layer followed (LWAF/LWAL) but the machine's own "request state 0"
(FUN_004e3ba0, decompile 139935) reset `+0x2e8` to 0 and the machine's tail then called the state setter
with 0 - the puppet's UPPER clip became `PAUS` while its state still read 102 (run `s46_b1.log`:
`puppet st 102 up PAUS ... lo LWAF`). The gate stays, and only the animation layer is mirrored.


