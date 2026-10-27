# PARTY_FINDINGS — why the guest keeps BOY2/GIR2 after a save load

Research only. No file under `src/` or `tests/` was modified, and no game process was run for this note.
Labels: **OBSERVED** = directly visible in the decompile/mod source/save file/notes; **DERIVED** = follows
from cited code but was not proven by a live read; **GUESS** = plausible, not proven; **UNKNOWN** = not
determined here.

Decompile line numbers are in `C:\Users\gyuro\coop-anything-obscure\local\decomp2\Obscure2.exe.c`; addresses
are from `Obscure2.exe.functions.tsv`. Mod line numbers are in this repo.

---

## 0. The data model in one screen

| Thing | Where | What it holds | Confidence |
|---|---|---|---|
| Live progress object | `*(game + 0x318)`, size 0x1cd4 | story/entity table at +0x814, 8 character records at +0x1b0c, level at +0x1c4c, chapter/counters/toggles from +0x1c50 | OBSERVED (decompile 99750-99770 allocates it; `sync.c:611-619`; NOTES:152) |
| Saved/parsed copy | `*(game + 0x31c)`, same size | the last save parsed by the game (the source of a LoadProgress) | OBSERVED that the two objects exist and state 2 copies +0x31c to +0x318; **DERIVED** that the menu load parser writes +0x31c |
| Character record | `progress + 0x1b0c + i*0x28`, i=0..7 | +0x00 character tag (BOY1…GIR4), +0x04 level tag, +0x08 pos_id (arrival door), +0x0c controller tag, +0x10 health float, +0x14..+0x20 weap0..3 | OBSERVED (parser `FUN_005405a0`, 193770-193840; `sync.c:617-619`; NOTES:210) |
| Character tags | dword | `BOY1`=0x424f5931 … `GIR4`=0x47495234 | OBSERVED (decompile 4681, 28898, …) |
| Controller tags | dword in memory | text `CHC1`=0x43484331, `CHC2`=0x43484332, `CHTM`=0x4348544d. In the raw save bytes these read `1CHC`, `2CHC`, `MTHC` (little-endian). | OBSERVED (decompile 98988, 97179-97182; `FUN_004a8e00/60`, 101732-101777) |
| Live humans | `world + 0x175c` manager: count +4, array +0xc | the actual `CCharacterHuman` objects; `human+0x14` tag, +0x23c live pos, +0x320 life, +0x2dc death/anim | OBSERVED (NOTES:108-110,150; `sync.c:30-49`) |
| Controllers | `world + 0x1748`, records stride 0x764 | `+0` human pointer, `+0xc` controller tag (`CHC1`/`CHC2`) | OBSERVED (NOTES:110; `sync.c:51-57`) |
| Camera | `world + 0x1764`, target at +0x17c | the human the camera follows | OBSERVED (NOTES:215; `sync.c:843-859`) |
| Inventory | `world + 0x1790` | count at +4, entries at +8 | OBSERVED (`sync.c:226-264`; NOTES:305) |
| Game state | `game+0x310` mode (1 in game, 4 menu), `game+0x320` request state (2 load, 3 load-by-name, 4 change level, 9 menu), `game+0x364` level, +0x368 entry, +0x370 flag | request/state machine | OBSERVED (NOTES:145-152; `sync.c:712-748`) |
| World | `*(game+0x378)`, level tag at +4 | the loaded level; `0` means no world | OBSERVED (`sync.c:27-28`; decompile 98038) |

