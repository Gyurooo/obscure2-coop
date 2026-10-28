# FINDINGS 28 — character abilities in sync (TASK 28)

Labels: **OBSERVED** = printed by a run/check in this task, or read in the decompile / `.tsv` (address cited);
**DERIVED** = follows from the cited code but was not seen live; **GUESS**; **UNKNOWN**.
Decompile: `local\decomp2\Obscure2.exe.c` (build 215294); live data from `tests/scan_abilities.py`
(two read-only solo launches: all ten slots, then slots 02/04/07/08/10 with both entity lists and the
NPC manager). Base: HEAD d90e580, `NET_VERSION` 14 -> **15** with this task's `PKT_APT`.

## 0. Result in one paragraph

The survey found only two live aptitude objects in the ten test saves (I015 `CToeLockPick`, H000
`CToeHeavyCase`) and decompiled both. A real bug surfaced on the way: after a save load the guest had no
character of its own, because `attach_player2` attached player 2 to the same human player 1 drives whenever
the save's controller record names manager entry 1 (I015: `BOY2 ctlCHC1`); fixed. A `PKT_APT` result sync
(the object's changed fields and position, plus the action announcement) is implemented and compiles, but
the live ability could not be driven to a result within the process budget: the game's own interaction
scan recognises Stan at the lock (`+0x104` = 2) yet its use never links the character to the object, and
the A presses in the final run changed nothing on either copy. So the sync path itself is **UNVERIFIED
live** (§3-§5) and the check FAILS on "the action never ran" - it is not a pass.

## 1. Survey (OBSERVED, two solo launches, read-only)

`tests/scan_abilities.py` (new) loads each save slot with the game's own `loadsave gameN.sav`, then prints
the live party, the 8 progress character records (`progress+0x1b0c`), every level entity whose RTTI class
is an aptitude object with its fields, both entity lists, and the NPC manager. The survey is read-only.

| slot | file | level | live party | player 1 (controller CHC1) | aptitude objects found (position, `+0x20` active / `+0x24` usable / `+0xa8` collected) |
|---:|---|---|---|---|---|
| 01 | game0.sav | I100 | BOY1, GIR1 | BOY1 | `CToeDocument` (383.2, -75.1, 1.5) 0/0/1; 2 `CToeDoor` |
| 02 | game1.sav | I015 | BOY1, BOY2 | **BOY2** | **`CToeLockPick` (-1380.3, -562.8, 109.1) 1/1/0 r 135**, cls `LCKP`; `CToeBreakableCase` (z 493); `CToeDoor` `+0x24 = 0` |
| 03 | game2.sav | D003 | BOY1, GIR1 | BOY1 | none |
| 04 | game3.sav | J002 | BOY1, GIR1 | BOY1 | `CToeDiscLock` (1315.8, -1944.9, 137.5) 1/1; `CToeChestKey` x2 (both `+0x20 = 0`, collected); 2 `CToeDoubleDoor` |
| 05 | game4.sav | J005 | BOY1, GIR1 | BOY1 | only 1 `CToeDoubleDoor` |
| 06 | game5.sav | G003 | BOY2, GIR1 | BOY2 | none |
| 07 | game6.sav | H000 | BOY3, GIR3 | **BOY3** | **`CToeHeavyCase` (-6.6, -579.0, 59.7) 1/1/0 r 200** plus its 4 `CToeEdge`; `CToeLockPick` (463.1, -93.3, 228.3) 1/1 (Stan is not in this party) |
| 08 | game7.sav | H006 | BOY1, GIR3 | BOY1 | `CToeDocument` (-55.2, 151.2, 99.5) 0/0/1; 3 `CToePedestal` |
| 09 | game8.sav | I004 | BOY1, GIR1 | BOY1 | none |
| 10 | game9.sav | I007 | BOY1, BOY2, GIR1, GIR3 | BOY1 | `CToeChestKey` `+0x20 = 0`, `CToeChain`, `CToeBreakableCase`, 4 doors |

* The `CToeDocument`/`CToeChestKey` entries in the manager's second list (`mgr+0x18`) sit at
  position 0 - they are inventory-derived objects, not placed level entities. The documents in the
  level list are already collected (`+0xa8 = 1`).
* No slot has a live `CToeDarkAura*` (Shannon), `CToeLadder`/leg-up (Corey) or an active Mei machine
  (`CToeDiscLock` exists in J002 but Mei is not in that party; `CToeChestKey` entities are inactive).
* **The two usable aptitude objects are the I015 lockpick (Stan = BOY1) and the H000 heavy case
  (Sven = BOY3).** In a pair, the save's controller record decides who is player 1: I015's record is
  `BOY2 ctlCHC1`, so the host plays Kenny and the guest's player 2 is **Stan** (the lockpick owner);
  H000's record is `BOY3 ctlCHC1`, so the host plays **Sven** (the heavy-case owner) and the guest's
  player 2 is Amy (no active object in H000). That gives one ability per direction.

## 2. Decompile: how each chosen object starts and what it leaves

### 2.1 `CToeLockPick` (class tag `LCKP`, RTTI `CToeLockPick`, vtable 0x65b3c4)

* Parse `FUN_0045b9e0` @0x45b9e0 (vtable+0x08) loads `assets\lockpick\lockpick.zwo`, the `item_closed`
  event id into `+0x190` (`0x24700001`) and builds the lock mesh parts.
* Eligibility check `FUN_0045a9e0` @0x45a9e0 (vtable+0x34), interaction type 1 (front):
  needs `+0x24 != 0`, `+0x14 != 4`, the character within radius `+0xa0`, facing dot
  `dot(char->target, normalize(char - lock)) > 0.5` and `|lock.z - char.z| <= 200`.
  **Only BOY1** gets prompt `0x1c000004` and `+0x104 = 1`; every other character gets prompt
  `0x4700003` and the same score 100. Type 2 (the back side, facing away: dot < -0.5) is BOY1 only
  and sets `+0x104 = 2`.
* Use `FUN_0045ac10` @0x45ac10 (vtable+0x70):
  * character tag == BOY1 and `+0x104 == 1` -> **completion**: trigger script event
    `0x24700001` (arg BOY1) and the `0x444f4c41` event, no mini-game;
  * character tag == BOY1 and `+0x104 != 1` -> **start the mini-game**: character+0x2bc = the lock
    object, stop the animation, lock the camera (`FUN_005d*`), play animation `0x4b0`, zero
    `+0x174/+0x180/+0x194/+0x198`;
  * character tag != BOY1 -> trigger event `0x24700001` with the character's tag (level I015) or 0,
    plus the `0x444f4c41` event - the refusal path.
* The mini-game itself is `FUN_004595f0` @0x4595f0 (vtable+0x14): a 3-D lock with pick tools, driven
  by the sticks; it plays `0x4c4b5031`/`0x4c4b504d` events and ends by calling the lock's own stop
  path (`0x45af60`, vtable+0x74) and, for `+0x14 == 3`, `FUN_0045a850(3)`, which triggers the same
  script event `0x34c0002b` with arg BOY1. **The bot cannot play it** (it needs continuous stick
  motion on the 3-D lock); the test uses the game's own completion path (§3).

### 2.2 `CToeHeavyCase` (class tag `HCAS`, RTTI `CToeHeavyCase`, vtable 0x65828c)

* Parse `FUN_00446770` @0x446770 reads `boy3_use` (+0x8b) and `can_climb` (+0x8c) - the case is a
  strength object for BOY3/BOY4 (Sven/Kenny), and can be climbed after it moves.
* Eligibility check `FUN_00448550` @0x448550 (vtable+0x34): needs `+0x24 != 0`, `+0x20 != 0`,
  `+0x1f0 == 0`, `+0x1ec == 0`, `+0xb8 == 0`, the character's held prop is none or the case, the
  character inside the case's block area (`+0x94/+0x98`, depth `+0x9c`, tolerance 20), moving toward
  the case (dot with the movement direction >= 0.525), and for type 1 a non-BOY3/BOY4 character is
  refused when it is at a side edge. It sets `+0x124` (side) and `+0x128` (interaction type), score 100.
* Use `FUN_004459d0` @0x4459d0 (vtable+0x70): a BOY3/BOY4 character starts the push
  (`+0x61 = 1`, `+0x88 = 0`, character+0x2bc = the case, push direction fields `+0x4c..+0x4f`,
  animation); any other character triggers event `0x8700008` and cancels.
* The push is a physical slide of the case along the block axis (the four `CToeEdge` objects around
  it are the case's edges); the case's own position `+0x6c..` moves while the character holds it.

### 2.3 The progress block already synced host->guest

`game+0x318` holds the story/entity state table at `+0x814` (`count` at `+0x814`, entries of 12 bytes
`{entity id, state, extra}`) and the 8 character records at `+0x1b0c`. `host_send_progress`
(`src/sync.c:2497`) sends every changed chunk of `+0x814..` and `+0x1b0c..+0x1cd4` as `PKT_REGION`, and
`guest_apply_regions` (`src/sync.c:2621`) writes them into the guest's progress object. So a **host**
ability result that is a story flag in `+0x814` reaches the guest automatically. It does not update the
guest's live level entities (doors, locks, cases), and the **guest's** own progress changes are not sent
to the host at all (the region upload is host->guest only).

## 3. Live measurement

Two pair runs on I015 (chk28b/chk28c, one per probe; `check_abilities.py --probe`):

1. **The guest had no character of its own.** `attach_player2` picked manager entry 1 as the partner.
   In I015 the save's controller record is `BOY2 ctlCHC1`, so player 1 already drives manager entry 1
   (BOY2) and player 2 was attached to the SAME human: both copies printed
   `host player1 BOY2 @1a3b6d90 ... | player2 BOY2 @1a3b6d90` (OBSERVED). With that, no guest character
   can use the lock pick (Stan = BOY1 was the AI teammate).
2. After the fix (`first human that player 1 does not control`) the guest's player 2 is **BOY1**:
   `guest player1 BOY2 ... | player2 BOY1 @1a0cbf18 pos (-1447.98,-355.41,28.99)` (OBSERVED).
3. The lock pick itself: the check's safe tp put Stan 90 units from the lock (radius 135, same floor,
   `ok settled at (-1294.77, -534.92, 109.08)`), and the game's own interaction check ran: the lock's
   `+0x104` became **2** (the back-side value `FUN_0045a9e0` writes only for BOY1), so the character was
   recognised as Stan and in reach. The A presses in that probe did nothing because of the pad mapping
   below (OBSERVED).
4. **The guest's own pad is virtual pad 0, not 1.** On the guest `XInputGetState(user=1)` returns
   `g_vpad[g_local_pad]` and `g_local_pad` is 0 (`src/obscoop2.c:636-670`), so `pad 1 ...` never reaches
   the guest's player 2 (DERIVED from the code, and the reason the first probe's A press was invisible).
   `check_breakables.py` already presses user 0 on the guest copy for the same reason. The check now
   presses user 0 on both copies.
