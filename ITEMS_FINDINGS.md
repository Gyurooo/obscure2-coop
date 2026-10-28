# ITEMS_FINDINGS — how Obscure II picks up a world item and removes its entity

Research note for TASK 4. Labels: **OBSERVED** = directly visible in the decompile / disassembly /
mod source; **DERIVED** = follows from the cited code but was not proven by a live read; **GUESS** =
plausible, not proven; **UNKNOWN** = not determined.

Decompile line numbers refer to a local Ghidra export of `Obscure2.exe` (`Obscure2.exe.c`).
Disassembly was taken read-only from `local\obscure2-test\Obscure2.exe` (build 215294) with
`i686-w64-mingw32-objdump`; addresses below are static (image base 0x400000, as used by the mod).

---

## 0. Summary

A world item is a `CToeItem*` object in the level's `CToeManager` (`world+0x1768`). It is identified
by a 4-character **class tag** at `+0x10` (e.g. `MAP\0`) and a per-entity **id** at `+4` (also a
4-character tag, e.g. `ME0A`), has its position at `+0x6c/+0x70/+0x74`, and a **collected flag** at
`+0xa8`.

The pickup is fully synchronous in one frame-visible sequence:

1. The human input update `FUN_004cf940` scans nearby entities, picks the best one whose virtual
   "is collectable" slot returns non-zero, stores it in **`character+0x73c`** and starts animation
   `0x640` (OBSERVED).
2. After 500 ms of that animation, the character state machine (`FUN_004e76c0`, case `0x640`) calls
   `FUN_004ddad0` if `item+0xa8 == 0` (OBSERVED).
3. `FUN_004ddad0` calls the item's virtual slot 26 (`vtable+0x68`) with the character as argument
   (OBSERVED). Base items use `FUN_0044d7c0`; `CToeItemMap` overrides it with `FUN_004508d0`,
   which routes ids `ME0A`/`MF0A` straight to `FUN_004026f0` (OBSERVED).
4. `FUN_004026f0` is the game's own "collect" path: it adds the item to the inventory object
   (`world+0x1790`, `FUN_004b1000`), sets **`item+0xa8 = 1`**, clears the visibility bit of the
   item's mesh (`item+0x34` -> `+0x18`), calls `vtable+0x84(0)` and sends the pickup event
   (OBSERVED).
5. The `+0xa8 = 1` flag makes both interaction checks (`FUN_0044d6a0` base, `FUN_00450770` map)
   return 0, so the item can no longer be picked up; the mesh is hidden. The object is **not
   freed and not removed from `CToeManager`** (OBSERVED).

Therefore "remove the item through the game's own removal path" = call the item's virtual slot 26
(`vtable+0x68`) with a valid character, or call `FUN_004026f0(item, character)` directly. The
object must not be freed by the mod.

---

## 1. Data model (item object)

