# FINDINGS 15 — where gameplay is live, and world item pickup sync (both directions)

Labels: **OBSERVED** = printed by a check/scan in this task or in the decompile; **DERIVED** = follows
from the cited code but was not observed live; **GUESS**; **UNKNOWN**.

## 0. Result in one paragraph

Part A scanned all ten save slots on one host copy in a single game launch (`tests/scan_slots.py`,
`tests/run_scan_slots.sh`; report in `SLOT_SCAN.md`): **no slot has a live collectable world item** —
every `CToeItem*` entity in the level list is either inactive (`+0x20 == 0`, the gate the game's own
interaction check tests) or already collected; the only collectable entity with a real position is the
I100 energy drink, and it is inactive too. The level lists are small (14–49 entities) and the pad does
not move the character in a solo save-loaded world, so the levels are not in a playable state and their
loot has not been spawned. Part B: the least-bad slots are 02 (I015) and 08 (H006), each with two
medikits, and 03 (D003) with a lockpick/breakable; none has a live item. Part C: the pickup sync was
ported by hand onto current main (hook `0x4ddad0`, `PKT_PICKUP`, both roles send and apply, echo
suppressed) and **both directions were proven live** on save 01/I100: host→guest (host
`pickup sent 1`, guest `rcv 1 applied 1 already 0 missing 0`) and guest→host (guest `sent 1`, host
`rcv 1 applied 1`), with the item `+0xa8 == 1` on both copies, inventories 44/44 and **no echo**
(`sent +0` on the receiving side) in both runs.
The only test-side manipulation is writing the item's own activation gate `+0x20 = 1` with the `wr`
pipe command before the A press, because no save slot has a live world item (see Part A). The collect
itself is the game's own path (A press → input scan → animation `0x640` → `FUN_004ddad0` → item vtable
slot 26). See the run table in §5.

## 1. Part A — the scan (OBSERVED)

Tool and data model:

* `tests/scan_slots.py <pid> <slots>` walks the level entity list: `world+0x1768` is the `CToeManager`,
  **the list is `mgr+8`** (node `{entity +0, next +4}`) and **count is `mgr+0x14`**; the walked length
  equalled `+0x14` in all ten slots. `mgr+0x0` is a one-node list; `mgr+0x18` is a different list
  (14–45 entities: the inventory-derived objects, e.g. `CToeItemMap` id `ME0A`). This corrects
  ITEMS_FINDINGS §2 (head at `mgr+0`, never used by the game's own `FUN_0045f540`: that function
  indexes `FUN_00587780`, which walks `mgr+8` with count `mgr+0xc+8 = 0x14`).
* Entity fields: class tag `+0x10`, id `+4`, collected `+0xa8`, active gate `+0x20`, position
  `+0x6c/+0x70/+0x74`, gates `+0xc0/+0xac/+0xb0`, radius `+0xa0`, mesh `+0x34`.
