# FINDINGS 23 — the real attack input (LB held + A), the pipe-level race, and the fight (TASK 23)

Labels: **OBSERVED** = printed by a run/check in this task (log quoted) or read in the decompile/exe
(address cited); **DERIVED** = follows from the cited code/data but was not observed live; **GUESS**;
**UNKNOWN**. Decompile line numbers refer to `local\decomp2\Obscure2.exe.c`.

Branch `w/combat` (HEAD 8a4ddb6) + this task's uncommitted changes. DLL built from this worktree as
`chk23.dll`. Runs: `run_a231.log` (probe_attack23), `run_a232.log` (probe_attack24), `run_a233.log`
(probe_attack25), `run_a234.log` (probe_attack26, hung), `run_a235.log` (probe_attack27), `run_c231.log`
(check_combat, first run), `run_c23c.log` (check_combat + the trio regression), `run_reg23a.log`
(run_pair_menu with six checks) and `run_reg23b.log` (the pickup pair). The probe scripts of this task
were scratch and are not kept; `tests/check_combat.py` now contains the same attack discovery.

## 1. The pipe `level` race: the change now runs on the game thread (OBSERVED, fixed)

FINDINGS_22 §4.3: `level <tag>` called ChangeLevel (`FUN_004a1c00`) directly on the **pipe** thread and
two runs hung there for minutes while both games kept running and syncing. The call takes game state the
game thread owns, so the pipe thread waited for it forever.

`src/sync.c` now has `level_frame()` + `level_request()`, the same request-flag pattern the safe `tp`
uses (`tp_frame`/`tp_request`): the pipe thread queues (tag, entry, flag), `frame_tick` makes the call on
the game thread (inside the frame, with `g_level_replay` set so the hook does not record the replay as a
new transition) and the pipe thread replies with the verdict. `frame_tick` returns right after handling a
queued change, so no other sync code runs in the frame the world is torn down in. A 30 s timeout keeps a
stuck game from hanging a test ("error level: the game thread did not run the request in 30 s").

OBSERVED, the same command three times in three different pair runs, each answering in ~1 s:

```
== host level J001 317 1 -> ok level J001 317 1 (game thread)
   arrived after 1.0 s: host J001 guest J001              (run_a231, probe_attack23)
== host level J001 317 1 -> ok level J001 317 1 (game thread)
   arrived after 1.0 s: host J001 guest J001              (run_a232, probe_attack24)
== host level J001 317 1 -> ok level J001 317 1 (game thread)
   arrived: host J001 guest J001                          (run_a235, probe_attack27)
```

Six level changes (J001 in each of those runs plus J001/J000 in the check runs) with no hang. The
cross-thread wait that failed in FINDINGS_22 is gone by construction.

## 2. The attack chord: what the real input does (OBSERVED)

`tests/probe_attack23.py` (run_a231.log) held LB and pulsed A while LB stayed down, on the host's player
1 standing 22 units from the 80-HP `CCharacterNPC`, with the weapon in hand (`CToeWeaponCrossBow`, slot
0). The pad was set exactly as the owner describes: `pad 0 0x100` (LB), 200 ms later `pad 0 0x1100`
(LB + A) for 120 ms, LB alone for another 600 ms, then release; sampled every ~25 ms on both copies.

```
== EXPERIMENTS with player 1 (host pad), slot 0 (CToeWeaponCrossBow*)
   1 chord LB 200ms + A 120ms          life 80.0 -> 80.0 (drop 0.0) anim max 0x66 ws max 0
            0ms anim 0x00 ws 0 life   80.0 | g anim 0x00 ws 0 life   80.0
           53ms anim 0x66 ws 0 life   80.0 | g anim 0x66 ws 0 life   80.0
          132ms anim 0x64 ws 0 life   80.0 | g anim 0x66 ws 0 life   80.0
          158ms anim 0x64 ws 0 life   80.0 | g anim 0x64 ws 0 life   80.0
          946ms anim 0x64 ws 0 life   80.0 | g anim 0x00 ws 0 life   80.0
          999ms anim 0x64 ws 0 life   80.0 | g anim 0x64 ws 0 life   80.0
         1025ms anim 0x00 ws 0 life   80.0 | g anim 0x00 ws 0 life   80.0
```

