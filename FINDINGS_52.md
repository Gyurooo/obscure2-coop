# FINDINGS 52 — the inventory's two cursors: where the wrong parameter comes from, and the mirror

Labels: **OBSERVED** = printed by a run/check in this task or read in the decompile (address/line cited);
**DERIVED** = follows from the cited code but was not seen live; **GUESS**; **UNKNOWN**.
Base: branch `w/combat` HEAD = TASK 51 WIP (protocol 26). Decompile `local\decomp2\Obscure2.exe.c`.

## 0. Plan (written before the code)

1. Decide where the pad-2 D-pad bindings' `param 0` comes from (§1): the game's menu data or our `o2.ipt`?
2. Wire TASK 51's unfinished parts (menu_tick fills/sends tab/cur0/cur1, calls menu_inventory_tick,
   pipe `menu` shows them), mirror only the PEER's cursor (owner copy never overwrites its own).
3. Extend check_menus.py: open from each side, host D-pad moves only cursor 0 on both copies, guest
   D-pad only cursor 1 on both, a selection by each player lands once on both, close from each side,
   both windows screenshotted with the two cursors on different items.
4. Measure the game's own 2-player pause behaviour and copy it.

## 1. Where `param` comes from: the game's menu data, NOT `obscoop_o2.ipt` (OBSERVED)

The binding array of every menu panel is built by **`FUN_00543710`** (the menu-file loader). It walks
the XMC file named by the menu's `menufile` property (the live inventory's is `menus\inventory_pc.xmc`,
string at 0x661dc0, decompile 98324) and for every `<input>` node reads:

```c
local_130 = FUN_00611e60(&DAT_0066b680,0);     // action
...
local_118 = FUN_00611e60("offset",0xffffffff); // pad base (0 / 0x28 / 0x50)
uVar10    = FUN_00611e60("param",0);           // <- the cursor/player parameter
FUN_00542ab0(local_130,uVar7,local_134,local_11c,local_118,uVar10);
```

and `FUN_00542ab0` stores `param_5` (offset) in `bd[6]` and `param_6` (param) in `bd[7]`:

```c
puVar4[6] = param_5;
puVar4[7] = param_6;
```

**`obscoop_o2.ipt` cannot carry this field.** Its format (FINDINGS_24 §1, `tests/ipt_table.py`) is
`u32 version, u32 count, count x { u8 bound, u32 device, u32 code }` — an action slot maps to one
device+code pair; there is no per-binding parameter. The ipt only decides *which* device/code answers
action slots 0x00-0x27 (player 1) / 0x28-0x4f (player 2), which is exactly what the mod's `ipt_fix`
already rewrites (device 3 / 4, obscoop2.c `ipt_parse`). **DERIVED**: the `param 0` on the pad-2 D-pad
bindings is the game's own `menus\inventory_pc.xmc` data, packed inside `datapack.hvp` (a scan of the
four .hvp files finds no plain-text `inventory_pc`, so the mod cannot fix the data on disk and must not
try: the real install is read-only).

