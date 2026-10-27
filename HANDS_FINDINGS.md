# HANDS_FINDINGS — the live (in-hand) weapon state and why the guest's hands are empty

Research for TASK5. Decompile line numbers are in `<test root>\decomp2\Obscure2.exe.c`;
addresses are from `Obscure2.exe.functions.tsv` and from `i686-w64-mingw32-objdump -d` on the shipped
`Obscure2.exe` (build 215294, image base 0x400000). Mod line numbers are `src/`.
Labels: **OBSERVED** = visible in the decompile/disassembly/mod source; **DERIVED** = follows from the cited
code but was not proven by a live read; **GUESS** = plausible, unproven; **UNKNOWN** = not determined.

---

## 1. Where a character's held weapon lives

**OBSERVED — the live slots are an array on `CCharacterHuman` itself.** `FUN_004a20c0` (0x4a20c0), the
level-change party writer, reads each live human's weapons for the progress table:

```c
param_4 = (int *)(iVar2 + 0x704);            // decompile 97018   iVar2 = live human
... *param_4 == 0 ? tag = 0 : tag = *(param_4[0] + 0x10)
uVar8 = *(uint *)(iVar2 + 0x714);            // decompile 97039   current slot index
*(uint *)(iVar6 + 0x1b30) = uVar8;           // decompile 97051   -> record+0x24
```

So:

| Field | Meaning | Evidence |
|---|---|---|
| `human+0x704 + 4*i`, i=0..3 | pointer to the live weapon object in slot i, 0 = empty | OBSERVED, decompile 97018-97038 |
| `weapon+0x10` | the weapon's 4-character tag (`SHOT`, `FLAS`, `ANYD`, …) | OBSERVED, decompile 97025, 133880-133900 |
| `human+0x714` | index of the slot in the hand / selected weapon (0..3) | OBSERVED, decompile 97039, 145418 |
| `record+0x14..+0x20` (`progress+0x1b20..+0x1b2c`) | the four weapon **tags** in the saved character record | OBSERVED, decompile 97017-97038, `PARTY_FINDINGS` §0 |
| `record+0x24` (`progress+0x1b30`) | the selected slot in the record | OBSERVED, decompile 97051, 145418, 145446 |

The record only stores tags (plus the selected index); the actual weapon objects are not in the 0x140-byte
character block and are not part of `PKT_REGION`. This is the gap `PARTY_FINDINGS` §4.3 names.

## 2. The game's own functions that set the live state

**OBSERVED — equip: `FUN_004dc870(weapon, slot)`, thiscall `ECX = human`** (decompile 133865-133940,
disassembly of the call in `FUN_004b05a0` at 0x4b0721-0x4b0724 pushes `(slot=0, weapon)` with `ECX = human`).
It is the only "put this weapon object in this slot" routine:

* refuses if any live human already holds a weapon with the same tag (`133882-133905`) and clears matching
  tags from the progress records (`133921-133935`);
* replaces the old object (`vtable+0x74`, `vtable+0x6c(0)`), stores the new pointer in `human+0x704+slot*4`,
  calls `vtable+0x6c(human)` (set owner), switches `human+0x714` to this slot when the current one is empty,
  and calls `vtable+0xcc` (show/equip) when this is the current slot (`133937-133960`).

**OBSERVED — find a live weapon object by tag: `FUN_004b0980(tag)`** (0x4b0980). Plain function, one stack
argument; it iterates the world's entity list (ECX = `*(world+0x1768)+0x18`) and returns the first entity
whose `+0x10` equals the tag and whose byte `+0xc` has bit 0 (`objdump 0x4b0980-0x4b09ed`; decompile 107003-107020).
`FUN_004f1b80` (0x4f1b80) uses exactly this to restore a saved party's weapons (decompile 145395-145430):

```c
if ((*local_10 != 0) && (piVar5 = FUN_004b0980(*local_10)) != 0 && (piVar5[3] & 1))
    { weapon vtable+0x6c(human); *slot = piVar5; }         // record tag -> live slot
human[0x1c5] = record[0x24];  weapon vtable+0xcc();        // selected slot + show
human[200]  = record[0x10];                                // health
```

**OBSERVED — create a weapon object from a tag: `FUN_0045cdd0(tag)`** (0x45cdd0) is the entity factory:
`operator_new(<class size>)` + the class constructor selected by the 4-character tag (shotgun 0x298,
uzi, bat, flashlight …; decompile 54539-55770), returns the object or 0. The game calls it with
`ECX = *(world+0x1768)` and then registers the result with `FUN_005544c0(entity)` on
`ECX = *(world+0x1768)+0x18` (`FUN_004b05a0`, objdump 0x4b0746-0x4b0752 and 0x4b07a0-0x4b07b6; decompile
106862-106904). `FUN_005544c0` appends `{entity, next}` to that list (decompile 207867-207895), which is the
list `FUN_004b0980` iterates.

## 3. What differs between host and guest

