# FINDINGS 51 — the inventory menu: one cursor per player, each driven by its own pad

Labels: **OBSERVED** = printed by a run/check in this task or read in the decompile (address cited);
**DERIVED** = follows from the cited code but was not seen live; **GUESS**; **UNKNOWN**.
Base: branch `w/combat`, TASK 50's result. Decompile `local\decomp2\Obscure2.exe.c`.

## 0. Plan (written before the code)

1. Read the Obscure 1 equivalent first (shared-context rule): `local\coopdll\src\sync.c` mirror the
   inventory **per real player** — the host sends each player's hold buttons, timer, mode, selected index
   (`section+0x19c`), scroll and animation, and the guest feeds them into its own player's CInventory
   update. Obscure II has no per-player CInventory in the menu any more: one `CMenuInventory` panel holds
   **both** cursors and both players' inputs (below), so the Obscure 1 data mirror is not the shape that
   fits here; the input has to arrive per pad instead.
2. Find in the decompile how the 2-player inventory keeps two cursors and which pad feeds each.
3. Measure it live (what our two copies actually see), then change the mod.
4. Prove with `check_menus.py` (extended) and the `OBSCOOP_LINK=steam` soak.

## 1. The live inventory panel and its two cursors (OBSERVED, decompile + live memory)

* `world+0x179c` = `game+0x46c` = the `CMenuInventory` object (`menus\inventory_pc.xmc`); the game object
  ctor builds it with `operator_new(0xa8)` + `FUN_0054ad30` (decompile 99840-99849), whose vtable is
  `0x66c18c` (RTTI `.?AVCMenuInventory@@`; the vtable address was resolved from the PE file, not guessed).
* World state 2 calls `(**(code **)(**(int **)(world+0x179c) + 0x24))(dt)` (decompile 110408) — the
  update `FUN_0054c040` — so state 2 **is** this panel.
* `FUN_0054c040` → `FUN_00542d00(dt)` → `FUN_00542c30(dt)`: the menu's **action-binding loop**.
  Each binding is 8 dwords (`FUN_00542ab0` writes them): `{action, target, timer, repeat_ms, held,
  need, padbase, param}`. For every binding it calls `slot 0x50` = `FUN_00542b70(action, need, 700,
  padbase)` ("is that action down on that pad block") and then `slot 0x2c` = `FUN_00542bf0(target, param)`
  (dispatch to the child panel, which ends in `panel->slot 0x18(target, 0, param)`).
* `FUN_00542b70(action, need, min_ms, padbase)` walks the panel's own pad-base list (`+0x54`, count
  `+0x64`) and checks `FUN_0059b3e0(base + action)`; the action records are
  `*(game+0x384) + 0x34 + i*4` (disassembly 0x4b2ba2: `mov 0x6c3068,%edx; mov 0x384(%edx),%ecx;
  call 0x59b3e0`), and `FUN_0059b3e0` is `*(manager+0x34 + index*4)`.
* **The live binding table** (read from the running game on both copies, identical): 35 bindings;
  pad bases `{0, 0x28, 0x50}` = pad 1, pad 2, keyboard.
  * `b00..b09`: pad base **0** (pad 1), **param 0** — actions 1,2,3,4 (up/down/left/right), 9,10 (A/B),
    0x1b,0x1d,0x1e,0x1c (tab left/right).
  * `b10..b19`: pad base **0x28** (pad 2), **param 1** for actions 1,2,3,4,9,10 — i.e. **player 2's own
    cursor and buttons**; the tab actions there carry param 0.
  * `b20..b28`: pad base 0x50 (keyboard), param 0.
  * `b29..b34`: pad base -1 (any), actions 0x16..0x1a,0x11 → targets 25..30 (document / map / close).
* The per-player cursor lives in the **tab panels**, `panel+0x138 + player*4`
  (`CMenuPanelWeapon`, vtable `0x66bffc`): `FUN_005498f0/FUN_00549810/FUN_00549960/FUN_00549880(player)`
  walk the grid via each cell's `+0xfc/+0x100/+0x104/+0x108` neighbour index and store the new cursor at
  `+0x138+player*4` (decompile 201041-201100). The panel's action entry is
  `FUN_0054c170(target, 0, player)` (vtable slot 0x18), which **gates player 2** on
  `panel+0x158+player*4` (decompile 203008) — the "this player is in the game" flag.
* The gate and the start positions are set per frame by the panel's own character read (decompile
  201320-201332): for each of the two characters, if its controller is an INPUT controller
  (`character+8 → +8 == 2`) then `gate = 1` and cursor = **0 (player 1) / 3 (player 2)**, else
  `gate = 0` and cursor = -1; the cursor item (`panel+0x120 + player*4`) is shown/hidden with that flag.
* **Live (OBSERVED)**: with the inventory open, both copies read `tab 0, cursor 0/3, gate 1/1` on the
  weapon tab — the game enables the **blue cursor on both copies in the puppet model too** (the gate
  reads the character's controller type, which is an input controller everywhere).

## 2. The bug (OBSERVED, this task's runs)

With the TASK 36 merged pad (`menu_merge`, obscoop2.c) the game receives the **same** merged pad on both
device slots, so either D-pad moved **player 1's** cursor and the player 2 one never moved:
`cur 0/3 → host DOWN 4/3 → guest DOWN 8/3 → guest RIGHT 9/3 → host RIGHT 10/3 → host UP x2 2/3`
(`run51_probe2.log`). The owner's report ("both players drive the same cursor") is exactly this.

**Fix (TASK 51)**: while the inventory is up the pads must stay **separate** — each copy already has
both pads (its own and the streamed one), and the game's own bindings read pad 1 for the red cursor and
pad 2 for the blue one. `menu_input_active()` still decides whether the remote pad reaches the game at
all; the new `menu_pads_separate()` (sync.c, world state 2) only stops the OR-merge in `menu_merge()`.
The pause menu keeps the merged pad (single cursor, unchanged, TASK 36).

## 3. Live results

(filled in below as the runs come in)