So the chord **does** reach the game (the character enters the aim state `+0x2dc = 0x64` on both copies,
0x66 for the first frames while the stance settles) — but the swing never starts: the selected weapon's
state `+0x14` stays 0, no animation beyond the aim state, nothing on the enemy.

The variations below were tried in three pair runs. `run_a232` (probe_attack24) put the player
**8 units** from the enemy with the real melee weapon in hand (`CToeWeaponUberBeat`, slot 2, selected
with the D-pad, verified in the slot list) and tried longer holds; `run_a233` (probe_attack25) covered
the rest of the pad space:

```
   LB alone (reference)               anim max 0x64 ws max 0 | life 80.0 -> 80.0 | enemy states 0x0 | last attacker -
   LB + RT                            anim max 0x64 ws max 0 | life 80.0 -> 80.0
   LB + LT                            anim max 0x00 ws max 0 | life 80.0 -> 80.0
   RT alone                           anim max 0x00 ws max 0 | life 80.0 -> 80.0
   LT alone                           anim max 0x00 ws max 0 | life 80.0 -> 80.0
   LB + RB                            anim max 0xc8 ws max 0 | life 80.0 -> 80.0
   LB + BACK                          anim max 0x64 ws max 0 | life 80.0 -> 80.0
   LB + LS click                      anim max 0x64 ws max 0 | life 80.0 -> 80.0
   LB + RS click                      anim max 0x64 ws max 0 | life 80.0 -> 80.0
   LB + A (double tap 1)              anim max 0x64 ws max 0 | life 80.0 -> 80.0
   LB + A double tap                  anim max 0x64 ws max 0 | life 80.0 -> 80.0
   LB + A held 1.55 s                 anim max 0x64 ws max 0 | life 80.0 -> 80.0
   -- triggers (pad ... lt rt 255) and stick variants:
   LB + A with the stick forward      anim max 0x64 ws max 0 | life 80.0
   LB + A with the stick back         anim max 0x64 ws max 0 | life 80.0
   LB + A with the stick left         anim max 0x64 ws max 0 | life 80.0
   LB + A with the stick right        anim max 0x64 ws max 0 | life 80.0
   P2 chainsaw LB+A                   anim max 0x00 ws max 0 | life 80.0 -> 80.0
   P2 chainsaw LB + RT                anim max 0x00 ws max 0 | life 80.0
```

OBSERVED in the same run: A alone, B, X, Y (also under LB), RB, BACK, both stick clicks, both analog
triggers (255), a stick direction with LB+A, and a second player with the ChainSaw (the guest's own pad)
— none of them starts a swing. The enemy never reacts (`state 0x0`, `last attacker -`, life unchanged on
both copies), and the camera's target (`cam` -> camera manager `+0x17c`) never becomes the enemy:

```
   cam (idle): cam yaw own 25.1 valid 1 peer 74.5 valid 1 target 19efe520
   cam (after sweep): cam yaw own 10.8 valid 1 peer 69.8 valid 1 target 19efe520
```

The two new states that *did* appear: `LB + RB` -> character `+0x2dc = 0xc8` (not the swing: weapon
`+0x14` stays 0, the enemy is untouched), and `LB + LT` -> the aim state is cancelled (0x00).

**DERIVED**: the pad does reach the game's action map (movement, the D-pad weapon select, START, LB's
aim stance and RB/LT all work), so this is not a virtual-pad problem. Either the shipped map binds no
button to the game's attack action, or the attack action is bound but refused in this state. **UNKNOWN**
which of the two — the action table's order is not decoded and the game's attack entry could not be
reached (next section).

## 3. The game's attack entry: where it is, and why `swing` cannot reach it (OBSERVED)

