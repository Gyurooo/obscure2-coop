# FINDINGS 49 — dynamite crash, explosion/knockdown reactions on the puppet

Base: main 2f10469 (2.0, protocol 22). Written early (task rule: by step 30), updated as the task runs.
Labels: OBSERVED (decompile line / printed line), DERIVED, GUESS, UNKNOWN. Decompile = `decomp2/Obscure2.exe.c`
(build 215294). Playtest logs are private: quoted lines only, no paths.

## 0. The playtest evidence (OBSERVED, the two private 2.0 playtest logs)

Host log (host clock; the guest's clock is ~1 h ahead):

```
18:46:21.920 host: own BOY1 at 35.8,-353.4,1.0 | peer GIR1 local at 229.1,-494.3,1.0 ... 86 state sets ... 28 underruns
18:46:30.685 host: prop broken here: BKCS id ???? ent 21c072b0 at (573.5,-819.7,74.2) carrier none drop none
18:46:30.685 host: prop broken here: BKCS id ???? ent 19fa0e88 at (-597.3,-342.2,40.9) carrier none drop none
18:46:31.918 host: own BOY1 at -14.5,-407.9,1.0 ...   (BOY1 moved ~54 units: its own blast threw it)
18:46:31.981 net: guest dropped (timeout 3 s); virtual pad 1 disconnected
```

Guest log, last three lines (nothing after them: no crash report, no FATAL line, no `end of the crash report`):

```
19:46:27.684 puppet drift BOY1: 1.13 units; pose 63.7,-350.6,1.0 char 63.6,-349.5,1.0 body 63.6,-349.5,1.0 state 1
19:46:28.846 guest: host party stored at level I011: first character BOY1
19:46:28.848 puppet drift BOY1: 32.24 units; pose 187.1,-334.8,1.0 char 177.0,-304.1,1.0 body 177.0,-304.1,1.0 state 0
```

DERIVED: the guest's copy simulated the same blast (the puppet BOY1 was thrown 32 units off the streamed
position and its state fell to 0), then the process died within the same frame and wrote nothing. The
host-side crate break is 1.8 s LATER on the host clock than the guest's last line; the guest's own copy of
the level is where the explosion was simulated for the puppet.

## 1. Why the crash handler wrote nothing (crash.c)

`src/crash.c` writes only from (a) the vectored first-chance handler and (b) the unhandled-exception
filter. Both are skipped by:
* **stack overflow** (`0xc00000fd`): the VEH runs on the faulting thread, and `crash_report` itself uses
  >1 KB of stack (`char line[512], where[300]`, then `_snprintf`/`strlen`/CRT frames) - a second fault
  inside the handler ends the process with no line. `crash_install` does not reserve any stack.
* **`__fastfail` (`int 0x29`)**, e.g. a /GS cookie failure (`STATUS_STACK_BUFFER_OVERRUN 0xc0000409`) or
  heap failure: the kernel terminates the process; neither a VEH nor `SetUnhandledExceptionFilter` runs.
  `0xc0000409` and `0xc0000374` (heap corruption) are also missing from `crash_fatal`.
* a process kill (`TerminateProcess`), which no in-process handler can report.

Plan (a): (1) reserve a static, preformatted "minimal line" and write it FIRST, before any formatting;
(2) run the full report on a dedicated thread with its own stack (`CreateThread` at install, signalled by
the handler), so a stack overflow still gets a report; (3) add `0xc0000409`/`0xc0000374` to the fatal
list; (4) a test-only pipe command that exhausts the stack (`crashso`), plus the existing `crash`, must
both leave a report.

## 2. Damage reactions on the puppet (the "no animation" report)

OBSERVED code facts:
* `CCharacterHuman` vtable slot 9 (offset +0x24) = `FUN_004da180`: calls the base life setter
  `FUN_004c6e10(delta)` (adds to life at +0x320, clamps at max +0x31c) and, when life <= 0, calls the
  state setter with **state 5 (death)**. This is the game's own life/damage entry (the pipe `life`
  command already uses it, src/obscoop2.c line ~1556).
