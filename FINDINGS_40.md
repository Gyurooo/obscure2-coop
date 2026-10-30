# FINDINGS 40 — what the guest called at +0x1ea6b, and why every entity table needs a world generation (TASK 40)

Labels: **OBSERVED** = printed by a run/check or read in the decompile/disassembly with a file:line or an
address; **DERIVED** = follows from the cited code but was not seen live; **GUESS**; **UNKNOWN**.
Base: `HEAD` = b7dd210 (TASK 39, WIP). No packet layout change, so `NET_VERSION` stays 20.

## 1. The faulting call (OBSERVED)

The reviewer's run 2 (`claude_verify_39_soak2.log`, dll `m39.dll`, md5 `f1b488c5...` — the same file the
runner copied into `local\obscure2-test2\xinput1_3.dll`) reports

```
*** fault at Obscure2.exe+0x1e0ff6  params 00000000 0000007f
*** eip Obscure2.exe+0x1e0ff6  ... eax 0000007f ebx 0000007f ... esi 169eb798
***   [ebp+4] XINPUT1_3.dll+0x1ea6b (base 0x5ab30000, image 0x400000)
```

* `objdump -d m39.dll --start-address=0x1001e740` shows `_prop_apply_break` and its inlined
  `prop_break_state`. **`XINPUT1_3.dll+0x1ea6b` is the instruction after `call *0x84(%esi)` at
  0x1001ea65** — i.e. the return address of
  `((void (__fastcall *)(void *, void *, int))mvt[33])((void *)mesh, NULL, 0)`, the prop's MESH
  "hide" call (sync.c, `prop_break_state`: `mesh = rd32(ent + 0x34)`).
* `Obscure2.exe+0x1e0ff6` = VA 0x5e0ff6 (image base 0x400000): in `FUN_005e0fd0`, a `this->0`
  free + strlen + malloc + strcpy helper (`movb (%eax), %cl / incl %eax / testb %cl, %cl / jne` at
  0x5e0ff6-0x5e0ffb). The fault is the first byte read of a string pointer that is **0x7f**
  (`eax = ebx = 0x7f`, fault params `00000000 0000007f` = read at 0x7f).
* **No static pointer to 0x5e0fd0 exists anywhere in the exe** (a scan of the whole file for the
  dword 0x5e0fd0 finds nothing; the CHAI vtable 0x653fdc has 0x412140/0x411f80/0x412010 at slots
  25/28/29 and 0x4028d0 at slot 33). So 0x5e0fd0 is not the "show" method of any class: the pointer
  the mod called through was not a vtable at all.

**Conclusion (OBSERVED + DERIVED):** the prop entity was still alive enough for `prop_alive()`
(`IsBadReadPtr(ent, 0x120)` and the class tag at +0x10 were fine), but its `+0x34` mesh object was
not a live mesh. `*(void ***)mesh` was a heap pointer (`esi` at the fault is 0x169eb798, the game's
heap, not the image), `mvt[33]` happened to be a code address in the exe, `code_in_exe()` accepted
it, and the call ran an arbitrary game function with the dead object as `this`.

## 2. Why the world key of TASK 39 did not stop it (OBSERVED)

The guest log of run 2 (`local\obscure2-test2\obscoop.log`) at the crash:

```
03:33:13.221 guest: prop went back to whole: CHAI id ???? ent 1c276bb8 (the game respawned it)
03:33:13.221 guest: prop table: 11 breakable/carryable entities in level J002
03:33:14.338 guest: host LoadByName "game3.sav" (world exists)
03:33:14.382 guest: real load of "game3.sav" issued (mode 1 request state 3)
03:33:14.518 guest: prop break packet: CHAI id ???? -> ent 1c273dc8 (1087.6,-893.2,-11.9) carrier none broken 0
03:33:14.518 guest: prop table: 19 breakable/carryable entities in level J002
03:33:14.518 guest: prop broken here: CHAI id ???? ent 1c275df0 at (1087.6,-893.2,-11.9) ...
03:33:14.559 guest: the world this copy built from the save itself is up (level J002, 171 ms after the load)
03:33:14.613 guest: prop break packet: ... -> ent 1c275df0 ... broken 1
(no further game-thread line; the first stall report follows)
```

* The load rebuilt the world under an **unchanged level tag J002**; the table grew 11 -> 19 entities
  in one 150 ms scan, i.e. **the scan at 14.518 ran while the game was still creating the level's
  entities** (the world is "up" only at 14.559).
