# FINDINGS 36 — the menu system, and shared menus (TASK 36)

Labels: **OBSERVED** = printed by a run/check or read in the decompile with a line number; **DERIVED** =
follows from the cited code but was not seen live; **GUESS**; **UNKNOWN**. Decompile line numbers refer to
`local\decomp2\Obscure2.exe.c`; addresses are exe addresses.

Base: `96daf17` (v1.8, protocol 18). This task: protocol 19. The owner's playtest material is private:
read only, never copied, and no path from it appears below.

## 1. The menu classes (OBSERVED, `rtti.txt`)

`rtti.txt` names the whole UI family: `CGameMenuFactory`, `CMenuFactory`, `CMenuAction`, `CMenuItem`
(+`Border`, `Energy`, `Icon`, `Life`, `Live`, `Rect`, `Selection`, `SelectionAlpha`, `SlideShowAlpha`,
`Sprite`, `Team`, `Text`, `TextDelayed`, `TextSave`, `TextTwoPlayers`), `CMenuMain`, `CMenuMaterial`,
`CMenuPanel` (+`Brightness`, `Document`, `Energy`, `FullScreen`, `Item`, `ItemLive`, `LoadSave`,
`MemoryCard`, `MessageBox`, `Options`, `SlideShow`, `Team`, `Video`, `Weapon`, `WeaponLive`),
`CMenuInventory` / `CMenuInventoryLive`, `CMenuWeaponIcon`, and `Cslh_RequestMainMenu`.

So: **every in-game menu is a `CMenuPanel*` inside one menu system**, and `CMenuInventoryLive` /
`CMenuPanelItemLive` / `CMenuPanelWeaponLive` are the *live* (in-game, over the world) variants. The
menu system is not a separate world: it is built from `menus\*.xmc` resources (`menus\pause_pc.xmc`,
strings.tsv 00661d9c) by `FUN_004a4060` and lives in the game object.

## 2. The world's level state machine: `world+0x11c` (OBSERVED, decompile + FINDINGS_30)

`world+0x11c` is the level state (FINDINGS_30 §2 observed 1 = normal play, 5 = pause menu, 6 = cinematic,
0x11 = game over). This task adds the other values the world code branches on:

| state | meaning | decompile |
|---|---|---|
| 1 | normal play (movement, interaction) | 110548 |
| 2 | a menu/frontend state entered with a mode 0/1/2 | `FUN_004b2600` 108417; left through `FUN_0054beb0(0,0)` 108368 |
| 3 | state entered with an object parameter | `FUN_004b2650` 108436 |
| 4, 9 | gameplay-like states the pad scan also runs in | 110548-110550 |
| **5** | **pause menu** | `FUN_004b2730` 108501, `FUN_004b2770` 108518, left in `FUN_004b24b0` 108370 |
| 6 | cinematic / scripted event | FINDINGS_30 |
| 7 | state entered from action 9 (A) when `world+0x188 != 0` | `FUN_004b2850` 108568 |
| 8 | state entered with a **string** (a scene name) | `FUN_004b2890` 108575 |
| 0xa..0x10 | more menu/loading states (0x10 shows `world+0x1794` again) | `FUN_004b24b0` 108380-108392 |
| 0x11 | game over | FINDINGS_30 |

`world+0x12c` is the **requested** state (FINDINGS_30 streams it as "scene kind"): every `FUN_004b26xx`
helper sets `world+0x12c = <state>` and `world+0x130 = <entry/function id>`, and the world's own update
consumes it and moves `world+0x11c` there. `world+0x180`/`+0x184` are the pending request/arg pair that
`FUN_004b2770` consumes (108518-108530).

**The menu panel objects are single instances on the world** (OBSERVED, 109385-109388):

```
world+0x1794 = *(DAT_006c3068 + 0x474)     the pause/panel menu object (states 5 and 0x10 hide it
                                           through vtable+0x20(0), 108372/108389)
world+0x1798 = *(DAT_006c3068 + 0x478)     the second panel (state 10 hides it, 108375; state 10 also
                                           calls it with 0x53464c4f = "OFLS" ... 110167)
world+0x179c = *(DAT_006c3068 + 0x46c)     a HUD sub-panel (updated at 110408/110744)
world+0x17a0 = *(DAT_006c3068 + 0x470)     the HUD/inventory panel (see §4)
```

