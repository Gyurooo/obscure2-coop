# TASK 11 FINDINGS — the guest's empty hands: what the pictures show and what differs in memory

Status labels: **OBSERVED** = printed by a check or visible in the decompile this session; **DERIVED** = follows
from the cited code but not proven live; **GUESS** = plausible, unproven; **UNKNOWN** = not established.
Decompile line numbers are `<local>\decomp2\Obscure2.exe.c`; addresses are static (image base 0x400000).

## 1. Seeing it (method: real window screenshots, then viewed as images)

`tests/shot_pair.py` captures each copy's own game window from outside the game with
`PrintWindow(hwnd, dc, PW_CLIENTONLY|PW_RENDERFULLCONTENT)`; if that comes back blank it falls back to a
`BitBlt` of the client area from the screen. Both copies' windows were **visible, not iconic**
(`iconic 0 visible 1 rect 806x629`, host at 20,20 and guest at 840,20), and PrintWindow returned 92.8 %
non-black pixels, so the capture is the real frame. The PNGs are `tests/shots/host.png` / `guest.png`
(git-ignored).

I viewed both images directly. **OBSERVED** (run 2, after save 01 → I100, ~10 s after the level was up):

* host: GIR1 stands with both arms raised, holding the **chainsaw**; BOY1 behind her holds a small bright
  object (taser). Both characters are in the "armed" animation.
* guest: same room, same positions, same characters — **arms hanging down, no weapon at all**, the
  unarmed animation.

So the difference is not merely a hidden mesh: the **guest's characters are not in the armed animation
state** either. The owner's report ("the characters hold nothing in their hands") is exactly what the
guest frame shows. An attempt to capture the D3D9 back buffer from inside `Present` (added to
`src/window.c`, `shot` pipe command) **froze the game's render thread** (both logs stop at the shot
request), so that approach was reverted and the external capture used instead.

## 2. Memory measurements (script `tests/check_hands_visible.py`, run 2)

Per live human (world+0x175c manager → +0xc array; tag +0x14; slots +0x704+4*i; selected slot +0x714):

| field | host (CBOW, slot 0) | guest (CBOW, slot 0) |
|---|---|---|
| weapon tag (+0x10) | CBOW | CBOW |
| vtable (+0) | 0065f7dc | 0065f7dc |
| vtable+0xcc "show" | 00486220 | 00486220 |
| vtable+0x84 "enable" | 0048bda0 | 0048bda0 |
| weapon+0xb8 ("shown", set by show) | 1 | 1 |
| weapon+0xa8 | 1 | 1 |
| weapon+0xc4 owner | host BOY1 | guest BOY1 |
| weapon+0x34 mesh | 1c5886f8 | 19d032d0 (non-zero) |
| mesh+0x18 | 0 | 0 |

All four slots and the selected index matched on both copies (`check_hands.py` passes), and every
render-side field above matched too. The whole-object diff (`/tmp` probe) showed only pointer-sized
fields plus these small differences on the CBOW object: **+0x18** (host 0x1a654, guest 0x1920b),
**+0x1c** (host 0, guest float 0.487), **+0xdc/+0xf4/+0xf8** (host 0/0/0, guest pointer/1/2).

The characters' own dwords that differ and are not pointers/timers: **human+0x218** (host 3, guest 2) and
**human+0x22c** (host 0x55, guest 0). Writing the host's values into the guest with the `wr` pipe command
did **not** change the picture, and the game overwrote both fields back within a second → they are derived
state, not the flag that selects the animation (**OBSERVED**).

## 3. The real difference: the guest's world entity list is not built the way the host's is

**OBSERVED** (live peek of the CToeManager at world+0x1768, linked list at mgr+0x18, nodes `{entity, next}`):

* host: **43 entities** — the level's items and weapons (`ENDR`, `MEDI`, `SYRI`, `TASE`, `FLAS`, `SERU`,
  `JEMM`, `444f4300` ammo, …) plus the party's weapons;
* guest: **8 entities — exactly the eight weapons the mod created itself**, nothing else.