5. A player-1-only phase in I015 is a SKIP (Kenny = BOY2 owns no aptitude object there); the ability
   phase is the guest's Stan on the lock pick.

The 3D-lock mini-game start (back side) cannot be driven by the bot; the test-only pipe command
`aptdone <0|1>` runs the game's own completion instead: the lock's use method (vtable+0x70 = FUN_0045ac10)
with the character and `+0x104 = 1` (the front-side completion branch: script event `0x24700001` with arg
BOY1), then the lock's own stop method (vtable+0x74). It is test-only, like `netpause`. The command needs
the character to be linked to the lock (`human+0x2bc`), which the game only does when it runs the
mini-game start; it was never reached in the runs below.

### The final run (chk28f, I015, OBSERVED)

```
abilities: host player1 BOY2 @1a2aa238 ... | player2 BOY1 @1a255418 ...
abilities: player 1 (host) = BOY2; usable aptitude objects for it: none
abilities: player 1 (host) SKIP (this character has no active aptitude object in this level)
abilities: player 2 (guest) = BOY1; usable aptitude objects for it: LCKP@183a3db0
abilities: tp player 2 (guest): safe tp at 90 units (ok settled at (-1294.77, -534.92, 109.08) after 0.8 s)
  no action facing the object; turning the back to it (safe tp refused every spot (48 tried))
  the action button did not start an action on LCKP (... p24=1 ... f104=2 ... char BOY1 ... action=@0)
  progress entries changed on the acting copy: 0
  result own   ((1, 1, 0, 0, 2, 0, 0, 306, -1380.33, -562.83, 109.08), ((1146049096, -1384.6, -450.8, 27.2, 0, 0, 1.0, 0.0),))
  the acting copy shows a result: NO
abilities: sync host  ... | prop sent 64 rcv 63 applied 63 ... | apt sent 0 rcv 0 applied 0 actions 0 | frames 997
abilities: sync guest ... | prop sent 63 rcv 64 applied 64 ... | apt sent 0 rcv 0 applied 0 actions 0 | frames 958
abilities FAIL:
```