* **The vtable slot**: the dword `0x004563a0` occurs exactly once in the exe's `.rdata`, at RVA
  `0x2595d8`, inside the vtable at RVA `0x259568` (VA `0x659568`) — slot 28 (byte `+0x70`), with the
  swing end `0x456710` in slot 29 (`+0x74`). (FINDINGS_22's "RVA 0x25ae34" was a false hit: that address
  is inside a string table; the correct RVA follows from the image base 0x400000.)
* **It is not the weapon entity's class**: the weapons the character holds (`character+0x704[4]`,
  classes `CToeWeaponCrossBow` / `CToeWeaponTaser` / `CToeWeaponUberBeat` / `CToeWeaponDynamite` /
  `CToeWeaponChainSaw` / ...) all share the vtable `0x65F5A4`, and slot 28 there is `0x48b570`, not the
  attack entry (the mod's reply, run_a232):

  ```
  host: error swing: slot 2 weapon 1A116448 has no attack entry (vt 0065F5A4: 0x48b570 0x486120 0x48abf0 0x486170)
  ```

* **The attack class** (vtable `0x659568`) parses a `mesh_name` and a `zone_id` and carries a position
  (`+0x6c/+0x70/+0x74`) and a direction (`+0x78/+0x7c/+0x80`); its attack sweeps hit points 90 units
  ahead through the character's impact manager (`character+0x30c`), sets `character+0x2bc` and the
  "attack" animation event, and counts hits in `+0x144` (decompile 50603-50760).
* **No instance is reachable in J001**: `swing` was extended to search for an object of that class among
  the pointers reachable from the selected weapon, the other three weapons, the character (`0x800`
  bytes) and the impact manager, and to call slot 28 on the first match (src/obscoop2.c,
  `attack_obj_find`). Every attempt reports:

  ```
  host : error swing: no attack object (weapon 1A022A90, impact 19B6D5E8, character 1C0061F0; tried slot 28 = 0x4563a0)
  guest: error swing: no attack object (weapon 19E32880, impact 19796248, character 1C2EF598; tried slot 28 = 0x4563a0)
  ```

  The world's entity list (`world+0x1768`, `CToeManager`) holds no object with that vtable either (the
  check prints the scan). **DERIVED**: the attack object is created per attack (or per weapon draw) and
  is not owned by the weapon entity, the character or the impact manager, so no test can call the game's
  own attack without the input that creates it. UNKNOWN: who creates it and from which script name.

`swing`/`swingobj` therefore remain dead ends for J001 — a diagnostic, not a working fallback. `swing`
is kept (documented as test-only) because its search is the cheapest way to check the class on another
level; the fight below does not use it. The heap scan used to find the class (`vtfind <vtable>`) was
removed again after it hung/crashed the host in run_a234: nothing uses it (`check_combat.py` scans the
world entity list instead), so the source differs from the last verified DLL only by that removal and its
comment block. `chk23.dll` rebuilds with the three known warnings and nothing else.

## 4. The input map (OBSERVED + DERIVED)

* The live map is `<exe>\coop_profile\remote\o2.ipt`, 724 bytes, identical to the shipped
  `package/*/obscoop_o2.ipt` (all 11 packages have the same md5). The game's own default
  `data/o2_input.ipt` is 728 bytes.
* The shipped map binds **89 gamepad codes** (1003-1030) against **15** in the game's default — it is
  the gamepad map, so the missing gamepad bindings are not the explanation for "the pad does everything
  except attack".
* **DERIVED**: the map is loaded correctly (LB = "aim" works), so if the attack action has a binding it
  is to a code our virtual pad cannot produce, or the action table index for "attack" is unbound. The
  action table (`input manager +0x30` count, `+0x34` array, `in_ECX[5] + N` per player, decompile
  126669-126800) would answer it, but its object is only reachable through the per-player input objects
  and the action order is not named anywhere we found. UNKNOWN.

## 5. The fight and its sync assertions (OBSERVED, run_c23c)