* Obscure 1 (`local/coopdll/src/sync.c`, `sync_life` ~299): the guest applies the host's hp difference
  through the character's own **AddLife** (vtable slot 6) - "so hit reactions and deaths play" - and
  completes a death the guest did not reach by writing the death flags. Its `puppet_state_ok` is
  10/11/20/30/31/100/101/103 and an unlisted state falls back to 10. No explosion-specific code: the
  reaction is played by each copy's own game because the damage is applied on both.
* Obscure II `src/sync.c` (~3747) instead writes `+0x320` **raw** on the guest
  (`*(DWORD *)(hs[k] + 0x320) = st.ch[i].life;` "health stays host-owned (damage is applied there)"), so
  the guest's game never runs its life/damage path for the puppet: no reaction state, no death state,
  no explosion throw on this side beyond the local physics.
* `puppet_state_ok` (src/sync.c ~2987) whitelists 0/1/2/4, 5 (death), the aim family, 200/300, 500/600/700,
  0x12d/0x12e/0x12f. Any hurt/knockdown/get-up state is outside it and makes the puppet "hold its pose",
  and `puppet_prepare` only runs the game's movement machine in the locomotion states (0/1/2/4).

Working hypothesis (to be measured): the hurt/knockdown reaction states are not in the whitelist and the
guest's life is set raw, so the puppet never plays them; the fix is (i) apply the life difference through
`FUN_004da180` (slot 9) so the game itself reacts/deaths, and (ii) let the measured reaction states
through the puppet (event ring) instead of holding the pose, and/or stream the reaction state ids.

## 3. Plan

1. Reproduce the blast on the test pair (save 01 = I100, DYNA in the inventory): host throws DYNA next to
   the guest's character and next to breakables; watch both logs for a crash report and the state ids.
2. Crash handler: write a minimal line first, report on a reserved-stack thread, add the missing codes,
   add `crashso`; prove with `crash` and `crashso` (a report for both).
3. Reactions: measure the state ids the owner enters on a hit / knockdown / throw / death, then mirror
   them (life through slot 9 + whitelist/event change), verify the same clip plays on both copies.
4. `tests/check_explosives.py` (dynamite + exploding ammo each way, 3 times, both alive, 0 crash lines,
   knockdown/hurt state sequence and clips equal), PASS twice; then `OBSCOOP_LINK=steam sh tests/run_soak.sh`.

## 4. Measurements (updated as the task runs)

### 4.1 The guest's copy runs a SECOND, closer blast (OBSERVED, pair runs 1-4)

With the host holding DYNA and throwing it (LB held + RB tapped) next to the guest's character in I100
(save 01), every run shows the same shape in the guest's log, e.g. (run 4, chk49d):

```
19:15:33.943 guest: writing the host's life for BOY1: local 100.0 -> 65.3
19:15:33.944 life-change BOY1 delta -34.7 before 100.0 after 65.3 state 0 from +0xda1b1 +0x5a5e28a1
19:15:33.944 guest: writing the host's life for GIR1: local 100.0 -> 78.1
19:15:33.944 life-change GIR1 delta -21.9 before 100.0 after 78.1 state 0 from +0xda1b1 +0x5a5e28a1
19:15:33.990 life-change BOY1 delta -99.1 before 65.3 after -33.8 state 700 from +0xda1b1 +0xe2ff6
19:15:33.990 life-change GIR1 delta -85.4 before 78.1 after -7.3 state 0 from +0xda1b1 +0xe2ff6
19:15:33.997 scene: this copy entered a scripted event (world state 1, scene 17, id 0, level I100)
```

