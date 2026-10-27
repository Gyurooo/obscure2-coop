# TASK6_FINDINGS — why the guest has no DYNA / FLBA weapon, and the fix

Research for TASK6. Decompile line numbers are in `local/decomp2/Obscure2.exe.c`; function addresses are the
`FUN_xxxxxxxx @ xxxxxxxx` headers in that file (image base 0x400000). Mod line numbers are `src/`.
Labels: **OBSERVED** = read in the decompile/disassembly, in the mod source, or printed by a live run;
**DERIVED** = follows from the cited code but was not itself read live; **GUESS** = plausible, unproven;
**UNKNOWN** = not determined.

Live baseline: current branch DLL (commit `446ded3`), loopback host+guest, save 01 → I100, 2026-10-27.
`tests/check_hands.py` was extended for this task to dump both inventories (index, 16-byte hex) when the
slot tags differ; that dump is quoted in §2.

---

## 0. Short answer

**OBSERVED (live + decompile).** Both DYNA and FLBA *are* in the host's inventory object — FLBA at index 23,
DYNA at index 28 — but the game's inventory **entries are 32 bytes** (`0x20` stride), while `PKT_ITEM` was
written for **16-byte** entries. `host_send_item` therefore transmits only the first `count*16` bytes of the
entry array, i.e. the first ~half of the entries. The guest's mirrored inventory has the host's entries
0..22 and **zeros from 23 on**, so `weapon_object()` finds no entry for FLBA/DYNA and returns before the
game's factory (`FUN_0045cdd0`) is reached. The mod's "build a weapon from its inventory entry" branch is
correct — it is exercised live for CBOW/TASE/UBET/SHOT/GUN/CSAW — it simply has no entry to build from.