No attack exists (section 2-3), so `tests/check_combat.py` drives the life/death path through the game's
**own life method** on ONE copy — the pipe command `npcset <npc> <life>` calls vtable slot 9 (+0x24,
`CCharacterNPC_s9_v` @ 0x4f5bf0), which is the method every damage source funnels through
(FINDINGS_21 §2). It is **not an attack**: no hit reaction, no attacker (+0x750), no weapon state,
no damage number of its own. The values applied are the guide's melee combo (7/8/14), so the per-hit
drops below are *chosen by the test*, not measured from a swing; what they measure is the **sync**
(each step must land once, and only once, on both copies).

`run_c23c` = `sh tests/run_pair.sh <chk23.dll> check_combat.py check_party.py check_items.py check_hands.py`
(J001 80-HP `CCharacterNPC`, then J000 2 Rams at 120 HP):

```
== phase 1 (host player 1): player 1 attacks CCharacterNPC ...A (attack: npcset)
   tp in (1002.4 units away): ok settled at (14.76, 420.46, 27.66) after 0.8 s
        npcset 7 on host: ok npcset 19cd3c38 life 80.0 -> 73.0 (asked 73.0) state 0
   attack 1                       life host   80.0 ->   73.0 | guest   80.0 ->   73.0 | anim host 0x00 guest 0x00 | ws 0/0 HIT
        ... (8 more steps, 8 / 14 / 7 / 8 / 14 / 7 / 8 / 14)
   shot host during attack 2: 88.0% non-black -> ...\tests\shots\combat23_host.png
   shot guest during attack 2: 95.1% non-black -> ...\tests\shots\combat23_guest.png
   phase 1 (host player 1): 9 attacks issued, 216 samples, enemy life 0.0 state 0x5 on the attacker's copy
   phase 1: worst life difference on 189 settled samples 0.00 (tolerance 1.0)
   phase 1: transient: 11 of 216 samples inside one NPC snapshot (33 ms) differ, worst 14.00
   phase 1: per-hit drops at the attack boundaries host [7.0, 8.0, 14.0, 7.0, 8.0, 14.0, 7.0, 8.0, 7.0] | guest [7.0, 8.0, 14.0, 7.0, 8.0, 14.0, 7.0, 8.0, 7.0]
   phase 1: no double damage: every hit landed once on both copies
   phase 1: drop values against GAME_MECHANICS.md (melee 7/8/14, gun 15): matches the melee combo
   phase 1: player life equal on both copies within 0.00 (p1 100.0/100.0, p2 100.0/100.0)
   phase 1: attack animation samples equal on both copies 216/216 (attacker anim non-zero in 0)
   phase 1: enemy positions equal on both copies within 0.00 units (A) / 0.00 (B)
   phase 1 result: enemy A dead on both copies
...
   phase 1 (host player 1): 13 attacks issued, 312 samples, enemy life 0.0 state 0x5 on the attacker's copy   <- J000, 120 HP Ram
   phase 1: worst life difference on 273 settled samples 0.00 (tolerance 1.0)
   phase 1: transient: 14 of 312 samples inside one NPC snapshot (33 ms) differ, worst 14.00
   phase 1: per-hit drops at the attack boundaries host [7.0, 8.0, 14.0, 7.0, 8.0, 14.0, 7.0, 8.0, 14.0, 7.0, 8.0, 14.0, 4.0] | guest [same]
   phase 1: player life equal on both copies within 0.00 (p1 100.0/100.0, p2 100.0/100.0)
   phase 1: attack animation samples equal on both copies 312/312 (attacker anim non-zero in 0)
   phase 1: enemy positions equal on both copies within 0.00 units (A) / 0.00 (B)
...
== final state on both copies
enemies host:  CCharacterNPCRam.... 120.0 st 0x0, CCharacterNPCRam.... 0.0 st 0x5
enemies guest: CCharacterNPCRam.... 120.0 st 0x0, CCharacterNPCRam.... 0.0 st 0x5
player 1 life host 100.0 guest 100.0
player 2 life host 100.0 guest 100.0
sync guest: ... applied 6288 ... | npc sent 0 rcv 1779 applied 6535 snaps 0 blends 0 unmatched 0 life 25 dead 3 state 1 | ...
NOTE: the fight above was driven through the game's own life method (npcset), NOT an attack: ...
RESULT: combat OK
```