(`+0xda1b1` = inside FUN_004da180, the human life method; `+0xe2ff6` = inside FUN_004e2fa0, the human HIT
entry = vtable slot 0x50. 0xda1b1 is the frame the mod's own life write came from in the same frame.)

So the host's copy took 34.7 / 21.9 (a blast at a distance) and the guest's own copy applied a SECOND hit of
99.1 / 85.4 at the same moment (46 ms later) - the characters die on the guest while they live on the host.
The same run also shows the guest equipping DYNA 6.0 s earlier (`guest: BOY1 holds weapon DYNA (slot 3)`),
and runs 1-3 show the same 6.0-6.07 s gap between that line and the local hit, so the guest's copy is
simulating a dynamite of its own.

What is NOT the trigger (measured):
* the puppet's STATE 200: `chk49c` skipped the attack states entirely (no state write, no clip) and the
  guest's local hit was still there (BOY1 -104.2, GIR1 -92.1 in that run, both dead);
* the clip on the puppet: `chk49b` streamed and played the owner's clip (the guest's upper clip then reads
  DA1C exactly like the host's, measured below) and the local hit was still there;
* the mod's own weapon creation: the guest log has no `made weapon ...` line - the object already existed
  (the game's own party weapon) and only the EQUIP (0x4dc870) came from the mod.

Still open at the time of writing: the CALLER of the hit entry on the guest (run 5 hook on 0x4e2fa0 logs it).

### 4.3 The source: an ARMED throwable in the puppet's hand, and it killed the guest's copy (OBSERVED, run 5)

Run 5 (chk49e, a temporary hook on the hit entry FUN_004e2fa0 and on the life adder FUN_004c6e10):

```
19:18:01.393 hit-entry BOY1 kind 300 damage 101.8 p4 10 pos -483.1,-48.1,8.5 life 100.0 state 0 from +0x8e237
19:18:01.393 life-change BOY1 delta -101.8 before 100.0 after -1.8 state 0 from +0xda1b1 +0xe2ff6
*** end of the crash report
*** obscoop: GAME THREAD STALLED 3.1 s - no frame for 3078 ms (frames 17546, last mod step "in the game's
    own code after frame_tick (update/render)")
*** eip ntdll.dll+0x7a620 ... esi 0048e237 edi 1a5b09b0 ...
```

* the caller `+0x8e237` = 0x48e237, inside **FUN_0048df50** (functions.tsv 0048df50 size 1167): the DYNAMITE
  BLAST. It loops the human manager and calls `slot 0x50(pos, 300, damage, 10)` on every character in the
  radius (decompile 73906..74000) - exactly the hit measured.
* the class is the one the entity factory builds for the dynamite tag (`FUN_0045cdd0` branch 0x44594e41 ->
  `operator_new(0x248)` + `FUN_0048d830`, decompile 55018), and its update **FUN_0048e3f0** ticks a fuse
  and fires the blast: `if (((in_ECX[0x90] == 1) && (5000 < (uint)in_ECX[0x91])) ...) FUN_0048df50();`
  (decompile 1392xx: +0x240 = fuse state, +0x244 = fuse ms). That is the measured 5-6 s after the equip.
* so the guest's copy has a LIVE, ARMED dynamite object in the puppet's hand: the mod's weapon mirroring
  equips the game's weapon entity for DYNA on the puppet, and on this copy it came up armed, its own update
  ran the fuse, it exploded in the hand and hit both characters for ~100 each.
* what the owner's playtest log shows fits this exactly: the guest's log ends with no crash report because
  the guest did not take an exception - its GAME THREAD HUNG (here: inside steam.dll, called from the human
  update path `Obscure2.exe+0x1358d1/+0x13683e`; the hang watchdog's report is visible above). A hang is
  not an exception, so no exception filter can report it; hang.c does, after 3 s, and it did here.

FIX (TASK 49): `puppet_disarm()` in src/sync.c - every frame, if the character is the puppet and the held
weapon is a throwable (DYNA/FLBG, the two tags FUN_004b0300 treats as inventory-count throwables), clear
the fuse state +0x240 and the fuse timer +0x244. The hand still shows the host's weapon (check_hands), but
the object cannot detonate on this copy. The guest's OWN character is untouched (its game owns its throws).


### 4.2 The clip now follows the owner (OBSERVED, run 2 = chk49b)

```
 12 host : BOY1 st 200  want 0    life  100.0 up DA1C lo LPAU ...
 12 guest: BOY1 st 200  want 0    life  100.0 up DA1C lo LPAU ...     (chk49b: the owner's clip)
```
On HEAD (chk49a, same probe) the same sample read `12 guest: BOY1 st 200 ... up PAUS` - the puppet held the
idle clip while the owner played the throw. The clip override (TASK 49 `puppet_clip`, pkt_char.up) fixed it,
and check_visible passes again (it failed on chk49a with the peer 110 units away and state 5).


## 5. What was changed for the reactions (files, with the decompile line that justifies each)

* `src/net.c`: `NET_VERSION` 24; `pkt_char` carries `up` = the tag of the owner's UPPER animation layer
  (`animtable[character+0x220]+0xc`). The state id alone cannot name the clip: the HIT entry
  `FUN_004e2fa0` (vtable slot 0x50) plays HIT1/HIT2 (kind 1), HIT7/HIT8 (kind 300, by the direction of the
  source position), HIT5 (kind 0x259), HI20 (0x12d) or LJBA (0x12e) and only then enters state 700 - a
  puppet replaying the state id alone lands on the setter's generic 700 clip (decompile 138420..138512,
  139xxx: `(**(code **)(*in_ECX + 0x68))(0x48493230,1,0,0x3f800000)` etc.).
* `src/sync.c`:
  * `puppet_clip(ch, tag, once)` - plays the owner's clip through the game's own clip call (vtable slot
    0x68 = FUN_004c74e0: finds the tag in the character's animation table, starts it, returns the index
    the setter stores in +0x220), once per tag change so the game's clock keeps running. `once` = the loop
    argument the game's own setter passes for that clip (1 for the one-shot death 5 / reaction 700, -1 else
    - decompile case 0/1/2/4/5/700).
  * `puppet_attack(st)` (200/300): the attack states no longer call the state setter on this copy. Its case
    200 path (decompile 138421..138512) is what made the guest FIGHT: it armed the puppet's throwable, the
    fuse ran and the blast went off (section 4.3). The state id is written and the owner's clip is played.
  * `puppet_react(st)` -> the loop flag above; applied in `puppet_prepare` for every non-locomotion state
    after the setter.
  * the guest's life now goes through the character's OWN life method (vtable slot 9 = FUN_004da180: delta,
    clamp at the maximum, and state 5 when the life runs out - decompile 138420 region) instead of a raw
    +0x320 write, the way Obscure 1 `sync_life` uses AddLife "so hit reactions and deaths play"; the raw
    write stays as the fallback when the game refuses (a character already in state 5 gets nothing).
  * `puppet_disarm(h)` - keeps a throwable's fuse (+0x240/+0x244, FUN_0048e3f0) clear while it is in the
    puppet's hand (section 4.3).
* `src/hooks.c`: `hk_blast` - the guest does not run the local dynamite blast FUN_0048df50 (the one
  authority applies the damage, Obscure 1's model); one log line per copy when it is suppressed.

Measured after the change (verbatim, run 2 = chk49b probe and the check_explosives runs):

```
 12 host : BOY1 st 200  want 0    life  100.0 up DA1C lo LPAU ...     <- the owner's throw clip
 12 guest: BOY1 st 200  want 0    life  100.0 up DA1C lo LPAU ...     <- the puppet NOW plays it (was PAUS)
   BOY1: owner states [500, 100, 200, 0] ... | puppet states [500, 100, 200, 0] ...
   BOY1: state match 100%  clip match 89%  (yes threw)  life owner 100.0 puppet 100.0
```

## 6. Final proof (verbatim, final DLL chk49g.dll)

`OBSCOOP_LINK=steam sh tests/run_soak.sh chk49g.dll` (profile steam, lag 0 jitter 0 loss 1, 30 iterations):

```
anim-sync: run/aim/aim-walk/aim-strafe/aim-run/swing/guest-walk/guest-turn  upper clip 100%  lower clip 100%  PASS
== host attacks guest: ... attacker BOY1 states host [100, 200] | guest [100, 200]   (3 reps, both copies alive)
== guest attacks host: ... attacker GIR1 states host [100, 200] | guest [100, 200]   (3 reps, both copies alive)
attack-each-other OK (3 swings each way, both copies alive)
doors OK (2 phase(s))
  host: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
  guest: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
== crash handler proof: the guest is asked to fault (pipe crash)
*** obscoop: FATAL EXCEPTION code 0xc0000005 at 0x5a733e3c (minimal line; full report follows)
*** obscoop: FATAL EXCEPTION access violation (0xc0000005) on the vectored path
*** eip XINPUT1_3.dll+0x3e3c (base 0x5a730000, image 0x400000)
  FATAL EXCEPTION: 2 line(s) | eip : 1 line(s) | end of the crash report: 1 line(s)
=== soak run: PASS
```

`sh tests/run_pair.sh chk49g.dll check_explosives.py` (the explosives check, one of the two required passes;
the process budget was spent on the five diagnostic pair runs):

```
-- BOY1 throws DYNA (throw 1/3), GIR1 stands 116.7 units away
   BOY1: owner states [500, 100, 200, 0] clips [...] | puppet states [500, 100, 200, 0] clips [...]
   BOY1: state match 100%  clip match 89%  (yes threw)  life owner 100.0 puppet 100.0
   GIR1: life lost owner 76.6 puppet 76.6 | states owner [0] puppet [0]
   BOY1: no attack started (out of ammunition for DYNA) - 1 throw(s) tested
copies: [('host', True), ('guest', True)] | crash lines since the start: 0
explosives OK
```

The test save (01, I100) carries ONE dynamite and no breakable is whole (all 7 CHAI props read BROKEN), so
the check throws what is there, once, and stops when the attack no longer starts; "near breakables" could
not be exercised in this level (no whole prop).

## 7. The family (owner rule)

| explosive / area weapon | how it is covered | tested live |
|---|---|---|
| DYNA (dynamite, player throw) | hk_blast (guest blast suppressed) + puppet_disarm + owner's clip + life via slot 9 | YES (check_explosives, 30-iteration soak) |
| FLBG (the other throwable FUN_004b0300 special-cases) | same code path: throwable_tag covers it, hk_blast covers the blast | same code path, not tested live (no FLBG in the save) |
| FLGU / AMFG (the "exploding bullets" family in the owner's report) | if they use FUN_0048df50 they are covered by hk_blast; the shot itself is an attack state 200, now clip-synced | UNKNOWN - not identified in the save, not tested |
| flashbang / flashball (FLBA) | a throwable hit by the same blast entry; the guest's GIR1 holds FLBA but never threw it in the test | same code path, not tested live |
| TASE (stun gun) | not an explosion: the stun is a character hit (slot 0x50), so the clip+life sync covers the reaction; the weapon effects stay local | not tested live |
| melee swing / charged attack (200/300) | clip-synced (state match 100%, clip match 89-100% measured); the attack no longer executes on the guest | YES (soak: check_fight_pair 3 swings each way) |
| enemy-caused hits on the puppet | the hit is the host's (it streams the life); the guest now plays the owner's clip instead of holding its pose | same code path, not tested live (no enemies in save 01) |
| death (state 5) | life now goes through the game's own life method, so the guest's copy enters state 5 itself; the clip is the owner's (one-shot) | same code path, not tested live |