| Field | Offset | Meaning | Confidence / evidence |
|---|---|---|---|
| vtable | `+0x00` | one of the `CToeItem*` class vtables | OBSERVED — RTTI scan gives 28 classes (`rtti.txt:392-419`); e.g. `CToeItemMap` vtable `0x659e84` (set by `FUN_004505d0`, decompile 46749-46750) |
| entity id | `+0x04` | per-instance id, parsed as a 4-char tag (e.g. `ME0A` = 0x4d453041) | OBSERVED — `FUN_00450690` stores `FUN_004a8e00(<attr>)` at `+4` (46806-46808); `FUN_004508d0` compares `+4` with 0x4d453041/0x4d463041 (46858-46859) |
| flags | `+0x0c` byte 0 & other bits | bit 0 = "owned/attached"; bit 0x200 special | OBSERVED usage — `FUN_004ddad0` tests `+0xc & 1` (134560); `FUN_004026f0` tests `+0xc & 0x200` (1305-1306) |
| class tag | `+0x10` | 4-char class tag (items: `MAP\0` etc.) | OBSERVED — `FUN_004505d0` sets `in_ECX[4] = 0x4d415000` ("MAP\0") (46749); `FUN_004026f0` passes `in_ECX[4]` to the event/UI code (1288) |
| mesh object | `+0x34` | renderable object; `mesh+0x18` bit 0x10 = visible | OBSERVED — `FUN_004026f0` clears bit 0x10 of `*(item+0x34)+0x18` (1298-1302); `FUN_0044d8a0` builds the mesh at `+0x34` |
| position | `+0x6c`, `+0x70`, `+0x74` | world position (x, y, z) | OBSERVED — `FUN_0044d6a0` and `FUN_00450770` compare these with `character+0x23c/+0x240/+0x244` (44145-44151, 46835-46844) |
| can-interact radius | `+0xa0` | float distance | OBSERVED — `FUN_0044d6a0` 44152; `FUN_00450770` 46839 |
| collected flag | `+0xa8` | 0 = live, 1 = collected/hidden, non-interactable | OBSERVED — set to 1 by `FUN_004026f0` (`in_ECX[0x2a] = 1`, 1296); tested by both can-interact methods (44143, 46826) and by the pick-up state machine (140585) |
| user character | `+0xc4` | character that used/collected it | OBSERVED — `FUN_0044d7c0` 44177, `FUN_0044da00` (44277-44294) |
| quantity | `+0xc8` | int, decremented by medikit use | OBSERVED — `FUN_00450aa0` (`*(in_ECX + 200)` = `+0xc8`, 47000-47002); `FUN_0044d850` parses "quantity" into `+200` (44198) |

### Item class tags
Found by scanning the item constructors in `0x44e000..0x451800` for `mov dword ptr [reg+0x10], imm`
(OBSERVED, disassembly):

`ACID`, `BATT`, `BKPK`, `BLEA`, `CABO`, `CROW`, `ENDR`, `GLYC`, `ICAM`, `ICE\0`, `ICRN`, `IDSC`,
`JEMM`, `JERR`, `JUBA`, `KEY\0`, `LVER`, `MAP\0`, `MEDI`, `PASS`, `SERU`, `SODA`, `STAT`, `STRI`,
`SYRI`, `WELD`.

(`CToeItemCircuit`, `CToeItemMedallion`, `CToeItemAmmo` and `CToeItemSyringe` live outside that
range / share constructors; their tags are not in the list above — UNKNOWN for those four. The map,
the only live item in I100, is covered.)

---

## 2. Where the entities live

`world + 0x1768` is a `CToeManager` (OBSERVED: created at level init by `FUN_0045f870`, vtable
`0x65b634`; the vtable's RTTI name is `. ?AVCToeManager@@` at TypeDescriptor `0x6aa088`; the world
destructor destroys it, decompile 109091-109093).

* count: `manager + 0x14` (OBSERVED — `FUN_0045f540` 55961-55978, `FUN_0045f640` 56033-56050,
  and dozens of loops, e.g. decompile 4945-4958)
* linked list: head at `manager + 0x0`; each node is `{value at +0, next at +4}` (OBSERVED —
  `FUN_00587780` 242324-242356 walks `*in_ECX` and `node[1]`)