So there is **one** pause menu object and **one** live-inventory panel per copy: a menu is a single
session state of the world, not a per-player object. That is what makes "a menu is shared" the natural
model (the game itself has no per-player menus).

## 3. The pause menu (OBSERVED, decompile 110548-110590)

The world update, while `world+0x11c` is 1, 4 or 9, scans for these state requests (110548-110586):

```c
if (world+0x11c == 1 && (FUN_004b2b30(0x23, 0x50) || FUN_004b2b30(0x23, ctl1[0x14])))
    FUN_004b2730();                       // -> pause menu, state 5
if (FUN_004b2b30(9, 0x50) || FUN_004b2b30(0x1f, ctl1[0x778]))
    FUN_004b2850();                       // -> state 7 (action 9 = A, only when world+0x188 != 0)
```

`FUN_004b2b30(slot, device)` (108740-108768) is "is action `slot` down for that action block":
`device < 0` walks **both** players' controllers (`+0x764` stride), otherwise it tests the one block
`FUN_0059b3e0(slot + device)` — `device = 0x50` is the global block (keyboard ESC is slot 0x73 =
0x23 + 0x50, FINDINGS_24 §1: the global block is 0x50+), and `ctl1[0x14]` is **player 1's** pad action
block. So:

* **the pause menu is opened by player 1's pad (slot 0x23) or by the keyboard** — it does NOT read
  player 2's pad. `FINDINGS_24 §5` measured that the pad's **START** drives no action slot; the game's
  own pause entry reads the pad's START separately (FINDINGS_22 §1: START took `world+0x11c` 1 -> 5).
* **inside state 5** the same check runs again on the PAUS record (`world+0x11c == 5`,
  `action_record+0x10 == 0x50415553` "PAUS", 209310): `FUN_004b2770` returns to the stored previous state
  (1 or 5) and hides the panel. So the pause menu is also closed by the same button, and it is *player 1's
  pad* that closes it.

**DERIVED:** to let player 2 open/close/navigate the pause menu on both copies, player 2's pad buttons
must be merged into player 1's pad **while state 5 is up** (that is the "merge both players' menu inputs"
option the task allows). Nothing else reads player 2's pad in the menu.

**UNKNOWN (measured next):** whether the menu actually reads the merged pad on the guest too — i.e.
whether the pause menu on the guest's copy is driven by its (streamed) player 1 pad.

## 4. The live inventory and the weapon wheel (OBSERVED, decompile 126760-126850, 205737-206200)

`FUN_004cf940` is the per-player input-controller update. Besides the gameplay slots it keeps a **UI
state** in the controller record at `+0xa4` (`in_ECX[0x29]`):

| UI state | raised by | what the game does |
|---|---|---|
| 1 | `in_ECX[0x14]` (LB, aim stance) | `FUN_00552360(character, 0)` |
| 2 | `local_34` + `in_ECX[0x15]` | (the aim/attack layer) |
| **3** | any of the D-pad actions `in_ECX[0x24..0x27]` | `FUN_00552360(character, 1)` = the **weapon wheel** |
| **4** | the item action `in_ECX[0x18]` (owner map: **RT**, code 1029) or the two mouse-wheel actions, or `*(*(world+0x17a0) + 0xa8) < 0x5dc` | `FUN_00551b70(character, world+0x1790 (inventory), 1)` = the **item menu** |

and then, always:

```c
FUN_00552360(character, ui_state == 3);
FUN_00551b70(character, world+0x1790, ui_state == 4);
```

`FUN_00551b70` (206141-206168) resolves the character's controller tag (`CHC1`/`CHC2`) to the player
index 0/1, and if the HUD object (`in_ECX+0x90`) is free or already showing that player, it stores
`character` into the panel (`+0x16c`) and the **inventory object** into it (`+0x170`, through
`FUN_00551040`, 205737-205748), marks the panel open (`+0x10 = 1`, `+0x98 = 1`) and calls its
`vtable+0x20(1)` / `+0x2c` / `+0x24`. The player index is stored at **panel+300 (0x12c)**.