* The game's own interaction scan runs and recognises Stan at the lock: `+0x104 = 2` is the back-side value
  `FUN_0045a9e0` writes only for BOY1, so the character, the reach (90 <= 135) and the facing were all
  accepted. **But the use never links the character to the object**: the lock's `+0xc4` stays 0,
  `human+0x2bc` stays 0 and the object/door state does not change on either copy, with A pressed through
  virtual pad 0 on the guest (the guest's own pad). The decompiled scan (`FUN_004cf940`, the block after
  `0x4d25f4`) uses the winner every frame and has no button gate, so the missing link is in the lock's own
  start path, not in the button. UNKNOWN which of its gates (`controller+0xa4`, the character animation
  state, or the camera lock on the ledge) stops it.
* The second placement (back to the lock) was refused at all 48 spots: the safe tp found no other floor
  on that ledge, so the front side of the lock was never tried live either.
* `aptdone` was never reached (it needs the link), so the test-only completion path is UNVERIFIED too.
* Screenshots `tests/shots/apt_guest_{before,after}_{host,guest}.png` are **black** (1286 bytes each):
  the copies run in the background and `PrintWindow` returns an empty frame - the capture problem
  FINDINGS_26 solved by raising the window. I looked at them: all four are uniformly black, nothing to
  describe.