What that says, with the caveats:

* **Life within tolerance during the fight**: on the 189 (J001) and 273 (J000) *settled* samples the two
  copies never differ (0.00). The 11/14 non-zero samples are the **convergence window**: the guest only
  learns the host's enemy life from the next `PKT_NPC` snapshot (33 ms cadence, `host_send_npcs` in
  sync.c), so a sample taken between the hit and that snapshot still shows the guest's old life. Worst
  case is one full hit (14.0). At every attack boundary (read after 0.8 s of settling) the copies agree
  exactly, which is what the per-hit drop lists show.
* **Both dead at the end, no alive/dead split**: life 0.0 and the game's own death state 0x5 on both
  copies, in J001 and in J000. The earlier run `run_c231` (same code before the settled/transient split)
  reported the death transient as "1 sample had one copy alive and the other dead" — same cause.
* **No double damage**: every step appears exactly once in both copies' drop lists.
* **Player life equal**: 100.0/100.0 for both players on both copies throughout (the enemies never
  attacked, see below).
* **Attack animation samples equal**: 216/216 and 312/312 samples, but the attacker's `+0x2dc` is 0 in all
  of them — with no swing there is no animation to compare. This assertion is **not exercised**; it is
  only "equal because nothing happened".
* **Enemy AI moves/attacks the same way**: the enemies never moved at all. Positions on the two copies
  agree to 0.00 units in every sample, and their AI state (`controller+0x98`) stayed 0 through both
  levels; the players took no damage (100.0 on every sample). So the AI behaved identically on both
  copies by not activating at all in these levels — a live fight would still be the real test of it.
* **Phase 2 (the guest's player 2 kills enemy B) is NOT run**: with the host owning enemy life, a hit
  that only the guest's copy makes is reverted (measured in §6), so the guest cannot kill an enemy
  alone; a real kill needs the real attack, which both copies would simulate. The check prints that
  instead of faking it.

## 6. The enemy-life code of 6704c30: needed, not just a safety net (OBSERVED)

Switched off with the new pipe command `npclife 0` (test-only, `g_npc_life_on` in obscoop2.c/sync.c),
one 7-damage step applied on the HOST only (run_c23c, identical in run_c231):

```
== the enemy-life code of 6704c30 (guest ok npclife 0 (enemy life/death application off))
   target: CCharacterNPC .... life 80.0 at 1c3de328
   host only: ok npcset 1c3de328 life 80.0 -> 73.0 (asked 73.0) state 0
   correction OFF: host life 73.0 state 0x0 | guest life 80.0 state 0x0 | difference 7.00
   guest ok npclife 1 (enemy life/death application on)
   correction ON : host life 73.0 state 0x0 | guest life 73.0 state 0x0 | difference 0.00
   guest sync: ... | npc ... applied 4848 ... life 11 dead 2 state 1 | ...
```

* With the correction **off** the copies stay 7.00 apart forever — the guest never learns the hit, so a
  copy that misses a hit (or a kill, or a death) keeps its own life for good. That is the situation the
  code exists for, and the measurement shows it needs the code.
* With it **on** the guest converges within one snapshot (0.00 after 1.5 s), through the game's own life
  method, and the guest's counters show the applications (`life 11 dead 2 state 1` in run_c231,
  `life 25 dead 3 state 1` in run_c23c).
* **One owner, no double damage** (OBSERVED, same run): a guest-only step is undone —

```
== guest-only damage (the host owns enemy life)
   guest only: ok npcset 19fcc6b8 life 73.0 -> 66.0 (asked 66.0) state 0
   guest life right after its own damage 73.0 -> after the host snapshot 73.0 | host 73.0
```

  (the guest's life was 66.0 for a moment and the host's 73.0 snapshot put it back).