* `prop_tick` only re-scans when `w != g_prop_world || level != g_prop_level`, and a rebuild that the
  heap lays out at the *same* addresses passes both tests - the same hole TASK 39 §3.8 fixed for doors
  ("same-address world rebuild"). Even when the world pointer differs, the first scan of the new world
  is taken **during the build**, so its pointers can be replaced a frame later.
* The break packets of 14.518 are deferred 350 ms (`prop_defer_break`); their deadline (14.868) falls
  exactly into the rebuild window, and the apply then runs `prop_break_state` on an entity whose mesh
  field is not a live mesh any more. That is the crash.

## 3. The rule this fixes (same family)

Every table the mod keeps of game entities had the same shape: build from the manager's entity lists
by class tag, keep the entity pointer, later call the game through a method slot read out of the
object. The missing invariants were:

1. a table may only be built/used when the world is in **normal play and stable** (the same entity
   set seen for a settle time), keyed on a **world generation** that changes on every rebuild - the
   world pointer and the level tag are both unreliable (a rebuilt world can land on the same heap
   addresses and keeps its level tag);
2. the object's **class vtable** must be re-checked right before every call - and that vtable must be
   a *static image address*, because a heap block reused for something else has heap data in its
   first dword (this crash);
3. packets that target a table must be **deferred while the table is not valid**, never applied on a
   half-built one.

## 4. Tables touched (see the code)

| table | built by | keyed on (before -> after) | identity check before a game call |
|---|---|---|---|
| props (chairs / breakables) `g_props` | `prop_scan` | level + world -> **world generation** | class tag + `rd32(ent)` (class vtable) + id; the mesh and collision objects must have their vtable in the image |
| drop items (inside a prop) | `prop_candidate`/`prop_drop_of` | - (read live) | item class tag + `rd32(item)` in the image before slots 34/32/33 |
| aptitude objects `g_apts` | `apt_scan` | level -> **level + world + generation** | class tag + id + `rd32(ent)` before the field writes |
| doors `g_doors` | `door_scan` | world + level -> **+ generation** | already class vtable/tag/id; now also "the vtable is an image address" |
| pickups | resolved live per packet | - | item vtable must be an image address |
| weapons (character slots) | read live | - | weapon vtable must be an image address |
| characters / party | read live (`world_humans`) | - | world check already in TASK 39 |

(To be completed with the live evidence sections as the runs finish.)

## 5. The fix (sync.c)

### 5.1 A world generation every table is keyed on

`world_gen_tick()` (once per `frame_tick`, before every table tick) keeps `g_world_gen`, and bumps it

* when this copy leaves normal play (`game+0x310 != 1`, a pending request at `game+0x320`, no world,
  no level tag),
* when the world object or its level tag changes,
* **and when the set of live level entities changes at all** - a signature over both manager lists
  (`mgr+8`, `mgr+0x18`: XOR of the entity pointers + count, so list order does not matter).

`world_ready()` (`g_world_gen && g_world_stable`) is true only after the same entity set has been seen
for `WORLD_SETTLE_MS` (150 ms). `world_playable()` is the mode/state test every tick already did; a
safety valve accepts a world whose entity set keeps changing (a script spawning/freeing props) after
~1 s of churn, so the tables can never stay unusable for ever.

That is the (a) half of the task: a table can only be built from a world that is in normal play and
was stable for two scans, and every table records the generation it was built in
(`g_prop_gen`, `g_apt_gen`, `g_door_gen`) - the TASK 39 world key alone could not see a same-address
rebuild or a scan taken while the world was still being filled (`11 -> 19` entities in one scan).

### 5.2 Stable entity identity before every game call

* `prop_alive(e, cls, vt)` now also compares the **class vtable** at `ent+0` with the one the scan
  recorded (`prop_slot.vt`, `prop_pending.vt`); a block the heap reused holds another object there.
* `image_ptr(p)` (new): "the pointer lies in the game's image". It is checked on every **vtable** the
  mod dereferences - the prop's mesh (`+0x34`) and collision (`+0x68`) objects, the drop item, the
  door, the weapon, the npc life method, the lock pick, the pickup item. `code_in_exe` only asked "may
  I jump here", and in the crash the "vtable" itself was heap memory (`esi 0x169eb798`) whose slot 33
  happened to be an exe address - the call then ran an unrelated game function (the string helper at
  `Obscure2.exe+0x1e0ff6`) on the dead object.