Consequences (DERIVED):

* the live inventory panel is **one shared object**; it shows **the player whose controller opened it**
  (`panel+0x12c`), and only one player's inventory can be on screen at a time;
* `world+0x17a0 + 0xa8` is the item menu's own **timer/countdown** (compared with 0x5dc = 1500 at
  126816; set to 4000 at 9787), which is what keeps the menu open for ~1.5 s after the button;
* the pads that raise these states are the **player's own** (`FUN_004cf940` runs per controller), so on
  both copies the same pad stream raises the same state — **if the two copies' controller records are
  wired the same way** (that is `attach_player2`, TASK 34/35).

**UNKNOWN (measured next):** whether the owner's observation ("the guest does not see the host's
inventory") is the *open state* not crossing, or the panel opening on the guest for the wrong player.

## 5. Map and documents

`CMenuPanelDocument` and the map are panels of the same menu system. The world states 7 (action 9 = A with
`world+0x188 != 0`) and 0xe are candidates; **UNKNOWN** which one shows the map and which the document;
the first live probe (below) reads `world+0x11c` and the four panel objects while a pad drives each menu.

## 6. What a menu does to the simulation

**DERIVED:** while `world+0x11c != 1` the world's gameplay update does not run its pad/movement scan (the
block at 110548 is guarded by `world+0x11c == 1 || 4 || 9`), which is the game's own pause. The mod must
keep the two copies' states equal, not invent a pause of its own.

## 7. Live probes (OBSERVED, two runs of the pair in I100, save 01)

Probe 1 (pad presses on each copy's own pad, reading both copies' memory):

```
baseline      st 1  ui BOY1 0 / GIR1 0  panel 1794 closed, 179c closed, 17a0 "open" (a HUD flag)
host START -> st 5 on BOTH copies within one sample (0.0 s)
guest DOWN x2 while the pause is open -> the only dword that changed in the host's pause panel is
              +0xa8 (its frame timer); the guest's pad does not move the pause menu
guest START -> st 5 on BOTH copies (the existing "guest START -> player-1 START pulse" path)
host BACK  -> st 2 on BOTH copies, panel world+0x179c +0x10 = 1 (the inventory menu, CMenuInventoryLive)
host B     -> st 1 on BOTH copies (closing the inventory with the host's pad works on both)
host D-pad RIGHT -> ui BOY1 +0xa4 = 3 on BOTH copies (the weapon wheel), back to 0 on release
host RT (trigger held) -> ui stays 0 (the item menu did not open; same as FINDINGS_24 §6.2)
guest pad DOWN/RIGHT while the inventory is open -> st stays 2 on both copies (nothing closed)
```

