# FINDINGS 53 — 2.1 playtest: effects on the partner's screen, stuck attack stance, carried/pushed/thrown props

Labels: **OBSERVED** = printed by a run/check in this task or read in the decompile (address cited);
**DERIVED** = follows from the cited code but was not seen live; **GUESS**; **UNKNOWN**.
Base: branch `w/combat`, HEAD c2a1d2b (2.1, protocol 26). Decompile `local\decomp2\Obscure2.exe.c`.
Written early (task rule: by step 30), updated as the task runs.

## 0. Plan

1. **Effects (item 1).** `hk_blast` (TASK 49) returns before the whole blast on the non-owner copy, so the
   guest never sees the host's explosion. The blast function itself spawns the effect with
   `FUN_00591230(0x57444558, 0,0,0, pos, 0,0,1, -1.0f, 1.0f, 1)` (decompile 83536) - a generic
   effect/particle spawner, the same entry every weapon effect uses (`W?FI` muzzle flashes, etc.).
   Plan: hook `FUN_00591230`, relay the effect (tag + position + the remaining arguments) to the peer,
   and replay it there through the same game call. No damage/physics is involved in an effect call.
2. **Stuck attack stance (item 2).** The aim stance is state 0x64 (GAME_MECHANICS: LB sets +0x2dc = 0x64).
   `puppet_prepare` skips the state setter entirely for the attack states 200/300 (TASK 49's
   `puppet_attack`) while `puppet_finish` force-writes the streamed state id, and `puppet_anim` refuses to
   call the setter when the value equals the last one it set (`g_pb_anim_done`). A state/clip that comes
   back to a value the setter last saw therefore never replays the clip. Measure with a stance check
   (LB in/out 5 times each player) before changing anything.
3. **Props (item 3).** (a) carry-walk: the carry pose (state 0xa8c / 0x12d, upper clip CHAB) is streamed,
   the LOWER-body layer is only driven by `puppet_gait` in the aim family, so a walking carrier's legs do
   not follow; (b) a pushed prop is simulated by the copy that interacts with it and its position is not
   streamed, so the two copies diverge; (c) a break caused by a THROWN prop is only applied on the copy
   that threw it (the guest's copy keeps the whole box and crashed right after a prop carry packet -
   measured below). Plan: stream the moving prop's transform from its owner, let the receiving copy apply
   the break of a prop broken by a thrown prop, and fix the crash found in the guest's last frames.

## 1. Evidence (private 2.1 playtest logs, quoted lines only)

OBSERVED (guest log, last lines before the process died; no crash report followed):

```
00:30:21.106 guest: prop carry packet: prop CHAI id ???? -> ent 1ed3d5a8 (-463.8,-5609.7,12.4), character BOY1 22ded620 (holds 0)
00:30:21.107 guest: prop carry applied: BOY1 id ???? -> BOY1
00:30:23.525 guest: prop carry packet: prop CHAI id ???? -> ent 1ed3d5a8 (-463.8,-5609.7,12.4), character BOY1 22ded620 (holds 1ed3d5a8)
00:30:23.531 guest: prop carry packet: ... (the file ends mid-second; the game thread never logged again)
```

