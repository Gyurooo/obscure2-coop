# FINDINGS 50 — held weapons follow their owner; chair carry on the puppet; windows

Labels: **OBSERVED** = printed by a run/check in this task or read in the decompile (address cited);
**DERIVED** = follows from the cited code but was not seen live; **GUESS**; **UNKNOWN**.
Base: branch `w/combat`, TASK 49's result (protocol 24). Decompile `local\decomp2\Obscure2.exe.c`.

## 0. Plan (written before the code, updated as the runs come in)

1. **Held weapons (ownership).** Today the hands are still the pre-puppet host-authoritative model:
   `host_send_state()` puts every human's four slot tags + selected slot into `pkt_state.ch[]` and the guest
   applies them to **every** character with `weapons_for()` — including the character it owns itself. The
   host's copy of the guest's character (GIR1) is a puppet and never changes its own slots, so the guest's
   own GIR1 was overwritten by the host's stale view again and again: the 86
   `guest: GIR1 holds weapon ...` lines in 6 minutes are that loop (**OBSERVED**, private playtest log).
   Fix: each copy fills `pkt_char.me.wep[4]` from its OWN character and streams `wsel` (already
   character+0x714); the receiver applies them to the **puppet only** through the game's equip path
   (0x4dc870) and its show call (weapon vtable+0xcc). The old `pkt_state` hand fields and
   `weapons_for`/`guest_weapons_frame` are removed.
