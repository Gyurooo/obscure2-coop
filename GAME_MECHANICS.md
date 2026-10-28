# Obscure II game mechanics that matter for the co-op mod and its bot tests

Sources: the owner (controls), and Koblasco's Steam guide "OBSCURE 2 IN-DEPTH STATS AND MECHANICS GUIDE"
(https://steamcommunity.com/sharedfiles/filedetails/?id=2430373771, values measured with Cheat Engine by its author).
Summarised in our own words; check a value live before relying on it.

## Controls (controller)
- Attack: HOLD LB (aim / attack stance, locks onto a target), then press A to attack (owner). LB alone only enters the stance
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

## Story events that change state (guide; relevant for cutscene and state sync)
- Some story moments set a character's HP or the battery to fixed values, empty the whole inventory (after the Friedmans
  fight, later a bag refills it depending on chests opened), or switch characters. These must reach both copies.
- Death is game over (reload a save); there is no permadeath in this game.