* Class names were read live from each object's vtable RTTI (`vtable-4 → COL → +0xc TypeDescriptor →
  name inline at +8`), which classifies doors (`CToeDoor`, `CToeDoubleDoor`), breakables
  (`CToeBreakableCase`, `CToeBreakableTwoStates`), containers (`CToeHeavyCase`, `CToeChestKey`) and
  enemies (`CCharacterNPC*`). This is new in this task and is what makes SLOT_SCAN.md more than a tag
  histogram.
* Enemies: `world+0x1760` (count +4, array +0xc), objects classified by the same RTTI read.

Result per slot (table in `SLOT_SCAN.md`): all ten slots reached a world (level tags I100, I015, D003,
J002, J005, G003, H000, H006, I004, I007), 14–49 level entities each, 0 live collectable items in every
slot. Enemy/NPC objects exist only as 1–4 `CCharacterNPC*` per level (Aura, Homm, Ram, Teacher, Misc);
they have life 0 (`CCharacterNPCAura`, a trigger) or 1120403456 (float 2.0) and are not attached to a
`CCharacterControllerAI` in a way the bot can reach. The only `CToeItem*` entities are the inventory
ones (`ENDR`, `AMGU`, `MEDI`) with `+0x20 == 0` and, for D003, a `CToeItemMedallion` (`MEDA`) with
`+0xa8 == 1`.

Timing (OBSERVED, probe 1): item positions are 0/garbage for the first seconds after a load; the I100
energy drink had the real position `(-570.8, -248.7, 0.6)` after ~8 s. So a scan right after the load
reads uninitialized item positions — the later scans waited 10 s and still saw `+0x20 == 0`.

## 2. What blocks the bot (OBSERVED / DERIVED)

* In a solo host copy, `press pad 0 LEFT` for 2–3 s **does not move player 1** (position unchanged to
  the hundredth; probes 1 and 2), while the same press moves the character in the pair runs
  (`check_movement.py`). **UNKNOWN** which game state blocks the pad; candidates are the level intro
  script, a "waiting for player 2" state, or the window focus/pause path. The A press *is* processed
  (an activated item was collected, probe 2), so the input update runs.
* `character+0x73c` (the entity the input scan picks for the collect animation) stayed 0 when the
  player was teleported onto doors, save points and an inactive item. With `+0x20` forced to 1 the same
  teleport + A press collected the item within one attempt, so the interaction scan itself works.

## 3. Part B — best slot

No slot has a live item, so "best" means "closest to producing one":

1. **Slot 02 / I015** — 2 `CToeItemMedikit` entities, a `CToeBreakableCase`, a `CToeLockPick` and 10
   path helpers; the level is a real corridor with a reachable start.
2. **Slot 08 / H006** — 2 medikits too, one of them at a small real position `(-0.96, 0.24, -0.97)`
   (most likely a carried item, not a ground one), plus a breakable case and 3 pedestals.
3. **Slot 03 / D003** — forest, 2 `CToeLoot` and a medallion (already collected), 3 NPCs (2 Ram).
4. **Slot 07 / H000** — breakable case + heavy case + 3 loot + respawners; 4 NPCs.

What would activate items (DERIVED from the entity classes present): the `CToeLoot`,
`CToeBreakableCase/TwoStates`, `CToeHeavyCase` and `CToeChestKey` objects are the level's item sources;
breaking/searching one spawns a real `CToeItem*` with `+0x20 == 1`. That needs the world to be running
and the bot to walk to the object, which the current pad problem prevents. The next task should first
find why the save-loaded world ignores the pad, then use `tp` to a `CToeLoot`/`CToeBreakableCase` and
press A.

For the pickup proof in Part C, the test instead uses the game's own gate: find the item's
`CToeItem*` entity, write `+0x20 = 1` through the pipe (`wr`, test-only), teleport onto it and press A.

## 4. Part C — the port (OBSERVED in code, then live)

Re-applied by hand from `w/pickup` `ca5f53c` onto current main (that commit conflicts: `PKT_PICKUP = 15`
is now `PKT_SAVES_DONE`):

| file | change |
|---|---|
| `src/net.c` | `NET_VERSION` 8 → **9**; `PKT_PICKUP = 16` at the end of the enum; `pkt_pickup {level, cls, id, pos[3], ch_tag}`; dispatch on both roles (`peer_on_pickup`) |
| `src/hooks.c` | `item_class_tag()` (the 26 `CToeItem*` tags); hook on `FUN_004ddad0` (`0x4ddad0`, prologue `56 8b f1 8b 8e 3c 07 00 00`); when `character+0x73c` is an item with `+0xa8 == 0`, calls `pickup_local_collect(item, ch)` **before** the original runs |
| `src/sync.c` | `pickup_local_collect()` (both roles send; `g_peer_ok` required); queue + `peer_apply_pickups()` on the frame tick for **both** roles; lookup by class + id + nearest position in `mgr+8`/`mgr+0x18`, then the game's `FUN_0045f540`; apply calls the item's vtable slot 26 with the human whose tag matches; counters `pickup sent/rcv/applied/already/missing` in the `sync` reply |
| `tests/check_pickup.py` | both directions: host player 1 collects (pad 0 on the host) and guest player 2 collects (`tp 1` + pad 0 on the guest, whose local pad is XInput user 0 — `XInputGetState` in `obscoop2.c`); asserts `+0xa8 == 1` on both copies, equal inventory counts, `sent/rcv/applied` move in the expected direction and **no echo**; forces `item+0x20 = 1` when the save left the item inactive (printed) |
| `tests/start_menu_load.py` | `OBSCOOP_SLOT=0..9` selects `gameN.sav` (default unchanged: `game0.sav`) |
| `tests/run_pair_menu.sh` | exports `SAVE_SLOT` (from `OBSCOOP_SLOT`, default 0) for `check_pickup.py` |
| `tests/scan_slots.py`, `tests/run_scan_slots.sh` | new: the Part A scanner and its one-launch runner |

Echo avoidance (OBSERVED by counters): an applied pickup calls the item's virtual slot 26 directly,
which is what `FUN_004ddad0` itself calls — the hook is on `FUN_004ddad0`, not on slot 26, so the
apply never re-enters the hook. `g_pickup_applying` is a second guard. The receiving copy's `sent`
stayed 0 in the proven run.

## 5. Live runs (verbatim excerpts; full logs in the session scratch)

| # | launcher | slot | result |
|---|---|---|---|
| 1 | `run_scan_slots.sh` | 0 | 30 entities, 1 item (ENDR, inactive), positions unset (read too early) |
| 2 | `run_scan_slots.sh` | 0..9 | all ten worlds, 0 live items (see SLOT_SCAN.md) |
| 3 | `run_scan_slots.sh` + 10 s settle | 0..9 | same, positions still unset for items |
| 4 | probe 1 (solo) | 0 | ENDR position real after ~8 s; LEFT does not move; A on doors/save points does not set `+0x73c` |
| 5 | probe 2 (solo) | 0 | world stable 30 entities for 50 s; `wr item+0x20=1` + tp + A → `a8=1` (the game collected it) |
| 6 | `run_pair_menu.sh` + `check_pickup.py` | 0 | **host→guest OK**: host `pickup sent 1`; guest `pickup rcv 1 applied 1 already 0 missing 0`; item `collected 1` on both; inventories 44/44; echo `sent +0` |
| 7 | `run_pair_menu.sh` + `check_pickup.py` | 1 | host→guest OK again (two MEDIKIT entities); guest→host FAILED because the only remaining medikit has `+0xb0 == 1` (the game's own interaction check refuses it, the test now filters such items) |
| 8 | `run_pair_menu.sh` + `check_pickup.py --guest-only` | 0 | FAILED: the guest's character was pulled back to the host's copy (326 units) between `tp` and the A press; no pickup sent |
| 9 | `run_pair_menu.sh` + `check_pickup.py --guest-only` (host's copy of the character teleported along) | 0 | **guest→host OK**: guest `pickup sent 1`; host `pickup rcv 1 applied 1 already 0 missing 0`; item `collected 1` on both; inventories 44/44; echo `sent +0` |
| 10 | `run_pair_menu.sh` + the six regression checks + `check_pickup.py --host-only` (final DLL `chk15.dll`) | 0 | party OK, items OK, hands OK (2 characters), hands visible OK (2 characters), entities OK (43/43), movement E/A/B/C PASS, **D FAIL** (`BOY1 anim differs in 26/50 samples`; the same phase failed in FINDINGS_13 runs 1–4 and passed in FINDINGS_14's final run — flaky heuristic, see below), **pickup host→guest OK again** (host `sent 1`, guest `rcv 1 applied 1`, both `collected 1`, 44/44, echo 0) |
| 11 | `run_pair.sh` (old flow) + party/items/hands (final DLL) | 01 | **all OK**: party OK (BOY1+GIR1, inventory 44/44), items OK (44 → 45 on both), hands OK (2 characters, same four weapons per slot and same selected slot on both copies) |

Regression note: every check that existed before this task passes with the pickup changes except
`check_movement.py` phase D, the "both pads at once" animation comparison. That phase is the known
flaky one in this project: FINDINGS_13 records `D: FAIL` in four runs and FINDINGS_14's final run
records `D: PASS` with 4/50 and 9/50 animation differences. In this run the *positions* were inside
every threshold (BOY1 mean 6.96 max 16.25, GIR1 mean 8.21 max 43.06) and only the animation sample
comparison failed; the pickup code is inert during that phase (an empty pickup queue and a hook that
only runs on `FUN_004ddad0`). **UNKNOWN** whether it is pure timing; not attributed to the pickup
change.

## 6. Open items (UNKNOWN)

* Why the pad does not move a save-loaded character in a solo copy (and whether the same is true in a
  pair; `check_movement.py` says no in a pair). Until this is understood, world items that the level
  would spawn are out of reach.
* Whether a real (unforced) live item can be produced in these saves at all — no slot has one after
  load, and the saves' own object sections only record collected medikits.
* The guest→host phase needs two live items in one slot; slot 02's two medikits are the candidate.