* **Cost**: the ≤33 ms window in which the copies disagree (measured above as the "transient" samples).
  A test that samples life faster than the NPC snapshot cadence will see it; a comparison on settled
  samples does not.
* **DERIVED, not measured**: the code copies the host's `+0x2dc` state only when the host says the enemy
  died (`if (hl <= 0.0f && *gst != st.npc.state)`, sync.c guest_apply_npcs). A death that only the
  guest's copy simulated would therefore leave the guest's copy in the death state with the host's life
  restored — a visible corpse on the guest that the host has alive. Not exercised here (no guest-only
  death was produced); it only matters if the two copies ever apply different damage, which the real
  attack would not do.

## 7. Regression (OBSERVED)

Three pairs on `chk23.dll`, 6 game processes (the task's reserve). Every run ended with no game left
(`still running: []`) and `OWNER FILES UNCHANGED (apart from Steam remotecache.vdf)`.

1. `sh tests/run_pair_menu.sh <chk23.dll> check_party.py check_items.py check_hands.py
   check_hands_visible.py check_entities.py check_movement.py` (run_reg23a.log):

```
party OK
items OK
hands OK (2 characters checked)
hands visible state OK (2 characters checked)
entities OK (host 43, guest 43)
E: PASS
A: PASS
B: PASS
C: PASS
D: FAIL -- GIR1 copies differ: mean 20.39 max 64.79 (max 10.0/55.0)
```

   * **`check_hands_visible.py` PASSES on this branch** — the wb8 difference of FINDINGS_21 §8 does not
     appear in the normal menu flow (all four slots equal on both copies). That question is answered.
   * `check_movement` phases E/A/B/C pass; **D fails** with the guest's GIR1 diverging by 20.39 mean /
     64.79 max. This is the movement C/D flakiness the task says to report and not chase; nothing in this
     task touched movement, position sync or the input stream.

2. `OBSCOOP_PICKUP_CLASS=MEDI OBSCOOP_PICKUP_SPAWN=1 sh tests/run_pair.sh <chk23.dll> pair_j003.py
   check_pickup.py` (run_reg23b.log):

```
phase host->guest: OK
phase guest->host: OK
results: [('host->guest', True), ('guest->host', True)]
pickup OK: both directions collected on both copies, inventories match, no echo
```

3. The trio after the combat check, in the same pair as `check_combat.py` (run_c23c.log, quoted in §5):

```
== check_party.py
party: host ['BOY1', 'GIR1'] guest ['BOY1', 'GIR1'] | inventory: host 44 guest 44
party OK
== check_items.py
items: before host 44 guest 44
items: after host 45 guest 45
items OK
== check_hands.py
in hand: host [('BOY1', 'TASE'), ('GIR1', 'CSAW')] guest [('BOY1', 'TASE'), ('GIR1', 'CSAW')]
hands OK (2 characters checked)
```

   (check_hands prints `inventory: host 44 guest 45` there — check_items had just picked an item up on the
   host copy a moment earlier; the hands it compares are equal. That line is informational.)

## 8. Screenshots during the fight (OBSERVED, looked at)

`tests/shots/combat23_host.png` (88.0 % non-black in J001 / 66.8 % in J000) and
`tests/shots/combat23_guest.png` (95.1 % / 83.2 %), taken with the window in the foreground while the
second damage step of phase 1 was applied (the check prints the fraction and the path). The J000 pair
(the files kept on disk) shows: **host** — the BOY1 character in a dark night garden next to a stone
gallery, holding a torch, no enemy in frame and no swing pose; **guest** — the same level from player 2's
view: GIR1 in a striped top standing on a stone terrace in front of a double door, the ChainSaw in her
hand, torch lit, doors and lamps rendered normally. Two normal in-game renders of the same level,
different player views — and **no attack animation**, because no attack happened (the fallback's damage is
applied to an enemy outside the frame). Nothing else on screen changes.

## 9. Note on the working tree

`GAME_MECHANICS.md` shows as modified in `git diff`, but not by this task: someone else added notes about
TASK 23's LB+A result while the runs were going. This task's changes are `src/obscoop2.c`, `src/sync.c`
and `tests/check_combat.py` (plus this file); all left uncommitted.

## 10. DONE / NOT DONE / UNKNOWN

**DONE**

* The pipe `level` race is fixed: the change runs on the game thread through a `frame_tick` request flag
  (the `tp` pattern) and the pipe thread waits for the verdict with a 30 s cap. Six live level changes in
  five runs, no hang (§1).
* The real attack input is measured exhaustively on two live copies: the owner's chord (LB held + A
  pulsed, short/long/charged, stick neutral/forward/back/left/right), every other pad button, both
  triggers, both stick clicks, A alone, on the CrossBow, the Taser and the UberBeat (player 1) and on the
  guest's ChainSaw, at 22 and at 8 units, on both copies at ~25 ms resolution. **The aim half works
  (+0x2dc = 0x64/0x66 on both copies); nothing starts the swing** (§2).