2. **Chair carry on the puppet.** The prop packet path already attaches the chair
   (`character+0x2bc` / `object+0xc4`, chair vtable slot 28 = 0x411f80). What the game's own pickup does
   *in addition* is at **FUN_00410da0** (chair slot 26, DERIVED): it sets the carrier's state through the
   game's setter (`slot 0x48(0xa8c)`) and plays the carry clip (`slot 0x68(0x4a4d464f, ...)`), then builds
   the two held meshes on the `RHand` bone. The mod's attach-only path leaves the puppet in its walking
   state with nothing in its hands -> no carry animation, chair on the floor (owner's report). The
   peer attach must run the game's own hold entry instead, and the chair's carried transform
   (slot 27 = FUN_00412720) must be driven while the puppet carries it.
3. **Windows.** Find the class/break path live and in the decompile (in progress).

## 1. Evidence read from the private playtest logs (quoted, no paths)

* `guest: GIR1 holds weapon CSAW (slot 2)` / `GUN? (slot 1)` / `SHOT (slot 0)` / `FLBA (slot 3)`, 86 lines
  in 6 minutes; host log 0 `holds weapon` lines — **OBSERVED** (DERIVED: the guest's own character was
  being overwritten by the host's `pkt_state` hand data).
* Carry: `guest: prop carry packet: prop CHAI id ???? -> ent 2219dbd8 (574.2,-733.2,0.0), character BOY1
  220d2b98 (holds 0)` -> `prop carry applied` -> six 500 ms heartbeats, then `prop carry applied:
  ----- id ---- -> BOY1` (detach). The chair's own position on the host at the break was
  `(552.1,-751.5,0.3)` while the guest's copy still had it at the pickup position — **OBSERVED**.

## 2. Live measurements (run 1 = chk50a, I100 + J005; run 2 = chk50a, J002 + G003)

**Vtable of CToeChair (0x653fdc), read live from both copies (identical):**
`20:00412f80 21:004038e0 22:00412600 23:00412690 24:004126a0 25:00412140(break) 26:004026f0
27:00412720(carried transform) 28:00411f80(attach) 29:00412010(detach) 30:004028b0 31:004028a0 32:004028c0`
(**OBSERVED**). Note `FUN_00410da0` is **not** a chair slot — the earlier guess was wrong; the chair's
take/hold work is all in the game's interaction code around slot 28 plus the chair's own update.

**J002 chair carry (host BOY1 picks a chair up, OBSERVED):** the owner's state is **301 (0x12d)** with the
upper clip **CHAB** (+0x220) and the lower clip **LPAU** (+0x224). The partner copy had already the SAME
state and both clips from the stream (`t01 H st 301 up220 CHAB lo224 LPAU | G st 301 up220 CHAB lo224 LPAU`)
— so the carry ANIMATION was never the missing piece on this build; `character+0x2bc`/`object+0xc4` and
`+0xb8` were applied on both copies too. What differs is the mesh: the carried transform
(`FUN_00412720`, slot 27) is what puts the prop's mesh in the hand (`mesh+0x1c8` / `mesh+0x1e0`), and the
entity position (+0x6c) is not that transform (both copies kept a position 75-83 units from the carrier).
The mod never called slot 27 on the copy that only applied the carry; the fix drives it from `prop_tick`
for a prop whose carrier is the puppet.

**G003 breakables (OBSERVED):** one `BK2S` `CToeBreakableTwoStates` at (2430.2, 942.1, 331.9), **already
broken in the save** (`+0xa4 1`, `+0x24 1`), so a live window break is not reachable from the test saves.
Its vtable 0x653944 slot 25 = **0x40ef20** (the class's break entry; objdump: checks +0xa4, hides the
whole mesh at +0x34, walks/shows the broken children at +0x108/+0x118, calls 0x591230, ends with
+0x14 = 1, +0x18 = 0, +0xa4 = 1). The mod's raw `prop_break_state` is the chair's shape and leaves this
family looking whole on the copy that only applied the packet — the fix queues the class entry
(`prop_game_break_tick`, run from `hk_game_update`, never Present; the chair's 0x412140 stays uncalled,
TASK 26).

## 3. Held weapons: the ownership model works (OBSERVED, chk50b, save 01)

`check_hands.py` (rewritten): 6 D-pad switches (3 by each player), every switch reached the partner copy
in **0 ms** (the check polls every 20 ms) and the partner's hand then stayed put for a full second after
each switch (`0 change(s)`); both copies ended with the same slots and the same selected slot:
`hands OK (each player's D-pad switch reached the partner within 300 ms; no flip-flop)`.
`puppet_weapons` reads the NEWEST stream sample (`puppet_latest`) instead of the interpolated pose, so the
switch is not delayed by the 55-220 ms playback buffer.

## 4. The chair-carried transform must NOT be driven from the frame hook (OBSERVED: hang)

First attempt: `prop_tick` (the Present hook) called the carrier's prop slot 27 (`FUN_00412720`) for every
prop whose table entry said "carrier is the puppet". Run 3: the guest's game thread **stalled inside
prop_tick**: `GAME THREAD STALLED 684.6 s ... last mod step "in prop_tick (guest)"`, frames frozen at
24364, right after `prop carry applied: ----- ...` detached the chair (`20:17:53.635`). The table's
`carrier` field is refreshed only every 150 ms, so the call ran on a chair whose detach had just released
its mesh state. Fix: the call moved to `puppet_finish` (the game's own character update, after the game's
own) and the carrier is read LIVE from the prop (`+0xc4 == character`), never from the table.

## 5. The carried-transform proof, before and after (OBSERVED, same level, same chair)

Probe: host BOY1 picks up chair #2 in J002; the partner copy of the same chair (by entity list index) is read
too. `b110` = the prop's `+0x110`, the `RHand` binding `FUN_00412720` looks up and stores; `mesh` = the mesh
transform fields it writes (`mesh+0x1c8` position, `mesh+0x1e0` quaternion).

| build | copy | before pickup | while carried |
|---|---|---|---|
| TASK 49 (`m49.dll`) | host (owns BOY1) | `mesh (591.94,-227.94,-11.91 ...) b110 ffffffff` | `mesh (32.52,31.26,-27.62,-0.03,-0.06,1.0,0.02) b110 a` |
| TASK 49 (`m49.dll`) | guest (puppet BOY1) | `mesh (591.94,-227.94,-11.91 ...) b110 ffffffff` | **`mesh (591.94,-227.94,-11.91 ...) b110 ffffffff` (never entered the hand)** |
| TASK 50 (`chk50c.dll`) | host | same | same |
| TASK 50 (`chk50c.dll`) | guest | same | **`mesh (32.52,31.26,-27.62,-0.03,-0.06,1.0,0.02)`** (the owner's transform) |

The baseline is the owner's report exactly: the chair's mesh stays on the floor position on the partner's
copy. With the carried transform called from `puppet_finish`, the partner's mesh takes the same in-hand
transform; the guest's game kept ticking (frames 20799 -> 22412) and `check_visible.py` still passed.