* `world_has_entity(ent)` (new): the entity must be in the current world's manager lists **right now**
  (`prop_held_anywhere()` covers a carried prop, which leaves the lists). It is checked in
  `prop_apply_break`, `apt_apply_packet` (whose writes now look at the slot's recorded vtable/tag/id
  first), `door_apply` and `door_use_run`.
* `prop_apply_break` refuses an entity that is neither listed nor in a hand, and logs it (this is the
  exact call sequence that crashed: break packet -> deferred apply -> mesh slot 33).

### 5.3 Packets are deferred while the table is not valid

`prop_tick`, `apt_tick`, `door_ensure`, `peer_apply_props`, `guest_apply_prop_state`,
`prop_tick_pending`, `door_apply_tick` and `peer_apply_pickups` all check `world_ready()` (and, for the
prop table, `g_prop_gen == g_world_gen`) before they build a table, apply a packet or call into the
game. While the world is not ready, the queues keep their packets (each queue already drops what never
becomes applicable after 10 s), and `prop_tick` forgets the table and flushes the pending-break list, so
nothing of the previous world is ever applied to the next one.

### 5.4 Tests

`check_breakables.py` is the direct test of the prop path (carry + break through the table on both
copies). `tests/check_doors.py` and the soak's door phases exercise the door table; the soak's level
changes exercise the generation churn.

## 6. Live evidence

### 6.1 `OBSCOOP_SLOT=3 sh tests/run_pair_menu.sh chk40a.dll check_breakables.py` (run_s40_break1.log)

```
breakables: 11 chair(s) on the host copy, 11 on the guest copy
breakables: player 1 (host) -> chair #7 ... picked up ... broken after 0.30 s ... break on the other copy: yes
breakables: player 2 (guest) -> chair #9 ... picked up ... broken after 0.30 s ... break on the other copy: yes
breakables: game ticks (frames) host 999 guest 953
breakables OK (chairs picked up, swung and broken on both copies; 2 chair(s) checked)
```

and the log's first table build now happens only once the world is settled:

```
03:48:05.170 host: world 191e4e68 in level J002 is settled: the entity tables are rebuilt from it
03:48:05.547 guest: world 19392e48 in level J002 is settled: the entity tables are rebuilt from it
03:48:05.547 guest: prop table: 11 breakable/carryable entities in level J002
```

### 6.2 Soak, twice in a row with the SAME final DLL (`run_s40_soak1.log`, `run_s40_soak2.log`, dll `chk40a.dll`)

| run | body | stalls / crash lines | verdict |
|---|---|---|---|
| `run_s40_soak1.log` | 30/30 one level, race A one level, race B one level, `attack animation OK`, `controls OK`, `doors OK (2 phase(s))` | **0 / 0** on both copies | `=== soak run: PASS` |
| `run_s40_soak2.log` | 30/30 one level, race A one level, race B one level, `attack animation OK`, `controls OK`, `doors OK (2 phase(s))` | **0 / 0** on both copies | `=== soak run: PASS` |

Verbatim (run 2):

```
soak OK (30 location changes, both copies alive)
   race A result: level J000/J000 after 0.3s -> one level
   race B result: level I100/I100 after 0.0s -> one level
attack animation OK (stance + attack animation on both copies, both players)
controls OK (each pad drives its own character on both copies)
doors OK (2 phase(s))
  host: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
  guest: alive 1, FATAL EXCEPTION lines 0 (unhandled 0), game-thread stall reports 0
=== soak run: PASS
```

The guest's door phase again hit the "no character for one frame while the world is rebuilt" case and the
check's retry (kept from TASK 39) ran the use: `usedoor 1 -> error usedoor: player 1 has no character`
-> `the guest world was being rebuilt: waited 0.0 s for one level, retrying` -> `usedoor 1 -> ok`.

### 6.3 Menus, party, items (`run_s40_menus.log`)

```
menus OK (12 checks)          (incl. "guest teammate restored while a menu is up (TASK 38 guard): PASS"
                               and "guest teammate unlinked again in normal play (the door fix): PASS")
party OK
items OK
```

### 6.4 Reconnect (`run_s40_reconnect.log`)

```
CASE 1: no level or load request reached the guest (no reload)
resume: IN SYNC after 0.5 s (level I100, 2 characters, worst copy difference 0.0 units)
CASE 2: kill the guest and start it again while the host keeps playing
late join: IN SYNC after 0.5 s (level I100, 2 characters, worst copy difference 0.0 units)
=== reconnect run (both): PASS
```