The fix is to put whole 32-byte entries on the wire (all `count`, up to the game's limit of 99), split into
chunks that keep each datagram under the Steam transport's 1200-byte rule, and to have the guest assemble a
complete inventory before writing it.

---

## 1. (a) Are DYNA and FLBA in the HOST inventory, and at which index?

**OBSERVED (live, baseline run).** `check_hands.py` reads `world+0x1790`, count at `+4`, entries at `+8` with
stride `0x20`. Host:

```
host inventory: count 44 (44 entries of 16 hex bytes, stride 0x20)
  host [23] 0100000041424c460100000001000000  tag=FLBA
  host [28] 01000000414e59440100000001000000  tag=DYNA
  host [29] 0100000047424c46a000000003000000  tag=FLBG
  host [30] 0100000055474c460100000001000000  tag=FLGU
```

(`tag` decodes the dword at entry+4 the way the game stores it: the memory bytes are the reverse of the
printable name — e.g. `BOY2` is stored as `0x424f5932`, `FUN_004b0370` decompile 106644; DYNA is `0x44594e41`,
factory branch decompile 55018-55023; FLBA is `0x464c4241`, factory branch decompile 55060-55065.)

**OBSERVED — the entry size is 32 bytes, not 16.**

| Fact | Evidence |
|---|---|
| entry address = `inv + 8 + i*0x20` | `FUN_004b04a0` (0x4b04a0) returns `uVar1 * 0x20 + 8 + in_ECX`, decompile 106752 |
| the inventory pass walks entries with `+0x20` | `FUN_004b05a0` (0x4b05a0), `local_8 = local_8 + 0x20`, decompile 106913 |
| an entry is 8 dwords | `FUN_004b0280` (0x4b0280) copies `in_ECX[0..7]`, decompile 106570-106588 |
| entry fields | `FUN_004b0300` (0x4b0300), decompile 106607-106629: `+0` flags, `+4` tag, `+8` id, `+0xc` ammo; for `flags&1` also `+0x10` (float) copied to the weapon, and for DYNA/FLBG rounded into the weapon's ammo at `+0xc8` (decompile 106621-106625) |
| capacity is 99 entries | `FUN_004b0430` (0x4b0430) constructs 99 entries (`iVar1 = 99`, decompile 106700); `FUN_004b07e0` (0x4b07e0) refuses to add past 99 (`*(uint *)(in_ECX + 4) < 99`, decompile 106930) |

**DERIVED — why the host has the objects.** The host's live slots come from the record→slot restore
`FUN_004f1b80` (0x4f1b80, decompile 145280-145430) using `FUN_004b0980` (0x4b0980) to find the entity by tag.
Those entities exist because the world build runs the inventory pass `FUN_004b05a0` over the save's 44
entries (called at decompile 109858), which builds one weapon entity per `flags&1` entry (§3).

---

## 2. (b) Does the guest's mirrored inventory contain the same 16-byte entries?

**OBSERVED — the wire format assumes 16-byte entries.**

* `src/net.c:36-37`: `#define ITEM_MAX 64` and
  `typedef struct { pkt_hdr h; DWORD level; DWORD count; DWORD data[ITEM_MAX * 4]; } pkt_item;   // inventory: count + 16-byte entries`
  — 4 dwords per entry.
* `src/sync.c:230-251` `host_send_item`: the hash loop (242) and the copy loop (247-248) both run
  `count * 4` dwords from `inv + 8` — a **contiguous** `count*16`-byte copy.
* `src/sync.c:253-264` `guest_on_item`: writes exactly those `count*4` dwords at `inv+8` and sets the count
  (`*(DWORD *)(inv + 4) = count`).

**DERIVED.** Because the game's entries are 32 bytes, a `count*16`-byte copy covers only entries
`0 .. count/2` (the first half of the array). Everything from `count/2 + 1` on stays whatever the guest had
(zero, since its own inventory is empty at world build — `PARTY_FINDINGS` §2.7). For `count = 44` the cut is
after entry 21; for `count = 45` after the first half of entry 22.

**OBSERVED (live, baseline run, same dump).** Guest:

```
guest inventory: count 44 (44 entries of 16 hex bytes, stride 0x20)
  guest [ 0] 0400000052444e450100000005000000  tag=ENDR        <- same as host [0]
  ...
  guest [22] 0800000000434f441b00000001000000  tag=444f4300    <- same as host [22]
  guest [23] 00000000000000000000000000000000  tag=-
  ...
  guest [43] 00000000000000000000000000000000  tag=-
```

Host and guest are byte-identical for entries 0..22 and the guest is **all zeros from 23 to 43**. Entry 22 is
covered because `check_items.py` ran first and briefly raised the host's count to 45 (45×16 = 720 bytes =
22×32 + 16, i.e. 22 whole entries plus the first 16 bytes of entry 22 — this is itself proof that the copy
stops at `count*16` bytes, not at `count*32`).

**OBSERVED (guest log, same run).** The build-from-inventory branch works for every entry below the cut and
fails for the two above it:

```
guest: made weapon CBOW (object 1C6A27B8) from the inventory entry
guest: BOY1 slot 0 = weapon CBOW (object 1C6A27B8)
guest: made weapon TASE ... / UBET ...
guest: weapon DYNA has no object and no inventory entry
guest: BOY1 slot 3 needs weapon DYNA, none in this world
guest: made weapon SHOT ... GUN? ... CSAW ...
guest: weapon FLBA has no object and no inventory entry
guest: GIR1 slot 3 needs weapon FLBA, none in this world
```

(The same four lines repeat every 5 s, i.e. `weapons_for` retries and keeps failing on the missing entry.)

**OBSERVED — other limits on the same path.**

* The game allows 99 entries (`FUN_004b0430` / `FUN_004b07e0`, §1), but `ITEM_MAX` is 64, so a correct copy
  would still drop entries 64..98.
* A full 99-entry mirror is 3168 bytes. The receive buffers are 4096 bytes (`src/net.c:391`,
  `src/steam.c:195`), but the Steam transport is deliberately kept under 1200 bytes per packet
  (`src/steam.c:180-188`: comment "every packet stays under 1200 bytes"), so the mirror has to be chunked
  rather than sent as one big packet.