The host's 43 entries are exactly what `FUN_004b05a0` (the game's inventory→entity pass) produces: it walks
the mirrored inventory (`world+0x1790`) and turns every entry into a world entity (decompile 106862-106904,
live-entry branch 106880-106904). On the guest that pass ran while its inventory was still empty and was
never run again after the mod mirrored the host's 44 entries, so the guest's world only ever contained the
weapons the mod built by hand.

**OBSERVED — the hand-built ones are not built like the game builds a live weapon.** Game's
`FUN_004b05a0` live-entry branch:

```c
piVar4 = FUN_0045cdd0(tag);            // factory, constructor loads the model
pcVar2 = *(code **)(*piVar4 + 0x20);   // 0x00476560: `mov eax,1; ret`
piVar4[10] = 0;                        // weapon+0x28 = 0
iVar5 = (*pcVar2)();                   // vtable+0x20  (always 1)
if (iVar5 != 0) piVar4[0x2a] = 1;      // weapon+0xa8 = 1, BEFORE the fill
FUN_004b0300(piVar4);                  // fill from the inventory entry
if (*(int *)(entry + 0x1c) != 0) {     // only a stored/consumed entry is disabled
    (**(code **)(*piVar4 + 8))(0);     // vtable+8(0)
    (**(code **)(*piVar4 + 0x84))(0);  // vtable+0x84(0) = disable the parts
}
FUN_005544c0(piVar4);                  // register in the world's entity list
```

The mod's `weapon_object()` (src/sync.c ~510-555) instead always takes the *collected-entry* branch:
`+0x28 = 0; vtable+8(0); FUN_004b0300; vtable+0x84(0); +0xa8 = 1; register`. vtable+8 is the weapon's
"apply definition" constructor (`FUN_00497140` for TASE: loads `weapons\taser.zwo`, creates the four hand
attachment parts at weapon+0x238..+0x248; `FUN_00486140` reads the `play_kine` property into weapon+0x22c),
and vtable+0x84 is the "enable/disable the parts" routine (`FUN_0048bda0`). Calling them on a live weapon
is at best pointless and is **DERIVED** (from the two branches of the same function) to leave the object in
the disabled/consumed state — no hand attachment and no drawn parts — which the later `vtable+0xcc` show
does not rebuild.

## 4. Fix attempts and what they did

### 4.1 Attempt (tried live, REVERTED): build the weapon along `FUN_004b05a0`'s live-entry branch

`weapon_object()` in `src/sync.c` was changed to follow the live-entry branch exactly: factory → `weapon+0x28 = 0`
→ `vtable+0x20` (0x476560, `mov eax,1; ret`) → `+0xa8 = 1` → `FUN_004b0300(entry)` → call `vtable+8(0)` and
`vtable+0x84(0)` **only if the entry's +0x1c is non-zero** → register.

**Live result (run 4): the guest's main thread stopped for good inside the equip.** The log ends with

```
00:53:18.495 [17752] guest: made weapon CBOW (object 1BA34CB0) from the inventory entry (live-entry path, stored 0)
```