OBSERVED (guest log, another session - the box broken by a throw on the host's copy never arrives as a
break on the guest's copy; the guest keeps the whole box; the host logs its break):

```
00:27:25.176 guest: prop break packet: BKCS id ???? -> ent 1e595910 (573.5,-819.7,74.2) carrier none broken 0
00:27:25.452 guest: prop break applied by its class: BKCS ... -> broken 1
```

(the guest only applies breaks the host announces; when a THROWN prop breaks another prop the host's copy
does not announce it - to be measured).

OBSERVED (guest log: the states the puppet refused; TASK 53 item 2 candidates):

```
00:22:46.627 puppet: state 1800 is not on the safe list (the puppet holds its pose)
00:25:56.250 puppet: state 1106 is not on the safe list (the puppet holds its pose)
```

## 2. The effect spawner (OBSERVED, decompile)

`FUN_0048df50` (the dynamite blast) starts with the visual/audio work and only later walks the humans
(decompile 83502..83600):

```
FUN_00591230(0x57444558,0,0,0,pfVar1,0,0,1,0xbf800000,0x3f800000,1);     // 83536: "WDEX" at the blast point
...
(**(code **)(*(int *)(*(int *)(DAT_006c3068 + 0x378) + 0x1644) + 0x74))(pfVar1,...);   // camera shock
```

`FUN_00591230(tag, a2, a3, a4, pos, a6, a7, a8, a9, a10, a11)` = `FUN_0058f830(tag)` (the effect type)
then `FUN_005911d0(...)` (decompile 248987..249000). 115 direct callers; the dominant argument pattern is
`(tag, 0,0,0, posptr, 0|val, 0|1, 1, -1.0f, 1.0f, 1)` (49 + 48 + 10 + 7 call sites). The weapon muzzle
flashes call it with the weapon object's position (`in_ECX + 0x1b`, e.g. 0x57474649 at 88000).

## 3. Measurements (run 1 = chk53a, save 01 = I100)

### 3.1 The attack stance, 5 in/out cycles each way (OBSERVED, run 1)

`check_stance.py` (new) held LB 0.7 s and released it 0.9 s, five times, for each player, sampling the
state (+0x2dc), the upper clip (+0x220) and the lower clip (+0x224) on BOTH copies every 40 ms:

```
-- BOY1: baseline on its own copy state 0 up PAUS lo WALK | partner copy state 0 up PAUS lo WALK
   cycle 1/5: owner    ['0/PAUS/WALK', '100/CBLK/LPAU', '0/PAUS/LPAU']
   cycle 1/5: partner  ['0/PAUS/WALK', '100/CBLK/LPAU', '0/PAUS/LPAU']
...
-- GIR1: ... '100/CSLK/LPAU' ... identical on both copies
```

The stance (state 100 = 0x64, the aim state, GAME_MECHANICS) and the way back are IDENTICAL on both
copies in all ten cycles. So LB alone does not reproduce the owner's "stuck in attack stance"; the first
check version called it a failure because it compared the lower clip to the pre-stance baseline (WALK) -
the game itself leaves LPAU after the stance on BOTH copies (OBSERVED above), which is not a bug. The
check now compares the two copies at the same instant and requires state 0 on both. Next: the same
cycles WITH an attack (RB) from the stance, which is the state the puppet's copy skips (`puppet_attack`).

### 3.2 Save 01 has no usable prop (OBSERVED, run 1; slot scan)

Every one of the 7 CHAI chairs of I100 is `enabled 0 broken 1` in save 01 - the save recorded them
destroyed, so nothing can be carried, pushed or broken there. A slot scan of save 1..9 with the game's
own load path gives the levels: 1 = I015, 2 = D003, 3 = **J002 (11 CToeChair)**, 4 = J005, 5 = G003,
6 = H000, 7 = H006, 8 = I004, 9 = I007. `check_breakables.py` therefore loads save slot 3 (game3.sav =
J002) on the host when the level it was started in has no whole prop; the guest follows the host's level
(TASK 37).

### 3.3 The prop's collision object (OBSERVED, run 1)

Each chair's `+0x68` collision object is a `CToeHoeEntity` (RTTI), e.g. `body 19ce9588 CToeHoeEntity`
(the `raw_move_test` in check_breakables reports whether a raw `+0x6c` write sticks or the body is the
source of truth).

## 4. The effect relay (implemented in chk53a/chk53b)

* `src/hooks.c`: `hk_effect` on the game's generic effect spawner `FUN_00591230` (9-byte prologue
  `55 8b ec 8b 45 08 56 8b f1`, epilogue `ret 0x2c` = eleven stack arguments; ECX = the effect manager
  `game+0x3c4`). It records the effect's tag, its position and the remaining arguments, and calls the
  game as before. `fx_spawn` plays a peer effect with the same call (the manager read live, the position a
  local copy); a relayed call is not recorded again (`g_fx_replaying`), so the copies cannot bounce one
  effect back and forth.
* `src/net.c`: `NET_VERSION` 27, `PKT_FX` (up to 4 effects per packet: tag, position, a6..a11), sent from
  the transport thread (`fx_send_local` in `net_tick`), received into a locked queue.
* `src/sync.c`: `fx_local_record` (normal play only, duplicates within 150 ms dropped), `fx_send_local`,
  `peer_on_fx`, `fx_replay_tick` (called from the game update hook, never from Present), counters in
  `sync` (`fx local/sent/rcv/played/dup/skipped/calls`) and one log line per replayed effect type:
  `effect from the peer played: <TAG> at (x,y,z)`.

## 5. Next steps (updated as the runs come in)