---

## 3. (c) How the game creates a weapon object from an inventory entry, and why `weapons_for()` never gets there

**OBSERVED — the inventory pass.** `FUN_004b05a0` (0x4b05a0, decompile 106821-106920) loops over the
inventory's entries (`local_8 = inv + 8`, `local_8 += 0x20`, decompile 106841/106913) and, per entry:

* `flags & 1` set (weapon/stackable entry), decompile 106884-106892:
  1. `FUN_0045cdd0(entry+4)` — the entity factory for the tag (0x45cdd0, decompile 54539+; branches for
     0x44594e41 = DYNA at 55018 and 0x464c4241 = FLBA at 55060);
  2. weapon `vtable+8(0)` (106886-106888);
  3. `FUN_004b0300(weapon)` — copies entry `{flags, tag, id, ammo, +0x10}` onto the weapon (0x4b0300,
     decompile 106607-106629, called at 106889);
  4. weapon `vtable+0x84(0)` (106890), `weapon+0xa8 = 1` (106891);
  5. `FUN_005544c0(weapon)` — registers the entity in the list at `*(world+0x1768)+0x18` (0x5544c0,
     decompile 207867-207895, called at 106892);
  6. for FLAS, also `FUN_004dc870(weapon, 0)` — the game's equip (106897-106910).
* `flags & 1` clear (106867-106882): the non-stackable branch, which requires `entry+0x18` and uses
  `vtable+0x20`; not used by weapons.

**OBSERVED — when it runs.** `FUN_004b05a0` is called from the world/save construction path at decompile
109858, i.e. once per world build. That is why the host has a DYNA and an FLBA entity and the guest does not:
the guest's world is built from its own (empty) inventory — `PARTY_FINDINGS` §2.7 — and the mirrored
inventory arrives later, through `PKT_ITEM`.

**OBSERVED — the mod's copy of that sequence is faithful.** `src/sync.c:492-537` `weapon_object()` calls
`0x4b0980` first; when that returns 0 it searches the mirrored inventory at the right `0x20` stride
(`rd32(inv + 8 + i*0x20 + 4) == tag`, sync.c:511-513), and on a hit runs exactly the game's sequence
(`0x45cdd0` → `vtable+8` → `0x4b0300` → `vtable+0x84` → `+0xa8=1` → `0x5544c0`, sync.c:518-534).

**DERIVED — why it never reaches the branch for slot 3.** For DYNA/FLBA both the find (`0x4b0980`, no entity
on the guest) and the entry search fail: `weapon_object` logs
`weapon %s has no object and no inventory entry` (sync.c:514-517) and returns 0 **before** the factory call at
sync.c:518. `weapons_for()` (sync.c:543-597) then logs `slot 3 needs weapon ..., none in this world`
(sync.c:565-571). The branch itself is proven correct live: the same run built CBOW/TASE/UBET/SHOT/GUN/CSAW
through it and equipped them, and the guest's slots 0..2 match the host.

---

## 4. The fix

**Cause in one sentence.** `PKT_ITEM`'s wire format copies `count*16` bytes of a `count*32` entry array, so
the guest mirror is truncated after entry ~22 and the tags past the cut (FLBA 23, DYNA 28, FLBG 29, …) have no
entry to build from.

**Change (src/ only):**