### Not measured live

* The H000 heavy case (host direction) was not run: the process budget was spent on the guest direction
  and the required regression (18 total). Its decompile basis is in §2.2; its push result (the case's
  position and `+0x1ec/+0x1f0`) is exactly what `PKT_APT` carries.
* The `PKT_APT` apply path is **UNVERIFIED live**: no ability result was produced, so `apt sent/rcv/applied`
  stayed 0 on both copies in every run.

## 4. Fix

Two changes, both in the shipped DLL:

1. **`attach_player2` (`src/sync.c`)** now picks the first human in the manager that player 1 does not
   control (and corrects a second controller that points at player 1's own character). The old code took
   manager entry 1, which is the same character whenever the save's controller record names that entry
   (I015: `BOY2 ctlCHC1`). This is what gives the guest a character of its own on every save.
2. **`PKT_APT` (21, `NET_VERSION` 14 -> 15) + `apt_tick` (`src/sync.c`)**: the copy that owns the acting
   character watches the aptitude objects and the doors near them every 150 ms
   (`LCKP`/`HCAS`/`DISL`/`DOC.`/`DAUR*` + `DORH`/`DODO`/`INDO`, 10 state fields and the position). It
   announces
   * kind 1 when its own character links to an aptitude object (`human+0x2bc`, the field the game's own
     use function writes) - the peer only logs it, the animation already follows in `ch_state`;
   * kind 2 with **exactly the fields that changed** (old value -> new value) and the position, when an
     object or its door changed. The other copy applies each field **only where its own value still
     equals the sender's "before"** (so a local change is never clobbered) and writes the position only
     when it still sits where the sender found the object. A result applied from the peer is not
     announced back (`prop_applied_here`, 2.5 s). The mini-game is never run on the peer: only its
     result (and, for the heavy case, its movement) travels.

## 5. Check - `tests/check_abilities.py` (new)

What it does: prints the live party and every aptitude object with its fields, then runs
* phase 1: the host's own player 1 against the ability it owns;
* phase 2: the guest's own player 2 (guest copy, `pad 0`, see §3) against the ability it owns.

It places the character with the mod's safe `tp`, presses A (facing, then with its back to the object),
optionally runs the test-only `aptdone`, takes a screenshot of both copies before/after, and compares the
object's result state **and the state of the doors within 500 units** between the copies. Exit 0 = PASS,
1 = FAIL; `--probe` prints the same and never fails.

Result on the final build (chk28f, I015): **FAIL** - the action never ran (§3). Verbatim tail:

```
  no action facing the object; turning the back to it (safe tp refused every spot (48 tried))
  the action button did not start an action on LCKP (...)
  the acting copy shows a result: NO
abilities FAIL:
  - player 2 (guest): the action never ran on the acting copy
```

Screenshots: all four (`apt_guest_before/after_{host,guest}.png`) are black - the copies run hidden in the
background and `PrintWindow` gives an empty frame (FINDINGS_26 raised the window to capture; this check
does not). Seen by viewing them: uniform black, nothing visible.

## 6. Regression (OBSERVED, chk28f.dll)

All four required commands, each with the two-copy harness; each run's own stop step ran
(`still running: []` in every log).

| # | command | result |
|---:|---|---|
| 1 | `sh tests/run_pair_menu.sh <dll> check_party.py check_items.py check_hands.py check_hands_visible.py check_entities.py check_movement.py` | **OK**: `party OK`, `items OK`, `hands OK (2 characters checked)`, `hands visible state OK (2 characters checked)`, `entities OK (host 43, guest 43)`; movement `E: PASS`, `A: PASS`, `B: PASS`, `C: PASS`, `D: PASS [warn: GIR1 anim differs in 5/50 samples (transition samples)]` |
| 2 | `OBSCOOP_SLOT=3 sh tests/run_pair_menu.sh <dll> check_breakables.py` | **OK**: `breakables OK (chairs picked up, swung and broken on both copies; 2 chair(s) checked)` |
| 3 | `OBSCOOP_PICKUP_CLASS=MEDI OBSCOOP_PICKUP_SPAWN=1 sh tests/run_pair.sh <dll> check_itemuse.py check_party.py pair_j003.py check_pickup.py` | **OK**: `RESULT: item use OK (each use landed once on both copies, lives equal, inventories identical)`, `party OK`, `RESULT: both copies in J003 with 2 live items`, `pickup OK: both directions collected on both copies, inventories match, no echo` |
| 4 | `sh tests/run_reconnect.sh <dll> both` | **PASS**: `=== reconnect run (both): PASS` (CASE 1 netpause 8 s, CASE 2 guest restarted) |

`apt sent 0 rcv 0 applied 0 actions 0` in every regression run's `sync` line: nothing in the new code
fired during normal play (no aptitude object was touched), so it did not change the existing behaviour.

## 7. Process budget

18 game processes: 2 solo survey launches (scan_abilities, all ten slots + the focused second pass),
2 probe pairs (chk28b, chk28c), 1 failed verification pair (chk28e - the host froze on the uninitialised
critical section), 1 final pair (chk28f), and the 4 regression commands x 2. Nothing was left running;
`git diff --stat` and the three modified files are listed in the task report.