* lookup: `FUN_0045f540(manager, class_tag, id)` returns the first entity whose `+0x10` equals the
  class tag and (when id != 0) whose `+4` equals the id (OBSERVED — 55960-55994, used by the key
  item `FUN_004501c0` at 46536-46543 and by the map's collect path at 44179-44183)
* enumeration: `FUN_0045f640(manager, class_tag, list)` adds every matching entity to a list
  (OBSERVED — 56029-56050); used by item-use code (e.g. `FUN_004501c0` 46536, `FUN_004504b0`).

**DERIVED:** every level entity, including world items, is in this manager; the map item found by
the old memory scan (`local/runs2/items.txt`, `CToeItemMap 1c2baa18`) is one of its values. A live
walk in the test prints the list (see the test output).

---

## 3. The pickup sequence (addresses)

### 3.1 Input scan — `FUN_004cf940` @ 0x4cf940

**OBSERVED** (decompile 128115-128240):

* for each nearby entity (`FUN_0040f330`/`FUN_004d98c0` iterate a list held by the controller):
  call `vtable+0x1c` and `vtable+0x20` ("usable"/"collectable"), then
  `vtable+0x34(type, character)` with type = 1, 2, 3 or 4 and keep the best aptitude (100 = in
  range) per type (128150-128205);
* if the best entity's `vtable+0x20()` is non-zero (collectable):
  `character+0x73c = entity`, `character->vtable+0x44(0,0,0)`, `character->vtable+0x48(0x640)`
  (128214-128222). `0x640` is the pick-up animation.
* otherwise it calls `vtable+0x34` then `vtable+0x70(character)` — i.e. the normal "use" action
  (doors, levers, map, …) (128224-128245).

### 3.2 Animation completes — `FUN_004e76c0`

**OBSERVED** (decompile 140565-140590): in the `0x640` case, when `character+0xbb > 500` (ms) and
`character+0x73c != 0` and `*(int *)(character+0x73c + 0xa8) == 0`, it calls `FUN_004ddad0()`.
After the animation it clears `character+0x73c`.

### 3.3 `FUN_004ddad0` @ 0x4ddad0 — the "collect the target" function

**OBSERVED** (disassembly 0x4ddad0-0x4ddb06; decompile 134553-134566):

```
4ddad0: 56                push esi
4ddad1: 8b f1             mov  esi, ecx              ; character
4ddad3: 8b 8e 3c 07 00 00 mov  ecx, [esi+0x73c]     ; item
4ddad9: 85 c9             test ecx, ecx
4ddadb: 74 28             je   ret
4ddadd: 8b 01             mov  eax, [ecx]            ; item vtable
4ddadf: 8b 50 68          mov  edx, [eax+0x68]       ; slot 26
4ddae2: 56                push esi                   ; character arg
4ddae3: ff d2             call edx                   ; item->Collect(character)
...
4ddafb: c7 86 3c 07 00 00 00 00 00 00  mov dword [esi+0x73c], 0
```

Prologue is 9 whole bytes (`56 8b f1 8b 8e 3c 07 00 00`), suitable for `hook_entry`.

**OBSERVED:** the script native `Cslh_ToeEntityCollect` (`0x4be3a0`) does the same thing manually:
`character+0x73c = item; call 0x4ddad0`. It is registered as `"ToeEntityCollect"` in
`FUN_004a97e0` (decompile 103925), and its vtable entry is `0x4be3a0` (vtable 0x663df0, slot 4).

### 3.4 Item virtual slot 26 (`vtable+0x68`) — the item's collect method

* Base item: **`FUN_0044d7c0` @ 0x44d7c0** (decompile 44166-44187):
  `FUN_004026f0(character)` then `item+0xc4 = character`, look-up of the item class, and
  `FUN_004b2890(name, 1, ..., 1, 0xfa)` = show the pickup message.
* `CToeItemMap`: **`FUN_004508d0` @ 0x4508d0** (decompile 46855-46864):
  if `item+4 == 0x4d453041` ("ME0A") or `0x4d463041` ("MF0A") -> `FUN_004026f0(character)`,
  otherwise -> `FUN_0044d7c0(character)`.
* Other item subclasses override the same slot only for their "use" behaviour (key, medikit, …);
  the collect path stays `FUN_004026f0`.

### 3.5 `FUN_004026f0` @ 0x4026f0 — the game's own removal / inventory add

**OBSERVED** (decompile 1284-1316; disassembly 0x4026f0-0x40282a):

```c
FUN_005ab670(7, item[4], item[1]);                       // item id/class bookkeeping
uVar3 = item->vtable[0x30]();
FUN_004b1000(inventory, uVar3, item->vtable[0x2c](uVar3)); // world+0x1790 inventory
item[0x2a] = 1;                                           // +0xa8: collected
if (item[0x0d]) *(uint *)(item[0x0d] + 0x18) &= ~0x10;     // mesh: hide (item+0x34)
item->vtable[0x84](0);                                     // extra hide/disable hook
... FUN_004c4060(..., 2, 3000, ...)                        // pickup event/UI
```

The function returns 1 and takes one stack argument (the character); it is `__thiscall` with
`ECX = item`. Callers: `0x44d7d8` (base collect), `0x4508fa` (map collect), `0x48624e` (another
item path) — OBSERVED by scanning all `E8` relative calls in the image.

Effect on the entity: **+0xa8 = 1**, mesh visibility bit cleared. The object stays in
`CToeManager`, but `FUN_0044d6a0`/`FUN_00450770` return 0 once `+0xa8 != 0`, so it cannot be
picked up again and is invisible. This is the game's "the item is gone" state.

---

## 4. What this means for the co-op sync

Smallest reliable sync (implemented in this task):

1. **Host hook** on `FUN_004ddad0` @ 0x4ddad0 (9-byte prologue above), i.e. exactly at the moment a
   character collects. `ECX` = character, `item = *(character+0x73c)`. If the item's class tag
   (`+0x10`) is a known item tag and `item+0xa8 == 0`, send `PKT_PICKUP { level, class, id,
   position, character tag }` and then run the original. This fires for both simulated players
   (host P1 and host-side P2), so a pickup made with either pad is seen.
2. **Guest apply** (main thread): find the same entity with
   `FUN_0045f540(world+0x1768, class, id)`; if found and `+0xa8 == 0`, call the item's virtual slot
   26 (`vtable+0x68`) with a character — the game's own collect path. If the entity is already
   collected (the guest's own simulation got there first) or absent, the item is already gone.
3. No memory is freed; no CToeManager list surgery; `PKT_ITEM` keeps the inventories in step
   (collecting also adds to the guest's inventory locally, which the host's next `PKT_ITEM`
   overwrites with the authoritative list).

Why not hook the item's slot 26 itself? It is per-class (base `0x44d7c0`, map `0x4508d0`, and
subclasses override different slots), while `FUN_004ddad0` is the single character-side entry
point for every item pickup.

Why not hook `FUN_004026f0`? It is shared with non-character collection paths (level init /
script auto-collect) and has no reliable "this was a world pickup" test; `FUN_004ddad0` always has
a character and the entity in `+0x73c`.

---

## 5. Risks / UNKNOWN

1. **The guest may collect the item on its own** before the packet arrives: both copies receive the
   same virtual pads and simulate both players. Then the packet sees `+0xa8 == 1` and is a no-op;
   the item is still gone on both, which is the desired end state. The test therefore also checks
   that the guest received the packet (counter in `sync` status).
2. **The character pointer** is needed by `FUN_004026f0` (it reads `character+0x10` for an event),
   so the guest must apply with a live human. The apply uses the human whose `+0x14` tag matches
   the sender's character, else player 1, else the first human.
3. **Item ids** are 4-character tags, not unique integers across levels; the level tag is in the
   packet and must match before applying.
4. **Level-init auto-collect** (items that start in the inventory) is not synced by this packet;
   `PKT_ITEM` already mirrors the resulting inventory.
5. Not tested here: items in containers/backpacks, dropping items, weapons on the ground, and the
   four item classes whose class tags were not found (`Circuit`, `Medallion`, `Ammo`, `Syringe`).
   Pickup of those would not be sent (host-side tag filter) — a gap, not a desync.
6. **`world+0x1768` is `CToeManager`** is DERIVED from the constructor vtable name and the
   count/list methods; the live test walks it and prints the item, which confirms the manager holds
   the map item (see the run output in the task report).
