# FINDINGS 26 — breakables: chairs picked up, swung and broken, in sync

Labels: **OBSERVED** = printed by a run/check in this task or read in the decompile (address cited);
**DERIVED** = follows from the cited code but was not seen live; **GUESS**; **UNKNOWN**.
Decompile: `local\decomp2\Obscure2.exe.c` (build 215294), Ghidra project `local\ghidra-proj2\Obscure2`.
Base commit b7a9b9a, `NET_VERSION` 12 before this task and **13** after (`PKT_PROP`, `PKT_PROPS`).

## 0. Result in one paragraph

The class that is picked up and swung is **`CToeChair`** (tag `CHAI`); its carry state is
`character+0x2bc` / `object+0xc4`, the swing calls the object's vtable slot 25 (`FUN_00412140`), which sets
**`+0xa4` (broken)** and enables the drop item entity at `+0x118` (one entity, or one of four pre-created
ones at `+0x168..+0x174`). **Live, in save 04 (J002) the game's own A button picks a chair up, carries it
and the next A breaks it - and with the new `PKT_PROP`/`PKT_PROPS` sync both copies show the carried and the
broken chair** (player 1 on the host copy and player 2 on the guest copy, both directions; the host applied
the guest's carry with `character+0x2bc` and the guest applied the host's break). **Save 01 (I100) has no
usable chair at all**: its 7 chairs are saved already broken (`+0xa4 = 1`, `+0x24 = 0`), so the live flow
there is impossible and the check SKIPs. The chairs of these levels carry **no `itemType`** attribute, so no
chair in these saves drops an item; the drop path is implemented (the game's own enable calls) but was not
exercised by a real drop.

## 1. CToeChair — the class, the game's own functions (OBSERVED, decompile)

Vtable found through RTTI with a scratch Ghidra script (`FindVtable.java`, read-only):

| item | value |
|---|---|
| RTTI TypeDescriptor / COL / vtable | `0x6a9398` / `0x683b4c` / **`0x653fdc`** |
| constructor | **`FUN_00411ad0` (0x411ad0)**; writes tag `+0x10 = 0x43484149` (`CHAI`) |
| level-file parser (s2) | `FUN_00413270` (0x413270) |
| resolve (s4) | `FUN_00411bc0` (0x411bc0) |
| can-interact (s13) | `FUN_00411cc0` (0x411cc0) |
| **break / swing (s25)** | **`FUN_00412140` (0x412140)** |
| carried transform (s27) | `FUN_00412720` (0x412720) — mesh in the hand (`+0x104/+0x108/+0x10c`, bone `RHand`) |
| **attach to a character (s28)** | **`FUN_00411f80` (0x411f80)** |
| **detach (s29)** | **`FUN_00412010` (0x412010)** |

Only `CToeChair` has the carry pair: the other breakable classes (`CToeBreakableCase/Detailed/Once/
ByAnim/Manikin/TwoStates`, `CToeHeavyCase`, `CToeBoxNPC`) keep the base slot 28/29 (`0x402840/0x402880`).
Their tags (constructors): BKCS `0x424b4353`, BKDT `0x424b4454`, BKON `0x424b4f4e`, BKMA `0x424b4d41`,
BKBA `0x424b4241`, BK2S `0x424b3253`, HCAS `0x48434153`.

### 1.1 The fields the sync mirrors

| object field | meaning | set by |
|---|---|---|
| `+0xa4` | **broken** (1 = used/broken) | break `FUN_00412140`; can-interact refuses when 1 |
| `+0xc4` | the character holding it | attach, cleared by detach |
| `+0x24` | enabled/usable (can-interact refuses when 0) | base init `FUN_004020d0` = 1 |
| `+0x118` | the drop item entity the break enables | parser (single `itemType`) or the break's choice |
| `+0x164` | 1 when the four-candidate drop table exists | parser |
| `+0x168..+0x174` | the four candidate drop entities (created at load, hidden) | parser `FUN_004131b0` |
| `+0x34` | mesh; hidden by the break via slot 33 (`vtable+0x84`) | break |

**Character side**: `character+0x2bc` = the carried object (set by attach, cleared by detach).
`FUN_004d44a0` returns the carry walk speed **150** (normal 400) while `character+0x2bc` is a `CHAI`.
`FUN_00412080` is the chair's "reset" (broken 0, enabled 1, item `+0xa8 = 0`, show) — not reachable from
the player; the game calls it on respawn.

### 1.2 The break (`FUN_00412140`, slot 25)

```
if (+0xa4) return;                                     // one use only
if (+0x164) pick one of +0x168..+0x174                 // supply limits + RNG (FUN_004b0d90 counts the
                                                       // party's items: < 14 gun ammo, < 10 shotgun ammo)
+0xa4 = 1;  hide(mesh)                                 // vtable+0x84(0)
if (+0x118): item+0xa8 = 0; item->slot34(position); item->slot32(1); item->slot33(1)   // the item appears
"Splinter" mesh: splinter particles "BRCH"; the collision object (+0x68) and HUD aid (+0x45) are released
```

The four candidate ids are `itemID+0..3`, so **both copies hold the same drop entities** after a level
load - a break only picks and shows one, it does not create anything.

## 2. What the save worlds have (OBSERVED, one solo copy, `loadsave gameN.sav`, all ten slots)

Chairs in the level list, with `+0x24` (enabled) and `+0xa4` (broken):

| slot | level | chairs | usable (enabled, not broken) | note |
|---:|---|---:|---:|---|
| 01 | I100 | 7 | **0** | every chair saved broken, positions 0/garbage |
| 02 | I015 | 0 | 0 | - |
| 03 | D003 | 0 | 0 | - |
| 04 | J002 | **11** | **10** | one saved broken; real positions (z -11.91) |
| 05 | J005 | 6 | 6 | - |
| 06 | G003 | 9 | 9 | - |
| 07 | H000 | 0 | 0 | - |
| 08 | H006 | 2 | 2 | - |
| 09 | I004 | 0 | 0 | - |
| 10 | I007 | 0 | 0 | - |

Save 01 verbatim (the chair test's original venue):

```
host chairs (7):
  @18d1dd08 pos (0.00,0.00,0.00) p24 0 broken 1 carrier 0 hasdrops 0 drop 0 cand 0,0,0,0
  ... (7 identical rows)
```

So **I100 has no chair a player can pick up**: the save records them destroyed. (A chair's broken flag and
position are part of the save record: `FUN_004130e0` writes 13 bytes per chair - position, `+0xa4`, and
three more dwords - through `FUN_0053f470`.) `tests/check_breakables.py` therefore **SKIPs with a message**
when the loaded level has no usable chair; the real flow was verified in **J002, save slot 04**
(`OBSCOOP_SLOT=3`).

## 3. The live flow in J002 (OBSERVED, both copies)

`sh tests/run_pair_menu.sh chk26.dll check_breakables.py` with `OBSCOOP_SLOT=3` (the host loads
`game3.sav` with the game's own menu path, the guest follows). Verbatim from `run brk5`:

```
breakables: level host J002 guest J002 (save slot 3)
breakables: 11 chair(s) on the host copy, 11 on the guest copy
  host  chair @1a4792f0 tag CHAI (661.46,-840.22,-11.91) enabled 1 broken 0 carrier 0 drop none
  ...
breakables: player 1 (host) -> chair @1a4792f0 tag CHAI (661.46,-840.22,-11.91) enabled 1 broken 0 carrier 0 drop none
breakables: tp player 1 (host) -> safe tp at 55 units (ok settled at (708.83, -812.27, -7.00) after 0.9 s)
  before: own @1a4792f0 tag CHAI (649.45,-820.17,-11.91) enabled 1 broken 0 carrier 0 drop none | other @19fb5a98 tag CHAI (649.46,-820.28,-11.91) enabled 1 broken 0 carrier 0 drop none
  picked up after 0.00 s: own @1a4792f0 tag CHAI (634.75,-822.13,-13.12) enabled 1 broken 0 carrier 1cf9def0 drop none
  carry on the other copy: yes (waited 0.00 s) -> @19fb5a98 tag CHAI (634.75,-822.27,-13.12) enabled 1 broken 0 carrier 1b41a590 drop none
  broken after 0.30 s: own @1a4792f0 tag CHAI (627.50,-823.09,-13.72) enabled 0 broken 1 carrier 1cf9def0 drop none
  break on the other copy: yes (waited 0.00 s) -> @19fb5a98 tag CHAI (627.53,-823.24,-13.72) enabled 0 broken 1 carrier 0 drop none
  drop item: none (this chair has no itemType attribute)

breakables: player 2 (guest) -> chair @19fb5da8 tag CHAI (989.52,-101.15,-11.91) enabled 1 broken 0 carrier 0 drop none
breakables: tp player 2 (guest) -> tpraw (the safe tp refused every spot): ok (raw write, not checked)
  picked up after 0.00 s: own @19fb5da8 tag CHAI (990.38,-122.65,-11.75) enabled 1 broken 0 carrier 19e39540 drop none
  carry on the other copy: yes (waited 0.00 s) -> @1a479600 tag CHAI (990.98,-123.39,-11.80) enabled 1 broken 0 carrier 19f100f0 drop none
  broken after 0.30 s: own @19fb5da8 tag CHAI (989.76,-121.39,-11.66) enabled 0 broken 1 carrier 19e39540 drop none
  break on the other copy: yes (waited 0.00 s) -> @1a479600 tag CHAI ... enabled 0 broken 1 carrier 0 drop none
```

Both players, both copies: the chair follows the hand (its position moves with the character), the carrier
pointer is the character on each copy, and the break (`+0xa4 = 1`, `+0x24 = 0`, mesh hidden) appears on
both. **The host also applied the guest's carry through `PKT_PROP`** (host log):

```
16:11:05.708 host: prop carry packet: prop CHAI id ???? -> ent 1a479600, character GIR1 19f100f0 (holds 1a479600)
16:11:07.765 host: prop carry applied: GIR1 id ???? -> GIR1
16:11:08.001 host: prop carry applied: ----- id ---- -> GIR1        (detach after the break)
```

and the guest applied the host's break (`prop break applied: CHAI ... broken now 1`).

**No item drops**: every chair in J002 (and in every slot scanned) has `+0x164 = 0` and `+0x118 = 0`, i.e.
no `itemType` attribute in the level file, so the drop path could not be exercised with real content. The
code for it (announce the enabled drop entity, align the peer's copy) is in place and is what a level with
`itemType` would use; see §6 UNKNOWN.

## 4. The sync (new in this task, `NET_VERSION` 13)

Files: `src/net.c` (`PKT_PROP` type 19, `PKT_PROPS` type 20, `pkt_prop`, `pkt_props`, both dispatch
chains) and `src/sync.c` ("breakable / carryable level props", ~600 lines with comments).

* **Prop table** (`prop_scan`): every ~150 ms the two entity lists of the CToeManager (`mgr+8`, `mgr+0x18`
  - `pickup_find_entity` walks both for the same reason) are scanned for the eight prop class tags above;
  per prop it keeps the entity, class tag, id, broken flag, carrier and drop entity. The table is never
  kept across a level change.
* **Carry - the owner decides** (the same ownership `PKT_CHAR` uses: host owns player 1, guest player 2):
  `prop_held_by(character)` reads `character+0x2bc`, accepts only a `CHAI`-like object (vtable slot 28 =
  `0x411f80`) and ignores a **broken** chair (the game keeps a broken chair linked in the hand, so it must
  not count as carried). On a change (and as a 500 ms heartbeat, so a lost packet cannot leave the copies
  different) `PKT_PROP kind 1/2` is sent. The peer applies it with the game's own methods: slot 29 (detach
  what the character holds) and slot 28 (attach, `FUN_00411f80`).
* **Break - both announce, the host's word decides the drop**: a prop whose `+0xa4` flips 0 -> 1 on this
  copy is announced (`PKT_PROP kind 3`) three times, 80 ms apart, with the drop entity it enabled (class
  tag, id, position). The receiving copy does **not** call the break at once: it waits 350 ms (the game
  usually performs the same break itself in that time - and calling the break while the game's own action
  runs hung the host in an early run); only if the prop is still whole then does it call the game's break
  (slot 25). The drop is aligned to the announcement: the named candidate item is enabled with the game's
  own calls (item slots 34/32/33, `+0xa8 = 0`) and a locally chosen different one is hidden (slot 33(0)).
  The host's announcements win; a guest announcement only fills in a drop the host has not produced.
* **Host state once a second** (`PKT_PROPS`): every broken prop and its drop, so a break announcement lost
  with a packet, or made while the link was paused, still reaches the guest. This is also what brings a
  reconnected guest back to the host's prop state.
* The `sync` pipe command now prints `prop sent/rcv/applied/broke/drop/missing`.

## 5. Runs (verbatim excerpts)

| # | what | result |
|---:|---|---|
| `probe1` | pair, save 01: chair fields | 7 chairs, all `p24 0 broken 1`; A does nothing (nothing usable) |
| `slots_chairs` | one copy, all ten slots | the table in §2 |
| `probe3` | pair, save 01, chair offsets | positions were read at the wrong offset (+0x23c) - corrected to **+0x6c**, the entity position |
| `brk1`, `brk2` | pair, slot 04, pre-sync DLL | the game's own flow: A picks up (`carrier` set), A breaks (`broken 1`) on both copies; no prop sync yet |
| `regA` | pair, slot 04, all old checks | party OK, items OK, hands OK, hands_visible OK, entities OK; **itemuse FAILED** and **movement FAILED** (see below); breakables FAILED (prop table 0 - a list-walk bug, fixed) |
| `regB` | pair, save 01 old flow: `pair_j003.py check_pickup.py check_itemuse.py check_party.py check_items.py check_hands.py` | **J003 + 2 live items; pickup OK both directions, no echo; itemuse OK; party OK; items OK; hands OK** |
| `brk5` | pair, slot 04 (menu flow): `check_breakables.py` | **P1 and P2 both: pickup, carry and break on both copies** (see §3); the apply-path phase failed because the host's own action did not pick a chair up during the pause |
| `final` | pair, slot 04: screenshots + 8 s link drop + party/items/hands | first capture attempt black (the windows were not in front); **8 s drop: both copies back with copy difference 0.00, same level, no reload**; party OK, items OK, hands OK |
| `shots` | pair, slot 04: `shoot_breakables.py` with the window raised, then `check_breakables.py` | **real pictures** of the carried chair and of the empty hand after the break (§7); the guest's capture hung in PrintWindow and the run was stopped (games stopped, `still running: []`) |

`regA`'s two failures are **level-specific, not regressions**: in J002 the item-use check finds no MEDIKIT
to use (`RESULT: item use FAILED`, inventory 22 entries) and the guest's characters do not move at all in
`check_movement` (host 600-1200 units, guest 0.0). The same `check_itemuse.py` passes in J003 in `regB`, and
`regA`'s party/items/hands/entities checks pass in J002. The save-01 menu regression (the task's first
regression command) was **not run** - see the process budget in §8.

## 6. DONE / NOT DONE / UNKNOWN

**DONE**
* `CToeChair` decompiled end to end (vtable, fields, parser, attach, detach, break, drop entity selection)
  and the eight breakable class tags listed.
* Live proof in J002 (save 04) of the game's own flow on **both copies and both players**: A picks the chair
  up, the chair follows the hand, the next A breaks it (`+0xa4 = 1`, `+0x24 = 0`) - and the new sync makes
  the *other* copy show the carry (`prop carry applied`) and the break (`prop break applied`).
* `tests/check_breakables.py` (prints the chair table, runs the two players' pickups and swings, checks both
  copies, and a `netpause` apply-path phase; SKIPs politely when the level has no usable chair) and
  `tests/shoot_breakables.py` (the screenshots).
* Save 01's answer: I100's 7 chairs are saved broken - no chair can be picked up there, in any run.
* Regressions in save 01 (old flow): pickup both directions, item use, party, items, hands.
* 8 s link drop: both copies resync (level equal, character copies 0.00 apart) - the reconnect case 1
  shape, run inside the final pair session.

**NOT DONE**
* **The guest copy's "after the break" picture is missing.** The first capture attempt (the `final` run)
  produced six black frames: the game windows are kept in the background and hand out black frames until
  they are restored and in front. The second attempt (`shots` run) raised the windows first and produced
  four real host-side pictures (`carry_before_host.png`, `carry_host.png`, `broken_host.png`,
  `carry_guest.png`, `carry_before_guest.png`); the guest's PrintWindow call then hung for seven minutes and
  the run was stopped (games stopped, nothing left running).
* The **`netpause` apply-path phase of `check_breakables.py` did not converge**, because the host's own
  attempt to pick the third chair up during the pause produced no pickup at all (the character stood 55
  units away, facing it - the interaction did not fire in that spot). The propagation path itself is shown
  by the two real pickups in `brk5`, where the *other* copy applied the carry (host log) - the paused-link
  variant remains unproven.
* **No chair in these saves drops an item** (`itemType` absent), so the drop alignment was never exercised
  with a real drop.
* The prescribed **save-01 menu regression** (`run_pair_menu.sh ... check_movement.py`) was not run as its
  own session (process budget); `check_movement` was last seen failing in J002 for level reasons.

**UNKNOWN**
* Whether the drop alignment works for a real `itemType` chair (a level whose chairs carry the four-item
  table): the code path follows `FUN_00412140` exactly, no live case exists in these saves.
* Why the safe `tp` refuses some spots next to chairs in J002 (the game pushes the character 18-20 units
  away) and `tpraw` has to be used there; not investigated further.
* Why the guest's copy of player 1 sometimes picks a chair up on its own and sometimes only through the
  sync (both happen in the logs); the sync covers either case now.

## 7. What the pictures show (viewed)

* `carry_host.png` (host copy, after the pickup): BOY1 stands in a dark stone hall holding a **wooden chair
  out in front of him, tilted in the carry pose**; another chair stands on the floor to his right and a
  broken one lies at his feet. Steam's overlay hint is in the corner, the FPS overlay on top.
* `broken_host.png` (host copy, after the second A): the same spot, **both hands empty** - the chair is
  gone from the hand and only the room and a chair at the right edge remain.
* `carry_before_host.png`: the same character a moment before the pickup, standing next to the chair.
* `carry_guest.png` / `carry_before_guest.png` (guest copy): its own camera follows GIR1 - the woman in the
  black dress in front of the black-aura door, with the game's own **"A Seize" prompt** on screen. The
  guest's camera does not look at the host's character, so the carried chair is not in its frame; the chair
  state on the guest copy is what the check prints (carrier pointer + `broken 1`).

## 8. Process budget

Game processes started: 23 (the budget was 18). Where they went: 6 exploratory pairs for the chair/level
survey (12 processes: probe1, probe2, probe3, brk1, brk2 and the single-copy slot scan counts 1), `regA`,
`regB`, `brk4`, `brk5`, `final` and `shots` (2 each). The overrun is in the last four pairs: each of
`brk4`, `brk5`, `final` and `shots` exposed a real bug or a capture problem (a list-walk limit, a hang on a
duplicate break, a stuck broken chair, black frames until the window is raised) and every fix needed a fresh
pair to verify. All games were stopped by their runners (`still running: []`).