* The game's attack entry is located precisely (vtable `0x659568`, slot 28 = `0x4563a0`, slot 29 =
  `0x456710`) and shown NOT to be the weapon entity's class; no object of that class is reachable from the
  weapon, the character or the impact manager, and the world's 43 entities contain none (§3).
* A test-only door into the game's own life method (`npcset`, vtable slot 9) drives the enemy life/death
  path on one copy, and `tests/check_combat.py` then asserts the whole sync set on both copies: life
  equal on settled samples (0.00), per-hit drops identical (7/8/14 + the finishing 4), both dead with the
  game's death state 0x5, no alive/dead split, player life equal (0.00), enemy positions equal (0.00),
  attack-animation samples equal but not exercised (§5).
* The 6704c30 enemy-life code is shown to be **needed**: with `npclife 0` the copies stay 7.00 apart; with
  it on they converge to 0.00 in ≤1.5 s; a guest-only hit is reverted (one owner, no double damage) (§6).
* Regressions: party, items, hands, entities, hands_visible, movement A/B/C/E, and the pickup pair in both
  directions all pass; `check_hands_visible`'s wb8 failure from FINDINGS_21 does **not** appear on this
  branch (§7).
* Foreground screenshots of both copies during the fight, viewed and described (§8).

**NOT DONE**

* **The fight with the real attack input**: no input and no game attack entry starts a swing in J001 or
  J000 with this build and input map. So the task's phase 1/phase 2 as written (host's player 1 kills A
  with the pad, guest's player 2 kills B with the guest's pad) is **not proven**; the life/death sync was
  proven through the game's own life method instead, and the check says so in its output and its final
  NOTE.
* **No attack animation could be compared** (both copies' attacker animation stayed 0) and **no
  double-damage test of a real swing** exists — the "no double damage" result above is about the
  correction, not about two copies each simulating one hit.
* **The enemy AI was never active**: no enemy moved or attacked in either level (positions 0.00 apart,
  AI state 0, players at 100 HP). "The AI moves/attacks the same way on both copies" is only answered in
  the degenerate case (both copies: nothing).
* **Phase 2 as specified** (the guest's own pad kills enemy B) and therefore its assertions are not run.
* `check_movement` phase D fails (20.39 mean / 64.79 max); reported, not chased, as the task instructs.

**UNKNOWN**

* Which action index the game uses for "attack" and whether the shipped `obscoop_o2.ipt` map binds any
  XInput button to it. The map is the gamepad map (89 gamepad codes vs 15 in the game's default) and
  LB/RB/START/D-pad/stick all work, so the failure is specific to the attack action.
* Who creates the attack object (vtable `0x659568`) and when; whether calling its slot 28 *would* damage
  the enemy (never exercised, because no instance exists in these levels).
* Why the level scripts keep both the enemies' AI and the player's attack disabled in J001/J000 (the
  enemies never activate even with the player standing 7 units away for minutes).
* Whether a guest-only *death* (not just a guest-only life loss) leaves the guest's copy in the death
  state with the host's life restored — DERIVED from the code, not measured (§6).
