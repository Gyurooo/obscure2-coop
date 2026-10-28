# PICKUP_PLAN — prove or fix world-item pickup sync

Goal: on two live copies, a world item collected on the host must also become collected on the guest
(`item+0xa8 == 1`, mesh hidden, same inventory count), or the reason it does not must be found and fixed.

## Current implementation (WIP commit `ca5f53c`)

* `src/hooks.c` hooks `FUN_004ddad0` @ `0x4ddad0` (the character-side collect call): when the host's
  character has a collectable item in `character+0x73c`, it sends `PKT_PICKUP {level, class tag, id,
  position, character tag}`.
* `src/net.c` carries `PKT_PICKUP = 15`; `src/sync.c` `guest_on_pickup` queues it and
  `guest_apply_pickups` (frame thread) looks the entity up in `CToeManager` (`world+0x1768`,
  `FUN_0045f540(manager, class, id)`), then calls the item's virtual slot 26 (`vtable+0x68`) with a
  live human — the game's own collect path (`ITEMS_FINDINGS.md` §3).
* Counters in the `sync` pipe reply: `pickup sent / rcv / applied / already / missing`.

Nothing in this path has ever been exercised live: save 01 is I100, which only contains a
`CToeItemMap` and no live collectable item (`tests/check_pickup.py` stopped at
`no live world item on the host`).

## How to find a collectible item per save slot

1. **Candidate slots from the save files (offline, read-only).** Every `Save/gameN.sav` is a serialized
   progress object with one section per visited level (`gameN.sav` header = current level; sections for
   all visited levels are present). A section lists the objects whose state was saved in that level,
   including collected items (`MEDI`, `BKCS`, `AMSH`, …). A current level with **no** collected-item keys
   is the least-played and therefore the best chance of a live item.
   From the ten saves (`game0..9` = slots 01..10):

   | slot | level | level name (from `cachpack.hvp`) | collected item keys in its section |
   |---:|---|---|---|
   | 01 | I100 | — | — (known: no live item) |
   | 02 | I015 | Couloir de Jeddidiah | 2× MEDI |
   | 03 | D003 | Foret_01 (forest) | none |
   | 04 | J002 | Salle d'Intronisation (story room) | none |
   | 05 | J005 | Parc (park) | 2× MEDI |
   | 06 | G003 | Plage-Buvette (beach bar) | — (ENDR only) |
   | 07 | H000 | — | none |
   | 08 | H006 | — | 2× MEDI |
   | 09 | I004 | Toilette (toilets) | — (ENDR only) |
   | 10 | I007 | Cours Central (courtyard) | none |

   `ENDR`/`AMGU`/`SAVE` are engine object tags, not collectable item classes; ignore them.

2. **Live entity scan.** `tests/scan_items.py <pid>` walks `world+0x1768` (`CToeManager`: count `+0x14`,
   linked list head `+0`, next `+4`) and prints every entity: class tag `+0x10`, id `+4`, collected flag
   `+0xa8`, position `+0x6c/+0x70/+0x74`; for items it also prints the gates the interaction check uses
   (`+0xc0`, `+0xac`, `+0xb0`, radius `+0xa0`). Live and non-collected items are the candidates.
   At most **3 live scans**, one run per candidate slot, games always stopped afterwards.

3. **Candidate order.** Slot 03 (D003, large forest, nothing collected), slot 05 (J005, park; only
   medikits collected so far), slot 10 (I007, central courtyard, nothing collected). Avoid slot 04
   (story-locked Salle d'Intronisation) and the small `Toilette` room unless needed. Slot 02 (I015) is
   the fallback. The first scan that shows a live item nearest to the player wins; no more scans.

4. **Prove the pickup.** `tests/check_pickup.py` (generalised to any slot) picks the nearest live item,
   `tp 0 x y z` teleports host player 1 onto it, presses A (pad user 0, as `bot.py` does), waits for the
   ~500 ms collect animation, and asserts:
   * the item's `+0xa8` becomes 1 (or the entity disappears) on the **host**,
   * the same on the **guest**,
   * both inventory counts are equal,
   * the guest's `pickup rcv` counter is ≥ 1, and prints both copies' `pickup sent/rcv/applied/already/missing`.

5. **Baseline, then fix.** Run the pair test with the current DLL unchanged (baseline). If the guest does
   not collect, read `obscoop.log` on both copies and the counters, fix `src/`, rebuild, rerun. At most
   **4 pair runs** total. Then run `check_party.py`, `check_items.py`, `check_hands.py` on the used slot
   when they apply (they assert save-01 specifics in `check_save.py`/`check_items.py`; if they do not
   apply, say so and run them once on slot 01 at the end).

## Safety

* Only `tests/run_pair.sh` (two copies in `local/obscure2-test*`) is used; no real install touched.
* `tasklist` is checked before every live run; a pre-existing `Obscure2.exe` means stop and report.
* Saves are only loaded through the game's own pause menu; never request a level tag directly, never
  edit `obscoop_levels.txt`.
* `duo.py stop` always runs (run_pair.sh does it), and the run is in the foreground with a long timeout.