**Decision**: keep the in-memory patch, but apply it **once per built array** (when the panel object /
array pointer / count changes, and on the frame the inventory opens), not every frame, and write only
entries that still carry 0. The cursor reset itself happens only on open
(`FUN_0054beb0` -> `FUN_00549be0` when the panel's `+0x10` changes), not per frame, so a patched table
and a mirrored cursor survive between packets.

## 2. Code (this task)

* `menu_inventory_tick(int just_opened)` (sync.c): patch the pad-2 D-pad params once per array build,
  then publish `tab/cur0/cur1` and mirror the PEER's own cursor only (host writes `+0x13c`, guest
  writes `+0x138`; counters `cursor writes p1/p2` let a check prove 0 writes to the copy's own cursor),
  only when the peer is in the same tab, the same level and its packet is fresh.
* `menu_tick`: calls it while world state 2, fills and sends `tab/cur0/cur1`, resets them to -1 in any
  other state, and sends a packet as soon as any of them changes.
* pipe `menu`: shows `tab/cur` on both sides and the cursor-write counters.

(measurements and the live runs are filled in below)

## 4. Live run: check_menus.py on chk52b (OBSERVED, loopback pair, save 01 = I100)

Verbatim decisive lines of `sh tests/run_pair.sh <...>/chk52b.dll check_menus.py` (full output in the
report; all 31 checks PASS, `menus OK (31 checks)`):

```
== starting in level I100 (normal play stable for 6 s)
== 3. the host opens the inventory (BACK: CMenuInventoryLive, state 2)
   inventory shown on both: PASS
   host  menu: menu local st 2 ui 0/0 tab 0 cur 0/3 ... binding fixes 4
== 4. two cursors: the host pad moves only cursor 0, the guest pad only cursor 1, on BOTH copies
   host D-pad DOWN        host st 2 ui (0, 0) cur (0, 4, 3) | guest st 2 ui (0, 0) cur (0, 4, 3)
   host D-pad moved cursor 0 on both copies (host 0->4, guest 0->4): PASS
   host D-pad left cursor 1 alone on both copies (host 3, guest 3): PASS
   guest D-pad DOWN       host st 2 ui (0, 0) cur (0, 4, 7) | guest st 2 ui (0, 0) cur (0, 4, 7)
   guest D-pad moved cursor 1 on both copies (host 3->7, guest 3->7): PASS
   guest D-pad left cursor 0 alone on both copies (host 4, guest 4): PASS
   pipe cursor writes (player 1, player 2): host (0, 2) | guest (2, 0)
   each copy writes only the PEER cursor (own-cursor writes: host p1 0, guest p2 0): PASS
== 5. a selection by each player lands once on both copies (move a weapon into a hand slot)
   player 1: cursor 0 -> bag cell 0 via [], then -> hand-slot cell 16 via ['LEFT', 'UP']
   player 2: cursor 3 -> bag cell 1 via ['LEFT', 'LEFT'], then -> hand-slot cell 20 via ['RIGHT', 'RIGHT', 'RIGHT', 'UP']
   both copies hold the same 24 grid cells after the two moves (the move landed once): PASS
   after the close (committed) host (('BOY1', 0, ('CLUB', 'TASE', 'UBET', 'DYNA')), ('GIR1', 2, ('BEAT', 'GUN.', 'CSAW', 'FLBA'))) | guest (same): PASS
   after the close both copies hold the same weapons: PASS
== 7. close and open from each side
   the guest's BACK closes the inventory on both copies: PASS
   the guest's BACK opens the inventory on both copies: PASS
   the host's BACK closes the inventory on both copies: PASS
   the host's BACK opens the inventory on both copies: PASS
menus OK (31 checks)
```

**OBSERVED**: the mirror now runs in both directions (host wrote player 2's cursor twice, guest wrote
player 1's twice) and no copy ever wrote its own cursor. The selection test checks the *committed*
result: player 1's hand slot 0 changed CBOW -> CLUB and player 2's SHOT -> BEAT, identically on both
copies; the two copies' 24 grid cells were identical before and after the two moves.

Screenshots `tests/shots/menus_host.png` / `menus_guest.png` (read by me): both windows show the WEAPONS
tab with all five tabs, the two character panels and the shared bag; the RED cursor is on the `100/6`
cell and the BLUE cursor on the crossbow cell, i.e. the two cursors on different items, on both windows.

**Test fix (not a relaxation):** the first chk52b run started while the level-load *scripted event* was
still running; the scene code drove world state 1 <-> 5 and the game closed the inventory when the event
ended (obscoop.log `scene: this copy entered a scripted event (world state 1 ...)` -> `menu state 2 -> 1`
2.5 s later on both copies). check_menus.py now waits for **6 s of continuous normal play** on both
copies before touching any menu (and 0.5 s between a close and the next open), which is a precondition
of the test, not a relaxed assertion.


## 3. Live measurements (OBSERVED, loopback pair, save 01 = I100)

### 3.1 The binding table and the patch (run `run52_probe1`, chk52a)

Live dump of the panel's binding array on both copies (35 bindings, identical): the pad-1 block
`b00..b09` is actions {1,2,3,4,9,10,0x1b,0x1d,0x1e,0x1c} with `padbase 0x0 param 0`; the pad-2 block
`b10..b19` is the same 10 actions with `padbase 0x28` and **param 1 for the six gameplay actions, param 0
for the four D-pad actions 0x1b..0x1e** (exactly the four TASK 51 found); `b20..b28` are padbase 0x50
(keyboard, param 0) and `b29..b34` padbase -1 (any pad) for the document/map/close targets. The mod's
patch wrote those four params to 1 on both copies (`binding fixes 4`) and the log line appeared once per
copy; the rest of the table is untouched. **OBSERVED**.

### 3.2 Cursor routing (run `run52_menus1`, chk52a, check_menus.py)

```
start: host (0, 0, 3) | guest (0, 0, 3)
host D-pad DOWN        host (0, 4, 3) | guest (0, 4, 3)   -> cursor 0 moved on BOTH, cursor 1 stayed 3
guest D-pad DOWN       host (0, 4, 7) | guest (0, 4, 7)   -> cursor 1 moved on BOTH, cursor 0 stayed 4
pipe cursor writes (player 1, player 2): host (0, 0) | guest (2, 0)
```
**OBSERVED**: each pad moves its own cursor on both screens, and the own-cursor write count is 0 on both
copies (guest mirrored the host's cursor twice; the host needed no correction for the guest's, because
the streamed pad had already moved it identically on loopback). The `menu` line now shows
`tab 0 cur 0/3` on both sides.

### 3.3 What a "selection" is on the weapon grid (run `run52_probe2`, chk52a)

The tab panel has 24 grid cells at `panel+0xc0 + i*4`; each cell object holds an item tag at +0xec and
its four neighbours at +0xfc (UP) / +0x104 (DOWN) / +0x108 (LEFT) / +0x100 (RIGHT) - the walk functions
FUN_00549810 / FUN_005498f0 / FUN_00549960 / FUN_00549880, whose targets are 4/3/5/6 in the bindings.
Cells 16..19 are player 1's four hand slots, 20..23 player 2's (FUN_00549be0 stores weapon `+0x10` into
cell `[slot + 0x10 + player*4]`). **A picks the item under the cursor up** (`panel+0x148[player] = 1`,
FUN_0054b2c0) and the **next A drops it** - a swap with the cell under the cursor (FUN_00549a10); B
cancels and restores the cursor (`panel+0x138[player] = panel+0x140[player]`). Dropping a bag weapon on
a hand-slot cell is the equip, and the panel writes the cells back to the characters on **close**
(FUN_0054beb0 -> FUN_00549f60), not on the drop. **OBSERVED**: guest A on cell 3 (CROS), RIGHT (from
cell 3 the right neighbour is cell 23), A swapped cells 3 and 23 on both copies; the character's
`+0x704` slots only change after the close. **DERIVED** from the cited decompile + OBSERVED panel state.