Probe 2 (a diff of the panel's first 0x200 bytes around each press):

```
inventory open (st 2), panel 179c: the ONLY dword that changes on a DOWN/RIGHT press (either pad) is
   +0x80, a running timer (host 0x7ce -> 0xb87 -> 0xf3e, guest 1 frame behind). No cursor field in the
   panel's first 0x200 bytes changes, so the selection lives in the CMenuItem objects the panel points
   at (+0x60/+0x70), not in the panel itself.
pause open (st 5), panel 1794: +0x50 = 0xfffffffe on both copies; a DOWN press (either pad) changes only
   +0xa8 (the frame timer). The panel's own memory does not hold the cursor either.
```

So: **opening and closing already cross the link for the pause (state 5) and the inventory (state 2)**,
because both copies' player-1 controller is fed by the same pad stream, and the guest's START is turned
into a player-1 START pulse. What is missing is (a) **player 2's pad driving the shared menu** (the pause
and the inventory read player 1's pad only: measured, the guest's presses changed nothing) and (b) a
**fallback when a pad packet is lost** (nothing re-converges the two copies' menu states).

The cursor is not a field of `world+0x1794` / `world+0x179c`; it lives in the `CMenuItem` objects those
panels point at. A check therefore asserts the *menu state* and a **functional** navigation signal
(the weapon-wheel selection `human+0x714`, which is readable and moves with the D-pad), not a raw cursor
dword. **UNKNOWN:** the exact cursor field (only reachable through the CMenuItem graph).

## 8. Design: a menu is a shared session state (written before the code)

**Model.** Each copy runs the same game, so a menu is not mirrored as data but *re-driven*: both copies
open the same menu on the same inputs, and while it is open both copies feed it the **same merged pad
input**. That keeps the cursor, tab and selection identical without the mod having to know the menu's
internal fields (which §7 could not even locate).

1. **State packet (`PKT_MENU`, protocol 19).** Both roles send `{level, state (world+0x11c), ui0, ui1
   (controller +0xa4), owner}` whenever one of them changes and 4x/s while any is not "normal". It is a
   *convergence* signal, not the primary path: the pads already carry the menu open/close.
2. **Convergence on the game's own input.** On a peer transition into a menu state we do not have (5 =
   pause, 2 = inventory, or a controller UI state 3/4), the receiver pulses the *same button* on the right
   pad (START for 5, BACK for 2, the D-pad for 3, RT for 4) through `XInputGetState`, exactly like the
   existing "guest START -> player-1 START pulse". On a peer transition back to 1 while we are still in a
   menu, the receiver pulses the same button to close. Pulses are one per transition and are suppressed
   while an injected pulse is running, so there is no ping-pong.
3. **Both players drive the open menu.** While a menu is up (`world+0x11c` 2 or 5, or any controller UI
   state 3/4) `XInputGetState` ORs the *other* player's pad into the pad it returns, on **both copies**
   (each copy has both pads: the local one and the streamed one). Both copies therefore run the same
   merged input and move identically. Sticks are merged only in the paused states (2/5); in the wheel /
   item menu (state 1) only buttons and triggers are merged, so the characters cannot walk.
4. **Closing on either closes on both**: a close is a pad press, which both copies see; if one copy
   missed it, rule 2 closes the other.
5. **Item use stays host-authoritative** (`PKT_ITEMUSE`, unchanged): navigating is shared, the use is
   applied once by the host.
6. **The whole family** is covered by the same two rules: the pause menu (state 5), the inventory with
   its WEAPONS/ITEMS/TEAM tabs and the document/map panels it opens (state 2 and the panels it drives),
   the weapon wheel and item menu (controller UI states 3/4). The map and the documents are
   `CMenuPanel*` items of that same menu system, so they move under the same merged input.


## 9. Result (OBSERVED, `tests/check_menus.py`, dll `chk36d.dll`, run `menu2.log`)

```
== starting in level I100
   before                 host st 1 ui (0, 0) | guest st 1 ui (0, 0)
== 1. the host opens the pause menu (START on the host pad)
   after host START       host st 5 ui (0, 0) | guest st 5 ui (0, 0)
   both copies show the pause menu after 0.00 s
   pause menu shown on both: PASS
   host  menu: menu local st 5 ui 0/0 seq 3 | peer st 5 ui 0/0 seq 3 age 187 ms | sent 3 rcv 3 pulses 0
== 2. the guest navigates it (D-pad on the guest pad) and closes it (START on the guest pad)
   after guest D-pad      host st 5 ui (0, 0) | guest st 5 ui (0, 0)
   still open while the guest navigates: PASS
   after guest START      host st 1 ui (0, 0) | guest st 1 ui (0, 0)
   guest closes the pause menu on both: PASS
== 3. the host opens the inventory (BACK: CMenuInventoryLive, state 2)
   after host BACK        host st 2 ui (0, 0) | guest st 2 ui (0, 0)
   inventory shown on both: PASS
== 4. the guest moves in the inventory (D-pad) and closes it with B (a plain menu action)
   after guest D-pad      host st 2 ui (0, 0) | guest st 2 ui (0, 0)
   still open while the guest navigates: PASS
   after guest B          host st 1 ui (0, 0) | guest st 1 ui (0, 0)
   both copies left the inventory after 0.30 s
   guest's B closes the inventory on both (merged input): PASS
== 6. the weapon wheel (controller+0xa4 = 3) shows on both copies from either pad
   host pad RIGHT         host st 1 ui (3, 0) | guest st 1 ui (3, 0)
   host's wheel on both copies (player 1): PASS
   guest pad RIGHT        host st 1 ui (0, 3) | guest st 1 ui (0, 3)
   guest's wheel on both copies (player 2): PASS
   after release          host st 1 ui (0, 0) | guest st 1 ui (0, 0)
   back to normal play on both: PASS
menus OK (10 checks)
```