### 6.5 What the new lines show in the logs

* `grep -c "is settled"` on the two mod logs of the last soak: 49 (host) / 68 (guest) - the table is
  rebuilt only after a settled world, including after every same-level save load.
* `grep -c "keeps changing"`: 0 - the safety valve was not needed.
* `grep -c "not in this world any more"`: 0 and `grep -c "never turned up"`: 0 - no packet was applied
  to (or dropped for) a dead entity in either soak; the prop carry/break records are there
  (`prop break applied` / `prop carry applied`: 3 host / 38 guest in the second soak's logs).

## 7. DONE / NOT DONE / UNKNOWN

### DONE (OBSERVED)

* The exact fault is identified from the failing build: `XINPUT1_3.dll+0x1ea6b` is the return address of
  `call *0x84(%esi)` in the inlined `prop_break_state` (the prop's MESH slot 33), and the game's
  `Obscure2.exe+0x1e0ff6` is a string-helper loop reading 0x7f. The "vtable" the mod called through was
  a heap pointer (`esi 0x169eb798`), its slot 33 an exe address by chance - no class in the exe has
  0x5e0fd0 in a vtable (a whole-file scan finds no reference to it). §1.
* The trigger is the world build: the guest log shows the prop table growing 11 -> 19 entities in one
  scan while a same-level load of `game3.sav` into J002 was still in progress, and the deferred break
  applied 350 ms later (§2, `local\obscure2-test2\obscoop.log` 03:33:13-14).
* The fix covers the family: world generation + settle for props, drop items, aptitude objects, doors,
  pickups, weapons; a class-vtable identity check on every cached entity and an image-address check on
  every vtable that is called through; "is this entity in the current world (or in a hand)" before the
  prop/apt/door calls; packets deferred while the table is not valid. §5.
* `check_breakables.py` PASSES (carry + break on both copies, 2 chairs) - the direct test of the table
  and of the break path that crashed (§6.1).
* `sh tests/run_soak.sh chk40a.dll` PASSES **twice in a row with the same DLL**: 30/30 one level, race
  A/B one level, attack animation OK, controls OK, doors 2 phases, 0 stall reports, 0 crash lines (§6.2).
  This is the first pair of consecutive PASS soaks since TASK 38 (TASK 39 could not show two).
* `run_pair_menu.sh ... check_menus.py check_party.py check_items.py`: menus OK (12 checks, both TASK 38
  assertions), party OK, items OK (§6.3).
* `run_reconnect.sh ... both`: PASS, both cases in sync after 0.5 s (§6.4).
* Every earlier fix is kept: TASK 35 (door freeze; the door tables are rebuilt the same way and the use
  still unlinks the teammate first), TASK 38 (the guard: `check_menus.py` asserts both halves), TASK 39
  (world key, door re-pick, `check_doors.py` retry).

### NOT DONE

* Nothing from the task's list is outstanding. Two items are **not tested live** (same code path):
  * the aptitude-object writes (`apt_apply_packet`) - the soak/party/items runs do not pick a lock or
    absorb an aura, so the new identity check there only runs when such a packet arrives;
  * the drop-item path of a break (`prop_item_enable`/`prop_align_drop`) - the chairs in slot 3 have no
    `itemType` (`drop item: none`), so the item-enable branch was not exercised this task (it was in
    TASK 39's crash, and now needs the vtable itself in the image).

### UNKNOWN

* Whether the TASK 39 build's crash *needed* a same-address world rebuild or only a mid-build scan: the
  log shows both (the table grew during the load), this task's fix covers both, and neither the world
  pointer nor a "same entity set" can be trusted alone - hence the generation.
* `check_doors.py`'s guest phase can still start while the guest's world is being rebuilt and answers
  `player 1 has no character` for one frame; the check retries and the use then runs (same as TASK 39).
  The mod does not retry a use that cannot start, by design (`soak34.py` only judges the level).
* How often the 150 ms settle delays the first prop/door apply after a level change is not measured; the
  queues hold the packets, so the effect is latency, not loss (0 "never turned up" lines in both soaks).

## 8. Process budget

| runs | processes |
|---|---|
| `check_breakables.py` (slot 3) | 2 |
| soak 1 (chk40a) | 2 |
| soak 2 (chk40a) | 2 |
| menus/party/items | 2 |
| reconnect both (host + guest + restarted guest) | 3 |
| **total** | **11 / 22** |