1. `net.c`: `ITEM_MAX` 64 → 99 (the game's own limit), and `pkt_item` carries whole 32-byte entries with an
   entry offset, a chunk count and the total, sized so one datagram stays under 1200 bytes
   (`ITEM_CHUNK 32` entries = 1024 bytes of data). Bump `NET_VERSION` because the wire format changes.
2. `sync.c` `host_send_item`: hash and copy `count*8` dwords (32 bytes/entry); send every chunk (offset,
   count, total) when the inventory changes, **and repeat the whole mirror once a second** so a lost
   datagram, or a guest whose world is not ready yet, still converges.
3. `sync.c` `guest_on_item`: validate the chunk, assemble it in a shadow buffer, and only when all chunks of
   a total are present write the entries into `world+0x1790` and set the count — no more partial mirror.
   (`n` is the whole datagram size, header included, as `net_handle` checks `sizeof(hdr)+h->len == n`; the
   first version of this fix compared `n` against the payload size and rejected every packet.)
4. `sync.c` `weapon_object`: entry loop bounded by the same 99 (and still `0x20` stride, unchanged).
5. No invented objects: the weapon is still constructed by `FUN_0045cdd0` and filled from the game's own
   inventory entry by `FUN_004b0300`, registered by `FUN_005544c0`, equipped by `FUN_004dc870`.

`tests/check_hands.py` keeps the inventory dump added for this task, so a future regression shows the
truncated entries directly.

### 4.1 Live verification (final run, loopback, save 01 -> I100)

**OBSERVED.** With the fixed DLL, the same three checks pass:

```
party: host ['BOY1', 'GIR1'] guest ['BOY1', 'GIR1'] | inventory: host 44 guest 44
party OK
items: before host 44 guest 44
items: after host 45 guest 45
items OK
host humans:  [('BOY1', ['CBOW', 'TASE', 'UBET', 'DYNA'], 0), ('GIR1', ['SHOT', '47554e00', 'CSAW', 'FLBA'], 2)]
guest humans: [('BOY1', ['CBOW', 'TASE', 'UBET', 'DYNA'], 0), ('GIR1', ['SHOT', '47554e00', 'CSAW', 'FLBA'], 2)]
in hand: host [('BOY1', 'CBOW'), ('GIR1', 'CSAW')] guest [('BOY1', 'CBOW'), ('GIR1', 'CSAW')]
hands OK (2 characters checked)
```

The slot 3 weapons were created through the game's own path, not copied: guest log

```
21:54:11.571 guest: made weapon DYNA (object 199396C0) from the inventory entry
21:54:11.571 guest: BOY1 slot 3 = weapon DYNA (object 199396C0)
21:54:11.571 guest: made weapon FLBA (object 1A0E48C0) from the inventory entry
21:54:11.571 guest: GIR1 slot 3 = weapon FLBA (object 1A0E48C0)
```

The first `weapons_for` attempt (21:54:06) ran before the first `PKT_ITEM` had been applied and logged
"no inventory entry" for all eight tags; the 5 s retry at 21:54:11 found the full mirror and built all
eight. That 5 s gap is why the guest's own retry logic stays in the mod: the item mirror may arrive just
after the guest's world becomes ready.

---

## 5. GUESS / UNKNOWN

* **GUESS** — the inventory is ordered by acquisition, so the newest pickups sit at the highest indices and
  are exactly the ones the 16-byte copy dropped. Not needed for the fix (any index past the cut was lost).
* **UNKNOWN** — whether entry `+0x18`/`+0x1c` (read only by the non-`flags&1` branch) carry anything for
  items in this save. The fix copies the whole 32-byte entry, so they are preserved either way.
* **UNKNOWN** — whether an item entry can appear twice with different ids (e.g. `444f4300` appears at
  indices 7, 18, 21-27, 34, 37-40, 43 — a door/key item with different `+8` ids). The mirror copies the
  array verbatim, so duplicates are preserved.
* **UNKNOWN** — the exact semantics of `entry+0x10` for non-DYNA/FLBG entries; `FUN_004b0300` copies it to
  the weapon's `+0x118` for every `flags&1` entry, and the fix now carries it (the old format did not).
* **UNKNOWN** — packet-loss behaviour over Steam for `PKT_ITEM` (unreliable, no ack). The fix repeats the
  whole mirror every second, so a lost chunk costs at most ~1 s; this was not measured live (loopback has
  no loss).