The screenshots taken with the inventory open on both copies (`tests/shots/menus_host.png`,
`tests/shots/menus_guest.png`, viewed): both show the same screen - the WEAPONS tab with the arrows
either side, STAN (left, "LOCK PICKING") and SHANNON (right, "BLACK AURA"), the Golf club (blue) and
Hockey stick (red) entries, the same shared item grid and the same four weapon icons in each character's
column. Only the window size differs (host 1280x720, guest 640x360); the menu content is identical.

### The two bugs this task's own first run exposed (OBSERVED, fixed)

1. **Both copies chased each other.** The first version corrected a divergence on *either* side
   ("peer has a menu I do not -> open; peer is at 1 and I have one -> close"), which is a positive
   feedback loop over a link with delay: the log showed `2 -> 1 -> 2 -> 1` every ~400 ms with each copy
   pulsing the other (`menu1.log`). Fixed by ordering menu changes with a sequence number (the same idea
   as the scene sync's `leave_seq`): only a state NEWER than the one already applied is acted on, and a
   tie is left to the host. `menu2.log` then shows one pulse per real divergence.
2. **`shot` is not a pipe command.** `bot.py shot` is a Python-side window grab; the check now calls it
   directly (`from bot import shot`).

### What is proven and what is not

* PROVEN live: the pause menu and the inventory open on both copies from the host's pad, stay open while
  the guest moves in them, and close on both from the guest's pad (START for the pause, B for the
  inventory - B is a plain menu action, so this is the merged input at work, not the START special case);
  the weapon wheel shows on both copies from either pad; both copies end in normal play in the same level.
* Same code path, not tested live: the documents and the map (they are `CMenuPanelDocument` / map panels
  opened from the same live-inventory menu, state 2, and move under the same merged input), and the item
  menu (controller UI state 4): it could not be opened from a test pad in either this task or TASK 24
  (holding RT does not raise it here), so only its state is streamed and its pads merged.
* The cursor field of the pause/inventory panels is still **UNKNOWN** (§7): the panels' own memory does
  not hold it, so the check asserts the menu state and the guest-driven close (a plain menu action)
  instead of a raw cursor dword.

## 10. Regression (OBSERVED, dll `chk36e.dll`, run `reg_all.log`)

| run | command | result |
|---|---|---|
| reg1 | `run_pair_menu.sh ... check_party.py check_items.py check_hands.py check_hands_visible.py check_entities.py` | **PASS** - `party OK`, `items OK`, `hands OK (2 characters checked)`, `hands visible state OK (2 characters checked)`, `entities OK (host 43, guest 43)` |
| reg2 | `run_pair_menu.sh ... check_movement.py` | **PASS** - A/B/C/D PASS (e.g. D: BOY1 `diff_mean 0.22`, GIR1 `0.37`; phase E ran `--early` and did not fail the run) |
| reg3 | `run_pair_menu.sh ... check_attack_anim.py check_controls.py check_doors.py` | **PASS** - `attack animation OK`, `controls OK (each pad drives its own character on both copies)` (the pad merge is off without a menu: no cross-talk), `doors OK (1 phase(s))` |
| reg4 | `OBSCOOP_SLOT=3 run_pair_menu.sh ... check_breakables.py` | **PASS** - `breakables OK (chairs picked up, swung and broken on both copies; 2 chair(s) checked)` |
| reg5 | `OBSCOOP_PICKUP_CLASS=MEDI OBSCOOP_PICKUP_SPAWN=1 run_pair.sh ... check_itemuse.py pair_j003.py check_pickup.py` | **PASS** - `RESULT: item use OK`, `phase host->guest: OK` / `phase guest->host: OK`, `pickup OK` |
| reg6 | `run_cutscene_pair.sh ... --skip-by guest` | **PASS** - `PASS: the skip on the guest ended the event on the host (forwarded skip applied, skips 1)`, `cutscene sync: PASS` |
| reg7 | `run_soak.sh ...` | **FAIL** - 29 of 30 iterations one level, both copies alive, both game threads running to the end; iteration 16 after the iteration-15 door phase: `== 16: host loads game3.sav -> load done, level I010 -> I010/J002 (30.1s, NOT one level)`; plus one watchdog report `GAME THREAD STALLED 3.2 s ... last mod step "in the game's own code after frame_tick (update/render)"` with `game thread running again` 3 s later |