**DERIVED.** The host plays the save normally, so its humans get their slots filled by the game's own
record→slot path (§2, `FUN_004f1b80`) when the save's world is built. The guest never rebuilds its party
from the host's records when the world is built (`PARTY_FINDINGS` §2.4/§2.5); the mod only copies the
0x140-byte record block at the level change, and that block carries tags, not the live objects. The guest's
own bodies are recreated by `FUN_004a3c10`, and the record→slot restore needs a live entity for each tag
in its own world entity list; nothing in the mod triggers that restore for the host's tags. So the guest's
`human+0x704[]` are 0 (or the guest's own old weapons) while the host's are full.
Measured live in §5 (baseline run).

**DERIVED (why the record copy alone does not fix it):** the record weapons are only *written* from the live
bodies (`FUN_004a20c0` decompile 97005-97057, `FUN_004f1dc0` decompile 145400-145425) and *read back* by
`FUN_004f1b80` through `FUN_004b0980`, i.e. only if a matching weapon **entity** already exists in the world.
`PKT_ITEM` copies the inventory entries (count + 16 bytes each, `sync.c:253-264`) but the game's
inventory→entity pass (`FUN_004b05a0`) is not re-run through a raw entry write, so the guest cannot rely on
the entity being present; the equip path therefore has to fall back to `FUN_0045cdd0(tag)`.

## 4. Chosen change (smallest that can work)

1. `ch_state` (net.c:27) gains `DWORD wep[4]` (live slot tags) and `DWORD wcur` (`human+0x714`). The host
   fills them in `host_send_state` from `human+0x704+i*4` → `weapon+0x10` and `human+0x714` (`sync.c`).
   Packet grows by 20×8 = 160 bytes (pkt_state 560 bytes, still one datagram).
2. The guest, in `guest_apply_state` (`sync.c`), for the human already matched by character tag, compares its
   four live slot tags with the host's. `guest_apply_weapons`/`weapons_for` then, for every differing
   non-empty slot:
   * finds the weapon object with `FUN_004b0980(tag)`;
   * if there is none but the mirrored inventory (`world+0x1790`) has an entry for the tag, builds it
     exactly the way the game's inventory pass does (`FUN_004b05a0` decompile 106880-106930): factory
     `FUN_0045cdd0(tag)` → `vtable+8(0)` → `FUN_004b0300(entry, ent)` → `vtable+0x84(0)` → `ent+0xa8=1` →
     register with `FUN_005544c0` on `*(world+0x1768)+0x18`;
   * calls the game's equip `FUN_004dc870(human, obj, slot)`;
   * finally makes the selected slot match `wcur` the way `FUN_004f1b80` does (`human+0x714 = wcur`, weapon
     `vtable+0xcc`), which is also what draws the weapon.
   Every call is guarded by a prologue check (`mem_ok`/`memcmp`), so a different build logs and skips instead
   of crashing; each step is logged with `logf`.
3. The apply runs from the **input-update hook** (`hk_input_update`, 0x4cf940), i.e. inside the game's own
   update, on a pending flag set by the snapshot. Reason: the first live attempt called the factory from the
   Present hook (`hk_dev_Present` → `frame_tick`) and the guest's whole logging stopped dead 17 s after the
   load (no weapon log line was reached; the process stayed alive with frozen memory) — the entity factory
   loads weapon assets and must not run inside Present. See §5.
4. No new packet, no new hook, no raw pointer into game objects apart from the scalar `human+0x714` the game
   itself writes in the same way (`FUN_004f1b80` 145418, `FUN_004d5f70` 130270-130292).

## 5. Live measurement (all runs on loopback, save 01 -> I100)

Baseline (unmodified source) and final output are quoted verbatim in the task report. Summary of what the
checks printed:

| Run | DLL | host hands | guest hands |
|---|---|---|---|
| baseline | current source | BOY1 CBOW/TASE/UBET/DYNA, GIR1 SHOT/GUN/CSAW/FLBA | same minus the 4th slot on both |
| 1 | creation from Present | — | guest stopped logging 17 s after the load; BOY1 CBOW only, GIR1 nothing; BOY1 record weap0 cleared (= one equip did happen) |
| 2 | lookup-only | same | all four slots empty; `FUN_004b0980` found **no** weapon object for any of the 8 tags |
| 3 (final) | lookup + build-from-inventory in the input hook | same | same as the host except the 4th slot; log: `weapon DYNA has no object and no inventory entry`, `weapon FLBA has no object and no inventory entry` |

Facts proven by these runs:
* The OBSERVED layout is right: the host's four live tags and `+0x714` come out as the save's records.
* On the guest the game itself restores slots 0-2 from the record block at spawn (baseline and run 3), but
  never the 4th (DYNA/FLBA); in another run (2) it restored none, so that restore is a race in the guest's
  own load, not something the mod controls.
* The guest's world does not reliably hold weapon **entities**: run 2's log shows `FUN_004b0980` returning 0
  for all eight tags while run 3 (same flow) had objects for six of them.
* The final run's guest stayed healthy for the whole test (party, inventory mirror and hands checks all
  read it; no freeze, logs continue to the end), and its log shows the exact reason the 4th slot stays
  empty: no DYNA/FLBA object and **no inventory entry with that tag**, so the game's own creation path has
  nothing to build from.

## 6. Remaining UNKNOWN / not done

1. **The 4th carried slot (DYNA on BOY1, FLBA on GIR1) is still empty on the guest** — the only measured
   difference left. The guest's mirrored inventory (44 entries, same count as the host) has no entry for
   those tags, so `weapons_for` refuses to invent an object. Not fixed.
2. **The build-from-inventory branch of `weapons_for` was never exercised by a live run** (the entry was
   missing every time it was reached). It is written from the game's own sequence in `FUN_004b05a0`, but it
   is UNVERIFIED; the safe behaviour on the owner's copy may still be "no entry, no create".
3. Whether the visual "empty hands" is the *selected* weapon not being drawn (which the `vtable+0xcc` in the
   final change addresses) or the slots themselves being empty (run 2's state). The test cannot see the
   rendering; it can only compare the slots and the selected index, which in the baseline already matched
   while the owner still saw empty hands. UNKNOWN.
4. What the game does with the guest's old weapon objects when the party is replaced at a level change
   (freed with the old world / leaked). Not changed by this fix.