and no `guest: BOY1 slot 0 = weapon CBOW` line ever follows: `FUN_004dc870` (the game's equip) does not
return. The process stays alive (the UDP thread keeps logging party stores) but its game thread is stuck;
the window stops repainting (a PrintWindow on it blocks). So the disable pair `vtable+8(0)` + `vtable+0x84(0)`
that the mod calls at creation is **required for the object to be in a consistent state** for the equip (most
likely the parts array at `weapon+0x23c`, 4 entries of 0x138 bytes, and the `play_kine` property at
`weapon+0x22c`); skipping it hangs the game. The change was **reverted** (`git checkout -- src/sync.c`) and
the DLL rebuilt from the unmodified source.

### 4.2 What is left as the working theory

**DERIVED, untested:** the weapons the guest holds are created (or restored) *after* the world exists, while the
host's are created by the level's own inventory pass before the characters' animation is set up. The guest's
world entity list contains only the mod's weapons (8) where the host's has the level's inventory-derived
entities (43). The guest therefore never has the game's own weapon entities at the moment its characters are
built, and whatever the game does when it wires a weapon to a character's hands/animation at world build is
never done on the guest. The smallest next step to try is **running the game's own inventory pass
`FUN_004b05a0` on `world+0x1790` once after the guest's inventory mirror is complete and the world exists**
(so the game creates its own weapon entities in the guest's world exactly as it does on the host) — not done
in this task; it is a bigger change (44 entries, asset loads) and needs its own live run.

## 5. Live results

| run | DLL | picture | check_hands | notes |
|---|---|---|---|---|
| 1 | shot in Present | — | OK | in-DLL backbuffer capture froze the render thread; reverted |
| 2 (baseline) | current source | host armed (chainsaw in hands), **guest arms down, nothing in hands** | OK (slots+selected equal) | `check_hands_visible` printed equal vtable/show/+0xb8/+0xa8/mesh-presence for every slot |
| 3 (manual pair) | current source | — | — | memory probes: host entity list 43, guest 8 (only the mod's weapons) |
| 4 (attempt 4.1) | live-entry build | blocked by the co-op join prompt, then frozen | — | guest froze inside equip after one created weapon (see 4.1) |
| 5 (final) | reverted source | — | check_party OK, check_items OK, check_hands OK, check_hands_visible **failed on one field** | see below |

**Run 5 result (verbatim in the task report).** Everything the host draws and the guest copies matched again
(slots, selected slot, class vtables, `show` entry, mesh presence), and `check_hands_visible.py` found exactly
one difference in the render fields:

```
differences host vs guest: [('GIR1', 'slot 0 wb8', 0, 1)]
```

`weapon+0xb8` is the "shown" flag that the game's `show` (`vtable+0xcc`) sets and its `hide` (`vtable+0x74`)
clears. On the host only the weapon in the hand has it set (CBOW for BOY1, CSAW for GIR1); on the guest the
GIR1's **slot 0 (SHOT)** also still has it set. That is a real leftover of the mod's guest equip sequence:
`FUN_004dc870` shows each weapon it equips while it is the current slot, and the mod then changes the current
slot with a raw `human+0x714 = wcur` write, whereas the game's own slot change (`FUN_004dc800`, decompile
133837-133862) **hides the previously selected weapon first** (`vtable+0x74` before the new `vtable+0xcc`).
This is the one measured state divergence left, but it is an extra shown weapon, not a missing one, so it
does not by itself explain the guest's empty hands.

## 6. Still UNKNOWN

1. Whether the visual "empty hands" is the selected weapon not being drawn, the character's "armed"
   animation not being entered, or both. The guest frame in run 2 showed **both**: no weapon mesh and the
   unarmed idle pose, although every slot, the selected index, the weapon class, its "shown" flag and its
   mesh pointer matched the host.
2. What exactly the game does at world build that the mod cannot reproduce by equipping later; the
   inventory-pass hypothesis in 4.2 is the next thing to try.
3. Whether the guest's missing inventory entities (43 vs 8) also make other items invisible on the guest.
4. What the game does with the guest's old weapon objects at a level change (freed or leaked).

## 7. Next changes, in order (for the next task)

1. In `weapons_for()`, when the selected slot has to change, call the old selected weapon's `vtable+0x74`
   first, exactly like `FUN_004dc800` — removes the `('GIR1','slot 0 wb8',0,1)` difference measured in
   run 5. Small and safe; no new addresses.
2. Then re-test the picture. If the hands are still empty, run the game's own inventory→entity pass on the
   guest (`FUN_004b05a0` with ECX = `world+0x1790`) once after the inventory mirror is complete, so the
   guest's world gets the same 43 entities the host has, and let the game's own restore (`FUN_004f1b80`)
   wire the weapons to the characters.
3. Only if both fail: look for a character-side "armed" animation switch (the pose difference is the
   strongest remaining clue, and no field of the human or the weapon measured here distinguishes it).