**The soak failure is the door/level-ask race, not the menus (OBSERVED + DERIVED):** in the failing window the
host's log shows the door's own `request ChangeLevel level I010` at 23:49:24.392 followed 0.7 s later by the
pipe load of `game3.sav` (23:49:25.071, `level is now J002`), i.e. the soak's own door phase immediately
before a load; the same shape (`... -> I100/J002 (30.0s, NOT one level)`) is in the earlier builds' logs
(`run_s34_soak3.log`, `run_s35_soak1.log`), so it predates TASK 36. The mod's new paths cannot run in that
window: the pad merge is only active while a shared menu is open (none was open during the soak; the guest's
`menu` line shows `st 1`), and `menu_tick` only pulses on a menu-state divergence. The stall report is in the
game's own update/render (the frame counter resumed 3 s later), not in a mod call. TASK 36's process budget
(28 game processes) was spent, so the soak could not be re-run.

**Not run: `run_reconnect.sh`** - the process budget (28) was reached with the seven rows above. The reconnect
handshake is untouched by this task (PKT_MENU is an additive packet with its own `else if` branch); this is
listed as NOT DONE rather than claimed.

## 11. DONE / NOT DONE / UNKNOWN

**DONE**

* The guest's door use (TASK 36 item 0): the failing gate was the test door driver's placement (`tz` from the
  character instead of the door anchor, so the game's 3-D gate stayed 113 units away) plus a race in
  `check_doors.py`'s reset; `check_doors.py --reset game3.sav` passes both phases in two independent runs
  (`doors OK (2 phase(s))` twice, logs `door2.log` / `door3.log`), with the guest's use proven by the door
  taking GIR1 as its user and both copies reaching the door's destination.
* The menu system is documented (`FINDINGS_36.md` §1-§7, decompile line numbers) and the design is written
  before the code (§8).
* Shared menus implemented for the family: pause menu (state 5), the live inventory with its tabs and the
  document/map panels (state 2), the weapon wheel and the item menu (controller UI state 3/4); NET_VERSION 19.
  Both copies publish the state, order changes with a sequence number, converge by pulsing the same button,
  and merge both pads into the shared menu on both copies (measured: the guest's B closes the inventory on
  both; the guest's START closes the pause on both).
* `tests/check_menus.py` passes 10/10 on a live pair; the two screenshots of the open inventory are
  identical on both copies (viewed).
* Regression rows 1-6 PASS (above).

**NOT DONE**

* `run_reconnect.sh both` - not run (process budget).
* The soak row FAILs on the pre-existing door/level-ask race described in §10 (not re-runnable inside the
  budget). It is not claimed as passing.
* The item menu (UI state 4) and the map/documents were not driven live: only the inventory's tabs were. The
  item menu could not be raised from a test pad (holding RT does not raise `controller+0xa4 == 4` here,
  the same as FINDINGS_24 §6.2), and the map/documents are menu items inside state 2 (same code path).

**UNKNOWN**

* The cursor/selection field of the pause and inventory panels: it is not in the panels' first 0x200 bytes
  (only the frame timers change), so it lives in the `CMenuItem` objects the panels point at.
* Whether a real two-PC Steam link (the owner's setup) opens the menus exactly like loopback: the probe and
  the checks ran on loopback (0-2 ms), where the pad stream arrives every frame.
