# Obscure II game mechanics that matter for the co-op mod and its bot tests

Sources: the owner (controls), and Koblasco's Steam guide "OBSCURE 2 IN-DEPTH STATS AND MECHANICS GUIDE"
(https://steamcommunity.com/sharedfiles/filedetails/?id=2430373771, values measured with Cheat Engine by its author).
Summarised in our own words; check a value live before relying on it.

## Controls (controller)
- The owner plays with a controller on the game's DEFAULT layout. The mod ships its own map `obscoop_o2.ipt`: check that it
  matches the default and does not move the attack.
- Attack: HOLD LB (aim / attack stance, locks onto a target), then press A to attack (owner; TASK 23 saw LB+A give the stance
  0x64/0x66 but no hit: the attack may be another button with LB held, or the enemies may be inactive). LB alone only enters the stance
  (TASK 22 saw LB set character `+0x2dc` = 0x64: that is the aim state).
- While aiming you can attack while holding forward or back on the stick, NOT while holding left or right (guide; game quirk).
- Melee combo: press attack again within ~0.25 s of the previous hit to extend the combo.
- Charged attack: only the CHAINSAW has one: hold the attack button >= 0.4 s; it holds the enemy in place while battery lasts.
- Melee weapons must lock onto a target again after an attack or combo (~0.1 s).
- D-pad = weapon quick-select (TASK 22). Weapons switch instantly once equipped; items are cycled in the item menu
  (0.2 s per item, the menu stays ~1.5 s, and no actions are possible while it is open).
- The action button picks up / uses things (boxes and chairs are picked up with it and swung with it again).

## Combat numbers (guide)
- Players: 100 HP max; below 40 HP = injured (slower walk/run animation). AI teammates take half damage in boss fights.
- Invulnerable during standing animations except reload and attack (battery reload, syringe fill, stuns, grabs, ledges).
- Melee (bat / hockey stick / golf club): 3-hit combo at the same height (7/8/14 damage), 2-hit upward, downward smash (15);
  spiked club a little more. Chainsaw 15 per hit, 20 low, charged 50 damage per second.
- Ranged: gun 15, shotgun 0-60 by distance, crossbow 125 (explosive), flashball 30 (incapacitates ~3 s), flare gun 150 over time,
  stun gun 5/s, uber flashlight 40 (wide), mini SMG 50/s. Throwables: dynamite 15-150 (can hurt the players), flashbang 250.
- Attack animations lock the player in place; only ranged weapons allow moving while shooting.
- Stuns: flinch, stagger (~0.5 s), step back, stumble, knockback, knockdown, incapacitation, etc. A hit during a stun restarts the
  stun animation. Enemies hit twice quickly often dash away or toward you.
- Enemy HP: Ram 60 (120 after the boat section), surrogate children 1, fly 45, evolved student 80, ogre 125, treeman 200,
  surrogate mother 300. Some drop a HEART on death (picked up for the syringe; hearts vanish when you leave the area).
  This matches the live J001 values (80 and 1 HP) and J000 (2 Rams at 120 HP).

## Healing and inventory (guide)
- Energy drink heals 30, first-aid kit 60; serums 50/75/100 made from hearts with the syringe.
- Inventory ITEMS are shared by all characters; WEAPONS only with characters who were with the finder (until the groups reunite).
- **Supply conditions (important for item tests):** some item spawns are skipped when the inventory already holds more than a
  limit: < 5 energy drinks, < 3 first-aid kits, < 21 gun bullets, < 10 shotgun shells, < 2 crossbow arrows, < 12 flashball
  grenades, < 9 flares, < 3 flashbangs. Some spawns are fixed and always appear. Re-entering the room re-checks the condition.
  OUR TEST SAVES hold 6+ first-aid kits (MEDI quantity 6 in save 01), so first-aid kit spawns are skipped there. This is a likely
  reason why so few live items were found (SLOT_SCAN.md). A save with fewer supplies spawns more.
- Boxes (environmental objects) can drop items when broken; the drops are fixed except in boss fights. Boxes and chairs are
  picked up with the action button and break when swung or hit.
- Battery: shared pool for the chainsaw, stun gun and uber flashlight; recharged at power boxes.

## Character aptitudes (each character has one; used for puzzles and progress; must work and sync in co-op)
From the community guide "obscure guide for dummy" (https://steamcommunity.com/sharedfiles/filedetails/?id=241744706) and the
stats guide: Corey climbs walls/ledges and shimmies (acrobatics), Mei hacks machines (a mini-game), Sven and Kenny push heavy
objects (strength), Stan picks locks (a mini-game), Shannon absorbs black auras/spores on doors, Amy reads faded documents and
solves riddles; Jun has no aptitude. Ledge moves, hacking and lock picking are animations or mini-games the guest copy must also
see and finish the same way (not synced yet; untested). Puzzle codes and keys: guides 2257482438 (all codes, Spanish) and
1990384144 ("The keys to success").

## PC and Steam version notes (community guides; relevant for players' setups and the save transfer)
- Saves on the Steam version are synced through Steam Cloud: Steam keeps them under `Steam\userdata\<user id>\254480\remote\`
  (with `remotecache.vdf` one folder up, and the input file `o2.ipt` among them). A save copied in from outside is only kept by
  Steam if it has the same name as the game's own saves; otherwise Steam's copy can win on the next sync
  (guide 1599088959, Russian). CHECK for the real two-account test: where the guest's transferred save is written versus where the
  Steam build reads it, and whether Steam Cloud overwrites it on the next start. The test harness redirects saves away from Steam.
- Known game crashes/freezes on modern PCs: using the STUN GUN can freeze or crash the game under DirectX 9; the community fix is a
  DXVK `d3d9.dll` (DirectX 9 on Vulkan) next to `Obscure2.exe` (guide 3722581300; the same idea fixes black screens, 3528679298;
  a black screen in the Kenny boss fight is described in 2385019953). Our mod reads the D3D9 view matrix for the camera yaw, so a
  player with a DXVK `d3d9.dll` installed is an untested setup: test it before telling players it works. Do not ship or download
  that DLL ourselves (third-party file on a file host).
- The game is 4:3 by default; widescreen patches exist (guides 3606707913, 442124251, 1123131599). They change the exe or config,
  which can change our hash-checked game identity (Obscure2.exe SHA-256 in the README): the mod should refuse or warn, not crash.
- "The game doesn't start" guides (887639483, 3731047704) mention deleting the MRS folder in Documents, i.e. the profile/save folder
  the mod also uses.

## Story events that change state (guide; relevant for cutscene and state sync)
- Some story moments set a character's HP or the battery to fixed values, empty the whole inventory (after the Friedmans
  fight, later a bag refills it depending on chests opened), or switch characters. These must reach both copies.
- Death is game over (reload a save); there is no permadeath in this game.