Save-file byte check (read-only dump of the test copy's `Save/game1.sav`, 2026-10-27):
the character records are stored in this same order. At a record start the bytes `31 59 4f 42`
are the dword 0x424f5931 (text `BOY1`), followed by the level dword, a 4-byte `pos_id`, the controller
dword (`32 43 48 43` = 0x43484332, text `CHC2`), a float 100.0 and four weapon tags. The pre-edit backup
`Save.1p.bak/game1.sav` has `4d 54 48 43` (= 0x4348544d, text `CHTM`) at that position where the edited
file has 0x43484332. This confirms the controller field and its byte order. It does **not** by itself
settle which characters the reported run used: the test copy's current `game1.sav` contains a BOY1/BOY2
pair, while TASK2/NOTES:315 say the host saw BOY1/GIR1. Which save file that run loaded is **UNKNOWN**.

---

## 1. Where does the game decide BOY1/GIR1 vs BOY2/GIR2?

### New 2-player game: hardcoded in `FUN_004a54c0` (0x4a54c0)

**OBSERVED.** `FUN_004a54c0` (decompile 98897-98915) is the new-game world setup:

```c
FUN_004a1e70();
FUN_004a5320(0x42313031);   // level B101
FUN_004a3930(0x424f5932);   // character BOY2
FUN_004a3930(0x47495232);   // character GIR2
FUN_004a1e80();
```

`FUN_004a3930` (0x4a3930, 97917-97987) loads that character's data/skins/anims
(`%scharacters\%s\%s%s.dic`, `skins`, `%slevels\%c\%s\%s%s.zwo`). The caller is the menu handler
`FUN_00555730` at decompile 208708-208713: when the selected menu item's tag is `NGM1`/`NGM2`
(0x4e474d31/0x4e474d32, "new game one/two player") it calls `FUN_004a54c0()`. So in a new game the
two names are **not read from any data file** — they are the two constants BOY2 and GIR2 in this function
(the level is the B101 constant above it).

### Save load: read from the save's `character` records by `FUN_005405a0` (0x5405a0)

**OBSERVED.** `FUN_005405a0` (decompile 193770-193840) parses one progress object from the save tree:

* `level_id` → `progress+0x1c4c`, `current_chapter` → `+0x1c68`, `chest` → `+0x1cd0` (193779-193791).
* For each `character` element it writes one record at `progress+0x1b0c+i*0x28` (193789-193836):
  character tag (parsed with `FUN_004a8e00` from the element's name/tag attribute), `level_id`, `pos_id`,
  health (float), `controller` (again `FUN_004a8e00`), and `weap0..3`.

The save keys are confirmed in `strings.tsv:2052-2062` (`character`, `level_id`, `pos_id`, `controller`,
`weap0..3` at 0x66b2a4-0x66b2f4). `FUN_004a8e00` (101732-101759) uppercases a 4-character text tag and builds
the game dword; `FUN_004a8e60` (101762-101777) prints it back. That is why the text form of the controller
is `CHC1`/`CHC2`/`CHTM` while the raw file bytes read `1CHC`/`2CHC`/`MTHC`.

**DERIVED (call target):** the parser is a thiscall; Ghidra does not show the `ECX` value at its call site.
The game's menu load path `FUN_004a4060` (0x4a4060) calls it at 185885 after opening the save's XML
(`common_state`). The parser must target the **saved copy** `*(game+0x31c)` because `FUN_004a1ba0` reads
`+0x1c4c` from `+0x31c` and state 2 copies `+0x31c` to `+0x318` (see §2). A live read of `ECX` at the call
site would confirm this; it was not done (research-only).

### The moment the names become live humans: `FUN_004a3c10` (0x4a3c10)

**OBSERVED.** Only when a world is built, `FUN_004a3c10` (98010-98118) loops over the 8 records and, for
each one whose record level (`+0x1b10`) equals `game+0x364` (the level being loaded), calls the world's
vtable slot 5:

```c
(**(code **)(**(int **)(in_ECX + 0x378) + 0x14))(
    record+0x1b0c,   // character tag
    record+0x1b14,   // pos_id / arrival door
    record+0x1b18);  // controller tag
```

(decompile 98084-98094). That is the actual "spawn this party member" call. The character assets are
loaded a little later by `FUN_004a58e0` (0x4a58e0) for the same records (99239-99247), called from the
per-frame `FUN_004a5f20` after the world exists (99276-99280).

So: **new game → constants BOY2/GIR2 in `FUN_004a54c0`; save load → the character tags in the save file,
parsed into `progress+0x1b0c`, then spawned by `FUN_004a3c10` from the records at the target level.**

---

## 2. Why does the guest keep BOY2/GIR2 although its LoadProgress runs?

This is a chain of six facts, not one bug.

### 2.1 The mod forwards the *request*, not the parsed save

**OBSERVED.** `hk_load_progress` (`src/hooks.c:77-94`) calls the game's original `LoadProgress`
and, if this is the host, sends `REQ_LOAD_PROGRESS` with the argument (the slot). The guest's
`guest_apply_requests` (`src/sync.c:781-833`, case at 814-818) calls the `g_load_progress` trampoline
directly. Nothing in the mod opens or parses `Save/gameN.sav` for the game. The save-file transfer
(`src/sync.c:86-222`) only writes the bytes to the guest's disk and acks them; it does not feed the
parser.

### 2.2 `LoadProgress` does not parse anything

**OBSERVED.** `FUN_004a1ba0` (decompile 96595-96606) is just:

```c
*(game + 0x320) = 2;                              // state 2
*(game + 0x364) = *(*(game + 0x31c) + 0x1c4c);    // level from the *already parsed* saved copy
*(game + 0x374) = arg;                            // save slot argument
```

The work happens on the next frame in `FUN_004a5520` state 2 (decompile 98960-98985):

```c
FUN_0053fe10(*(game + 0x31c));                    // copy saved copy -> live progress
(**(code **)(**(int **)(game + 0x318) + 8))();    // progress vtable[2]
level = *(*(game + 0x318) + 0x1c4c);
*(game + 0x364) = level;
*(game + 0x464) = *(game + 0x374);
FUN_004a3c10(level, 0);                           // build/load the level
...
*(game + 0x310) = 1;                              // in game
```

`FUN_0053fe10` (193312-193360) copies the whole live progress from the argument, including the
0x140-byte character table. So LoadProgress is a **copy of `game+0x31c` plus a level load**, not a
save-file parse.

### 2.3 The guest's `game+0x31c` is its own, never the host's

**DERIVED.** The only code that parses a save into `+0x31c` is the game's own menu/load path
(`FUN_004a4060` → `FUN_005405a0`; 185885). The guest reaches the auto-load through the mod's
`REQ_LOAD_PROGRESS`, which calls only `FUN_004a1ba0`. The guest never ran the menu parser after its
own new game, so `+0x31c` contains the guest's own state (fresh/new-game or its own local save), not
the host's save. `PKT_REGION` also never writes `game+0x31c`; it writes only the live object
`game+0x318` (`src/sync.c:686-709`). Consequence: the state-2 copy restores the guest's own table,
not the save's BOY1/GIR1.

### 2.4 `FUN_004a3c10` refuses to build a world that already exists

**OBSERVED.** `FUN_004a3c10` starts with (decompile 98038):

```c
if (*(int *)(in_ECX + 0x378) != 0) goto LAB_004a3e8c;   // world != 0 -> return
```

The guest is already in its own game (world != 0), so state 2 changes the progress object and the
level tag but **does not create or replace any human**. The live humans at `world+0x175c` remain
BOY2/GIR2. This is why "the guest's LoadProgress runs" is true and still irrelevant for the party.

### 2.5 The host's ChangeLevel writes the guest's own party back into the table

**OBSERVED.** When the host's level request reaches the guest, `FUN_004a5520` starts state 4
(decompile 98936-98945):

```c
if (*(int *)(in_ECX + 800) == 4) {
    FUN_004a20c0(*(game+0x370), *(game+0x364), *(game+0x368), 0);
}
FUN_004a3760();   // world teardown
```

`FUN_004a20c0` (0x4a20c0, 96894-97102) first iterates the **live humans** (world+0x175c) and writes each
one's character tag + controller tag into the progress table (`FUN_005402c0`, 96913-96965), with the
current level and a per-character default pos_id; then (96970-96997) it moves the records that were at
the old level with a non-zero controller to the **new** level and the arrival entry. In other words, the
guest's BOY2/GIR2 are re-registered as the party at the new level. `FUN_004a3760` (97816-97865) then
destroys the world and sets `game+0x378 = 0` (97850). Later in the same state 4, `FUN_004a3c10` builds
the new world and spawns every record whose level equals `game+0x364` — now BOY2/GIR2 again
(98084-98094). The host's party table can never win this: the game has just overwritten it from the
live bodies.

### 2.6 `PKT_REGION` arrives too late and only at `+0x318`

**OBSERVED.** The host sends the character table as the block `+0x1b0c..+0x1cd4` in `PKT_REGION`
(`src/sync.c:617-663`, `PROG_CHR_OFF=0x1b0c`, `PROG_END=0x1cd4`). The guest queues it and applies it
only when (decompile 698, `src/sync.c:686-709`):

* `game+0x310 == 1` (in game) and `game+0x320 == 0` (idle), and
* its world's level tag `world+4` equals the packet's level.

That is after the party was already spawned. And it writes only `game+0x318` (the live object), never
`game+0x31c` (the copy LoadProgress reads). So even a perfectly synced table cannot change the live
party by itself; the next level change will overwrite it from the live bodies anyway (§2.5).

### 2.7 Inventory count 0 until `PKT_ITEM`

**OBSERVED.** The inventory object is `world+0x1790` (`sync.c:226-264`; NOTES:305). It is created with
the guest's own world and is not part of the 0x140-byte character table or the progress block that
LoadProgress copies. The guest's world is never rebuilt from the save (it already exists), so its
inventory stays empty until `host_send_item`/`guest_on_item` mirror the host's count and entries
(`sync.c:230-264`). That is exactly the observed "inventory 0 until PKT_ITEM".

### 2.8 The counter-case that works

**OBSERVED in NOTES:315** (and consistent with the code): if the guest loads save 01 from **its own
menu before connecting**, the world is 0 at that moment, the game's own menu path parses the
(transferred, byte-identical) save into `game+0x31c`, and state 2 builds the world from it; the party
is then BOY1/GIR1 and the rest of the sync works. The bug is specifically the *automatic, in-game*
application of the host's load.

**Answer to Q2 (one sentence):** the guest's LoadProgress copies the guest's own, never-parsed
`game+0x31c` into the live progress object and cannot rebuild an existing world; the next host level
change re-derives the party table from the guest's live BOY2/GIR2 bodies before rebuilding the world,
so the guest re-spawns BOY2/GIR2 and its inventory (a world object, not a progress field) stays empty
until `PKT_ITEM`.

---

## 3. Smallest change in the mod that makes the guest load the save's party

### 3.1 Recommended: override the character table at the state-4 prep point

The host's correct 0x140-byte character table is already on the wire in `PKT_REGION`; the problem is
only timing (§2.5/2.6). The smallest working change is to keep a copy of it on the guest and install it
**after** `FUN_004a20c0` has done its damage, but **before** `FUN_004a3760` tears the world down and
`FUN_004a3c10` rebuilds it:

1. **Stash the host table** (`src/sync.c`, `guest_on_region`, under the existing `g_reg_cs`): when
   `r->off == PROG_CHR_OFF (0x1b0c)` and `r->len >= 0x140`, copy the first 0x140 bytes into a static
   `g_host_party[0x140]`, record `r->level` and set a valid flag. Do this on receipt, not only when
   `guest_apply_regions` is allowed to apply it (the region may be queued while the guest is still on
   the old level).

2. **Hook `FUN_004a20c0` (0x4a20c0)** in `src/hooks.c`:
   * prologue is `55 8b ec 83 ec 08` (6 whole bytes; dumped read-only from the shipped exe), so
     `hook_entry((BYTE*)0x4a20c0, p_party, 6, ...)` is safe;
   * signature: thiscall, `ECX = game`, stack args `(int flag, unsigned level, unsigned entry, int *weapons)`;
   * call the original through the trampoline, then if `g_role == 2 && g_apply_host_req &&
     g_host_party_valid && g_host_party_level == level` and `game+0x318` is writable, `memcpy` the
     0x140-byte stash over `*(game+0x318)+0x1b0c`. Do **not** gate on the original's return value: the
     original can return 0 after writing the level/records (96999-97003) and state 4 still proceeds.
   * Because `FUN_004a20c0` runs at the very top of state 4 (98936-98944), the copy is in place before
     `FUN_004a3760` (98945) and `FUN_004a3c10` (99011), so the rebuilt world spawns BOY1/GIR1.

3. **Send the table before the level request** (`src/sync.c`): move
   `host_send_progress(1)` *before* `net_send_req(REQ_LEVEL, ...)` in `host_watch_level` (715-748) and
   in `host_welcome_guest` (750-760). The guest then has the current table (with the host's level) by
   the time its state 4 runs. Optionally, in `guest_apply_requests` (REQ_LEVEL case, 791-796), keep the
   request queued for up to ~500 ms until `g_host_party_valid && g_host_party_level == r.a`, with a
   fallback to the old behaviour on timeout — this closes the UDP reorder hole.

Sketch (research note only; not applied):

```c
/* hooks.c, near the request globals */
static BYTE g_host_party[0x140];
static DWORD g_host_party_level;
static volatile LONG g_host_party_valid;
typedef int (__fastcall *party_t)(void *, void *, int, unsigned, unsigned, int *);
static party_t g_party_table;

static int __fastcall hk_party_table(void *game, void *edx, int flag, unsigned level, unsigned entry, int *weapons)
{
    int r = g_party_table(game, edx, flag, level, entry, weapons);
    if (g_role == 2 && g_apply_host_req && g_host_party_valid && g_host_party_level == level) {
        unsigned obj = *(unsigned *)((BYTE *)game + 0x318);
        if (obj && !IsBadWritePtr((void *)(uintptr_t)(obj + 0x1b0c), 0x140))
            memcpy((void *)(uintptr_t)(obj + 0x1b0c), g_host_party, 0x140);
    }
    return r;
}

/* install_request_hooks */
static const BYTE p_party[6] = { 0x55, 0x8b, 0xec, 0x83, 0xec, 0x08 };
g_party_table = (party_t)hook_entry((BYTE *)0x4a20c0, p_party, 6, (void *)hk_party_table, "party table (0x4a20c0)");
```

```c
/* sync.c, guest_on_region, inside the g_reg_cs section */
if (r->off == PROG_CHR_OFF && r->len >= 0x140) {
    memcpy(g_host_party, r->data, 0x140);
    g_host_party_level = r->level;
    InterlockedExchange(&g_host_party_valid, 1);
}
```

Note the include order: `sync.c` is included **after** `hooks.c` (`sync.c:1`), so the stash must be
declared in `hooks.c` (as above) or exposed through an accessor; a declaration in `sync.c` would be too
late for the hook function in `hooks.c`.

**Why this is the smallest:** no packet format change, no new game-file parse, no world pointer
tampering; one new hook (the existing `hook_entry` machinery), one 0x140-byte stash, one reorder. It
reuses the host table that `PKT_REGION` already sends and the game's own state-4 world rebuild.

### 3.2 Alternative A: hook `FUN_004a3c10` instead (0x4a3c10)

Same stash, but install the copy at the **entry** of the world builder: if `world == 0` and the stash
level equals `game+0x364`, copy the 0x140 bytes into `*(game+0x318)+0x1b0c` before calling the original.
This is more targeted (the copy happens exactly before the spawn loop) but the prologue is longer:
`55 8b ec 6a ff 68 33 49 64 00` (10 whole bytes). It also fires for a fresh world created at the menu,
which is harmless if the level matches. The `FUN_004a20c0` hook is preferred because its 6-byte prologue
is simpler and it only fires on a level change.

### 3.3 Alternative B: no hook — have the guest load the save at its own menu

**OBSERVED** (NOTES:315, 328-329). Zero mod code: the guest loads the transferred save 01 from its own
menu **before** connecting, so the world is 0, the game's parser fills `game+0x31c`, and state 2 builds
the world with BOY1/GIR1. This is the smallest change in the colloquial sense and the current
workaround, but it is a user step, not a mod fix, and it requires the ten `Save/gameN.sav` files to be
fully transferred before the load.

### 3.4 Alternative C: rewrite the live humans' `+0x14` tags (not recommended)

One could write the host's character tags into the guest's live `CCharacterHuman` objects
(`human+0x14`, `sync.c:13`). It is the smallest write, but it is semantically wrong: the model, skin,
animations and weapon set remain BOY2/GIR2 while every tag-specific game check and the script/character
lookups take the BOY1/GIR1 path. See the risks in §4.4; do not do this.

---

## 4. What could crash or desync (risky structures)

### 4.1 World/human lifecycle (highest risk)

* `FUN_004a3760` is the game's own world teardown: for mode 1 it calls the world destructor and sets
  `game+0x378 = 0` (decompile 97816-97865, 97850). The world owns the human manager
  (`world+0x175c`, count +4, array +0xc), the controller records (`world+0x1748`, stride 0x764,
  human pointer at +0, tag at +0xc), the NPC manager (`world+0x1760`) and the camera
  (`world+0x1764`). If a fix zeroes `game+0x378` or calls `FUN_004a3c10` without this teardown,
  all those pointers dangle and the next frame crashes. NOTES:181-183 records exactly a forced level
  jump that tore the world down and crashed ("never guess a level").
* If the party table is written **without** a world rebuild, `FUN_004a3c10`'s spawn is not reached and
  nothing changes; if a rebuild is forced while the old humans still exist, the manager gets four
  humans (BOY1, GIR1, BOY2, GIR2). `attach_player2` (`sync.c:68-84`) assumes the array has exactly two
  entries and writes `arr[1]`; `player_human(1)` (`sync.c:51-57`) and the camera target then point at
  whichever body happens to be second. Duplicated bodies also mean duplicated script entities and
  two controller records driving one body.
* The spawn call is `world vtable+0x14(tag, pos_id, controller)` (98086-98087); it needs a valid world
  and a valid character tag. Calling it directly without the preceding world/level setup is a crash
  candidate.

### 4.2 Level and arrival door (`pos_id`)

* The spawn loop takes only records whose `record+0x1b10` level equals `game+0x364` (98084-98086). If
  the host's table records are at a different level (stale packet, a save made in another level, a
  party split across levels), the guest spawns **nobody** or only the matching members; the partner
  is missing and `attach_player2`/camera/state matching silently do nothing.
* `pos_id` (`record+0x1b14`) is the arrival door id. State 4 resolves it against the level's door
  entities (`HRDD`/`ODOD`, id at +4; decompile 99017-99031). If the guest's level data does not contain
  that id (different build/DLC/modded level), the party is not placed correctly or the level load
  fails. Host and guest must run the same level pak files.
* Do not carry the host's table across a level the host has not loaded; guard on
  `g_host_party_level == <request level>`.

### 4.3 Character assets and weapons

* `FUN_004a58e0` loads the party's character assets per level from the records (99239-99247) after the
  world exists, and `FUN_004a3930` has tag-specific filename variants (e.g. BOY2 gets a `B` suffix when
  chapter > 6; GIR3 when chapter > 7; 97919-97945). A tag whose data/skins/anims are not present in the
  guest's install (or a table written late, after `FUN_004a58e0` already ran for another tag) can make
  the character fail to load or crash on an animation/weapon request.
* The records carry `weap0..3` at +0x14..+0x20 and health at +0x10. The live weapon state is separate
  (`character+0x704`); `FUN_004a20c0`'s optional weapon sync (97005-97060) copies live weapons into the
  table. A table override that does not also align the live weapons/health leaves a one-frame
  mismatch, and the next level change may write the guest's own values back.

### 4.4 Character-tag semantics

* The game hardcodes many tag comparisons for character-specific behaviour and assets, for example
  decompile lines 4681, 9441, 26891, 28724-28798, 29006, 29338-29389, 34917, 37606-38902, 38529,
  53211-53327, 56597, 57053, 58606. Re-labelling a BOY2/GIR2 body as BOY1/GIR1 (Alternative C) makes
  those paths take the BOY1/GIR1 branch while the body still has BOY2/GIR2 assets — a mismatch that can
  crash on a missing animation/skin or silently break weapons and cutscenes. The safe version is to
  spawn the right tag from the start (the recommended fix), not to rename live bodies.

### 4.5 Controller attachment and 2P mode

* The controller tag in the record (text `CHC1`/`CHC2`/`CHTM`; dwords 0x43484331/0x43484332/0x4348544d)
  decides which controller record controls the spawned human. The original save has `CHTM` (teammate
  AI) for the partner; the repo's workaround edits the save to `CHC2` (NOTES:328). If the guest loads a
  table with `CHTM` for GIR1, the game keeps her on AI and player 2 gets no body; `attach_player2`
  (`sync.c:68-84`) only writes the controller pointer at `world+0x1748+4+0x764`, it does not set the
  game's "two players" mode or the controller tag. NOTES:322 records exactly this: after a save load the
  game is still in one-player mode and the partner does not move. The guest's transferred saves are
  byte-identical after a complete transfer (`tests/check_savexfer.py`), so the edited `CHC2` arrives —
  but only after the transfer finishes.
* If the record's controller is `CHC1`/`CHC2` but the guest's live controller records still point at the
  old BOY2/GIR2 bodies, the game can drive a body that no longer exists or attach two controllers to one
  body. The table override must be paired with the world rebuild (which recreates the controller
  records/attachment) — which the recommended fix does.

### 4.6 Progress mix (desync, usually not a crash)

* Only the party table is copied by the recommended fix. The rest of the save/progress stays the
  guest's: the entity/story table at +0x814 (up to 380 entries of 12 bytes), chapter at +0x1c68,
  counters at +0x1c50..+0x1c60, chest flag at +0x1cd0, and the inventory at `world+0x1790`. The mod
  syncs the entity table and the +0x1b0c..+0x1cd4 block with `PKT_REGION` (617-665) and the inventory
  with `PKT_ITEM` (230-264), but only after the guest is in game at the host's level. For the interval
  between the party spawn and the first applied region/item, scripts can see a mixed state (e.g. a door
  the host opened is still closed on the guest, an item the host has is missing). This is a desync, not
  a memory fault, but cutscenes keyed to party/story state can take the wrong branch.
* State 2 on an in-game guest also copies `game+0x31c` over the live progress object (193312-193360),
  which can wipe host-synced entity/table bytes. The mod's region re-send repairs only the parts it
  covers. A safer variant is to skip state 2 entirely on an in-game guest (apply only the table override
  at state 4), but that changes more of the mod's current behaviour.

### 4.7 Health/death/anim state

* The table's health (+0x10) and the live life (`character+0x320`) are separate; `PKT_STATE` applies
  life/animation only to a human whose tag matches (`sync.c:429-437`). Before the party matches, the
  guest's old bodies receive nothing; after the override they match, but the guest's new bodies start
  at the save's health and then get the host's current life. If the host's player 1 is down at the swap,
  the guest can be alive for a frame or two until the first snapshot, and the death/swap test
  (`tests/check_death.py`) can see a wrong partner. The death animation (+0x2dc) follows the same
  tag-matched path.

### 4.8 Network and save-transfer timing

* `PKT_REGION` has no sequence/level ordering check beyond the level tag; UDP can deliver an older table
  after a newer one, and the stash would regress. Use the packet header `seq` or ignore a stash whose
  `r->level` is not the level being built, and protect the 0x140-byte stash with `g_reg_cs` (a torn
  memcpy could mix two parties).
* `host_send_progress(1)` + `net_send_req(REQ_LEVEL)` is still two UDP packets. On loopback/Steam they
  are normally ordered, but loss/reorder can let state 4 run before the stash; the optional deferral in
  `guest_apply_requests` (§3.1.3) closes this. Without it, the failure is graceful (the guest keeps its
  own party), not a crash.
* If the fix instead relies on the guest's own menu load of the transferred save, it must wait until all
  ten files are written and acked. The current transfer retransmits an unacked 512-byte chunk after
  250 ms (`sync.c:86-222`); a load started mid-transfer can read a short/partial 40 KB file, and the
  game's parser may see missing `character` records (empty party) or garbage (crash on a record field).
  `tests/check_savexfer.py` checks the finished state only.
* The `LoadProgress` argument is a slot/parameter (`game+0x374`), not a level or a party. A guest whose
  own `Save/gameN.sav`/`game+0x31c` came from a different slot than the host's argument can copy the
  wrong save over its live progress in state 2. The recommended fix does not touch `+0x31c`, but the
  state-2 copy still happens today.

### 4.9 Save write-back

* After the override, the guest's live table says BOY1/GIR1 but its own story/chapter/inventory may still
  be its own (until PKT_REGION/PKT_ITEM). If the guest saves, the written save combines the host's party
  with the guest's story state; a later load of that file would be inconsistent. The host's save
  transfer overwrites the guest's files on each welcome, which masks this in the current test flow, but
  it is a real hazard for a manual save on the guest.

---

## 5. Open / UNKNOWN items

1. **`FUN_005405a0`'s `ECX` at the `FUN_004a4060` call site** (185885): Ghidra does not render the
   thiscall object. The `+0x31c` target is DERIVED from `FUN_004a1ba0` (reads +0x31c's level) and
   state 2 (`FUN_0053fe10(game+0x31c)`), not proven by a live read. A breakpoint/read of `ECX` at
   `0x4a4060` would settle it.
2. **Which save file the reported run used.** The test copy's current `Save/game1.sav` has a BOY1/BOY2
   pair; TASK2/NOTES:315 report host BOY1/GIR1. The test copies' saves were replaced over time (there
   are `Save.1p.bak` and `Save.xfer.bak`), so the byte-level party identity of that run is UNKNOWN; the
   mechanism above does not depend on which pair it was.
3. **Whether `world vtable+0x14` is the only spawn path.** Level scripts may also create/remove humans
   (`Cslh_CharacterHuman*` natives, strings.tsv:1123/1167/1320); the decompiled level-load path is the
   one exercised by the save load. A script-driven spawn would need the same table override anyway.
4. **The exact effect of `FUN_004a3760` on the old humans/controllers/camera** is inferred from the
   world=0 write and the destructor call; no live test was run for this note (TASK2 forbids running the
   game).
5. **The host's save edit** (MTHC → 2CHC) is present in the file pair checked by
   `tests/check_savexfer.py`; whether the guest's parser sees the edited controller at the moment the
   host's load is applied depends on the transfer completing first (UNKNOWN in the failing run).

---

## 6. Evidence index (quick jumps)

| Claim | Evidence |
|---|---|
| New game = B101 + BOY2 + GIR2 | `FUN_004a54c0` 0x4a54c0, decompile 98897-98915; menu call 208708-208713 |
| Save = per-character records | `FUN_005405a0` 0x5405a0, decompile 193770-193840; strings.tsv:2052-2062; save-file byte dump |
| Controller text/dword mapping | `FUN_004a8e00` 101732-101759, `FUN_004a8e60` 101762-101777; comparisons 0x43484331/32/0x4348544d (98988, 97179-97182) |
| LoadProgress = state 2 + copy +0x31c | `FUN_004a1ba0` 96595-96606; state 2 98960-98985; `FUN_0053fe10` 193312-193360 |
| Party spawn only when world == 0 | `FUN_004a3c10` 98038; spawn 98084-98094 |
| Level change re-registers live party | state 4 top 98936-98945; `FUN_004a20c0` 96894-97102; teardown `FUN_004a3760` 97816-97865 (world=0 at 97850) |
| Party assets load after build | `FUN_004a58e0` 99070-99258 (calls 99239-99247); `FUN_004a5f20` 99259-99293 (call 99276-99280) |
| Mod forwards only the request | `src/hooks.c:77-94`; `src/sync.c:781-833` |
| Mod regions only to +0x318, level-gated | `src/sync.c:617-665`, `686-709` |
| Save transfer writes files only | `src/sync.c:86-222`; `tests/check_savexfer.py` |
| Inventory is a world object | `src/sync.c:226-264`; NOTES:305 |
| Guest keeps its party / 1P mode | NOTES:315, 322, 329 |
| Hook prologues (read-only exe dump) | `FUN_004a20c0` = `55 8b ec 83 ec 08`; `FUN_004a3c10` = `55 8b ec 6a ff 68 33 49 64 00`; `FUN_004a1c00`/`FUN_004a1ba0` match `hooks.c:140-147` |
